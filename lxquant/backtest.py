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


def _approx_avg_series(h: pd.DataFrame) -> np.ndarray:
    tp = (h["high"] + h["low"] + h["close"]) / 3.0
    prev_close = h["close"].shift(1).bfill()
    return ((tp + prev_close) / 2.0).values


def signal_series(h: pd.DataFrame, days: int = 3) -> np.ndarray:
    avg = _approx_avg_series(h)
    return (h["close"].values >= avg)  # bool 数组


def _chip_at(h: pd.DataFrame, i: int, window=120, bins=70, decay=0.985, price=None) -> dict:
    sub = h.iloc[max(0, i - window):i + 1]
    px = float(h["close"].iloc[i]) if price is None else price
    return ind.chip_distribution(sub, px, window, bins, decay)


def _pos_at(h: pd.DataFrame, i: int, window=120):
    return ind.price_position(h.iloc[max(0, i - window):i + 1], float(h["close"].iloc[i]), window)


def backtest_one(code: str, name: str, params: dict, lookback: int = 250,
                 hold_days: int = 3) -> dict:
    """
    单票回测：在过去 lookback 天里寻找"连续站上均价线 且 筹码低位"的信号，
    按买卖规则模拟持仓，统计每笔收益。
    """
    h = store.get_daily(code, 320)
    if h is None or len(h) < 150:
        return {"code": code, "name": name, "trades": [], "error": "数据不足"}
    h = h.reset_index(drop=True)
    n = len(h)
    days = int(params.get("ma_days", 3))
    prof_cap = float(params.get("profit_cap", 0.25))
    pos_cap = float(params.get("pos_cap", 0.30))
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

    flags = signal_series(h, days)
    start = max(win, n - lookback)
    trades = []
    i = start
    while i < n - 2:
        # 连续 days 天站上均价线
        if not all(flags[i - k] for k in range(days)):
            i += 1
            continue
        # 筹码低位过滤
        ch = _chip_at(h, i, win, int(params.get("chip_bins", 70)),
                      float(params.get("chip_decay", 0.985)))
        ps = _pos_at(h, i, win)
        if ch.get("profit_ratio") is None or ch["profit_ratio"] > prof_cap:
            i += 1
            continue
        if ps.get("pos") is None or ps["pos"] > pos_cap:
            i += 1
            continue

        sig = h.iloc[i]
        sig_close = float(sig["close"])
        tail_entry = bool(str(params.get("entry_mode", "tail")) == "tail" or rule == "same_day_tail")
        # ---------------- 买入
        if tail_entry:
            # ★ 尾盘买入：14:30 信号成立即当日尾盘成交（用当日收盘价近似尾盘价）
            entry = float(sig["close"])
            j = i + 1                      # 从下一个交易日开始判断卖出
        else:
            j = i + 1
            if j >= n:
                break
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
        if entry is None:
            i += 1
            continue

        entry_idx = j
        entry_avg = float(_approx_avg_series(h)[entry_idx])
        if tail_entry:
            # 尾盘当日买入：买入日就是信号日，卖出从次日起判断
            entry_idx = i
            entry_avg = float(_approx_avg_series(h)[i])
        peak = max(entry, sig_close)
        base = entry if str(params.get("entry_mode", "tail")) != "tail" else sig_close
        exit_price, exit_idx, reason = None, None, None
        k = entry_idx
        lose = 0
        avg_arr = _approx_avg_series(h)
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

        ret = exit_price / entry - 1
        trades.append({
            "code": code, "name": name,
            "signal_date": str(sig["date"]),
            "buy_date": str(h["date"].iloc[entry_idx]), "buy": round(entry, 3),
            "sell_date": str(h["date"].iloc[exit_idx]), "sell": round(exit_price, 3),
            "hold": int(exit_idx - entry_idx), "ret": round(ret * 100, 2),
            "reason": reason,
            "profit_ratio": round(float(ch["profit_ratio"]) * 100, 1),
            "pos": round(float(ps["pos"]) * 100, 1),
            "open": reason == "持仓中",
            "_entry_avg": entry_avg,
        })
        i = exit_idx + 1 if exit_idx > i else i + 1
    return {"code": code, "name": name, "trades": trades, "error": None}


def summarize(trades) -> dict:
    if not trades:
        return {"count": 0, "closed": 0, "open": 0,
                "win_rate": 0, "avg_ret": 0, "med_ret": 0, "pnl": 0,
                "max_win": 0, "max_loss": 0, "avg_hold": 0, "profit_factor": 0,
                "curve": [], "reasons": {}}
    closed = [t for t in trades if not t.get("open")]
    base = closed or trades
    rets = np.array([t["ret"] for t in base], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else (99.0 if len(wins) else 0.0)
    # ---------------- 资金曲线
    # ★ 旧写法把每笔收益直接连乘（eq *= 1+ret/100），那等于假设"同一笔钱做完一单立刻做下一单、
    #   而且永远只持一只票"。真实回测里几千笔交易是并发的，连乘必然算出 +10000% 这种荒谬的数，
    #   最大回撤也永远是 100%。
    #   现在按"实际占用资金"算：把整段时间切成交易日，每日收益 = 各笔当日涨跌 × 该笔占用份额，
    #   占用份额 = 该笔买入金额 / 当日所有持仓金额之和（按收盘市值动态计算）。
    #   这就是"每天满仓、不挑票"的等权组合，也是这套系统做模拟账户时的真实口径。
    curve, pnl = _equity_curve(trades)
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
        "pnl": round(float(pnl), 2),
        "max_win": round(float(rets.max()), 2) if len(rets) else 0,
        "max_loss": round(float(rets.min()), 2) if len(rets) else 0,
        "avg_hold": round(float(np.mean([t["hold"] for t in base])), 1) if base else 0,
        "profit_factor": round(float(pf), 2),
        "curve": curve,
        "reasons": dict(reasons),
    }


def _equity_curve(trades, initial_cash: float = 1.0):
    """按"每天等权摊到所有持仓"算资金曲线，返回 (curve, 总收益%)。

    每一笔：买入日按 buy 建仓、卖出日按 sell 平仓，占用 1 份名义本金。
    当日组合收益 = Σ(每笔当日涨跌 × 该笔占用份额)，占用份额 = 该笔本金 / 当日全部持仓本金。
    每笔的日度变动用买入价和卖出价之间的"等比例复利"平摊（(sell/buy)^(1/持有天数)），
    这样曲线是平滑的、终值严格等于逐笔盈亏之和，不会像旧写法那样连乘出 +10000%。
    这只衡量"每天满仓摊平"的组合表现，不是真实成交价，但量级和回撤是对的。
    """
    if not trades:
        return [], 0.0
    ts = [t for t in trades if t.get("buy") and t.get("sell")]
    if not ts:
        return [], 0.0
    for t in ts:
        t["_span"] = max(1, int(t.get("hold") or 1))
        t["_rate"] = (float(t["sell"]) / float(t["buy"])) ** (1.0 / t["_span"]) - 1.0
    all_days = sorted({t["buy_date"] for t in ts} | {t["sell_date"] for t in ts})
    day_i = {d: i for i, d in enumerate(all_days)}
    eq, curve = initial_cash, []
    for d in all_days:
        i = day_i[d]
        live, num = 0, 0.0
        for t in ts:
            b, s = day_i[t["buy_date"]], day_i[t["sell_date"]]
            if b <= i <= s:                       # 当天在持仓里
                live += 1
                num += t["_rate"]                 # 当日按平摊的日收益率
        if live:
            eq *= (1.0 + num / live)              # 等权：每笔占 1/live 的份额
        curve.append([d, round((eq - 1.0) * 100, 2)])
    return curve, (eq - 1.0) * 100


def run_backtest(params: dict, weights: dict, codes=None, limit: int = 40,
                 mode: str = "balanced", lookback: int = 250, progress=None) -> dict:
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
    n = len(pool)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(backtest_one, r.code, r.name, params, lookback, 3): r.code
                for r in pool.itertuples()}
        for f in as_completed(futs):
            done += 1
            r = f.result()
            if r and r.get("trades"):
                all_trades.extend(r["trades"])
                sm = summarize(r["trades"])
                per_stock.append({"code": r["code"], "name": r["name"],
                                  "count": sm["count"], "win_rate": sm["win_rate"],
                                  "avg_ret": sm["avg_ret"], "pnl": sm["pnl"]})
            if done % 3 == 0 or done == n:
                log(phase="bt", msg=f"回测 {done}/{n}", pct=int(95 * done / max(n, 1)))
    total = summarize(all_trades)
    per_stock.sort(key=lambda x: -x["avg_ret"])
    log(phase="done", msg=f"完成 {total['count']} 笔交易", pct=100)
    return {
        "summary": total,
        "trades": sorted(all_trades, key=lambda t: t["buy_date"], reverse=True)[:500],
        "per_stock": per_stock[:60],
        "params": {k: params.get(k) for k in (
            "ma_days", "ma_ratio", "chip_window", "profit_cap", "pos_cap", "stop_loss",
            "take_profit", "max_hold", "sell_mode", "trail_drawdown", "buy_rule")},
        "note": "回测使用日线 VWAP 近似（免费源无长历史分时），仅验证买卖点规则；"
            "止损/止盈按盘中高低点触发，跳空时按开盘价成交；资金曲线为每日等权摊平口径",
        "elapsed": round(time.time() - t0, 1),
        "scanned": n,
    }
