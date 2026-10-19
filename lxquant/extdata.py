# -*- coding: utf-8 -*-
"""
外部增强数据（设计思路参考 GitHub 项目 1nchaos/adata）

本系统用它补强两处短板：
  1. get_stock_shares()    —— 流通股本历史（list_a_shares），据此算**真实历史换手率**
  2. trade_calendar()      —— 交易日历，判断当天是否开市、找"最近交易日"

实现方式：**直连数据源**（东方财富数据中心 / 深交所月度日历），
只在直连失败时才退回 adata 库，因此打包版不装 adata 也能用。
所有接口都做了降级：失败返回 None，主流程照常走估算逻辑，不会崩。
"""
import json
import time
import urllib.request

import pandas as pd

try:
    import adata  # noqa: F401
    HAS_ADATA = True
except Exception:
    HAS_ADATA = False

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Referer": "https://data.eastmoney.com/"}


def _http_json(url: str, timeout: float = 12.0):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _suffix(code: str) -> str:
    """6 位代码 → 东方财富的 SECUCODE 后缀"""
    c = str(code).zfill(6)
    if c[0] in "69":
        return c + ".SH"
    if c[0] in "03":
        return c + ".SZ"
    return c + ".BJ"

_MEM = {}          # 进程内缓存 {key: (ts, value)}
CAL_TTL = 12 * 3600
SHARES_TTL = 7 * 24 * 3600
LIST_TTL = 7 * 24 * 3600


def _cached(key, ttl, fn):
    now = time.time()
    hit = _MEM.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = None
    if val is not None:
        _MEM[key] = (now, val)
    return val if val is not None else (hit[1] if hit else None)


# ---------------------------------------------------------------- 交易日历
_SZSE_API = "http://www.szse.cn/api/report/exchange/onepersistenthour/monthList?month={y}-{m}"
_SZSE_HDR = {"User-Agent": _UA["User-Agent"], "Referer": "http://www.szse.cn/market/trend/index.html"}
_CAL_FAIL_TS = [0.0]          # 最近一次失败时间（避免反复卡网络）
CAL_RETRY = 30 * 60           # 失败后 30 分钟内不再重试


def _cal_bundled() -> set | None:
    """读取随程序附带的 lxquant/calendar.csv（离线、秒开，打包版靠它）"""
    try:
        import pathlib
        f = pathlib.Path(__file__).with_name("calendar.csv")
        if not f.is_file():
            return None
        out = {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()}
        return out or None
    except Exception:
        return None


def _cal_csv() -> set | None:
    """读取 adata 自带的日历 CSV（离线、秒开）；没装 adata 则 None"""
    if not HAS_ADATA:
        return None
    try:
        import pathlib
        base = pathlib.Path(adata.__file__).parent / "stock" / "cache" / "calendar"
        out = set()
        for f in sorted(base.glob("*.csv")):
            try:
                df = pd.read_csv(f)
            except Exception:
                continue
            if "trade_date" in df.columns and "trade_status" in df.columns:
                ok = df[df["trade_status"] == 1]
                out |= {str(d)[:10] for d in ok["trade_date"]}
        return out or None
    except Exception:
        return None


def _cal_direct() -> set | None:
    """直连深交所月度日历；第一个月拿不到数据就立刻放弃（快速失败）"""
    y = time.localtime().tm_year
    out = set()
    for m in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        req = urllib.request.Request(_SZSE_API.format(y=y, m=m), headers=_SZSE_HDR)
        with urllib.request.urlopen(req, timeout=5) as r:
            js = json.loads(r.read().decode("utf-8", "ignore"))
        rows = (js or {}).get("data") or []
        if not rows:
            if m == 1:            # 连第一个月都失败 → 网络不可用，别再试
                return None
            break
        for r in rows:
            if str(r.get("jybz")) == "1":
                out.add(str(r.get("jyrq"))[:10])
    return out or None


def trade_days() -> set | None:
    """返回 {交易日字符串 'YYYY-MM-DD', ...}；失败返回 None（主流程不受影响）。"""

    def load():
        s = _cal_bundled() or _cal_csv()   # 1) 本地 CSV，零网络
        if s:
            return s
        if time.time() - _CAL_FAIL_TS[0] < CAL_RETRY:
            return None
        try:                                # 2) 深交所
            s = _cal_direct()
        except Exception:
            s = None
        if not s:
            _CAL_FAIL_TS[0] = time.time()
        return s

    return _cached("cal", CAL_TTL, load)


def is_trade_day(date_str: str) -> bool | None:
    """None = 无法判断（不要因此阻断流程）"""
    cal = trade_days()
    if not cal:
        return None
    return str(date_str)[:10] in cal


def last_trade_day(ref: str | None = None) -> str | None:
    """ref 当天或之前最近的交易日"""
    cal = trade_days()
    if not cal:
        return None
    ref = str(ref or time.strftime("%Y-%m-%d"))[:10]
    cand = [d for d in cal if d <= ref]
    return max(cand) if cand else None


# ---------------------------------------------------------------- 流通股本
_SHARES_API = ("https://datacenter.eastmoney.com/securities/api/data/v1/get"
               "?reportName=RPT_F10_EH_EQUITY"
               "&columns=SECUCODE,SECURITY_CODE,END_DATE,TOTAL_SHARES,LIMITED_SHARES,"
               "LISTED_A_SHARES,CHANGE_REASON"
               "&filter=(SECUCODE%3D%22{sym}%22)"
               "&pageNumber=1&pageSize=200&sortTypes=-1&sortColumns=END_DATE"
               "&source=HSF10&client=PC")


def _shares_direct(code: str) -> pd.DataFrame | None:
    """直连东方财富数据中心，不需要 adata（打包版走这条路）"""
    js = _http_json(_SHARES_API.format(sym=_suffix(code)))
    if not js or not js.get("success"):
        return None
    rows = (js.get("result") or {}).get("data") or []
    if not rows:
        return None
    out = pd.DataFrame([{"change_date": str(r.get("END_DATE"))[:10],
                         "float_shares": r.get("LISTED_A_SHARES")} for r in rows])
    out["float_shares"] = pd.to_numeric(out["float_shares"], errors="coerce")
    out = out[(out["float_shares"] > 0) & (out["change_date"] != "None")]
    if out.empty:
        return None
    return out.sort_values("change_date").reset_index(drop=True)


def float_shares(code: str) -> pd.DataFrame | None:
    """
    流通股本历史 → DataFrame[change_date, float_shares]
    adata 的字段：list_a_shares = 上市流通A股（真正的流通股本）
                  limit_shares  = 限售股（不是流通股，别用错）
    优先直连东方财富（无需第三方库），失败再退回 adata。
    """
    code = str(code).zfill(6)

    def load():
        try:
            d = _shares_direct(code)
            if d is not None and not d.empty:
                return d
        except Exception:
            pass
        if not HAS_ADATA:
            return None
        df = adata.stock.info.get_stock_shares(stock_code=code)
        if df is None or df.empty or "list_a_shares" not in df.columns:
            return None
        out = df[["change_date", "list_a_shares"]].copy()
        out.columns = ["change_date", "float_shares"]
        out["change_date"] = out["change_date"].astype(str).str[:10]
        out = out[pd.to_numeric(out["float_shares"], errors="coerce") > 0]
        if out.empty:
            return None
        return out.sort_values("change_date").reset_index(drop=True)

    return _cached(f"shares:{code}", SHARES_TTL, load)


def prefetch_shares(codes, workers: int = 32) -> int:
    """把一批股票的流通股本**并发**拉进进程缓存，返回命中数。

    为什么需要它：`analyzer.analyze` 里是逐只串行调用 `turnover_series` →
    `float_shares`，每只都是一次东方财富请求（实测串行 293ms/只）。
    600 只就是 176 秒，而且全部卡在单线程上，扫描再快也没用。
    在扫描开始前用线程池预热一遍，同样的请求量只要 1~2 秒。
    """
    todo = []
    seen = set()
    for c in codes or ():
        c = str(c).zfill(6)
        if c in seen:
            continue
        seen.add(c)
        hit = _MEM.get(f"shares:{c}")
        if not (hit and time.time() - hit[0] < SHARES_TTL):
            todo.append(c)
    if not todo:
        return 0
    from concurrent.futures import ThreadPoolExecutor

    ok = [0]

    def _one(c):
        try:
            if float_shares(c) is not None:
                ok[0] += 1
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 32), 64))) as ex:
        list(ex.map(_one, todo))
    return ok[0]


def turnover_series(code: str, dates, volumes) -> pd.Series | None:
    """
    按交易日算出**真实换手率**（小数，如 0.0123 = 1.23%）。
    dates/volumes: 等长的日线日期与成交量（股）。
    找不到股本历史时返回 None，调用方回退到估算换手率。
    """
    sh = float_shares(code)
    if sh is None or sh.empty:
        return None
    d = pd.DataFrame({"date": [str(x)[:10] for x in dates],
                      "volume": pd.to_numeric(pd.Series(list(volumes)), errors="coerce")})
    # merge_asof 要求键是数值：转成 YYYYMMDD 整数
    d["dkey"] = d["date"].str.replace("-", "").astype("int64")
    sh = sh.sort_values("change_date").copy()
    sh["dkey"] = sh["change_date"].str.replace("-", "").astype("int64")
    sh["float_shares"] = pd.to_numeric(sh["float_shares"], errors="coerce")
    merged = pd.merge_asof(d.sort_values("dkey"), sh[["dkey", "float_shares"]].sort_values("dkey"),
                           on="dkey", direction="backward")
    out = merged["volume"] / merged["float_shares"]
    return out.replace([float("inf"), float("-inf")], pd.NA).astype(float)


# ---------------------------------------------------------------- 上市日期
def list_dates() -> dict | None:
    """{code: 'YYYY-MM-DD'} 上市日期；adata 首次拉取较慢（可能 2~4 分钟），7 天缓存。"""
    if not HAS_ADATA:
        return None

    def load():
        df = adata.stock.info.all_code()
        if df is None or df.empty or "list_date" not in df.columns:
            return None
        return {str(c).zfill(6): str(d)[:10]
                for c, d in zip(df["stock_code"], df["list_date"])}

    return _cached("listdate", LIST_TTL, load)


def status() -> dict:
    """自检：真实换手率是否可用（打包版未装 adata 时 adata=False 但 shares 仍为 True）"""
    probe = None
    try:
        probe = _shares_direct("600519")
    except Exception:
        probe = None
    return {"adata": HAS_ADATA,
            "shares": bool(probe is not None and not probe.empty),
            "calendar": bool(trade_days()),
            "last_trade_day": last_trade_day()}


def age_days(code: str, ref: str | None = None) -> int | None:
    """上市至今的交易日近似天数（用自然日/1.45 估算交易日）"""
    ld = list_dates()
    if not ld:
        return None
    d0 = ld.get(str(code).zfill(6))
    if not d0:
        return None
    ref = ref or time.strftime("%Y-%m-%d")
    try:
        from datetime import date
        a = date.fromisoformat(d0)
        b = date.fromisoformat(str(ref)[:10])
        return max(0, int((b - a).days / 1.45))
    except Exception:
        return None
