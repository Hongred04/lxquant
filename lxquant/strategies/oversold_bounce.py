# -*- coding: utf-8 -*-
"""示例策略：跌得多的反弹。

这是一个「故意和默认方案反着来」的样本，用来说明怎么写自己的策略。
调研数据里唯一有正超额的方向：前 20 日跌超 20% 的票，5 日均值 +2.83%、胜率 65.3%。

想改：直接改这个文件里的数字，存盘后回界面点「重新扫描」就生效，不用重启。
想留一份原来的：复制成别的名字（key 别重复）。
"""
import numpy as np

from .. import indicators as ind
from .base import Ctx, Facts, Gate, Strategy


def _gate_drop(f: Facts, ctx: Ctx, p: dict) -> dict:
    """近 N 天跌得够多（跌得越狠，反弹空间越大）。"""
    n = int(p.get("drop_lookback", 20) or 20)
    need = float(p.get("drop_pct", 0.20) or 0.20)
    d = ctx.hist
    if len(d) <= n:
        return {"ok": False, "why": "数据不够"}
    chg = float(d["close"].iloc[-1]) / float(d["close"].iloc[-1 - n]) - 1.0
    if chg <= -need:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "近 %d 天跌了 %.1f%%，要跌超 %.0f%%" % (n, chg * 100, need * 100)}


def _gate_no_limit_down(f: Facts, ctx: Ctx, p: dict) -> dict:
    """最近几天不能还在跌停板上趴着（跌停买不进，第二天大概率继续跌）。"""
    d = ctx.hist
    if len(d) < 4:
        return {"ok": False, "why": "数据不够"}
    c = d["close"].astype(float).values[-4:]
    chg = c[1:] / c[:-1] - 1.0
    worst = float(np.nanmin(chg))
    if worst <= -0.095:
        return {"ok": False, "why": "最近 3 天有跌停"}
    return {"ok": True, "why": ""}


def _gate_turn(f: Facts, ctx: Ctx, p: dict) -> dict:
    """今天得有回头的意思：收盘价站上今天这根 K 线的一半位置。"""
    r = ctx.row()
    hi, lo, c = float(r["high"]), float(r["low"]), float(r["close"])
    if hi <= lo:
        return {"ok": False, "why": "今天没有振幅"}
    pos = (c - lo) / (hi - lo)
    need = float(p.get("turn_min", 0.5) or 0.5)
    if pos >= need:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "今天收在最低到最高之间的 %.0f%% 位置，要 ≥ %.0f%%" % (pos * 100, need * 100)}


class OversoldBounce(Strategy):
    key = "oversold_bounce"
    name = "跌多了抢反弹"
    desc = ("找近一个月跌得很惨、但今天开始有回头的票。逻辑是超跌反弹，"
            "赚的是情绪修复的钱，所以必须快进快出，拿久了就是个坑。")
    # 这几项此前散在各 gate 函数的 p.get(...) 默认值里，界面上看不到。
    # 显式声明后会经 Strategy.params() 合并进参数，参数页能直接调。
    defaults = {
        "drop_lookback": 20,
        "drop_pct": 0.20,
        "turn_min": 0.5,
    }
    weights = {"drop": 40.0, "turn": 35.0, "pos": 25.0}

    gates = [
        Gate("drop", "跌得够狠", "近一个月跌幅超过设定值", _gate_drop, cost=1),
        Gate("nolimit", "没在跌停", "最近 3 天没有跌停", _gate_no_limit_down, cost=1),
        Gate("turn", "今天回头了", "收盘价在当天振幅的上半段", _gate_turn, cost=1),
    ]

    def facts(self, ctx: Ctx, p: dict) -> Facts:
        d = ctx.hist
        n = int(p.get("drop_lookback", 20) or 20)

        def b_chg():
            if len(d) <= n:
                return None
            return float(d["close"].iloc[-1]) / float(d["close"].iloc[-1 - n]) - 1.0

        return Facts({"chg": b_chg})

    def score(self, f, checks, p):
        w = p.get("_weights") or self.weights
        chg = f.get("chg")
        # 跌得越多分越高，跌 40% 打满
        s_drop = min(1.0, max(0.0, -(chg or 0.0) / 0.40))
        r = checks
        s_turn = 1.0 if r.get("turn") else 0.0
        s_pos = 1.0 if r.get("nolimit") else 0.0
        total = (w.get("drop", 40) * s_drop + w.get("turn", 35) * s_turn
                 + w.get("pos", 25) * s_pos)
        norm = sum(abs(w.get(k, 0)) for k in ("drop", "turn", "pos")) or 100.0
        return round(total / norm * 100, 2)
