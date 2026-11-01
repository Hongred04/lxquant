# -*- coding: utf-8 -*-
"""涨停 / 连板识别。

为什么单独成模块：涨跌停幅度按板块不同，用统一的 9.9% 去判会把一半的板漏掉。

    主板（60/00）        10%
    创业板（30/301）     20%
    科创板（688/689）    20%
    北交所（8/4/92）     30%  → 本策略不参与（流动性差、幅度太大）
    ST / *ST             5%   → 本策略不参与

"连板 3 天""首阴"这类说法，离开这套阈值就没有意义 —— 同一根 K 线在主板是涨停，
在创业板可能只是半路。所有涉及涨停的判断都必须走这里，不要在各处写死数字。
"""
from __future__ import annotations

# 容忍度：涨停价四舍五入后，实际涨幅可能略低于标准值（如 9.97%），
# 但不会低太多；反过来除权日会出现假涨停，交给调用方过滤 |chg| 异常。
TOL = 0.005


def board(code: str) -> str:
    """返回板块：main / gem（创业板+科创板）/ bj（北交所）"""
    c = str(code or "")
    if c[:3] in ("300", "301", "688", "689"):
        return "gem"
    if c[:2] in ("43", "83", "87", "88", "92") or c[:1] in ("4", "8"):
        return "bj"
    return "main"


def limit_pct(code: str, name: str = "") -> float:
    """该股票的涨跌停幅度（小数，0.10 = 10%）。ST 一律 5%。"""
    nm = str(name or "").upper()
    if "ST" in nm:
        return 0.05
    b = board(code)
    if b == "gem":
        return 0.20
    if b == "bj":
        return 0.30
    return 0.10


def is_limit_up(code: str, chg: float, name: str = "") -> bool:
    """chg 用小数（0.0999 = 9.99%），不是百分数。"""
    if chg is None:
        return False
    return chg >= limit_pct(code, name) - TOL


def is_limit_down(code: str, chg: float, name: str = "") -> bool:
    if chg is None:
        return False
    return chg <= -(limit_pct(code, name) - TOL)


def tradeable(code: str, name: str = "") -> bool:
    """这套策略只做主板 / 创业板 / 科创板；北交所和 ST 不碰。"""
    if "ST" in str(name or "").upper():
        return False
    if "退" in str(name or ""):
        return False
    return board(code) in ("main", "gem")


def streaks(rows) -> list:
    """给一串「是否涨停」的布尔值，返回每天**截至当天**的连板数。

    rows 按时间正序。第 i 天的值 = 从第 i 天往前数连续涨停的天数。
    """
    out, cur = [], 0
    for lu in rows:
        cur = cur + 1 if lu else 0
        out.append(cur)
    return out
