# -*- coding: utf-8 -*-
"""持仓跟踪的口径测试。

钉三处最容易错的地方：
  · 到期日是「买入日之后的第 40 个**工作日**」，不是 40 个自然日；
  · 两只票等权，合计收益是算术平均，不是相乘；
  · 已经有一笔持仓时不能再记一笔 —— 覆盖会把买入日期弄丢，而那是这笔交易
    唯一不可再生的信息。

这些错了界面上都看不出来：进度条照样在走，只是到期日提前了两周。
"""
import datetime as dt
import os
import tempfile
from pathlib import Path

from lxquant import fin_pos
from lxquant import finance


def _tmp_pos():
    # 必须是 Path：_save() 里要用 with_suffix() 写临时文件
    return Path(tempfile.mkdtemp(prefix="finpos-")) / "pos.json"


class _Patch:
    """临时替换属性，退出时还原（项目 runtime 没有 pytest 的 monkeypatch）。"""

    def __init__(self, obj, name, val):
        self.obj, self.name, self.val = obj, name, val

    def __enter__(self):
        self.orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.val)
        return self

    def __exit__(self, *a):
        setattr(self.obj, self.name, self.orig)


def test_trading_days_skips_weekend():
    """周五买入，第 40 个交易日必须落在工作日上。"""
    due = fin_pos._trading_days("2026-11-06", 40)      # 周五
    d = dt.date.fromisoformat(due)
    assert d.weekday() < 5, f"到期日 {due} 落在周末"
    gap = (d - dt.date(2026, 11, 6)).days
    assert 52 <= gap <= 60, f"40 个工作日应跨 8 周左右，实际 {gap} 天"


def test_trading_days_count_is_exact():
    """周一 + 5 个工作日 = 下周一。写成自然日会算成同周周六。"""
    assert fin_pos._trading_days("2026-11-09", 5) == "2026-11-16"


def test_settle_averages_two_stocks():
    """两只票各一半：合计是算术平均，不是复利相乘。"""
    prices = {"601916": 3.30, "601336": 47.0}
    act = {"buy_date": "2026-11-04", "due_date": "2026-12-30",
           "items": [{"code": "601916", "name": "浙商银行", "buy": 2.97},
                     {"code": "601336", "name": "新华保险", "buy": 52.19}]}
    with _Patch(fin_pos, "_last_price", lambda c: prices[c]):
        s = fin_pos._settle(act)
    r1 = round((3.30 / 2.97 - 1) * 100, 1)
    r2 = round((47.0 / 52.19 - 1) * 100, 1)
    assert abs(s["items"][0]["ret"] - r1) < 0.051, s["items"][0]
    assert abs(s["items"][1]["ret"] - r2) < 0.051, s["items"][1]
    assert abs(s["ret"] - (r1 + r2) / 2) < 0.051, s["ret"]


def test_settle_handles_missing_quote():
    """取不到现价就退回买入价、收益 0，不能变成 NaN。"""
    act = {"items": [{"code": "601916", "name": "浙商银行", "buy": 2.97}]}
    with _Patch(fin_pos, "_last_price", lambda c: 0.0):
        s = fin_pos._settle(act)
    assert s["items"][0]["now"] == 2.97
    assert s["items"][0]["ret"] == 0.0


def test_view_without_file_is_empty():
    """首次打开（没有持仓文件）返回空状态，不抛异常。"""
    with _Patch(fin_pos, "POS", _tmp_pos()):
        v = fin_pos.view()
    assert v["ready"] is True
    assert v["active"] is None
    assert v["history"] == []


def test_open_rejected_when_already_holding():
    """已有一笔时不许再记 —— 覆盖会丢掉买入日期。"""
    fake = {"picks": [
        {"code": "601916", "name": "浙商银行", "board": "银行", "price": 2.97, "score": 87},
        {"code": "601336", "name": "新华保险", "board": "保险", "price": 52.19, "score": 63},
    ]}
    with _Patch(fin_pos, "POS", _tmp_pos()), \
            _Patch(finance, "load", lambda: fake), \
            _Patch(fin_pos, "_last_price", lambda c: 0.0):
        r1 = fin_pos.open_pos()
        assert r1["ok"], r1.get("msg")
        assert r1["active"]["due_date"], "开仓后必须有预计到期日"
        assert len(r1["active"]["items"]) == 2
        r2 = fin_pos.open_pos()
        assert not r2["ok"], "第二笔应该被拒"
        assert "持有" in r2["msg"], r2["msg"]
