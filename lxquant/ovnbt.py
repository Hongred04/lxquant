# -*- coding: utf-8 -*-
"""隔夜低吸的历史净值曲线（回测）—— 回答「这套规则到底赚不赚钱」。

和 overnight.py 的分工：

    overnight.py   记**已经发生的**每一笔（账本）。笔数少，攒够样本要几个月。
    ovnbt.py       用同一套规则跑**全市场历史**，第一天就能给出一条收益率曲线。

账本回答「我执行得怎么样」，曲线回答「规则本身成不成立」。两件事不能混。

────────────────────────────────────────────────────────────────
三个口径，必须写在界面上，否则数字会被误读
────────────────────────────────────────────────────────────────
1. **买入价用信号日收盘价、卖出价用次日收盘价。**
   实盘是 14:40 的快照价、次日 14:50 的价，日线上都拿不到，只能用收盘价近似。
   这是本模块唯一无法消除的误差源 —— 不许把它当成精确回测来宣传。

2. **同一买入日多笔按等权分配，日收益取算术均值后复利。**
   曲线等价于"每天满仓、收益全额再投入"。实盘不可能天天满仓，
   所以累计跌幅看着比账面体验更狠，这是复利口径的固有特征，不是 bug。

3. **一字跌停卖不掉的顺延到下一个交易日（最多 3 天）**，和 `overnight.do_settle` 一致。
   少了这一条会高估约 0.15 个百分点/笔（实测 352 笔：-1.46% → -1.61%）。

────────────────────────────────────────────────────────────────
两条独立样本，同向才算数（该项目一贯的验证标准）
────────────────────────────────────────────────────────────────
    d_    全市场 5290 只，1.3 年，不复权  —— 样本量大，主曲线用它
    dl_   512 只，4.2 年，前复权          —— 口径干净，只作交叉验证

不复权为什么不影响结论：单日涨跌超过 21% 的整行剔除（除权日必然触发），
持仓只有 1 天，除权落在持仓窗口内的概率极低。而前复权样本池只有 512 只，
代表性弱得多 —— 所以主图用全市场，前复权那条只用来确认方向。
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time

from . import limitup
from .config import CACHE_DIR, DATA_DIR

# ---------------------------------------------------------------- 参数
# 和 overnight.py 的常量保持同源：改那边就要同步改这里，不然曲线和账本对不上。
MIN_STREAK = 3          # 前一交易日连板 ≥3
YIN_MAX = 0.99          # 收盘 ≤ 开盘 × 0.99 = 实体阴线至少 1%
MIN_BARS = 40           # 上市不足 40 根的不参与（次新连板是另一套逻辑）
WARMUP = 30             # 前 30 根不出信号（连板序列需要上下文）
MAX_DEFER = 3           # 一字跌停最多扛 3 天（= do_settle 的 deferred <= 3）
ABNORMAL = 0.21         # 单日涨跌 >21%：除权/异常，整行剔除

DIR = DATA_DIR / "overnight"
CACHE = DIR / "curve.json"

# 主口径 / 交叉验证口径。顺序有意义：第一个是主图。
SCOPES = [
    ("d", "全市场", "不复权 · 日线缓存全部标的"),
    ("dl", "前复权样本池", "512 只 · 4.2 年 · 用来交叉验证方向"),
]

_REBUILD_LOCK = threading.Lock()
_BUILDING = [False]       # 用 list 装，省一个 global
_LAST_TRY = [0.0]         # 上次尝试时刻，失败时节流，避免每 3 秒重跑一次全市场
_LAST_ERR = [""]


# ---------------------------------------------------------------- 数据读取
def _names() -> dict:
    """股票名单：只读盘上的快照，**绝不联网**。

    回测在后台线程里跑 30 秒，卡在网络请求上就白算了；名称只用来挡 ST/北交所，
    拿一份几小时前的快照完全够用。没有快照就退化成空表 —— 只少一层过滤，不会崩。
    """
    import pandas as pd
    p = CACHE_DIR / "stock_list.pkl"
    if not p.exists():
        return {}
    try:
        df = pd.read_pickle(p)
        return dict(zip(df["code"].astype(str), df["name"].astype(str)))
    except Exception:
        return {}


def latest_day() -> str:
    """日线缓存更新到哪一天（拿 000001 当探针，和 overnight._probe_cache_date 同法）"""
    try:
        import pandas as pd
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


# ---------------------------------------------------------------- 核心扫描
def _sell_index(h, lo, c, pc, i: int, lim: float, n: int) -> tuple:
    """从 i+1 起找第一个能卖出的交易日，返回 (下标, 顺延次数)。

    一字跌停（最高=最低 且 收盘贴跌停）当天卖不掉，只能顺延，最多扛 MAX_DEFER 天；
    扛满了也跑不掉就按当天收盘强结，和 `overnight.do_settle` 的处理一致。

    单独成函数是为了可测：顺延与否每笔差 0.15 个百分点（352 笔实测 -1.46% vs -1.61%），
    这种量级的口径错误从曲线上看不出来，只能靠单测钉住。

    边界（`defer < MAX_DEFER` 而不是 `<=`）：原定卖点是 i+1，往后顺延 MAX_DEFER 次
    最多到 i+1+MAX_DEFER。写成 `<=` 会多扛一天 —— 看着只差一天，但和
    `do_settle` 的 deferred 计数对不上，账本和曲线就会出现两种口径。
    """
    j, defer = i + 1, 0
    while j < n and defer < MAX_DEFER:
        stuck = (h[j] - lo[j] < 1e-6 and pc[j] > 0
                 and c[j] <= pc[j] * (1 - lim + limitup.TOL))
        if not stuck:
            break
        j += 1
        defer += 1
    return j, defer


def _scan(prefix: str, names: dict) -> tuple:
    """扫一个口径，返回 (逐笔记录, 全部出现过的交易日)。

    逐只票一遍循环，不做跨票对齐 —— 每只票的连板序列只跟自己有关，
    拼在一起反而容易在停牌缺口上算错。
    """
    import pandas as pd

    files = sorted(glob.glob(str(CACHE_DIR / f"{prefix}_*.pkl")))
    rows, days = [], set()

    for f in files:
        code = os.path.basename(f).split(f"{prefix}_")[-1].replace(".pkl", "")
        nm = names.get(code, "")
        if not limitup.tradeable(code, nm):
            continue
        try:
            df = pd.read_pickle(f)
        except Exception:
            continue
        if df is None or len(df) < MIN_BARS:
            continue

        d = df.copy()
        d["date"] = d["date"].astype(str).str.slice(0, 10)
        d = d.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        if (d[["open", "close", "high", "low"]] <= 0).any().any():
            continue

        # 除权/异常整行剔除：不剔的话，除权日会被当成涨停，连板数从那天起全错，
        # 而且错得看不出来（这正是 overnight._rebuild_history 里同一条规则）。
        d["prev"] = d["close"].shift(1)
        d["chg"] = d["close"] / d["prev"] - 1
        d = d[(d["chg"].abs() <= ABNORMAL) | d["chg"].isna()].reset_index(drop=True)
        d["prev"] = d["close"].shift(1)
        d["chg"] = d["close"] / d["prev"] - 1

        lim = limitup.limit_pct(code, nm)
        d["lu"] = d["chg"] >= lim - limitup.TOL
        d["streak"] = limitup.streaks(d["lu"].tolist())

        o, c = d["open"].values, d["close"].values
        h, lo = d["high"].values, d["low"].values
        pc, stk, dt = d["prev"].values, d["streak"].values, d["date"].values
        n = len(d)
        days.update(dt.tolist())

        for i in range(WARMUP, n - 1):
            if stk[i - 1] < MIN_STREAK:
                continue
            if not (c[i] <= o[i] * YIN_MAX and c[i] < pc[i]):
                continue

            # 次日收盘卖 ≈ 实盘次日 14:50 卖。一字跌停卖不掉就顺延。
            j, defer = _sell_index(h, lo, c, pc, i, lim, n)
            if j >= n or c[j] <= 0:
                continue

            rows.append({
                "date": str(dt[i]), "sell_date": str(dt[j]), "code": code, "name": nm,
                "streak": int(stk[i - 1]),
                "buy": round(float(c[i]), 3), "sell": round(float(c[j]), 3),
                "hold": int(j - i), "defer": defer,
                "ret": round((c[j] / c[i] - 1) * 100, 2),
            })
    return rows, days


# ---------------------------------------------------------------- 汇总
def _curve(rows: list) -> list:
    """按**卖出日**聚合 → 等权、逐日复利的累计收益率曲线 [[日期, 百分比], ...]。

    为什么按卖出日而不是买入日：钱是卖出那一刻才变的。记在买入日会让曲线
    比真实资金早一天跳动，看图的人会以为"当天买当天就有盈亏"（那正是 T+0 的错觉）。
    起点补一个 [首个买入日, 0]：刚建仓、还没结算，资金原封不动。
    """
    by = {}
    for r in rows:
        by.setdefault(r["sell_date"], []).append(float(r["ret"]))
    if not by:
        return []
    eq, pts = 1.0, [[min(r["date"] for r in rows), 0.0]]
    for dt in sorted(by):
        v = by[dt]
        eq *= 1 + (sum(v) / len(v)) / 100
        pts.append([dt, round((eq - 1) * 100, 2)])
    return pts


def _kpi(rows: list, pts: list, days: set) -> dict:
    """一条曲线的全部指标。空样本返回 None 字段，界面显示「—」。"""
    if not rows or not pts:
        return {"n": 0, "avg": None, "med": None, "win": None, "payoff": None,
                "total": None, "mdd": None, "signal_days": 0, "span": 0, "util": None}

    r = sorted(float(x["ret"]) for x in rows)
    win = [x for x in r if x > 0]
    loss = [x for x in r if x <= 0]
    payoff = ((sum(win) / len(win)) / abs(sum(loss) / len(loss))
              if win and loss and sum(loss) else None)

    # 最大回撤要在**净值**上算，不是在收益率上：-20% 之后再来 -20% 是 -36%，不是 -40%。
    eq, peak, mdd = 1.0, 1.0, 0.0
    for _, pct in pts:
        eq = 1 + pct / 100
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)

    first, last = pts[0][0], pts[-1][0]
    span = len([d for d in days if first <= d <= last]) or len(pts)
    # pts[0] 是建仓点（0%），不是一次结算，别把它算成"有票可买的日子"。
    n_days = max(len(pts) - 1, 0)

    return {
        "n": len(r),
        "avg": round(sum(r) / len(r), 2),
        "med": round(r[len(r) // 2], 2),
        "win": round(len(win) / len(r) * 100, 1),
        "payoff": round(payoff, 2) if payoff else None,
        "total": pts[-1][1],
        "mdd": round(mdd * 100, 1),
        "signal_days": n_days,
        "span": span,
        # 资金利用率：一年里有多少个交易日真的有票可买。低 = 大部分时间空仓。
        "util": round(n_days / span * 100, 1) if span else None,
    }


def _yearly(rows: list) -> list:
    """分年统计。逐年都负才叫"稳定亏"，有的年份正就得说清楚是哪一年。"""
    by = {}
    for x in rows:
        by.setdefault(str(x["date"])[:4], []).append(float(x["ret"]))
    out = []
    for y in sorted(by):
        v = by[y]
        out.append({"y": int(y), "n": len(v),
                    "avg": round(sum(v) / len(v), 2),
                    "win": round(len([z for z in v if z > 0]) / len(v) * 100, 1)})
    return out


def _pack(key: str, label: str, caliber: str, rows: list, days: set) -> dict:
    pts = _curve(rows)
    return {
        "key": key, "label": label, "caliber": caliber,
        "curve": pts, "kpi": _kpi(rows, pts, days), "yearly": _yearly(rows),
        "first": pts[0][0] if pts else "", "last": pts[-1][0] if pts else "",
    }


# ---------------------------------------------------------------- 构建 / 缓存
def build() -> dict:
    """跑一遍全部口径，写进 `data/overnight/curve.json`。约 35 秒。

    为什么落盘而不是每个请求现算：全市场 5290 个 pkl 读完就要 8 秒，
    整段 35 秒 —— 放在 HTTP 请求里必然超时。曲线一天只需要重算一次。
    """
    names = _names()
    t0 = time.time()
    scopes = {}
    for key, label, caliber in SCOPES:
        rows, days = _scan(key, names)
        scopes[key] = _pack(key, label, caliber, rows, days)

    data = {
        "asof": latest_day(),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 1),
        "scopes": scopes,
    }
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, CACHE)      # 原子替换：算到一半被关掉也不会留下半个 JSON
    return data


def load() -> dict | None:
    try:
        if not CACHE.exists():
            return None
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _run_build() -> None:
    try:
        build()
        _LAST_ERR[0] = ""
    except Exception as e:
        _LAST_ERR[0] = f"{type(e).__name__}: {e}"
        try:
            from . import runlog
            runlog.warn("隔夜低吸曲线重算失败", err=_LAST_ERR[0])
        except Exception:
            pass
    finally:
        _BUILDING[0] = False


def rebuild_async() -> bool:
    """起一个后台线程重算。已经在算就返回 False，不排队、不重复跑。

    回测不是关键路径：算不出来时页面显示上一次的曲线 + 「数据截止 X 日」，
    绝不能让「曲线还没算好」把整个隔夜低吸页卡住。
    """
    with _REBUILD_LOCK:
        if _BUILDING[0]:
            return False
        _BUILDING[0] = True
    _LAST_TRY[0] = time.time()
    threading.Thread(target=_run_build, daemon=True, name="ovnbt").start()
    return True


# ---------------------------------------------------------------- 给界面
def view() -> dict:
    """前端要的全部内容：曲线 + 指标 + 是否过期 / 是否正在算。

    过期（asof < 日线最新日）时**先返回旧曲线**，同时在后台重算 ——
    首屏永远是秒开的，用户不会对着转圈等 35 秒。
    """
    c = load()
    today = latest_day()
    stale = bool(c and today and str(c.get("asof") or "") < today)

    # 过期就补算，但失败时 60 秒内不再重试：否则页面每轮询一次就烧 35 秒 CPU。
    if (c is None or stale) and not _BUILDING[0] and time.time() - _LAST_TRY[0] > 60:
        rebuild_async()

    if not c:
        return {"ready": False, "building": _BUILDING[0], "stale": False,
                "error": _LAST_ERR[0], "asof": "", "built_at": "",
                "main": None, "cross": None}

    scopes = c.get("scopes") or {}
    main = scopes.get(SCOPES[0][0])
    cross = scopes.get(SCOPES[1][0])
    return {
        "ready": bool(main and main.get("curve")),
        "building": _BUILDING[0],
        "stale": stale,
        "error": _LAST_ERR[0],
        "asof": c.get("asof") or "",
        "built_at": c.get("built_at") or "",
        "seconds": c.get("seconds"),
        "main": main, "cross": cross,
    }
