# -*- coding: utf-8 -*-
"""
技术指标库（公式口径参考 QUANTAXIS 的 QAIndicator / MyTT 实现）

QUANTAXIS 的指标模块有两个值得借鉴的点：
  1. 全部用**通达信/麦语言公式**的原始定义（SMA(X,N,M) 是带权重的递推均值，
     和 pandas 的 ewm(span=N) 不是一回事），这样算出来的 MACD/KDJ 和看盘软件一致；
  2. 指标统一返回**序列**而不是最后一个值，方便绘图和批量 apply。

本模块只依赖 numpy/pandas，全部是纯函数（输入 Series/ndarray，输出 Series）。
"""
import numpy as np
import pandas as pd


def _s(x):
    return x if isinstance(x, pd.Series) else pd.Series(np.asarray(x, dtype=float))


def MA(x, n=5):
    return _s(x).rolling(int(n), min_periods=1).mean()


def EMA(x, n=12):
    return _s(x).ewm(span=int(n), adjust=False).mean()


def SMA(x, n, m=1):
    """通达信 SMA(X,N,M) = (M*X + (N-M)*SMA_prev) / N，等价于 alpha=M/N 的 EMA"""
    return _s(x).ewm(alpha=float(m) / float(n), adjust=False).mean()


def HHV(x, n):
    return _s(x).rolling(int(n), min_periods=1).max()


def LLV(x, n):
    return _s(x).rolling(int(n), min_periods=1).min()


def STD(x, n):
    return _s(x).rolling(int(n), min_periods=2).std(ddof=0)


def REF(x, n=1):
    return _s(x).shift(int(n))


def CROSS(a, b):
    a, b = _s(a), _s(b)
    return (a > b) & (a.shift(1) <= b.shift(1))


# ------------------------------------------------------------------ 指标
def MACD(close, short=12, long=26, m=9):
    """返回 (DIF, DEA, MACD柱)；MACD 柱 = (DIF-DEA)*2"""
    c = _s(close)
    dif = EMA(c, short) - EMA(c, long)
    dea = EMA(dif, m)
    return dif, dea, (dif - dea) * 2


def KDJ(high, low, close, n=9, m1=3, m2=3):
    h, l, c = _s(high), _s(low), _s(close)
    hh, ll = HHV(h, n), LLV(l, n)
    rng = (hh - ll).replace(0, np.nan)
    rsv = ((c - ll) / rng * 100).fillna(50.0)
    k = SMA(rsv, m1, 1)
    d = SMA(k, m2, 1)
    return k, d, 3 * k - 2 * d


def RSI(close, n=14):
    c = _s(close)
    lc = REF(c, 1)
    up = (c - lc).clip(lower=0)
    total = (c - lc).abs()
    den = SMA(total, n, 1).replace(0, np.nan)
    return (SMA(up, n, 1) / den * 100).fillna(50.0)


def BOLL(close, n=20, p=2):
    """返回 (上轨, 中轨, 下轨)"""
    c = _s(close)
    mid = MA(c, n)
    sd = STD(c, n)
    return mid + p * sd, mid, mid - p * sd


def ATR(high, low, close, n=14):
    h, l, c = _s(high), _s(low), _s(close)
    pc = REF(c, 1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return SMA(tr, n, 1)


def OBV(close, volume):
    c, v = _s(close), _s(volume)
    sign = np.sign(c.diff().fillna(0.0))
    return (sign * v).cumsum()


def VOL_RATIO(volume, n=5):
    """量比：当日成交量 / 前 N 日均量"""
    v = _s(volume)
    base = v.shift(1).rolling(int(n), min_periods=1).mean().replace(0, np.nan)
    return (v / base).fillna(1.0)


# ------------------------------------------------------------------ 绘图用序列
def series(hist: pd.DataFrame, max_bars: int = 780) -> dict:
    """把一根根 K 线要一起画的东西全部算成等长数组（给前端 K 线图用）。

    一次算全，前端只负责画：均线 / 布林带 / MACD / KDJ / RSI / 量比。
    K 线的周期由调用方决定（日 / 周 / 月），这里不关心 —— 公式在哪个周期上
    算都是一样的，所以周线月线的指标也是"同口径"的。
    NaN 统一转成 None：json 里 NaN 不是合法数字，浏览器解析会直接报错。
    """
    if hist is None or len(hist) < 5:
        return {"bars": []}
    h = hist.reset_index(drop=True).tail(int(max_bars)).reset_index(drop=True)
    c, hh, ll, v = h["close"], h["high"], h["low"], h["volume"]

    def arr(series_or_none):
        if series_or_none is None:
            return None
        out = []
        for x in pd.Series(series_or_none).tolist():
            try:
                fx = float(x)
                out.append(round(fx, 3) if np.isfinite(fx) else None)
            except Exception:
                out.append(None)
        return out

    ma = {f"ma{n}": arr(MA(c, n)) for n in (5, 10, 20, 30, 60)}
    bup, bmid, bdn = BOLL(c)
    dif, dea, macd = MACD(c)
    k, d, j = KDJ(hh, ll, c)
    r6, r12, r24 = RSI(c, 6), RSI(c, 12), RSI(c, 24)
    vr = VOL_RATIO(v, 5)

    def r3(x):
        return round(float(x), 3) if np.isfinite(float(x)) else None

    bars = []
    for i, row in enumerate(h.itertuples()):
        o, cl, hi, lo = float(row.open), float(row.close), float(row.high), float(row.low)
        bars.append({
            "d": str(row.date),
            "o": r3(o), "c": r3(cl), "h": r3(hi), "l": r3(lo),
            "v": float(row.volume) if np.isfinite(float(row.volume)) else 0.0,
            "pc": None if i == 0 else r3(float(h["close"].iloc[i - 1])),
        })
    vol_ma = {f"v{n}": arr(MA(v, n)) for n in (5, 10)}
    return {
        "bars": bars,
        "ma": ma,
        "boll": {"up": arr(bup), "mid": arr(bmid), "dn": arr(bdn)},
        "macd": {"dif": arr(dif), "dea": arr(dea), "hist": arr(macd)},
        "kdj": {"k": arr(k), "d": arr(d), "j": arr(j)},
        "rsi": {"r6": arr(r6), "r12": arr(r12), "r24": arr(r24)},
        "vol": {"ma5": vol_ma["v5"], "ma10": vol_ma["v10"], "ratio": arr(vr)},
    }


# ------------------------------------------------------------------ 汇总
def snapshot(hist: pd.DataFrame) -> dict:
    """
    给定日线 DataFrame(date/open/high/low/close/volume)，
    返回最近一根的全部指标值 + 几条常用判读，供详情页展示。
    """
    if hist is None or len(hist) < 30:
        return {}
    h = hist.reset_index(drop=True)
    c, hh, ll, v = h["close"], h["high"], h["low"], h["volume"]

    dif, dea, macd = MACD(c)
    k, d, j = KDJ(hh, ll, c)
    r6, r14 = RSI(c, 6), RSI(c, 14)
    up, mid, dn = BOLL(c)
    atr = ATR(hh, ll, c)
    obv = OBV(c, v)
    vr = VOL_RATIO(v, 5)
    ma5, ma10, ma20, ma60 = MA(c, 5), MA(c, 10), MA(c, 20), MA(c, 60)

    i = len(h) - 1
    px = float(c.iloc[i])

    def f(series, nd=3):
        try:
            val = float(series.iloc[i])
            return None if not np.isfinite(val) else round(val, nd)
        except Exception:
            return None

    # 相对强弱：收盘价在 BOLL 通道中的位置
    bw = (float(up.iloc[i]) - float(dn.iloc[i])) if f(up) is not None and f(dn) is not None else 0
    bpos = round((px - float(dn.iloc[i])) / bw * 100, 1) if bw > 0 else None

    tags = []
    if bool(CROSS(dif, dea).iloc[i]):
        tags.append("MACD 金叉")
    elif bool(CROSS(dea, dif).iloc[i]):
        tags.append("MACD 死叉")
    if f(k) is not None and f(d) is not None:
        if float(k.iloc[i]) < 20 and float(d.iloc[i]) < 20:
            tags.append("KDJ 超卖")
        elif float(k.iloc[i]) > 80 and float(d.iloc[i]) > 80:
            tags.append("KDJ 超买")
    if f(r14) is not None:
        if float(r14.iloc[i]) < 30:
            tags.append("RSI 超卖")
        elif float(r14.iloc[i]) > 70:
            tags.append("RSI 超买")
    if bpos is not None and bpos > 100:
        tags.append("突破布林上轨")
    if f(vr) is not None and float(vr.iloc[i]) >= 2:
        tags.append("放量(量比≥2)")
    if f(ma20) is not None and px > float(ma20.iloc[i]) and f(ma5) is not None and float(ma5.iloc[i]) > float(ma20.iloc[i]):
        tags.append("多头排列")

    return {
        "ma": {"ma5": f(ma5), "ma10": f(ma10), "ma20": f(ma20), "ma60": f(ma60)},
        "macd": {"dif": f(dif), "dea": f(dea), "hist": f(macd),
                 "cross": "gold" if bool(CROSS(dif, dea).iloc[i]) else
                          ("dead" if bool(CROSS(dea, dif).iloc[i]) else None)},
        "kdj": {"k": f(k, 1), "d": f(d, 1), "j": f(j, 1)},
        "rsi": {"r6": f(r6, 1), "r14": f(r14, 1)},
        "boll": {"up": f(up), "mid": f(mid), "dn": f(dn), "pos": bpos},
        "atr": {"atr": f(atr), "pct": round(float(atr.iloc[i]) / px * 100, 2) if f(atr) and px else None},
        "obv": {"slope5": round(float(obv.iloc[i] - obv.iloc[max(0, i - 5)]), 0) if i >= 5 else None},
        "vol_ratio": f(vr, 2),
        "tags": tags,
    }
