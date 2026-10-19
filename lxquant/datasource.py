# -*- coding: utf-8 -*-
"""行情数据源（纯标准库 urllib，规避 requests/akshare 依赖问题）

实测可用的数据源（2026-10 本机）：
  * 新浪 hq.sinajs.cn 实时行情
  * 新浪 quotes.sina.cn 5 分钟 K 线（最多 1023 根，约 22 个交易日）
  * 新浪 vip.stock.finance.sina.com.cn 全市场股票列表
  * 腾讯 ifzq.gtimg.cn 日线(前复权) / 5 分钟 / 当日分时
东方财富、网易、qt.gtimg.cn 在本机被网络策略拦截。
"""
import json
import re
import time
import urllib.parse
import urllib.request

import pandas as pd

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class DataError(RuntimeError):
    pass


def _fetch(url: str, headers: dict | None = None, timeout: int = 15,
           retries: int = 3, encoding: str = "utf-8") -> str:
    h = {"User-Agent": UA, "Accept": "*/*", "Connection": "close"}
    if headers:
        h.update(headers)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.35 * (i + 1))
    raise DataError(f"请求失败 {url[:90]} -> {type(last).__name__}: {last}")


# ---------------------------------------------------------------- 代码规范化
def norm(code: str) -> str:
    """任意写法 -> 6 位数字代码。支持 sh600519 / 600519.SH / 600519。"""
    c = str(code).strip().lower()
    c = re.sub(r"^(sh|sz|bj)", "", c)
    c = re.sub(r"\.(sh|sz|bj|ss)$", "", c)
    c = re.sub(r"\D", "", c)
    return c.zfill(6) if c else ""


def market(code: str) -> str:
    """返回 sh / sz / bj"""
    c = norm(code)
    if c.startswith(("60", "68", "51", "58", "56", "11", "90")):
        return "sh"
    if c.startswith(("00", "30", "12", "15", "16", "18", "20")):
        return "sz"
    if c.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


def full(code: str) -> str:
    c = norm(code)
    return f"{market(c)}{c}"


def is_stock(code: str) -> bool:
    c = norm(code)
    return c.startswith(("600", "601", "603", "605", "688", "000", "001",
                         "002", "003", "300", "301", "83", "87", "43", "92"))


# ---------------------------------------------------------------- 股票列表
def stock_list(force: bool = False) -> pd.DataFrame:
    """全市场 A 股快照（代码 名称 现价 涨跌幅 成交量 成交额 换手率 市盈率 等）"""
    out, page, num = [], 1, 100
    base = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?page={p}&num={n}&sort=symbol&asc=1&node=hs_a"
            "&symbol=&_s_r_a=page")
    while True:
        txt = _fetch(base.format(p=page, n=num),
                     headers={"Referer": "https://finance.sina.com.cn/"})
        txt = txt.strip()
        if not txt or txt in ("null", "[]"):
            break
        try:
            rows = json.loads(txt)
        except Exception:
            rows = json.loads(re.sub(r"(\w+):", r'"\1":', txt))
        if not rows:
            break
        for r in rows:
            out.append({
                "code": norm(r.get("code") or r.get("symbol")),
                "name": r.get("name") or "",
                "price": _f(r.get("trade")),
                "chg_pct": _f(r.get("changepercent")),
                "open": _f(r.get("open")),
                "high": _f(r.get("high")),
                "low": _f(r.get("low")),
                "prev_close": _f(r.get("settlement")),
                "volume": _f(r.get("volume")),          # 股
                "amount": _f(r.get("amount")),          # 元
                "turnover": _f(r.get("turnoverratio")),  # %
                "pe": _f(r.get("per")),
                "pb": _f(r.get("pb")),
                "mktcap": _f(r.get("mktcap")),          # 万元
                "nmc": _f(r.get("nmc")),                # 流通市值 万元
                "volume_ratio": _f(r.get("volume_ratio") or 0),
            })
        if len(rows) < num:
            break
        page += 1
        if page > 90:
            break
    df = pd.DataFrame(out)
    if df.empty:
        raise DataError("股票列表获取失败")
    df = df[df["code"].str.len() == 6]
    return df.reset_index(drop=True)


def _f(v):
    try:
        if v in (None, "", "-", "--"):
            return float("nan")
        return float(v)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------- 实时行情
def realtime(codes) -> pd.DataFrame:
    """新浪实时行情，一次最多 100 个代码。"""
    codes = [full(c) for c in codes]
    rows = []
    for i in range(0, len(codes), 90):
        chunk = codes[i:i + 90]
        txt = _fetch("https://hq.sinajs.cn/list=" + ",".join(chunk),
                     headers={"Referer": "https://finance.sina.com.cn/"})
        for line in txt.split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
            if not m:
                continue
            sym, body = m.group(1), m.group(2)
            p = body.split(",")
            if len(p) < 32:
                continue
            price, prev = _f(p[3]), _f(p[2])
            chg = (price / prev - 1) * 100 if prev else float("nan")
            rows.append({
                "code": norm(sym), "name": p[0], "open": _f(p[1]), "prev_close": prev,
                "price": price, "high": _f(p[4]), "low": _f(p[5]), "bid": _f(p[6]),
                "ask": _f(p[7]), "volume": _f(p[8]), "amount": _f(p[9]),
                "date": p[30], "time": p[31], "chg_pct": chg,
                "avg_price": (_f(p[9]) / _f(p[8])) if _f(p[8]) else float("nan"),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 日线
def _sina_kline(sym: str, scale: int, count: int) -> list:
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_s=/CN_MarketDataService"
           f".getKLineData?symbol={sym}&scale={scale}&ma=no&datalen={count}")
    txt = _fetch(url, headers={"Referer": "https://finance.sina.com.cn/"})
    a, b = txt.find("["), txt.rfind("]")
    if a < 0 or b < 0:
        raise DataError(f"{sym} K 线为空")
    return json.loads(txt[a:b + 1])


def _tencent_kline(sym: str, scale: str, count: int) -> list:
    """腾讯接口（目前部分网络会返回 501，仅作备用）"""
    kind, _, field = scale.partition(":")
    url = f"https://ifzq.gtimg.cn/appstock/app/{kind}?param={sym},{field},,{count},qfq"
    j = json.loads(_fetch(url, headers={"Referer": "https://gu.qq.com/"}))
    node = (j.get("data") or {}).get(sym) or {}
    for k in (f"qfq{field}", field, "day", "m5"):
        if node.get(k):
            return node[k]
    return []


def daily(code: str, count: int = 260) -> pd.DataFrame:
    """
    不复权日线（新浪 scale=240，最多约 300 根）。
    注意：分时均价线策略本质上是"价格 vs 当日 VWAP"，用不复权数据与实盘一致。
    字段: date open close high low volume(股) amount(元)
    """
    sym = full(code)
    arr = _sina_kline(sym, 240, min(int(count), 300))
    rows = []
    for x in arr:
        rows.append({
            "date": x["day"][:10], "open": _f(x["open"]), "close": _f(x["close"]),
            "high": _f(x["high"]), "low": _f(x["low"]), "volume": _f(x.get("volume")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} 日线为空")
    df["amount"] = df["volume"] * (df[["high", "low", "close"]].sum(axis=1) / 3)
    df = df.dropna(subset=["close"]).drop_duplicates("date")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- 5 分钟线
def kline_scale(code: str, scale: int = 30, count: int = 200) -> pd.DataFrame:
    """
    任意分钟周期的 K 线（新浪 scale=5/15/30/60/240）。

    为什么全市场扫描用 30 分钟线而不是 5 分钟线：
      分时均价线就是当日 VWAP = 累计成交额 / 累计成交量，这两个数都是**可累加**的，
      所以只要"切分点"落在同一时刻，30 分钟线算出来的日 VWAP 与 14:30 尾盘 VWAP
      跟 5 分钟线**逐位相同**（本机实测 600519/601021/002415 差值 0.00000%）。
      而 30 分钟线一天只有 8 根，datalen=200 就覆盖 25 个交易日、
      响应体 28KB（5 分钟线 144KB），解析也快一个数量级。

    唯一要注意的：tail_from / preview_at 必须正好落在 30 分钟线的收尾时刻
    （10:00 10:30 11:00 11:30 13:30 14:00 14:30 15:00），否则要用更细的周期，
    这件事交给 store.pick_scale() 自动挑。
    """
    sym = full(code)
    if scale >= 240:
        return daily(code, count)
    arr = _sina_kline(sym, int(scale), min(int(count), 1023))
    rows = [{
        "time": x["day"][:16], "open": _f(x["open"]), "high": _f(x["high"]),
        "low": _f(x["low"]), "close": _f(x["close"]),
        "volume": _f(x.get("volume")), "amount": _f(x.get("amount")),
    } for x in arr]
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} {scale} 分钟线为空")
    df = df[df["close"] > 0].drop_duplicates("time")
    return df.sort_values("time").reset_index(drop=True)


def kline5(code: str, count: int = 1023, source: str = "sina") -> pd.DataFrame:
    """
    5 分钟 K 线（成交量单位：股，成交额单位：元）。
    新浪最大 datalen=1023 ≈ 22 个交易日，胜在快（~100KB）；腾讯 320 根仅 7 天且当前常 501。
    本机实测：100 并发拉 5 分钟线 96/96 成功，2.1s —— 这是全市场扫描的主力数据源。

    注意：全市场扫描现在走 kline_scale(scale=30)，见上面那段说明；
    这个 5 分钟版本留给详情页的"近 5 日分时走势"用，因为那里要更细的颗粒度。
    """
    sym = full(code)
    if source == "tencent":
        arr = _tencent_kline(sym, "kline/mkline", min(int(count), 800))
        rows = []
        for x in arr:
            t = str(x[0])
            rows.append({
                "time": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:00",
                "open": _f(x[1]), "close": _f(x[2]), "high": _f(x[3]),
                "low": _f(x[4]), "volume": _f(x[5]) * 100, "amount": _f(x[6]) * 100,
            })
    else:
        arr = _sina_kline(sym, 5, min(int(count), 1023))
        rows = [{
            "time": x["day"], "open": _f(x["open"]), "high": _f(x["high"]),
            "low": _f(x["low"]), "close": _f(x["close"]),
            "volume": _f(x.get("volume")), "amount": _f(x.get("amount")),
        } for x in arr]
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} 5 分钟线为空")
    df = df[df["close"] > 0].drop_duplicates("time")
    return df.sort_values("time").reset_index(drop=True)


def minute_today(code: str) -> pd.DataFrame:
    """当日分时。优先腾讯逐分钟，失败时用新浪 5 分钟线拼出当日折线。"""
    sym = full(code)
    try:
        url = f"https://ifzq.gtimg.cn/appstock/app/minute/query?code={sym}&r={time.time():.3f}"
        j = json.loads(_fetch(url, headers={"Referer": "https://gu.qq.com/"}))
        d = ((j.get("data") or {}).get(sym) or {}).get("data") or {}
        rows = []
        for line in d.get("data") or []:
            p = line.split()
            if len(p) < 4:
                continue
            t = p[0]
            rows.append({"time": f"{t[:2]}:{t[2:4]}", "price": _f(p[1]),
                         "volume": _f(p[2]) * 100, "amount": _f(p[3])})
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = d.get("date")
            return df
    except Exception:
        pass
    k = kline5(code, 60)
    last_date = str(k["time"].iloc[-1])[:10]
    k = k[k["time"].str.startswith(last_date)].copy()
    k["time"] = k["time"].str[11:16]
    tot = k["amount"].cumsum()
    vol = k["volume"].cumsum()
    k["price"] = k["close"]
    k["avg"] = (tot / vol).where(vol > 0)
    k["date"] = last_date
    return k[["time", "price", "volume", "amount", "date", "avg"]].reset_index(drop=True)
