"""资金曲线指标：分母必须是「真正交易过的那段」，不能把空仓期也算进去。

踩过的坑：curve 覆盖所有日线数据的并集（约 4 年），而候选交易只在回测窗口内
（约 1 年）。拿 4 年当分母，年化被摊薄成 1/4 —— 实测真实 -2.57% 被显示成
年化 -0.63%，资金利用率 24.9% 被显示成 3.5%，看起来像"几乎没风险"。
"""
from datetime import date, timedelta

import numpy as np

from lxquant import portfolio

START, END = 1_000_000.0, 900_000.0


def _curve(n_flat, n_live):
    """前 n_flat 天躺平（没交易），后 n_live 天线性下跌到 90 万。

    日期必须**单调递增**，否则按日期截断会失效（第一版就踩了这个坑：
    日期写成 2025-01-{i%28+1}，不单调，截断点落到第 2 天，测出来 297 天）。
    """
    d0 = date(2025, 1, 1)
    pts = []
    for i in range(n_flat):
        pts.append([(d0 + timedelta(days=i)).isoformat(), START, 0.0])
    for i in range(1, n_live + 1):
        eq = START + (END - START) * i / n_live
        pts.append([(d0 + timedelta(days=n_flat + i - 1)).isoformat(), eq, eq * 0.5])
    return pts


def test_metrics_use_only_trading_window():
    curve = _curve(200, 100)
    # 买入日取"最后一根躺平的柱子"：那天权益还是 100 万，之后才开始亏
    closed = [{"buy_date": curve[199][0], "ret_net": -5.0, "pnl": -1000.0}]
    m = portfolio._metrics(curve, closed, START)

    assert m["days"] == 101, f"分母应该是交易窗口（约 100 天），实际 {m['days']}"
    assert abs(m["total"] - (-0.10)) < 1e-6, m["total"]
    # 100 天亏 10% → 年化约 -23%；若按 300 天算只有 -8.5%，差三倍
    assert m["annual"] < -0.20, f"年化应按 100 天折算，实际 {m['annual']:.3f}"


def test_utilization_not_diluted_by_idle_days():
    curve = _curve(200, 100)
    closed = [{"buy_date": curve[199][0], "ret_net": -5.0, "pnl": -1000.0}]
    m = portfolio._metrics(curve, closed, START)
    # 交易窗口里市值约占一半，利用率应在 50% 附近，而不是被 300 天摊成 16%
    assert 0.4 < m["util"] < 0.6, f"资金利用率被摊薄了：{m['util']:.3f}"


def test_metrics_without_trades_falls_back_to_full_curve():
    curve = _curve(10, 5)
    m = portfolio._metrics(curve, [], START)
    assert m["days"] == 15           # 没有交易时无处可截，用全段
    assert m["win_rate"] == 0.0


def test_metrics_empty_curve_is_safe():
    m = portfolio._metrics([], [], START)
    assert m["days"] == 0 and m["annual"] == 0.0
    assert isinstance(m["_eq"], np.ndarray)
