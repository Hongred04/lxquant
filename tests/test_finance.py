# -*- coding: utf-8 -*-
"""择时口径的测试：收盘日过滤 + 距进场线的距离。

这两个东西错了界面上完全看不出来 ——
  · 不过滤盘中数据，信号会随盘中价格漂移，同一句话两小时后自我否定；
  · gap 算错，用户看到的「还差 0.8 个百分点」其实是 3.2。
今天这一轮就是这么踩的，所以钉住。
"""
import datetime as dt

import pandas as pd

from lxquant import finance


def _df(dates):
    return pd.DataFrame({"date": dates, "close": [1.0] * len(dates)})


def test_drop_unclosed_before_15():
    """盘中：最后一根「今天」必须丢掉，否则拿到的是实时价。"""
    df = _df(["2026-11-02", "2026-11-03", "2026-11-04"])
    out = finance._drop_unclosed(df, now=dt.datetime(2026, 11, 4, 10, 30))
    assert list(out["date"]) == ["2026-11-02", "2026-11-03"], out["date"].tolist()


def test_drop_unclosed_after_close_keeps_today():
    """15:10 之后：今天的收盘价已经定稿，必须保留。"""
    df = _df(["2026-11-02", "2026-11-03", "2026-11-04"])
    out = finance._drop_unclosed(df, now=dt.datetime(2026, 11, 4, 15, 30))
    assert list(out["date"]) == ["2026-11-02", "2026-11-03", "2026-11-04"]


def test_drop_unclosed_right_at_close():
    """15:05 仍算盘中（留 5 分钟给数据源落定），15:10 才切。"""
    df = _df(["2026-11-03", "2026-11-04"])
    assert len(finance._drop_unclosed(df, now=dt.datetime(2026, 11, 4, 15, 5))) == 1
    assert len(finance._drop_unclosed(df, now=dt.datetime(2026, 11, 4, 15, 10))) == 2


def test_gap_when_above_ma():
    """均线上方：从 +1.2 跌到 −2 需要 3.2 个百分点，不是 0.8。"""
    assert finance._gap(1.2, 2.0) == 3.2
    assert finance._gap(0.0, 2.0) == 2.0


def test_gap_when_approaching():
    assert finance._gap(-1.5, 2.0) == 0.5


def test_gap_when_already_inside():
    """已跌破进场线（−2.89）：距离是 0，不是 0.89。"""
    assert finance._gap(-2.89, 2.0) == 0.0
    assert finance._gap(-2.0, 2.0) == 0.0


def test_index_close_ends_on_closed_day():
    """真实数据：不管现在几点，返回的最后一天不能是「今天未收盘」。"""
    px = finance._index_close()
    assert len(px) > 500, f"长表没生效，只有 {len(px)} 根"
    now = dt.datetime.now()
    last = str(px.index[-1])[:10]
    if (now.hour, now.minute) < (15, 10):
        assert last < now.strftime("%Y-%m-%d"), f"盘中却返回了今天 {last}"
    assert px.index.is_monotonic_increasing, "日期必须有序"


def test_allow_needs_both_gates():
    """两个条件缺一不可。

    · 只破 20 日线（-3）、年线还在高位（+5）：这是普通回调，2008 上半年全是这种，
      买了就被埋，不能放行；
    · 只破年线（-10）、20 日线刚反弹到 +1：跌久了但当天不恐慌，也不放行；
    · 两个都破：放行。
    """
    assert finance._allow(-3.0, 5.0) is False
    assert finance._allow(1.0, -10.0) is False
    assert finance._allow(-3.0, -10.0) is True


def test_allow_boundary_is_strict():
    """恰好等于阈值不算（−2.00 / −8.00 要"超"过）。"""
    assert finance._allow(-2.0, -8.0) is False
    assert finance._allow(-2.01, -8.0) is False
    assert finance._allow(-2.01, -8.01) is True
