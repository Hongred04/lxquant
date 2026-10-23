# -*- coding: utf-8 -*-
"""当前的默认方案：连涨三天站上分时均价线 + 套牢盘少 + 价格在低位 + 底部横着走。

这就是你原来那套，只是被拆成了可插拔的形式。
换方案不用改这个文件，去 data/strategies/ 放新的 .py 即可。
"""
import numpy as np

from .. import indicators as ind
from .base import Ctx, Facts, Gate, Strategy


# ---------------------------------------------------------------- 关卡
def _gate_ma(f: Facts, ctx: Ctx, p: dict) -> dict:
    """连续 N 天站上分时均价线（尾盘口径优先）。"""
    tail = f["tail"]
    if tail is not None and str(p.get("entry_mode", "tail")) == "tail":
        if tail["ok"]:
            return {"ok": True, "why": ""}
        d = tail.get("detail") or []
        bad = [x for x in d if not x.get("ok")]
        if bad:
            return {"ok": False, "why": "%s 那天收在平均成本下方 %.2f%%"
                    % (str(bad[0].get("date"))[5:], abs(bad[0].get("surplus") or 0))}
        return {"ok": False, "why": "站上平均成本的天数不够（%d 天）" % (tail.get("streak") or 0)}
    s = f["streak"]
    if s["ok"]:
        return {"ok": True, "why": ""}
    d = s.get("detail") or []
    bad = [x for x in d if not x.get("ok")]
    if bad:
        return {"ok": False, "why": "%s 那天收在平均成本下方 %.2f%%"
                % (str(bad[0].get("date"))[5:], abs(bad[0].get("surplus") or 0))}
    return {"ok": False, "why": "连续站上平均成本的天数不够（%d 天）" % (s.get("streak") or 0)}


def _gate_chip(f: Facts, ctx: Ctx, p: dict) -> dict:
    cap = float(p.get("profit_cap", 0.25)) * 100
    pr = f["chip"].get("profit_ratio")
    if pr is None:
        return {"ok": False, "why": "算不出套牢盘"}
    if pr * 100 <= cap:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "上方套牢盘 %.0f%%，要 ≤ %.0f%%" % (pr * 100, cap)}


def _gate_pos(f: Facts, ctx: Ctx, p: dict) -> dict:
    cap = float(p.get("pos_cap", 0.30)) * 100
    ps = f["pos"].get("pos")
    if ps is None:
        return {"ok": False, "why": "算不出价格位置"}
    if ps * 100 <= cap:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "价格在区间 %.0f%% 位置，要 ≤ %.0f%%" % (ps * 100, cap)}


def _gate_bottom(f: Facts, ctx: Ctx, p: dict) -> dict:
    b = f["bottom"]
    if not b.get("ok"):
        return {"ok": False, "why": b.get("note") or "走势还没收敛（振幅偏大或有明显斜度）"}
    return {"ok": True, "why": ""}


def _gate_trend(f: Facts, ctx: Ctx, p: dict) -> dict:
    t = f["trend"]
    if t["above"]:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "低于 %d 日均线" % int(p.get("ma_trend_period", 20) or 20)}


# ---------------------------------------------------------------- 方案
class MaCostLow(Strategy):
    key = "ma_cost_low"
    name = "均价线 + 低位低套牢"
    desc = ("连续几天价格站在当天分时平均成本上方，同时头上等着解套的筹码不多、"
            "整体还在近半年的低位区。思路是找「跌不动了、有资金在托」的票。")
    weights = {"surplus": 25.0, "profit": 25.0, "position": 25.0, "bottom": 15.0, "trend": 10.0}

    gates = [
        Gate("ma", "价格站在成本上", "连续几天价格都在当天平均成本上方",
             _gate_ma, cost=2),
        Gate("chip", "套牢盘少", "头上压着等着解套的筹码不多",
             _gate_chip, cost=3),
        Gate("pos", "价格低", "在近 120 天区间的下边",
             _gate_pos, cost=3),
        Gate("bottom", "底部横着走", "最近 20 天没在一路往下掉",
             _gate_bottom, cost=2, enable_key="bottom_enable"),
        Gate("trend", "趋势向上", "短期均线方向向上",
             _gate_trend, cost=1, enable_key="ma_trend_enable"),
    ]

    def facts(self, ctx: Ctx, p: dict) -> Facts:
        d = ctx.hist
        px = ctx.close()
        n = len(d)
        ma_days = int(p.get("ma_days", 3))
        ma_ratio = float(p.get("ma_ratio", 1.0) or 1.0)
        ma_tol = float(p.get("ma_tol", 0.0) or 0.0)
        chip_win = int(p.get("chip_window", 120))
        bottom_days = int(p.get("bottom_days", 20) or 20)
        tail_from = str(p.get("tail_from", "14:30"))
        tp = int(p.get("ma_trend_period", 20) or 20)

        def _streak_seq():
            # 回测用：整段日线一次的近似序列，避免每天重算一遍
            return ctx.memo("approx_avg", lambda: _approx_avg_series(ctx.daily))

        def b_streak():
            if ctx.k5 is not None:
                avx = ind.daily_avg_price(ctx.k5, tail_from=tail_from)
                return ind.consecutive_above(avx, ma_days, ma_ratio, ma_tol)
            av = _streak_seq()
            ok = d["close"].values >= av[:n] * ma_ratio - ma_tol
            need = ma_days
            streak, mins = 0, []
            for k in range(need - 1, -1, -1):
                j = n - 1 - k
                if j < 0:
                    break
                mins.append(bool(ok[j]))
                streak = streak + 1 if ok[j] else 0
            passes = all(mins) and len(mins) == need
            return {"ok": passes, "days": len(mins), "streak": streak,
                    "detail": [], "avg_surplus": None, "fails": 0}

        def b_tail():
            if ctx.k5 is None:
                return None
            avx = ind.daily_avg_price(ctx.k5, tail_from=tail_from)
            w = ind.tail_window_stats(avx, ma_days, tail_from, ma_ratio)
            # 14:00 左右跑到时今天还没定型，先按"截至现在"的均价线挑出要盯的
            try:
                w["preview"] = ind.tail_preview(avx, ma_days, tail_from,
                                                at=p.get("preview_at"), ratio=ma_ratio)
            except Exception:                               # noqa: BLE001
                w["preview"] = None
            return w

        def b_chip():
            sub = d.iloc[max(0, n - chip_win):]
            return ind.chip_distribution(sub, px, chip_win,
                                         int(p.get("chip_bins", 70)),
                                         float(p.get("chip_decay", 0.985)))

        def b_pos():
            sub = d.iloc[max(0, n - chip_win):]
            return ind.price_position(sub, px, chip_win)

        def b_bottom():
            return ind.bottom_structure(d, bottom_days,
                                        float(p.get("bottom_amp", 0.40)),
                                        float(p.get("bottom_slope", 0.12)))

        def b_trend():
            c = d["close"].astype(float).values
            ma = float(np.mean(c[-tp:])) if len(c) >= tp else None
            ma5 = float(np.mean(c[-5:])) if len(c) >= 5 else None
            ma20 = float(np.mean(c[-20:])) if len(c) >= 20 else None
            return {"above": bool(ma is not None and px >= ma), "ma": ma,
                    "ma5": ma5, "ma20": ma20,
                    "ma5_gt_ma20": bool(ma5 and ma20 and ma5 > ma20)}

        return Facts({"streak": b_streak, "tail": b_tail, "chip": b_chip,
                      "pos": b_pos, "bottom": b_bottom, "trend": b_trend})

    def score(self, f: Facts, checks: dict, p: dict) -> float:
        w = p.get("_weights") or self.weights
        if not checks.get("ma"):
            return 0.0
        tail_mode = str(p.get("entry_mode", "tail")) == "tail"
        av = f["streak"]
        sur_v = None
        if tail_mode:
            t = f.get("tail") or {}
            sur_v = t.get("avg_surplus")
        if sur_v is None:
            sur_v = av.get("avg_surplus")
        s_sur = min(1.0, max(0.0, (sur_v or 0) / 100.0) / 0.03) if sur_v is not None else 0.0

        cap = float(p.get("profit_cap", 0.25)) or 0.25
        pr = f["chip"].get("profit_ratio")
        s_pro = 0.0 if pr is None else max(0.0, min(1.0, (cap - pr) / cap))

        pcap = float(p.get("pos_cap", 0.30)) or 0.30
        ps = f["pos"].get("pos")
        s_pos = 0.0 if ps is None else max(0.0, min(1.0, (pcap - ps) / pcap))

        amp_cap = float(p.get("bottom_amp", 0.40)) or 0.40
        amp = f["bottom"].get("amp")
        s_bot = 0.0 if amp is None else max(0.0, min(1.0, (amp_cap - amp) / amp_cap))
        if f["bottom"].get("higher_low"):
            s_bot = min(1.0, s_bot + 0.2)

        tr = f["trend"]
        s_tr = 0.5 * (1.0 if tr["above"] else 0.0) + 0.5 * (1.0 if tr["ma5_gt_ma20"] else 0.0)

        total = (w.get("surplus", 25) * s_sur + w.get("profit", 25) * s_pro
                 + w.get("position", 25) * s_pos + w.get("bottom", 15) * s_bot
                 + w.get("trend", 10) * s_tr)
        norm = sum(abs(w.get(k, 0)) for k in ("surplus", "profit", "position", "bottom", "trend")) or 100.0
        return round(total / norm * 100, 2)

    def extra_checks(self, f: Facts, ctx: Ctx, p: dict) -> dict:
        # tail_watch：今天还没定型，但已经只差这一下 —— 界面上会给个黄色角标
        pv = (f.get("tail") or {}).get("preview") if (f.get("tail") or {}) else None
        return {"close_ma": bool(f["streak"].get("ok")),
                "tail": bool((f.get("tail") or {}).get("ok")),
                "tail_watch": bool((pv or {}).get("watch"))}


def _approx_avg_series(h):
    """日线近似分时均价线，只在回测里用（免费源没有长历史分时）。"""
    tp = (h["high"] + h["low"] + h["close"]) / 3.0
    prev = h["close"].shift(1).bfill()
    return ((tp + prev) / 2.0).values
