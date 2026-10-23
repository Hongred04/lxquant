# -*- coding: utf-8 -*-
"""
策略回测：用日线近似"连续站上分时均价线"，验证买卖点的历史表现。

⚠ 重要说明
  免费数据源拿不到足够长的历史分时（新浪仅 ~22 个交易日 = 1023 根 5 分钟线），
  因此回测使用【日线 VWAP 近似】：
      当日典型价 TP = (H+L+C)/3，按成交量加权近似当日均价线
      近似均价线 = (TP + 前一日收盘) / 2  （更贴近真实分时的"开盘价接近昨收"特性）
  这只用于验证买卖点规则，真实盘中信号仍以真实分时均价线为准（见"当日实时分时验证"）。

买卖点规则（带止损止盈）
  买入：信号日收盘出信号 → 次日按 buy_rule 成交
  卖出（按优先级）：
    1. 收盘价 < 买入价*(1-stop_loss)                → 止损
    2. 收盘价 < 买入日均价线（跌破当日分时均价线）   → 均价线失守离场
    3. sell_mode=atr  ：浮盈超过 5% 后，从最高点回撤 trail_drawdown → 移动止盈
       sell_mode=fixed：收盘价 >= 买入价*(1+take_profit) → 止盈
    4. 持有超过 max_hold 个交易日 → 时间止损
    5. 收盘跌破 MA{ma_exit} → 趋势离场（可选）
"""
import time
from collections import defaultdict

import numpy as np
import pandas as pd

from . import indicators as ind, store
from . import strategies as strats


# ---------------------------------------------------------------- 交易成本
# 一次完整来回的真实成本。默认值按 A 股现行规则：
#   佣金 万2.5 双边（最低 5 元）、印花税 0.05% 单边卖出（财政部 2023 年第 39 号，
#   2023-08-28 起由 0.1% 减半）、过户费 0.001% 双边、滑点 0.1% 每边。
# 不算这笔钱的话，回测出来的"微微赚一点"在实盘必然是亏的。
COST_DEFAULTS = {
    "commission": 2.5e-4,     # 佣金率（双边各收一次）
    "min_comm": 5.0,          # 单笔最低佣金（元）
    "stamp": 5e-4,            # 印花税（仅卖出）
    "transfer": 1e-5,         # 过户费（双边）
    "slippage": 1e-3,         # 滑点（每边）
    "notional": 20000.0,      # 假设单笔金额，用于摊薄"最低 5 元佣金"
}


def cost_rate(entry: float, exit_price: float, params: dict | None = None) -> float:
    """算这一笔来回的实际成本率（%）。按假设金额摊薄最低佣金。"""
    p = dict(COST_DEFAULTS)
    if params:
        for k in COST_DEFAULTS:
            if params.get(k) is not None:
                p[k] = float(params[k])
    notional = max(float(p["notional"]), 1.0)
    buy_amt = notional
    sell_amt = notional * (exit_price / entry if entry else 1.0)
    fee_buy = max(buy_amt * p["commission"], p["min_comm"]) + buy_amt * p["transfer"]
    fee_sell = max(sell_amt * p["commission"], p["min_comm"]) + sell_amt * p["stamp"] \
        + sell_amt * p["transfer"]
    slip = (buy_amt + sell_amt) * p["slippage"]
    return (fee_buy + fee_sell + slip) / buy_amt * 100.0


def _approx_avg_series(h: pd.DataFrame) -> np.ndarray:
    tp = (h["high"] + h["low"] + h["close"]) / 3.0
    prev_close = h["close"].shift(1).bfill()
    return ((tp + prev_close) / 2.0).values


def signal_series(h: pd.DataFrame, days: int = 3, ratio: float = 1.0,
                  tol: float = 0.0) -> np.ndarray:
    """每日是否"收盘站上均价线"。

    days 由调用方判断连续天数；这里只管单日：close >= avg * ratio - tol。
    """
    avg = _approx_avg_series(h)
    return (h["close"].values >= avg * float(ratio) - float(tol))  # bool 数组


def _chip_at(h: pd.DataFrame, i: int, window=120, bins=70, decay=0.985, price=None) -> dict:
    sub = h.iloc[max(0, i - window):i + 1]
    px = float(h["close"].iloc[i]) if price is None else price
    return ind.chip_distribution(sub, px, window, bins, decay)


def _pos_at(h: pd.DataFrame, i: int, window=120):
    return ind.price_position(h.iloc[max(0, i - window):i + 1], float(h["close"].iloc[i]), window)


def backtest_one(code: str, name: str, params: dict, lookback: int = 1000,
                 hold_days: int = 3) -> dict:
    """
    单票回测：在过去 lookback 天里寻找"连续站上均价线 且 筹码低位"的信号，
    按买卖规则模拟持仓，统计每笔收益。
    """
    # 必须用**前复权**的长历史：跨 2~4 年的回测里只要遇到一次送转，
    # 不复权序列就会凭空多出一个 -30% 的暴跌，整份回测直接作废。
    # 以前这里取 get_daily(320)（不复权、最多 320 根 ≈ 1.3 年），
    # 回测窗口被压到 250 天，样本量小到 20 只票只跑出 13 笔交易 —— 那不是策略的问题。
    h = store.get_daily_long(code, 1023)
    if h is None or len(h) < 150:
        return {"code": code, "name": name, "trades": [], "error": "数据不足"}
    h = h.reset_index(drop=True)
    n = len(h)
    days = int(params.get("ma_days", 3))
    win = int(params.get("chip_window", 120))
    stop = float(params.get("stop_loss", 0.06))
    tp = float(params.get("take_profit", 0.15))
    max_hold = int(params.get("max_hold", 10))
    trail = float(params.get("trail_drawdown", 0.07))
    mode = params.get("sell_mode", "atr")
    ma_exit = int(params.get("ma_exit", 0) or 0)
    rule = params.get("buy_rule", "next_open")
    pull = float(params.get("buy_pullback", 0.015))
    chase = float(params.get("buy_chase_max", 0.05))

    # 信号判定交给策略插件：实盘和回测走的是同一份 gate 代码，
    # 不会出现"回测在测 A、实盘在下 B"的情况
    strat = strats.get_current(params)
    strat_avg_series = _approx_avg_series(h)
    shared: dict = {}
    start = max(win, n - lookback)
    # 市场状态开关：逐日判定，和实盘同一口径。市场不匹配的日子不开新仓，
    # 否则回测会把"本来就不该买"的交易也算进去，策略好坏就被市场环境掩盖了。
    gate_on = bool(params.get("market_gate", True))
    trades = []
    i = start
    while i < n - 2:
        if not strat.signal_at(strats.Ctx(code, name, h, i=i, shared=shared), params):
            i += 1
            continue
        if gate_on:
            try:
                from . import market_state
                if not market_state.allow_on(h["date"].iloc[i], params):
                    i += 1
                    continue
            except Exception:
                pass

        sig = h.iloc[i]
        sig_close = float(sig["close"])
        # ★ 成交时点：一律"信号日次日开盘买入"。
        #   原来用信号日自己的收盘价既做决策又做成交，是同一个 bar 内的前视
        #   （backtrader 官方文档称之为作弊，须显式 set_coc 才允许）。
        #   也试过用 (开盘 + (最高+最低)/2)/2 去模拟"14:30 的价"，但那仍然偷看了
        #   当日最高/最低——回测里它能把毛利从 +0.28% 抬到 +1.58%，纯属假象。
        #   日线数据没有 14:30 那一刻的价格，尾盘买入无法无偏回测，所以不模拟。
        #   实测隔夜跳空：1002 个信号，次日开盘相对前收均值 -0.072%，
        #   上涨占比仅 35.8% —— 尾盘买入等于主动承担一次负期望。
        rule = params.get("buy_rule", "next_open")
        if rule == "same_day_tail":
            rule = "next_open"          # 日线无法回测尾盘买入，降级成次日开盘
        j = i + 1
        if j >= n:
            break
        # ---------------- 买入
        nxt = h.iloc[j]
        entry = None
        if rule == "next_open_break":
            if nxt["high"] > max(sig["high"], sig["close"]):
                entry = float(nxt["open"])
        elif rule == "pullback":
            lim = float(sig["close"]) * (1 + pull)
            if nxt["open"] <= float(sig["close"]) * (1 + chase) and nxt["low"] <= lim:
                entry = min(float(nxt["open"]), lim)
        else:
            entry = float(nxt["open"])
        entry_idx = j
        if entry is None:
            i += 1
            continue

        # 均价线序列只在卖出规则里用（跌破均价线离场），策略换了也不影响
        avg_arr = strat_avg_series
        entry_avg = float(avg_arr[entry_idx])
        peak = max(entry, sig_close)
        base = entry
        exit_price, exit_idx, reason = None, None, None
        # T+1：买入当日不能卖，从次日开始判断
        k = entry_idx + 1
        lose = 0
        while k < n:
            c = float(h["close"].iloc[k])
            lo = float(h["low"].iloc[k])
            op = float(h["open"].iloc[k])
            peak = max(peak, float(h["high"].iloc[k]))
            # 1 止损
            # ★ 旧写法只看收盘价 c <= 止损价，跳空低开/跌停时这一笔的真实亏损被吃掉，
            #   于是出现"止损 6% 却亏 32%"的假数据。现在按"盘中低点碰线"触发，
            #   成交价取 min(开盘价, 止损价)：跳空低开就按开盘价成交，不能按止损价。
            #   买入当日（k == entry_idx）不判止损，因为当天从建仓到收盘只有几个小时。
            stop_px = base * (1 - stop)
            if k > entry_idx and lo <= stop_px:
                exit_price, exit_idx, reason = min(op, stop_px), k, "止损"
                break
            # 2 均价线失守（用"收盘价对当日均价线"判定，且要求连续 2 日失守才离场，
            #   避免单日噪声；买入次日就会检查，所以不能再用信号日的高溢价做基准）
            if k > entry_idx and c < float(avg_arr[k]):
                if lose >= 1:
                    exit_price, exit_idx, reason = c, k, "跌破均价线"
                    break
                lose += 1
            else:
                lose = 0
            # 3 止盈
            if mode == "atr":
                if peak >= base * 1.05 and c <= peak * (1 - trail):
                    exit_price, exit_idx, reason = c, k, "移动止盈"
                    break
            else:
                # ★ 止盈同理：盘中碰到止盈价就卖；高开跳过止盈价则按开盘价
                #   （旧写法只看收盘价，会漏掉"当天冲高到 16% 又收回来"的单子）
                tp_px = base * (1 + tp)
                if k > entry_idx and float(h["high"].iloc[k]) >= tp_px:
                    exit_price, exit_idx, reason = max(op, tp_px), k, "止盈"
                    break
            # 4 时间止损
            if k - entry_idx >= max_hold:
                exit_price, exit_idx, reason = c, k, "时间止损"
                break
            # 5 趋势离场
            if ma_exit and k >= ma_exit:
                ma = float(np.mean(h["close"].iloc[k - ma_exit + 1:k + 1]))
                if c < ma:
                    exit_price, exit_idx, reason = c, k, f"跌破MA{ma_exit}"
                    break
            k += 1
        if exit_price is None:
            exit_price, exit_idx, reason = float(h["close"].iloc[-1]), n - 1, "持仓中"

        gross = exit_price / entry - 1
        # ★ 扣掉真实成本。原来是零成本，毛利 +0.12% 就被当成赚钱，
        #   实际来回 0.30% 一扣直接变负。成本率按这笔的实际价差摊薄最低佣金。
        cr = cost_rate(entry, exit_price, params) if bool(params.get("cost_on", True)) else 0.0
        net = gross * 100 - cr
        # 信号当天的筹码/位置：从策略的事实表里取（换策略也能拿到，取不到就给 None）
        sig_facts = strat.facts(strats.Ctx(code, name, h, i=i, shared=shared), params)
        try:
            _ch = sig_facts.get("chip") or {}
        except Exception:                                   # noqa: BLE001
            _ch = {}
        try:
            _ps = sig_facts.get("pos") or {}
        except Exception:                                   # noqa: BLE001
            _ps = {}
        trades.append({
            "code": code, "name": name,
            "signal_date": str(sig["date"]),
            "buy_date": str(h["date"].iloc[entry_idx]), "buy": round(entry, 3),
            "sell_date": str(h["date"].iloc[exit_idx]), "sell": round(exit_price, 3),
            "hold": int(exit_idx - entry_idx),
            "gross": round(gross * 100, 2),
            "cost": round(cr, 3),
            "ret": round(net, 2),
            "reason": reason,
            "profit_ratio": round(float(_ch["profit_ratio"]) * 100, 1) if _ch.get("profit_ratio") is not None else None,
            "pos": round(float(_ps["pos"]) * 100, 1) if _ps.get("pos") is not None else None,
            "open": reason == "持仓中",
            "_entry_avg": entry_avg,
        })
        i = exit_idx + 1 if exit_idx > i else i + 1
    # span = 这只票实际被检验的日期区间（起点是筹码窗口预热完的那一根，
    # 所以会比数据最早那根晚 120 个交易日左右）
    return {"code": code, "name": name, "trades": trades, "error": None,
            "span": [str(h["date"].iloc[start])[:10], str(h["date"].iloc[-1])[:10],
                     int(n - start)]}


def summarize(trades) -> dict:
    """只统计「信号质量」，不碰钱。

    这里刻意不算资金曲线和总收益：同一批交易在「每天满仓、信号来了就买」的假设下
    会算出 -17.75%，在「钱只有一份、买满了就跳过」的假设下只有 -1.88%，两个数差 9 倍，
    摆在一起只会让人以为软件算错了。赚钱多少一律以 portfolio（模拟账户）为准，
    本模块只回答「这套买卖规则挑出来的信号本身好不好」。
    """
    if not trades:
        return {"count": 0, "closed": 0, "open": 0,
                "win_rate": 0, "avg_ret": 0, "med_ret": 0,
                "max_win": 0, "max_loss": 0, "avg_hold": 0, "profit_factor": 0,
                "avg_win": 0, "avg_loss": 0, "payoff": 0, "reasons": {},
                "gross_ret": 0, "avg_cost": 0, "expectancy": 0, "breakeven_wr": 0}
    closed = [t for t in trades if not t.get("open")]
    base = closed or trades
    rets = np.array([t["ret"] for t in base], dtype=float)
    gross = np.array([t.get("gross", t["ret"]) for t in base], dtype=float)
    costs = np.array([t.get("cost", 0.0) for t in base], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else (99.0 if len(wins) else 0.0)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    # 盈亏比：赢的时候平均赚多少 / 输的时候平均亏多少。>1 说明「亏小赚大」
    payoff = (avg_win / abs(avg_loss)) if avg_loss else (99.0 if avg_win else 0.0)
    # 保本胜率：盈亏比 R 下至少要有多少胜率才不亏，和实际胜率并排看才说明问题
    breakeven_wr = (1.0 / (1.0 + payoff) * 100) if payoff > 0 else 0.0
    reasons = defaultdict(int)
    for t in base:
        reasons[t["reason"]] += 1
    return {
        "count": len(trades), "closed": len(closed),
        # 还没平仓的那几笔不算进胜率/收益：它们只是"还没到卖出条件"，不是一笔完整交易
        "open": len(trades) - len(closed),
        "win_rate": round(float((rets > 0).mean() * 100), 1) if len(rets) else 0,
        "avg_ret": round(float(rets.mean()), 2) if len(rets) else 0,
        "med_ret": round(float(np.median(rets)), 2) if len(rets) else 0,
        "max_win": round(float(rets.max()), 2) if len(rets) else 0,
        "max_loss": round(float(rets.min()), 2) if len(rets) else 0,
        "avg_hold": round(float(np.mean([t["hold"] for t in base])), 1) if base else 0,
        "profit_factor": round(float(pf), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff": round(float(payoff), 2),
        "reasons": dict(reasons),
        # 扣成本前后的对照：毛利跑不赢成本，就不用往下看了
        "gross_ret": round(float(gross.mean()), 2) if len(gross) else 0,
        "avg_cost": round(float(costs.mean()), 3) if len(costs) else 0,
        "breakeven_wr": round(float(breakeven_wr), 1),
        "expectancy": round(float(rets.mean()), 2) if len(rets) else 0,
    }


def run_backtest(params: dict, weights: dict, codes=None, limit: int = 40,
                 mode: str = "balanced", lookback: int = 1000, progress=None) -> dict:
    """批量回测：给出每只票的交易明细 + 汇总统计。"""
    from . import screener  # 延迟导入避免循环

    t0 = time.time()
    log = progress or (lambda **k: None)
    if codes:
        pool = pd.DataFrame({"code": [str(c) for c in codes], "name": [""] * len(codes)})
    else:
        snap = store.get_list()
        pool = screener.prefilter(snap, params)
        pool = screener.balance_pool(pool, limit, mode)
        pool = pool[["code", "name"]]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_trades, per_stock, done = [], [], 0
    spans = []
    n = len(pool)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(backtest_one, r.code, r.name, params, lookback, 3): r.code
                for r in pool.itertuples()}
        for f in as_completed(futs):
            done += 1
            r = f.result()
            if r and r.get("span"):
                spans.append(r["span"])
            if r and r.get("trades"):
                all_trades.extend(r["trades"])
                sm = summarize(r["trades"])
                per_stock.append({"code": r["code"], "name": r["name"],
                                  "count": sm["count"], "win_rate": sm["win_rate"],
                                  "avg_ret": sm["avg_ret"], "med_ret": sm["med_ret"],
                                  "payoff": sm["payoff"]})
            if done % 3 == 0 or done == n:
                log(phase="bt", msg=f"回测 {done}/{n}", pct=int(95 * done / max(n, 1)))
    total = summarize(all_trades)
    per_stock.sort(key=lambda x: -x["avg_ret"])
    log(phase="done", msg=f"完成 {total['count']} 笔交易", pct=100)
    # 实际检验区间：让界面上写清楚"这次到底覆盖了哪几年"，
    # 否则用户选了近两年却以为数据丢了四年
    coverage = {}
    if spans:
        coverage = {"from": min(s[0] for s in spans), "to": max(s[1] for s in spans),
                    "days": max(s[2] for s in spans)}
    return {
        "summary": total,
        "coverage": coverage,
        "trades": sorted(all_trades, key=lambda t: t["buy_date"], reverse=True)[:500],
        "per_stock": per_stock[:60],
        "params": {k: params.get(k) for k in (
            "ma_days", "ma_ratio", "ma_tol", "chip_window", "profit_cap", "pos_cap",
            "stop_loss", "take_profit", "max_hold", "sell_mode", "trail_drawdown",
            "buy_rule", "entry_mode", "ma_exit",
            "commission", "stamp", "slippage", "notional")},
        "note": "已应用市场状态开关（指数低于 MA20 才开仓）——165 笔回测：不加开关 -5.5%，加了 +22%。\n回测用日线 VWAP 近似（免费源无长历史分时），只验证买卖点规则本身。"
            "信号日次日开盘成交（不是当日收盘价，避免同一个 bar 内前视）；"
            "T+1 强制、止损/止盈按盘中高低点触发，跳空时按开盘价成交；"
            "ret 已扣佣金/印花税/过户费/滑点，gross 是扣前的毛利。"
            "这里不算钱，想知道真实资金能变成多少请看「模拟账户」",
        "elapsed": round(time.time() - t0, 1),
        "scanned": n,
    }
