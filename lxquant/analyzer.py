# -*- coding: utf-8 -*-
"""个股技术分析：把日线 + 5 分钟线 + 筹码全部算好，供选股与详情页使用。"""
import numpy as np
import pandas as pd

from . import indicators as ind
from . import datasource as ds
from . import store
from . import extdata as ext
from . import strategies as strats


def _num(v, nd=3):
    try:
        v = float(v)
        if not np.isfinite(v):
            return None
        return round(v, nd)
    except Exception:
        return None


def analyze(code: str, name: str = "", params: dict | None = None,
            daily: pd.DataFrame | None = None, k5: pd.DataFrame | None = None,
            rt: dict | None = None) -> dict:
    """
    返回结构：
      code/name/price : 基本信息（price 为最新可用价：优先实时）
      avg            : 分时均价线相关（连续达标、明细、今日均价）
      chip           : 筹码分布（获利盘、平均成本、分布直方图）
      pos            : 价格分位 / 距高点回撤
      bottom         : 低位横盘结构
      trend          : 均线趋势
      checks         : 每一项是否通过（用于界面上的"逻辑链条"展示）
      score          : 综合评分
    """
    p = params or {}
    ma_days = int(p.get("ma_days", 3))
    ma_ratio = float(p.get("ma_ratio", 1.0))
    ma_tol = int(p.get("ma_tol", 0))
    chip_window = int(p.get("chip_window", 120))
    chip_bins = int(p.get("chip_bins", 70))
    chip_decay = float(p.get("chip_decay", 0.985))
    profit_cap = float(p.get("profit_cap", 0.25))
    pos_cap = float(p.get("pos_cap", 0.30))
    trend_period = int(p.get("ma_trend_period", 20))
    bottom_days = int(p.get("bottom_days", 20))

    if daily is None:
        daily = store.get_daily(code)
    if daily is None or len(daily) < 30:
        raise ValueError(f"{code} 日线数据不足")

    last = daily.iloc[-1]
    price = _num(rt["price"]) if rt and rt.get("price") else _num(last["close"])

    avx = ind.daily_avg_price(k5, tail_from=p.get("tail_from", "14:30")) if k5 is not None else pd.DataFrame()
    streak = ind.consecutive_above(avx, ma_days, ma_ratio, ma_tol)
    # 尾盘口径：不看收盘价，而是看 14:30 的价 vs 截至 14:30 的均价线
    tail_w = ind.tail_window_stats(avx, ma_days, str(p.get("tail_from", "14:30")), ma_ratio)
    # 尾盘前试算：14:00 左右跑到时，今天还没定型，先按"截至现在"的均价线挑出要盯的
    tail_pv = None
    if avx is not None and not avx.empty:
        tail_pv = ind.tail_preview(avx, ma_days, str(p.get("tail_from", "14:30")),
                                   at=p.get("preview_at"), ratio=ma_ratio)

    # 筹码分布：优先用真实换手率（参考 adata 的流通股本口径），失败则退回固定衰减
    turnover = None
    if bool(p.get("real_turnover", True)):
        try:
            turnover = ext.turnover_series(
                code,
                daily["date"].tolist()[-chip_window:],
                daily["volume"].tolist()[-chip_window:],
            )
        except Exception:
            turnover = None
    chip = ind.chip_distribution(
        daily, price, chip_window, chip_bins, chip_decay,
        turnover=turnover.values if turnover is not None else None,
        intensity=float(p.get("turnover_intensity", 1.0)),
    )
    pos = ind.price_position(daily, price, chip_window)
    bot = ind.bottom_structure(daily, bottom_days,
                               float(p.get("bottom_amp", 0.40)),
                               float(p.get("bottom_slope", 0.12)))

    # 均线趋势
    closes = daily["close"].astype(float).values
    ma = float(np.mean(closes[-trend_period:])) if len(closes) >= trend_period else None
    ma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else None
    ma10 = float(np.mean(closes[-10:])) if len(closes) >= 10 else None
    ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else None
    ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else None
    above_ma = bool(ma is not None and price >= ma)

    # 今日分时均价（若 5 分钟数据覆盖今天，直接用；否则用日线 close/vwap 近似）
    today_avg = None
    if not avx.empty:
        today_avg = _num(avx["avg_price"].iloc[-1])

    # 量能：近 5 日均量 / 近 20 日均量
    vol = daily["volume"].astype(float).values
    vr5_20 = float(vol[-5:].mean() / vol[-20:].mean()) if len(vol) >= 20 and vol[-20:].mean() > 0 else None

    # 所有的判定都交给策略插件：实盘和回测共用同一份 gate，
    # 不会出现"回测在测 A、实盘在下 B"
    strat = strats.get_current(p)
    ctx = strats.Ctx(code, name, daily, k5=k5, rt=rt)
    facts = strat.facts(ctx, p)
    checks, gate_rows = strat.check_all(facts, ctx, p)
    bot = facts.get("bottom") or {"ok": False, "amp": None, "slope": None,
                                  "higher_low": False, "note": "策略没用这一关"}
    chk_ma = bool(checks.get("close_ma", checks.get("ma")))
    chk_bottom = bool(checks.get("bottom"))

    return {
        "code": code, "name": name or "", "price": price,
        "chg_pct": _num((rt or {}).get("chg_pct"), 2) if rt else _num((price / float(daily["close"].iloc[-2]) - 1) * 100, 2),
        "date": str(avx["date"].iloc[-1]) if not avx.empty else str(last["date"]),
        "stock_date": str(last["date"]),
        "strategy": strat.key,
        "gates": gate_rows,
        "avg": {
            "ok": bool(streak["ok"]), "need": ma_days, "have": streak["days"],
            "streak": streak["streak"], "detail": streak["detail"],
            "avg_surplus": streak["avg_surplus"], "fails": streak.get("fails", 0),
            "today_avg": today_avg,
            "today_surplus": _num((price / today_avg - 1) * 100, 2) if today_avg else None,
            # ---- 尾盘口径 ----
            "tail_from": tail_w.get("tail_from"),
            "tail_ok": bool(tail_w["ok"]), "tail_streak": tail_w["streak"],
            "tail_detail": tail_w["detail"], "tail_surplus": tail_w["avg_surplus"],
            "tail_fails": tail_w.get("fails", 0),
            "preview": tail_pv,
        },
        "chip": {k: v for k, v in chip.items()},
        "pos": pos,
        "bottom": bot,
        "trend": {
            "ma5": _num(ma5), "ma10": _num(ma10), "ma20": _num(ma20), "ma60": _num(ma60),
            "above": above_ma, "period": trend_period,
            "ma5_gt_ma20": bool(ma5 and ma20 and ma5 > ma20),
            "vol_ratio": _num(vr5_20, 2),
        },
        "checks": checks,
        "score": 0.0,
    }


# ---------------------------------------------------------------- 评分
def score(a: dict, weights: dict, params: dict) -> float:
    """综合评分，具体怎么打分由当前策略决定（见 strategies/*.py 的 score 方法）。"""
    p = dict(params or {})
    p["_weights"] = weights or {}
    strat = strats.get(a.get("strategy") or strats.current_key(p))
    ctx = strats.Ctx(a.get("code", ""), a.get("name", ""),
                     pd.DataFrame({"close": [a.get("price") or 0]}),
                     i=0, shared={"_pre": a})
    # 直接把 analyze 已经算好的字段喂成事实表，不重复计算
    facts = strats.Facts({
        "streak": lambda: {"ok": a["checks"].get("close_ma", a["checks"].get("ma")),
                           "avg_surplus": (a.get("avg") or {}).get("avg_surplus")},
        "tail": lambda: {"ok": a["checks"].get("tail"),
                         "avg_surplus": (a.get("avg") or {}).get("tail_surplus"),
                         "preview": (a.get("avg") or {}).get("preview")},
        "chip": lambda: a.get("chip") or {},
        "pos": lambda: a.get("pos") or {},
        "bottom": lambda: a.get("bottom") or {},
        "trend": lambda: a.get("trend") or {"above": False, "ma5": None, "ma20": None,
                                             "ma5_gt_ma20": False},
    })
    return strat.score(facts, a.get("checks") or {}, p)


# ---------------------------------------------------------------- 买入信号
def eval_buy(hist: pd.DataFrame, sig_idx: int, params: dict) -> dict:
    """
    在 sig_idx(信号日收盘后) 给出买点建议：
      next_open       次日开盘价买入
      next_open_break 次日高开突破信号日最高价才买
      pullback        次日回踩到 信号日收盘*(1+pullback) 以内才买（谨慎）
    返回 buy_price / buy_day / valid / note
    """
    if sig_idx + 1 >= len(hist):
        return {"valid": False, "executed": None, "note": "信号日尚无次日数据（今日刚出信号）"}
    nxt = hist.iloc[sig_idx + 1]
    sig = hist.iloc[sig_idx]
    rule = params.get("buy_rule", "next_open")
    if rule == "next_open_break":
        if nxt["high"] <= max(sig["high"], sig["close"]):
            return {"valid": False, "executed": None, "note": "次日未突破信号日高点，未买入"}
        return {"valid": True, "executed": True, "price": _num(nxt["open"]),
                "day": str(nxt["date"]), "note": "突破买入"}
    if rule == "pullback":
        lim = float(sig["close"]) * (1 + params.get("buy_pullback", 0.015))
        chase = float(sig["close"]) * (1 + params.get("buy_chase_max", 0.05))
        if nxt["open"] > chase:
            return {"valid": False, "executed": None, "note": "次日高开过大，不追高"}
        if nxt["low"] <= lim:
            px = min(float(nxt["open"]), lim)
            return {"valid": True, "executed": True, "price": _num(px),
                    "day": str(nxt["date"]), "note": "回踩买入"}
        return {"valid": False, "executed": None, "note": "次日未回踩到买点，未买入"}
    return {"valid": True, "executed": True, "price": _num(nxt["open"]),
            "day": str(nxt["date"]), "note": "次日开盘买入"}


def plan_targets(price: float, a: dict, params: dict) -> dict:
    """
    买卖点规划（买入后默认持有到止盈/止损/换手）：
      · 止损 = max(现价×-6%, 昨日分时均价线×0.995, 20日区间低点×0.985)
        —— 策略的逻辑是"收盘站上均价线"，一旦跌回均价线下方就是逻辑失效；
      · 止盈 = 现价 × +15%（或用户参数）；
      · 盈亏比 < 1.5 提示"性价比不足"。
    """
    price = float(price)
    stop_pct = float(params.get("stop_loss", 0.06))
    min_stop = float(params.get("min_stop", 0.025))
    detail = (a.get("avg") or {}).get("detail") or []
    avgp = (detail[-1]["avg"] if detail else None) or (a.get("avg") or {}).get("today_avg") or price
    lo20 = (a.get("bottom") or {}).get("lo") or (a.get("pos") or {}).get("lo20")
    cands = [price * (1 - stop_pct), avgp * 0.992]
    if lo20:
        cands.append(float(lo20) * 0.985)
    cands = [c for c in cands if c and 0 < c < price]
    # 止损必须留出最小空间，否则"贴着均价线"会被日内噪声轻易打掉
    floor_stop = price * (1 - min_stop)
    stop_price = max([floor_stop] + [c for c in cands if c <= floor_stop] or [price * 0.97])
    stop_price = min(stop_price, price * (1 - 0.004))
    tp = price * (1 + float(params.get("take_profit", 0.15)))
    sc = a.get("score") or 0
    if sc >= 80:
        pos_pct = 20
    elif sc >= 70:
        pos_pct = 15
    elif sc >= 60:
        pos_pct = 10
    else:
        pos_pct = 5
    rr = (tp - price) / max(price - stop_price, 1e-9)
    return {
        "stop": _num(stop_price), "stop_pct": _num((stop_price / price - 1) * 100, 2),
        "target": _num(tp), "target_pct": _num((tp / price - 1) * 100, 2),
        "avg_line": _num(avgp), "position_pct": pos_pct, "rr": _num(rr, 2),
        "ok": bool(rr >= 1.5),
        "note": "" if rr >= 1.5 else "止盈空间不足，建议等回调",
    }
