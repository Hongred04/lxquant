# -*- coding: utf-8 -*-
"""隔夜低吸曲线（ovnbt）的口径测试。

这套东西的价值全在数字对不对：曲线画得再好看，口径错一点结论就反了。
所以这里钉住三件事：
  1. 复利是不是按**结算日**算的，起点有没有补 0；
  2. 一字跌停卖不掉的顺延，边界对不对（多了会算成"当天卖掉了"，少了会多扛一天）；
  3. 空样本不能崩，也不能返回 0% 假装"不赚不亏"。
"""

from lxquant import ovnbt


def test_curve_starts_at_zero_and_compounds_by_sell_date():
    rows = [
        {"date": "2026-01-05", "sell_date": "2026-01-06", "ret": 10.0},
        {"date": "2026-01-05", "sell_date": "2026-01-06", "ret": -10.0},
        {"date": "2026-01-07", "sell_date": "2026-01-08", "ret": -50.0},
    ]
    pts = ovnbt._curve(rows)
    # 起点是首个买入日、值必须是 0（刚建仓，钱还没动）
    assert pts[0] == ["2026-01-05", 0.0], f"起点不对：{pts[0]}"
    # 1/6 两笔等权：均值 0% → 净值不变
    assert pts[1] == ["2026-01-06", 0.0], f"等权均值算错：{pts[1]}"
    # 1/8 单笔 -50% → 累计 -50%（从 0 再跌一半，不是 -60%）
    assert pts[2] == ["2026-01-08", -50.0], f"复利算错：{pts[2]}"


def test_curve_compounds_not_sums():
    """两笔 -50% 不能相加成 -100%（那是线性口径），复利应该是 -75%。"""
    rows = [
        {"date": "2026-02-02", "sell_date": "2026-02-03", "ret": -50.0},
        {"date": "2026-02-04", "sell_date": "2026-02-05", "ret": -50.0},
    ]
    pts = ovnbt._curve(rows)
    assert pts[-1][1] == -75.0, f"两笔 -50% 应为 -75%，实际 {pts[-1][1]}"


def test_sell_index_defers_on_locked_limit_down():
    """一字跌停：最高=最低、收盘贴跌停 → 必须顺延，不能假装当天卖掉。"""
    n = 6
    # 连续两个一字跌停：9.00 → 8.10 → 7.29（每天 10%），第 4 天正常交易
    px = [10.0, 9.0, 8.1, 7.29, 7.0, 7.2]
    h, lo, c = list(px), list(px), list(px)
    pc = [0.0, 10.0, 9.0, 8.1, 7.29, 7.0]
    # 买入日下标 1，原定卖点下标 2；2、3 两天都卖不掉，下标 4 才成交
    j, defer = ovnbt._sell_index(h, lo, c, pc, 1, 0.10, n)
    assert (j, defer) == (4, 2), f"应顺延 2 天到下标 4，实际 {j}/{defer}"


def test_sell_index_defers_at_most_max_then_force_close():
    """连续一字跌停超过 MAX_DEFER 天：扛满就强结，不许无限等下去。"""
    n = 10
    px = [10.0, 9.0, 8.1, 7.29, 6.56, 5.9, 5.31, 5.31, 5.31, 5.31]
    h = list(px)
    lo = list(px)
    c = list(px)
    pc = [0.0] + px[:-1]
    j, defer = ovnbt._sell_index(h, lo, c, pc, 1, 0.10, n)
    # 买入日 1 → 原定卖点 2，往后顺延 MAX_DEFER=3 次，停在下标 5
    assert defer == ovnbt.MAX_DEFER, f"顺延次数应封顶 {ovnbt.MAX_DEFER}，实际 {defer}"
    assert j == 1 + 1 + ovnbt.MAX_DEFER, f"下标应为 {1 + 1 + ovnbt.MAX_DEFER}，实际 {j}"


def test_sell_index_sells_next_day_when_normal():
    """正常次日能卖：不许多等一天（多等一天就变成另一种策略了）。"""
    h = [10.0, 11.0, 12.0]
    lo = [10.0, 10.5, 11.0]
    c = [10.0, 10.9, 11.8]
    pc = [0.0, 10.0, 11.0]
    j, defer = ovnbt._sell_index(h, lo, c, pc, 0, 0.10, 3)
    assert (j, defer) == (1, 0), f"正常应 T+1 卖，实际 {j}/{defer}"


def test_kpi_empty_sample_is_none_not_zero():
    """空样本必须返回 None，不能返回 0 —— 界面上 0% 的意思是"不赚不亏"，
    和"还没有样本"是两件完全不同的事。"""
    k = ovnbt._kpi([], [], set())
    assert k["n"] == 0
    assert k["avg"] is None and k["total"] is None and k["win"] is None, f"空样本应为 None：{k}"


def test_kpi_max_drawdown_is_on_equity():
    """回撤要在净值上算：-20% 之后再 -20% 是 -36%，不是 -40%。"""
    rows = [
        {"date": "2026-03-02", "sell_date": "2026-03-03", "ret": -20.0},
        {"date": "2026-03-04", "sell_date": "2026-03-05", "ret": -20.0},
        {"date": "2026-03-06", "sell_date": "2026-03-09", "ret": 50.0},
    ]
    pts = ovnbt._curve(rows)
    k = ovnbt._kpi(rows, pts, {"2026-03-02", "2026-03-03", "2026-03-04",
                               "2026-03-05", "2026-03-06", "2026-03-09"})
    assert k["mdd"] == -36.0, f"最大回撤应为 -36.0，实际 {k['mdd']}"
    assert k["total"] == -4.0, f"累计应为 -4.0（0.8×0.8×1.5），实际 {k['total']}"


def test_yearly_groups_by_buy_year():
    rows = [
        {"date": "2025-12-30", "sell_date": "2026-01-02", "ret": 5.0},
        {"date": "2026-01-05", "sell_date": "2026-01-06", "ret": -5.0},
    ]
    y = ovnbt._yearly(rows)
    # 按**买入年**分组：12-30 买的那笔算 2025，哪怕 1 月才卖
    assert [x["y"] for x in y] == [2025, 2026], f"分组年份不对：{y}"
    assert y[0]["n"] == 1 and y[1]["n"] == 1
