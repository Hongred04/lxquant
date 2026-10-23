# -*- coding: utf-8 -*-
"""我的策略：改这一行写清楚它想抓什么。

放好这个文件（不用改程序），打开软件 →「我的 → 参数设置」里就能选到它。
改完存盘，回到界面点一下「重新扫描」就生效，不用重启。
"""
import numpy as np
from lxquant.strategies.base import Ctx, Facts, Gate, Strategy
from lxquant import indicators as ind


def _gate_shape(f, ctx, p):
    """例子：最近 N 天涨跌幅不超过某个范围。"""
    n = int(p.get("my_lookback", 20))
    cap = float(p.get("my_rise_cap", 0.15))
    d = ctx.hist
    if len(d) <= n:
        return {"ok": False, "why": "数据不够"}
    chg = float(d["close"].iloc[-1]) / float(d["close"].iloc[-1 - n]) - 1.0
    if chg <= cap:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "近 %d 天涨了 %.1f%%，要 ≤ %.0f%%" % (n, chg * 100, cap * 100)}


class MyStrategy(Strategy):
    key = "my_strategy"                 # 唯一标识，别和别的重名
    name = "我的策略"                    # 界面上显示的名字
    desc = "一句话说清楚这套逻辑在赌什么。"

    gates = [
        Gate("shape", "涨得不多", "最近一段时间没有暴涨", _gate_shape, cost=1),
        # 想加第二关：
        # Gate("chip", "套牢盘少", "...", _gate_chip, cost=3),
    ]

    def facts(self, ctx: Ctx, p: dict) -> Facts:
        d = ctx.hist
        return Facts({
            # 只有被 gate 引用到的键才会真的算，所以可以放心多写
            "close": lambda: float(d["close"].iloc[-1]),
        })

    def score(self, f, checks, p):
        # 不写就用默认的「过了几关给几分」
        return super().score(f, checks, p)
