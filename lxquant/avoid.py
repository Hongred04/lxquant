# -*- coding: utf-8 -*-
"""避雷打分：给每只票算一个「不该买」的分数，用在选股名单上做减法。

为什么做这个：`docs/因子研究-2026-11.md` 里 37 个因子的结论是 —— **alpha 几乎全在空头端**。
只买最好的 20% 年化 1.3%（市场 8.9%）、超额 t=0.36 等于没有；反过来剔除最差的 40%，
年化 8.3% vs 基准 5.4%、回撤还降、夏普 0.25→0.40，而且剔除比例 20/30/40 是单调的。

但那条路走不通：剔除 40% 后要持有 300+ 只，10 万本金买不了。
所以这里只取它的一半 —— **不荐股，只标雷**。名单照旧由 `screener` 出，
这里只回答"这份名单里哪几只是统计上最不该碰的"。

三个因子（方向和 `factor_lab/13_avoid.py` 完全一致，不能改）：
    ma60  = MA60 / 收盘        越高越好。低 = 价格远在均线上方 = 涨过了
    std20 = 20 日收益率标准差    越低越好。高 = 波动太大
    corr20= 收盘与 log(成交量) 的 20 日相关   越低越好。高 = 放量跟得紧

    score = ( rank(ma60) + (1-rank(std20)) + (1-rank(corr20)) ) / 3

三条必须守住的：
1. **只用「最新交易日有行情」的票打分**。日线缓存是按需更新的，实测 5234 只里
   只有 2300 只更新到 11-02，其余停在 10-19~10-23。拿十天前的分数冒充今天，
   比不算还糟 —— 所以池子按最新交易日卡死，池子大小写在界面上。
2. **d_ 是不复权**。除权日的暴跌会被算成真实下跌，把 std20 顶上去，凭空空一只票。
   处理：最近 20 个交易日内出现过 |涨跌| > 21% 的票，本次不打分（窗口被污染）。
3. **不改选股结果**。这里只产出标记，`screener` 照样出它的名单。
   一旦这里开始偷偷删票，用户看到的"命中 50 只"就和实际不符了。
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time

from .config import CACHE_DIR, DATA_DIR

# 打分口径变了就加一版：旧缓存的百分位不能拿来当新算法的结果
CACHE_VERSION = 2

CACHE = DATA_DIR / "avoid.json"

DROP = 0.40          # 剔除比例。研究里 20/30/40 单调变好，取最严的那档
LOOKBACK = 90        # 只读最近 90 个交易日：算 ma60 要 60 天，留一点余量
ABNORMAL = 0.21      # 单日涨跌超过这个数 = 除权/异常

_LOCK = threading.Lock()
_LAST_TRY = [0.0]    # 上次尝试（成功或失败）的时间戳，失败后 60 秒内不重试

# 三项因子点名的措辞。索引对应落盘的四元组 [pct, r_ma, r_std, r_corr]
WHY = {
    "ma60": "价格已经在 60 日均线上方 —— 这套买的是跌下来的，不是追上去的",
    "std20": "波动太大（20 日振幅全市场前列，止损容易被扫）",
    "corr20": "价量同向太强（涨跌都跟着放量，是跟风盘不是错杀）",
}


def _probe_day() -> str:
    """日线缓存最新到哪天。拿 000001 当探针 —— 它没更新，全市场都没更新。"""
    try:
        import pandas as pd
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


def _read_pool(day: str):
    """读全市场日线，只留「最后一天正好是 day」的票。

    返回 (长表, 股票数, 跳过只数)。长表是 concat 后的 date/code/close/volume，
    交给 pivot 做**按日期**对齐 —— 不能用位置对齐：各票长度不同（上市晚、停牌），
    按位置拼会让最后一行错位，而那正是唯一要打分的那一行。
    """
    import pandas as pd

    frames, skipped = [], 0
    for f in sorted(glob.glob(str(CACHE_DIR / "d_*.pkl"))):
        code = os.path.basename(f)[2:-4]
        try:
            df = pd.read_pickle(f)
            if df is None or len(df) < 40:
                skipped += 1
                continue
            tail = df[["date", "close", "volume"]].tail(LOOKBACK).copy()
            # 最后一天对不上的，说明这条缓存没更新到今天 —— 不参与。
            # 这是本模块最要紧的一道门：宁可池子小，不能拿陈数据打分。
            if str(tail["date"].iloc[-1])[:10] != day:
                skipped += 1
                continue
            tail["date"] = tail["date"].astype(str).str[:10]
            tail["code"] = code
            frames.append(tail)
        except Exception:
            skipped += 1
    if not frames:
        return None, 0, skipped
    return pd.concat(frames, ignore_index=True), len(frames), skipped


def build() -> dict:
    """算一遍并落盘。约 20 秒（读 5000 个 pkl 占大头）。"""
    import numpy as np
    import pandas as pd

    t0 = time.time()
    day = _probe_day()
    if not day:
        return {"ok": False, "msg": "没有日线缓存，先跑一次选股"}

    df, n_stock, skipped = _read_pool(day)
    if df is None:
        return {"ok": False, "msg": f"没有一只票的缓存更新到 {day}"}

    C = df.pivot(index="date", columns="code", values="close").astype(float)
    V = df.pivot(index="date", columns="code", values="volume").astype(float)

    # ---- 三个因子 ----
    EPS = 1e-9
    ret = C / C.shift(1) - 1
    ma60 = C.rolling(60, min_periods=30).mean() / (C + EPS)
    std20 = ret.rolling(20, min_periods=10).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        corr20 = C.rolling(20, min_periods=10).corr(np.log(V + 1))

    # 除权：最近 20 个交易日内有过异常涨跌的票，std20/corr20 窗口已被污染
    dirty = (ret.abs() > ABNORMAL).tail(20).any()

    def winsor(x):
        return x.clip(lower=x.quantile(0.01), upper=x.quantile(0.99))

    # 只对最后一行做截面处理 —— 要的是"今天谁最差"，不是历史序列
    r_ma = winsor(ma60.iloc[-1]).rank(pct=True)     # 高 = 价格在均线下方多 = 超跌
    r_std = winsor(std20.iloc[-1]).rank(pct=True)   # 高 = 波动大（差）
    r_corr = winsor(corr20.iloc[-1]).rank(pct=True)  # 高 = 价量同向（差）
    score = ((r_ma + (1 - r_std) + (1 - r_corr)) / 3).where(~dirty)

    score = score[score.notna()]
    if len(score) < 100:
        return {"ok": False, "msg": f"{day} 可打分的票只有 {len(score)} 只，太少"}

    pct = score.rank(pct=True)          # 分数在池子里的百分位，0~1

    def p100(x):
        return int(round(float(x) * 100)) if pd.notna(x) else -1

    # ---- 落盘 ----
    # 存百分位整数而不是原始因子值：界面要说的是"你排在后 8%"，
    # 不是"你的 ma60 是 1.0237"。原始值不落盘，体积省一半以上。
    items = {code: [p100(pct[code]), p100(r_ma[code]), p100(r_std[code]), p100(r_corr[code])]
             for code in score.index}

    data = {
        "v": CACHE_VERSION,
        "asof": day,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pool": int(len(score)),
        "stocks": int(n_stock),
        "skipped": int(skipped),
        "dirty": int(dirty.sum()),
        "drop": DROP,
        "drop_n": int((pct <= DROP).sum()),
        "elapsed": round(time.time() - t0, 1),
        "items": items,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    os.replace(tmp, CACHE)
    _LAST_TRY[0] = time.time()
    return {"ok": True, **{k: v for k, v in data.items() if k != "items"}}


def load() -> dict | None:
    try:
        if not CACHE.exists():
            return None
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or int(d.get("v") or 0) != CACHE_VERSION:
            return None
        return d
    except Exception:
        return None


def _why(rec: list) -> str:
    """把三个百分位翻译成一句人话：到底哪一条让它被剔。

    只点最差的那一项。三项都点等于没点 —— 用户记不住三条，也判断不了该信哪条。
    """
    _, r_ma, r_std, r_corr = rec
    # 统一成"越差数字越小"：ma60 分位低=差；std/corr 分位高=差，取反
    cand = []
    if r_ma >= 0:
        cand.append((r_ma, "ma60"))
    if r_std >= 0:
        cand.append((100 - r_std, "std20"))
    if r_corr >= 0:
        cand.append((100 - r_corr, "corr20"))
    if not cand:
        return "综合分数偏低"
    cand.sort(key=lambda x: x[0])
    return WHY[cand[0][1]]


def annotate(codes: list) -> dict:
    """给一批代码贴标记。选股出名单后调用。

    hit = 池子里查得到的只数（查不到 = 缓存没更新到当天，或新股不够 60 天）；
    n   = 其中被标红的只数。分开报，界面才能说清"几只没数据、几只该躲"。
    """
    d = load()
    if not d:
        return {"ready": False, "items": {}, "n": 0, "hit": 0}
    pool = d.get("items") or {}
    cut = round(float(d.get("drop") or DROP) * 100)
    out, n = {}, 0
    for code in codes:
        rec = pool.get(str(code))
        if not rec:
            continue
        p = int(rec[0])
        bad = p <= cut
        if bad:
            n += 1
        out[str(code)] = {"pct": p, "drop": bad, "why": _why(rec) if bad else ""}
    return {"ready": True, "asof": d.get("asof"), "pool": d.get("pool"),
            "drop": d.get("drop"), "built_at": d.get("built_at"),
            "n": n, "hit": len(out), "items": out}


def view(codes: list | None = None) -> dict:
    """页面用的视图。不带 codes 时只给元信息，不带两千多条明细。"""
    d = load()
    today = _probe_day()
    if not d:
        return {"ready": False, "asof": "", "pool": 0, "today": today, "items": {}}
    meta = {k: d.get(k) for k in
            ("asof", "built_at", "pool", "stocks", "skipped", "dirty",
             "drop", "drop_n", "elapsed")}
    meta["ready"] = True
    meta["today"] = today
    # 缓存之后行情又走了：这份打分不是最新的，界面要说一句
    meta["stale"] = bool(today and d.get("asof") and d["asof"] < today)
    if codes:
        meta.update(annotate(codes))
    return meta


def ensure(fresh_day: str = "") -> dict:
    """确保缓存可用：过期就**在后台**重算，本次先返回旧的。

    不能同步算 —— 20 秒会把请求拖死，而这里只是给名单贴标记，
    晚 20 秒出标记不影响下单（名单本身已经在屏幕上了）。

    节流分两档，这是有区别的：
      * **没有缓存**（第一次打开、或上一次算失败）→ 10 秒就重试。
        用户这时候正盯着「正在算」四个字，让他等满 60 秒还没动静，
        界面就是在撒谎 —— 这是实测踩到的，不是理论担忧。
      * **有缓存但过期** → 60 秒。这时候用的是旧数据，界面正常显示，
        后台慢慢算就行，没必要被每次轮询反复触发。
    """
    d = load()
    day = fresh_day or _probe_day()
    stale = (not d) or (day and d.get("asof") != day)
    wait = 10 if not d else 60

    if stale and time.time() - _LAST_TRY[0] > wait:
        if _LOCK.acquire(blocking=False):
            _LAST_TRY[0] = time.time()

            def _run():
                try:
                    build()
                except Exception:
                    import traceback
                    traceback.print_exc()
                finally:
                    _LOCK.release()

            threading.Thread(target=_run, daemon=True).start()

    return d or {}
