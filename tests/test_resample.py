"""日线合成周/月线：口径必须与腾讯原生周线一致。

日期取该周期**最后一个交易日**（不是自然周最后一天）—— 沿用了原缓存格式，
否则详情页画图时横轴会跳。
"""
import pandas as pd

from lxquant import store


def _daily():
    """三周 + 跨月的日线，凑够断言需要的形态。"""
    rows = []
    # 2026-03-02(一) ~ 2026-03-20(五)，三个完整交易周
    d = pd.Timestamp("2026-03-02")
    px = 10.0
    while d <= pd.Timestamp("2026-03-20"):
        if d.weekday() < 5:                        # 只造交易日
            o = px
            c = round(px + (0.1 if d.day % 3 else -0.15), 2)
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": o, "close": c,
                "high": round(max(o, c) + 0.2, 2),
                "low": round(min(o, c) - 0.2, 2),
                "volume": 1000 + d.day * 10,
            })
            px = c
        d += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_week_bars_count_and_last_day():
    df = _daily()
    w = store.resample_daily(df, "week")
    assert w is not None and len(w) == 3, f"三周应合成 3 根，实际 {len(w)}"
    # 每根日期 = 该周最后一个交易日（周五）
    for d in w["date"]:
        assert pd.Timestamp(d).weekday() == 4, f"{d} 不是周五"


def test_week_ohlc_aggregation():
    df = _daily()
    w = store.resample_daily(df, "week")
    first = df[df["date"] <= w["date"].iloc[0]]
    bar = w.iloc[0]
    assert bar["open"] == first["open"].iloc[0], "open 应取周内首日"
    assert bar["close"] == first["close"].iloc[-1], "close 应取周内末日"
    assert bar["high"] == first["high"].max(), "high 应取周内极值"
    assert bar["low"] == first["low"].min(), "low 应取周内极值"
    assert bar["volume"] == first["volume"].sum(), "volume 应求和"


def test_month_bars():
    df = _daily()
    m = store.resample_daily(df, "month")
    assert m is not None and len(m) == 1, f"3 月应合成 1 根，实际 {len(m)}"
    assert pd.Timestamp(m["date"].iloc[0]).month == 3


def test_empty_input_returns_none():
    assert store.resample_daily(None, "week") is None
    assert store.resample_daily(pd.DataFrame(), "week") is None


def test_prices_stay_positive():
    """合成不能产生非正价格（负价会把 K 线纵轴拉穿）。"""
    w = store.resample_daily(_daily(), "week")
    for col in ("open", "close", "high", "low"):
        assert (w[col] > 0).all(), f"{col} 出现非正值"
