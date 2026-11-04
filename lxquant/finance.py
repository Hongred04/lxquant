# -*- coding: utf-8 -*-
"""大金融中长线：只做一件事 —— 在大盘跌到位时买 1 家银行 + 1 家保险，拿 40 天。

为什么只留这一个策略：
    10.8 年、5559 只、前复权的全样本测下来，所有能做到的方案收益都落在 5~7%，
    真正拉开差距的是**回撤**和**能不能执行**。大金融 2 只（1 银行 + 1 保险）
    是年化 6.5% / 回撤 -7.6% / 夏普 0.88 / 10 次调仓，资金效率最高，
    而且一屏看完，不用每天盯盘。

规则（参数写死，不给调 —— 给的旋钮越多，越容易用过拟合的参数骗自己）：
    进场：上证指数相对 20 日均线跌幅 > GATE
    选股：银行里避差分最高的 1 只 + 保险里最高的 1 只
    持有：HOLD_DAYS 天后全部卖出，中途不看
    仓位：各一半

避差分（和 factor_lab 里验证过的一致，不能改方向）：
    ma60 = MA60 / 收盘      越高越好（价格在均线下方多 = 超跌）
    std20 = 20 日收益率标准差  越低越好
    corr20 = 收盘与 log(成交量) 的 20 日相关  越低越好
    score = (rank(ma60) + (1-rank(std20)) + (1-rank(corr20))) / 3   —— 板块内排名
"""
from __future__ import annotations

import json
import os
import threading
import time

from .config import DATA_DIR

GATE = 2.0                  # 上证相对 MA20 跌幅超过 2% 才买
HOLD_DAYS = 40              # 持有 40 天后卖
QUOTA = (("银行", 1), ("保险", 1))   # 买 1 银行 + 1 保险

CACHE = DATA_DIR / "fin_state.json"
CACHE_VERSION = 3

# 大金融池：按板块分组，板块内按代码排序（顺序固定，方便分位复现）
POOL = {
    "银行": (
        ("000001", "平安银行"), ("001227", "兰州银行"), ("002142", "宁波银行"), ("002807", "江阴银行"),
        ("002936", "郑州银行"), ("002948", "青岛银行"), ("002966", "苏州银行"), ("600000", "浦发银行"),
        ("600015", "华夏银行"), ("600016", "民生银行"), ("600036", "招商银行"), ("600908", "无锡银行"),
        ("600919", "江苏银行"), ("600926", "杭州银行"), ("600928", "西安银行"), ("601009", "南京银行"),
        ("601128", "常熟银行"), ("601166", "兴业银行"), ("601169", "北京银行"), ("601187", "厦门银行"),
        ("601229", "上海银行"), ("601288", "农业银行"), ("601328", "交通银行"), ("601398", "工商银行"),
        ("601528", "瑞丰银行"), ("601577", "长沙银行"), ("601658", "邮储银行"), ("601665", "齐鲁银行"),
        ("601818", "光大银行"), ("601838", "成都银行"), ("601860", "紫金银行"), ("601916", "浙商银行"),
        ("601939", "建设银行"), ("601963", "重庆银行"), ("601988", "中国银行"), ("601997", "贵阳银行"),
        ("601998", "中信银行"), ("603323", "苏农银行"),
    ),
    "保险": (
        ("601318", "中国平安"), ("601319", "中国人保"), ("601336", "新华保险"), ("601601", "中国太保"),
        ("601628", "中国人寿"),
    ),
    "券商": (
        ("000686", "东北证券"), ("000728", "国元证券"), ("000750", "国海证券"), ("000776", "广发证券"),
        ("000783", "长江证券"), ("002500", "山西证券"), ("002670", "国盛证券"), ("002673", "西部证券"),
        ("002736", "国信证券"), ("002926", "华西证券"), ("002939", "长城证券"), ("002945", "华林证券"),
        ("600030", "中信证券"), ("600109", "国金证券"), ("600369", "西南证券"), ("600906", "财达证券"),
        ("600909", "华安证券"), ("600918", "中泰证券"), ("600958", "东方证券"), ("600999", "招商证券"),
        ("601108", "财通证券"), ("601136", "首创证券"), ("601162", "天风证券"), ("601236", "红塔证券"),
        ("601375", "中原证券"), ("601377", "兴业证券"), ("601555", "东吴证券"), ("601688", "华泰证券"),
        ("601696", "中银证券"), ("601788", "光大证券"), ("601878", "浙商证券"), ("601901", "方正证券"),
        ("601990", "南京证券"),
    ),
    "期货": (
        ("001236", "弘业期货"), ("002961", "瑞达期货"), ("600927", "永安期货"), ("603093", "南华期货"),
    ),
    "信托": (
        ("600816", "建元信托"),
    ),
}

_LOCK = threading.Lock()
_LAST_TRY = [0.0]


def _probe() -> str:
    """日线缓存最新到哪天。"""
    try:
        import pandas as pd
        from .config import CACHE_DIR
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


def _factors(df):
    """单只票的三个因子（只算最后一行，不需要整段序列）。"""
    import numpy as np

    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    if len(c) < 40:
        return None
    ret = c.pct_change()
    # 除权/异常：最近 20 天有 |涨跌|>21% 的算不准，跳过
    if (ret.abs() > 0.21).tail(20).any():
        return None
    ma60 = float(c.tail(60).mean() / c.iloc[-1]) if c.iloc[-1] > 0 else np.nan
    std20 = float(ret.tail(20).std())
    # 价量相关：成交量取对数，避免量纲影响
    cv = np.corrcoef(c.tail(20).values, np.log(v.tail(20).values + 1))[0, 1]
    if not all(np.isfinite(x) for x in (ma60, std20, cv)):
        return None
    return ma60, std20, float(cv)


def build() -> dict:
    """算一遍并落盘。首次约 20 秒（81 只票要拉日线）。"""
    import numpy as np
    from . import datasource as ds
    from . import store

    t0 = time.time()
    day = _probe()

    # ---- 1. 逐只算因子 ----
    raw = {}          # code -> (ma60, std20, corr20)
    meta = {}         # code -> (name, board)
    price = {}
    failed = 0
    for board, items in POOL.items():
        for code, name in items:
            try:
                df = store.get_kline(code, "day", 120)
                if df is None or len(df) < 40:
                    failed += 1
                    continue
                f = _factors(df)
                if f is None:
                    failed += 1
                    continue
                raw[code] = f
                meta[code] = (name, board)
                price[code] = float(df["close"].iloc[-1])
            except Exception:
                failed += 1

    if len(raw) < 20:
        return {"ok": False, "msg": "大金融行情没取到，稍后再试"}

    # ---- 2. 板块内截面排名 ----
    # 为什么板块内排而不是全局排：券商波动天然比银行大，
    # 混在一起排会让券商的 std20 永远偏高、永远排最后，等于没选。
    score = {}
    for board in {b for _, b in meta.values()}:
        codes = [c for c, (n, b) in meta.items() if b == board]
        if len(codes) < 2:
            for c in codes:
                score[c] = 50.0
            continue
        ma = np.array([raw[c][0] for c in codes])
        sd = np.array([raw[c][1] for c in codes])
        cv = np.array([raw[c][2] for c in codes])

        def rank(x):
            order = np.argsort(np.argsort(x))           # 0..n-1
            return (order + 0.5) / len(x) * 100          # 百分位

        s = (rank(ma) + (100 - rank(sd)) + (100 - rank(cv))) / 3
        for c, v in zip(codes, s):
            score[c] = float(v)

    # ---- 3. 择时 ----
    ix = ds.index_daily("sh000001")
    ix = ix.sort_values("date")
    close = ix["close"].astype(float)
    ma20 = close.tail(20).mean()
    vs20 = float((close.iloc[-1] / ma20 - 1) * 100)
    allow = vs20 < -GATE

    # ---- 4. 按配额选股 ----
    picks = []
    for board, k in QUOTA:
        cand = [c for c in score if meta[c][1] == board]
        cand.sort(key=lambda c: -score[c])
        for c in cand[:k]:
            picks.append({
                "code": c, "name": meta[c][0], "board": board,
                "score": round(score[c], 0), "price": round(price[c], 2),
            })

    data = {
        "v": CACHE_VERSION,
        "asof": str(ix["date"].iloc[-1])[:10],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vs20": round(vs20, 2),
        "gate": GATE,
        "allow": bool(allow),
        "hold_days": HOLD_DAYS,
        "picks": picks,
        "scanned": len(raw),
        "failed": failed,
        "elapsed": round(time.time() - t0, 1),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE)
    _LAST_TRY[0] = time.time()
    return {"ok": True, **data}


def load():
    try:
        if not CACHE.exists():
            return None
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or int(d.get("v") or 0) != CACHE_VERSION:
            return None
        return d
    except Exception:
        return None


def view() -> dict:
    d = load()
    if not d:
        return {"ready": False, "picks": [], "allow": False}
    d = dict(d)
    d["ready"] = True
    return d


def ensure() -> None:
    """缓存没有或在 10 分钟内过旧就后台重算。"""
    d = load()
    day = _probe()
    stale = (not d) or (day and d.get("asof") and d["asof"] < day)
    if not stale or time.time() - _LAST_TRY[0] < (10 if not d else 60):
        return
    if not _LOCK.acquire(blocking=False):
        return
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
