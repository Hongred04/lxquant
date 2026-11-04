# -*- coding: utf-8 -*-
"""大金融中长线：只做一件事 —— 在大盘跌到位时买 1 家银行 + 1 家保险，拿 40 天。

为什么只留这一个策略：
    全样本测下来，所有玩法（波段、轮动、多因子）的收益都落在 3~7%，
    真正拉开差距的是**回撤**和**能不能执行**。大金融 2 只（1 银行 + 1 保险）
    资金效率最高，而且一屏看完，不用每天盯盘。

规则（参数写死，不给调 —— 给的旋钮越多，越容易用过拟合的参数骗自己）：
    进场：**两个条件同时成立**
          ① 上证相对 20 日均线跌幅 > GATE
          ② 上证相对 250 日均线（年线）跌幅 > GATE250
    选股：银行里避差分最高的 1 只 + 保险里最高的 1 只
    卖出：HOLD_DAYS 天后全部卖出，或者提前跌破买入价 STOP_PCT% 就砍（先到先执行）
    仓位：各一半

条件②是 2026-11 换数据源之后才加上去的，来历必须写清楚：
    腾讯全历史（2007-2026，19 年）跑下来，只留条件①的策略最大回撤 -57.3%，
    而且**整段回撤全部发生在 2007-10 → 2008-09**，这 220 个交易日里 99% 的时间满仓 ——
    它不是被一笔交易打穿，是在崩盘里反复进场、反复止损。
    加条件②（只在大盘比年线还低 8% 时抄底）之后：年化 3.1%→4.2%，
    回撤 -57.3%→-36.8%；2010 年以后是 +5.0% / -17.9%。
    阈值不是扫出来的最优点：-8 / -10 / -12 三档年化都在 4.1~4.2%、
    回撤都是 -36.8%，是个平台不是刀尖。

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
from datetime import datetime

from .config import DATA_DIR

GATE = 2.0                  # 条件一：上证相对 MA20 跌幅超过 2%
GATE250 = 8.0               # 条件二：上证相对 MA250（年线）跌幅超过 8%
HOLD_DAYS = 40              # 持有 40 天后卖
STOP_PCT = 8.0              # 或：收盘价跌破买入价 8% 就卖（先到先执行）
QUOTA = (("银行", 1), ("保险", 1))   # 买 1 银行 + 1 保险

CACHE = DATA_DIR / "fin_state.json"
CACHE_VERSION = 6

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


def _drop_unclosed(df, col: str = "date", now=None):
    """丢掉「今天还没收盘」的那根日线。

    行情接口在盘中就会返回一根日期是今天的 K 线，值是实时价。拿它算 vs20 / std20，
    等于让信号随盘中价格漂移：上午 10 点显示「可以买」，下午 2 点可能变「再等等」，
    而用户看到的都是「今天的信号」—— 同一句话两小时后自我否定。

    这套规则的决策基准是**收盘价**（收盘后看信号、次日开盘买），
    所以 15:10 之前一律用昨收。留 10 分钟给数据源把收盘价落定。
    """
    if df is None or not len(df):
        return df
    now = now or datetime.now()
    if (now.hour, now.minute) >= (15, 10):
        return df
    today = now.strftime("%Y-%m-%d")
    s = df[col].astype(str).str[:10]
    return df[s < today].reset_index(drop=True)


def _gap(vs20: float, gate: float) -> float:
    """离进场线还差几个百分点；0 表示已经在窗口里。

    只测过三种错法：`gate - |vs20|`（均线上方时把 3.2 算成 0.8）、
    `-vs20 - gate`（已跌破时算出 0.89 这种正数）、忘记 max。
    正确就是 `vs20 + gate` 再截 0。
    """
    return round(max(0.0, vs20 + gate), 2)


def _allow(vs20: float, vs250: float) -> bool:
    """两个条件同时成立才放行。抽成函数是为了能单测 —— 不能为了测它去联网。

    只留 vs20 那一条时，2008 那种单边下跌里几乎天天"跌到位"，
    买完几天就被止损打出来，然后再买 —— 19 年回测的最大回撤 -57.3%
    全部发生在那一年的 220 个交易日里，是这么反复磨出来的。
    """
    return (vs20 < -GATE) and (vs250 < -GATE250)


def _index_close():
    """上证收盘价序列：本地长表打底，新浪补最新，再裁掉未收盘的那根。

    为什么不能只用 `datasource.index_daily`：它走新浪，`datalen` 上限 1023 根
    = 4.2 年。个股有 19.7 年、指数只有 4.2 年，拼在一起就是「长回测实际
    只跑了 4 年」（2022 年之前 vs20 全 NaN，被当成空仓）。

    两家在重叠日期的收盘价最大差 0.005（四舍五入），所以拼接是安全的。
    """
    import pandas as pd
    from . import datasource as ds

    px = None
    f = DATA_DIR / "idx_long.pkl"
    if f.exists():
        try:
            d = pd.read_pickle(f)
            px = d.set_index("date")["close"].astype(float)
        except Exception:
            px = None

    try:
        a = ds.index_daily("sh000001")
        a["date"] = a["date"].astype(str).str[:10]
        s = a.set_index("date")["close"].astype(float)
        if px is None or len(px) < 200:
            px = s
        elif len(s) and s.index[-1] > px.index[-1]:
            px = pd.concat([px, s[s.index > px.index[-1]]])
    except Exception:
        pass

    if px is None or not len(px):
        raise RuntimeError("拿不到上证指数")

    px = px[~px.index.duplicated(keep="last")].sort_index()
    now = datetime.now()
    if (now.hour, now.minute) < (15, 10):
        px = px[px.index < now.strftime("%Y-%m-%d")]
    return px


def _probe() -> str:
    """日线缓存最新到哪天（只算已收盘的）。

    这里必须和 build() 用同一套口径。原来直接取最后一根，盘中会拿到今天的
    实时价那根，于是 `asof(昨收) < probe(今天)` 永远成立 → ensure() 认为
    「缓存过期」，每 60 秒重算一遍，白烧 CPU 而结果一个字都不变。
    """
    try:
        import pandas as pd
        from .config import CACHE_DIR
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        df = _drop_unclosed(df)
        if df is None or not len(df):
            return ""
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


def _factors(df):
    """单只票的三个因子（只算最后一行，不需要整段序列）。"""
    import numpy as np

    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    # 必须 60 根：ma60 是 c.tail(60).mean()，只有 40 根时 pandas 会静默算成
    # 40 日均线，把「上市两个月的新股」判成「跌破 60 日线」—— 凭空给高分。
    if len(c) < 60:
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

    # 指数先算：它的最新收盘日决定「个股缓存算不算新」。
    # 收盘后个股缓存可能还停在盘中那根（被 _drop_unclosed 丢掉），
    # 于是指数已经到 11-04、信号还停在 11-03 —— 用户会以为软件没更新。
    ix_close = _index_close()
    ix_last = str(ix_close.index[-1])[:10]
    refetch = 0

    # ---- 1. 逐只算因子 ----
    raw = {}          # code -> (ma60, std20, corr20)
    meta = {}         # code -> (name, board)
    price = {}
    chg = {}          # code -> 当日涨跌幅（%），卡片上要显示，不给的话只能看到价格没有方向
    failed = 0
    for board, items in POOL.items():
        for code, name in items:
            try:
                df = store.get_kline(code, "day", 120)
                df = _drop_unclosed(df)
                # 落后于指数就强制重拉一次（每天收盘后第一次会走这里，其余时间命中缓存）
                if df is not None and len(df) and str(df["date"].iloc[-1])[:10] < ix_last:
                    df = _drop_unclosed(store.get_kline(code, "day", 120, force=True))
                    refetch += 1
                if df is None or len(df) < 40:
                    failed += 1
                    continue
                f = _factors(df)
                if f is None:
                    failed += 1
                    continue
                raw[code] = f
                meta[code] = (name, board)
                c = df["close"].astype(float)
                price[code] = float(c.iloc[-1])
                prev = float(c.iloc[-2]) if len(c) > 1 else 0.0
                chg[code] = round((price[code] / prev - 1) * 100, 2) if prev > 0 else 0.0
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
    # 复用第 1 步算好的指数（长表打底 + 新浪补最新 + 裁掉未收盘）。
    close = ix_close
    spot = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else spot
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    ma250 = float(close.tail(250).mean())
    vs20 = float((spot / ma20 - 1) * 100)
    vs60 = float((spot / ma60 - 1) * 100)
    vs250 = float((spot / ma250 - 1) * 100)
    ix_chg = float((spot / prev - 1) * 100) if prev > 0 else 0.0
    # 两个条件必须同时成立。只看 vs20 会在熊市里天天"跌到位"，
    # 19 年回测的口径差就从这里来（-57.3% 的回撤全在 2008 那一段）。
    allow = _allow(vs20, vs250)

    # 最近 120 天的偏离度序列：界面上画成一条迷你轨道图，
    # 让「现在离进场线还有多远」变成看得见的位置，而不是只有一个百分数。
    ser = ((close / close.rolling(20, min_periods=10).mean() - 1) * 100).tail(120)

    # ---- 4. 按配额选股 ----
    picks = []
    for board, k in QUOTA:
        cand = [c for c in score if meta[c][1] == board]
        cand.sort(key=lambda c: -score[c])
        total = len(cand)
        for n, c in enumerate(cand[:k], 1):
            picks.append({
                "code": c, "name": meta[c][0], "board": board,
                "score": round(score[c], 0), "price": round(price[c], 2),
                "chg": chg.get(c, 0.0),
                # 三条因子的原始值一起给出：卡片上要能回答「为什么是它」
                "ma60r": round((raw[c][0] - 1) * 100, 1),
                "std20": round(raw[c][1] * 100, 2),
                "corr20": round(raw[c][2], 2),
                "rank": n, "rank_total": total,
            })

    data = {
        "v": CACHE_VERSION,
        "asof": str(close.index[-1])[:10],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vs20": round(vs20, 2),
        "gate": GATE,
        "gate250": GATE250,
        "allow": bool(allow),
        "hold_days": HOLD_DAYS,
        "stop_pct": STOP_PCT,
        "picks": picks,
        "market": {
            "spot": round(spot, 2),
            # 当日涨跌：顶栏要和「上证 3604」并排显示，不能拿 vs20 顶替 ——
            # vs20 是「相对 20 日线」，和「今天涨了几个点」是两件事，
            # 位置挨在一起，用户一定读成当日涨跌。
            "chg": round(ix_chg, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma250": round(ma250, 2),
            "vs60": round(vs60, 2),
            "vs250": round(vs250, 2),
            # 还差多少才到进场线：0 表示已经到了。
            # 公式是 vs20 + GATE（跌破时为负、取 0），不是「GATE - |vs20|」——
            # 后者在均线上方会算错（v=+1.2 时还差 3.2，不是 0.8），
            # 而前者取反写（-vs20-GATE）会在已跌破时算出 0.89 这种鬼数字。
            "gap": _gap(vs20, GATE),
            "gap250": _gap(vs250, GATE250),
            "ser": [[str(d), round(float(v), 2)] for d, v in ser.items()],
        },
        "scanned": len(raw),
        "failed": failed,
        "refetch": refetch,
        "elapsed": round(time.time() - t0, 1),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.parent / (CACHE.name + ".tmp")
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
    # asof 缺失（老版本缓存/文件被改坏）必须当成过期 —— 原来写成
    # `d.get("asof") and ...`，缺字段时整个表达式是 None，判成「不过期」，
    # 于是一份没有日期的缓存会被永远用下去。
    stale = (not d) or (not d.get("asof")) or (day and d["asof"] < day)
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
