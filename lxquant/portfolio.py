# -*- coding: utf-8 -*-
"""
组合账户回测（账户模型参考 QUANTAXIS 的 QIFI / QAMarket）

原先是"每只票各自算买卖点，再把所有交易的收益率连乘"——这会算出一个
根本买不到的资金曲线：40 只票同时开仓、每笔都用全部资金复利。

QUANTAXIS 的做法值得照搬：把策略和**账户**分开。
  · 策略只负责产出候选信号（买什么、哪天买、哪天卖、什么价）
  · 账户负责在**有限的资金和仓位**下决定哪些信号真的能成交，并按日盯市

本模块实现后者：
  现金 → 按 max_pos / pos_pct 约束下单 → 逐日按收盘价重估 → 卖出结算费用
  费用口径：佣金（默认万 2.5，最低 5 元）+ 卖出印花税（千 1）+ 滑点
输出：真实资金曲线 + 年化 / 最大回撤 / 夏普 / 卡玛 / 胜率 / 盈亏比。
"""
import math
import time
from collections import defaultdict

import numpy as np
import pandas as pd

from . import backtest as bt, store


def build_trades(params: dict, weights: dict, codes=None, limit: int = 40,
                 mode: str = "balanced", lookback: int = 250, progress=None,
                 workers: int = 10):
    """第一阶段：逐票产出候选交易（不受资金约束），同时带回每只票的日线"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from . import screener

    log = progress or (lambda **k: None)
    if codes:
        pool = pd.DataFrame({"code": [str(c) for c in codes], "name": [""] * len(codes)})
    else:
        snap = store.get_list()
        pool = screener.prefilter(snap, params)
        pool = screener.balance_pool(pool, limit, mode)
        pool = pool[["code", "name"]]

    trades, daily = [], {}
    n = len(pool)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(bt.backtest_one, r.code, r.name, params, lookback, 3): r.code
                for r in pool.itertuples()}
        for f in as_completed(futs):
            done += 1
            code = futs[f]
            try:
                r = f.result()
            except Exception:
                r = None
            if r and r.get("trades"):
                trades.extend(r["trades"])
            h = store.get_daily(code, 320)
            if h is not None and len(h):
                daily[code] = {str(d)[:10]: float(c)
                               for d, c in zip(h["date"], h["close"])}
            if done % 5 == 0 or done == n:
                log(phase="bt", msg=f"生成信号 {done}/{n}", pct=int(60 * done / max(n, 1)))
    return trades, daily, n


def run_portfolio(trades, daily, initial_cash: float = 1_000_000.0,
                  max_pos: int = 5, pos_pct: float = 0.2,
                  commission: float = 2.5e-4, min_comm: float = 5.0,
                  stamp: float = 1e-3, slippage: float = 0.0) -> dict:
    """第二阶段：在有限资金下按日撮合，产出真实资金曲线"""
    t0 = time.time()
    if not trades:
        return {"ok": False, "error": "没有候选交易", "summary": {}, "curve": [], "trades": []}

    # 所有交易日（各票日线的并集）
    all_dates = sorted({d for m in daily.values() for d in m})
    if not all_dates:
        return {"ok": False, "error": "没有日线数据", "summary": {}, "curve": [], "trades": []}

    by_buy = defaultdict(list)
    for t in trades:
        by_buy[t["buy_date"]].append(t)
    for k in by_buy:
        # 排序只能用**信号当日已知**的信息：获利盘越低（上方套牢越少）越优先。
        # 千万别按事后收益率排序——那是偷看答案，回测会虚高。
        by_buy[k].sort(key=lambda x: (float(x.get("profit_ratio") or 100), x["code"]))

    cash = float(initial_cash)
    positions = {}          # code -> dict(shares, cost, exit_date, exit_price, trade)
    closed, skipped, taken = [], 0, 0
    curve = []

    def px(code, d):
        m = daily.get(code) or {}
        if d in m:
            return m[d]
        older = [k for k in m if k <= d]
        return m[max(older)] if older else None

    for d in all_dates:
        # ---------- 1. 卖出（含当日买入当日离场的）
        for code in list(positions.keys()):
            p = positions[code]
            if p["exit_date"] <= d:
                price = float(p["exit_price"]) * (1 - slippage)
                gross = price * p["shares"]
                fee = max(gross * commission, min_comm) + gross * stamp
                cash += gross - fee
                cost = p["cost"]
                pnl = (gross - fee) - cost
                closed.append({**p["trade"], "shares": p["shares"],
                               "buy_amt": round(cost, 2), "sell_amt": round(gross - fee, 2),
                               "fee": round(fee, 2),
                               "pnl": round(pnl, 2),
                               "ret_net": round(pnl / cost * 100, 2) if cost else 0.0,
                               "sell_date": max(p["exit_date"], str(d))})
                del positions[code]

        # ---------- 2. 买入
        equity_prev = curve[-1][1] if curve else initial_cash
        for t in by_buy.get(d, []):
            if len(positions) >= max_pos:
                skipped += 1
                continue
            entry = float(t["buy"])
            if entry <= 0:
                skipped += 1
                continue
            # 单票预算按**当前权益**的 pos_pct 算（复利），且不超过手头现金
            budget = min(cash, equity_prev * pos_pct)
            shares = int(budget // (entry * (1 + slippage)) // 100) * 100
            if shares < 100:
                skipped += 1
                continue
            price = entry * (1 + slippage)
            gross = price * shares
            fee = max(gross * commission, min_comm)
            if gross + fee > cash:
                shares -= 100
                if shares < 100:
                    skipped += 1
                    continue
                gross = price * shares
                fee = max(gross * commission, min_comm)
            cash -= gross + fee
            positions[t["code"]] = {"shares": shares, "cost": gross + fee,
                                    "exit_date": t["sell_date"], "exit_price": t["sell"],
                                    "trade": t}
            taken += 1

        # ---------- 3. 盯市
        mv = 0.0
        for code, p in positions.items():
            c = px(code, d)
            mv += (c if c is not None else p["trade"]["buy"]) * p["shares"]
        equity = cash + mv
        curve.append([d, round(equity, 2), round(mv, 2)])

    # 期末强制平仓（未到卖点的持仓按最后价结算，不额外计费）
    for code, p in list(positions.items()):
        c = px(code, all_dates[-1]) or p["trade"]["buy"]
        gross = c * p["shares"]
        pnl = gross - p["cost"]
        closed.append({**p["trade"], "shares": p["shares"], "buy_amt": round(p["cost"], 2),
                       "sell_amt": round(gross, 2), "fee": 0.0, "pnl": round(pnl, 2),
                       "ret_net": round(pnl / p["cost"] * 100, 2) if p["cost"] else 0.0,
                       "sell_date": all_dates[-1]})
    positions.clear()

    eq = np.array([c[1] for c in curve], dtype=float)
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    n = len(eq)
    total = eq[-1] / initial_cash - 1 if n else 0.0
    annual = (1 + total) ** (252.0 / n) - 1 if n > 1 and total > -1 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak if n else np.array([0.0])
    mdd = float(dd.min()) if n else 0.0
    sd = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    calmar = (annual / abs(mdd)) if mdd < 0 else 0.0

    wins = [c for c in closed if c["ret_net"] > 0]
    losses = [c for c in closed if c["ret_net"] <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0.0
    gp = sum(c["pnl"] for c in wins)
    gl = abs(sum(c["pnl"] for c in losses))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
    util = float(np.mean([c[2] / c[1] for c in curve if c[1] > 0])) if curve else 0.0

    summary = {
        "initial_cash": initial_cash,
        "final_equity": round(float(eq[-1]), 2) if n else initial_cash,
        "total_ret": round(total * 100, 2),
        "annual": round(annual * 100, 2),
        "mdd": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(float(pf), 2),
        "trades": len(closed),
        "taken": taken,
        "skipped": skipped,
        "days": n,
        "max_pos": max_pos,
        "pos_pct": round(pos_pct * 100, 1),
        "util": round(util * 100, 1),
        "avg_hold": round(float(np.mean([c["hold"] for c in closed])), 1) if closed else 0,
    }
    reasons = defaultdict(int)
    for c in closed:
        reasons[c["reason"]] += 1
    summary["reasons"] = dict(reasons)
    # 曲线转成百分比（相对初始资金），前端直接画
    curve_pct = [[d, round((v / initial_cash - 1) * 100, 2)] for d, v, _ in curve]
    closed_sorted = sorted(closed, key=lambda c: c["sell_date"], reverse=True)
    return {
        "ok": True,
        "summary": summary,
        "curve": curve_pct,
        "trades": closed_sorted[:300],
        "elapsed": round(time.time() - t0, 2),
        "note": "账户模型：等权仓位 + 佣金/印花税/滑点，逐日盯市；未必成交的候选会被跳过",
    }


def run(params: dict, weights: dict, codes=None, limit: int = 40, mode: str = "balanced",
        lookback: int = 250, initial_cash: float = 1_000_000.0, max_pos: int = 5,
        pos_pct: float = 0.2, commission: float = 2.5e-4, stamp: float = 1e-3,
        slippage: float = 0.0, progress=None) -> dict:
    """一站式：生成候选 → 组合撮合"""
    log = progress or (lambda **k: None)
    trades, daily, n = build_trades(params, weights, codes, limit, mode, lookback, progress)
    log(phase="bt", msg="账户撮合中…", pct=70)
    r = run_portfolio(trades, daily, initial_cash, max_pos, pos_pct,
                      commission, 5.0, stamp, slippage)
    r["scanned"] = n
    r["candidates"] = len(trades)
    return r
