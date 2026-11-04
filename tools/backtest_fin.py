# -*- coding: utf-8 -*-
"""用 19 年全历史重算净值曲线（fin_history.json）与历史机会（fin_trades.json）。

为什么要有这个脚本
------------------
界面上的「年化 / 回撤 / 净值曲线 / 历史机会」以前是 factor_lab 里几个一次性脚本
分别算的，口径各不相同（一个是每 40 天固定调仓的网格，一个是日频回放），
数字看着能对上纯属碰巧。现在统一到**一个日频回放引擎**，一份数据源（腾讯全历史），
跑一次同时产出两个 json —— 三个数字从此一定是同一件事。

规则（和 lxquant/finance.py 写死的一致）：
    进场：上证相对 MA20 跌超 GATE，**且** 相对 MA250 跌超 GATE250
    选股：银行 1 + 保险 1，各按板块内避差分取最高
    卖出：40 个交易日到期，或收盘跌破买入价 STOP_PCT% （先到先执行）
    成本：往返 0.35%，空仓按年化 1.2% 计息

用法：./runtime/python.exe tools/backtest_fin.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lxquant.config import DATA_DIR           # noqa: E402
from lxquant.finance import (                  # noqa: E402
    POOL, QUOTA, GATE, GATE250, HOLD_DAYS, STOP_PCT, _drop_unclosed,
)

WHICH = ("银行", "保险")
COST = 0.0035
CASH_DAILY = 0.00005
BEG = "2007-03-01"        # 保险最早 2007-01 上市，再往前没有「1 银行 + 1 保险」可买


def load():
    f = DATA_DIR / "fin_long.pkl"
    if not f.exists():
        raise SystemExit("缺 data/fin_long.pkl，先跑 tools/fetch_fin.py")
    df = pd.read_pickle(f)
    # 和界面同一套口径：15:10 之前丢掉「今天还没收盘」那根，
    # 否则曲线会停在盘中实时价上，而信号停在前一天。
    df = _drop_unclosed(df)
    codes = {c for b in WHICH for c, _ in POOL[b]}
    d = df[df["code"].astype(str).isin(codes)][["date", "code", "close", "volume"]]
    C = d.pivot(index="date", columns="code", values="close").astype("float32").sort_index()
    V = d.pivot(index="date", columns="code", values="volume").astype("float32").sort_index()
    return C, V


def score_of(C, V):
    ret = C / C.shift(1) - 1
    ma = C.rolling(60, min_periods=60).mean() / C
    sd = ret.rolling(20, min_periods=15).std()
    cv = C.rolling(20, min_periods=15).corr(np.log(V + 1))
    out = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    for board in WHICH:
        cols = [c for c, _ in POOL[board] if c in C.columns]
        out[cols] = (ma[cols].rank(axis=1, pct=True)
                     + (1 - sd[cols].rank(axis=1, pct=True))
                     + (1 - cv[cols].rank(axis=1, pct=True))) / 3 * 100
    return out


def index_close(C):
    ic = pd.read_pickle(DATA_DIR / "idx_long.pkl").set_index("date")["close"].astype(float)
    return ic.reindex(C.index).ffill()


def name_of(code):
    for items in POOL.values():
        for c, n in items:
            if c == code:
                return n
    return code


def board_of(code):
    for b, items in POOL.items():
        if any(c == code for c, _ in items):
            return b
    return ""


def simulate(C, S, ic):
    dates = list(C.index)
    vs20 = (ic / ic.rolling(20, min_periods=15).mean() - 1) * 100
    vs250 = (ic / ic.rolling(250, min_periods=200).mean() - 1) * 100

    nav, nd, pos, trades = [1.0], [dates[0]], None, []
    for i, d in enumerate(dates):
        if pos is not None:
            px = C.loc[d, pos["picks"]].astype(float)
            ratio = px / pos["buy"]
            avg = float(ratio.mean()) if np.isfinite(ratio).all() else pos["last"]
            held = i - pos["i"]
            reason = None
            if held >= HOLD_DAYS:
                reason = "到期"
            elif avg <= 1 - STOP_PCT / 100:
                reason = "止损"
            if reason:
                nav.append(nav[-1] * (1 - COST) * (avg / pos["last"]))
                nd.append(d)
                trades.append({
                    "date": pos["date"], "sell": str(d)[:10],
                    "vs20": round(pos["vs20"], 2), "vs250": round(pos["vs250"], 2),
                    "picks": [{"code": c,
                               "name": name_of(c),
                               "board": board_of(c),
                               "score": round(float(pos["score"][c]), 0),
                               "buy": round(float(pos["buy"][c]), 2),
                               "sell": round(float(px[c]), 2),
                               "ret": round(float(px[c] / pos["buy"][c] - 1) * 100 - COST * 100, 2)}
                              for c in pos["picks"]],
                    "ret": (avg - 1) * 100 - COST * 100,
                    "held": held, "why": reason,
                    "mkt": round(float(ic.loc[d] / ic.loc[pos["date"]] - 1) * 100, 2),
                })
                pos = None
                continue
            nav.append(nav[-1] * avg / pos["last"])
            nd.append(d)
            pos["last"] = avg
            continue

        nav.append(nav[-1] * (1 + CASH_DAILY))
        nd.append(d)
        if i < 250 or not np.isfinite(vs20.get(d, np.nan)) \
                or not np.isfinite(vs250.get(d, np.nan)):
            continue
        if vs20[d] >= -GATE or vs250[d] >= -GATE250:
            continue
        sc = S.loc[d].dropna()
        picks = []
        for b, k in QUOTA:
            cand = [c for c in sc.index if any(c == x for x, _ in POOL[b])]
            if cand:
                picks += list(sc[cand].nlargest(k).index)
        if len(picks) < 2:
            continue
        buy = C.loc[d, picks].astype(float)
        if (buy <= 0).any():
            continue
        nav[-1] *= (1 - COST)
        pos = {"i": i, "date": str(d)[:10], "picks": picks, "buy": buy,
               "last": 1.0, "vs20": float(vs20[d]), "vs250": float(vs250[d]),
               "score": {c: sc[c] for c in picks}}

    s = pd.Series(nav, index=nd)
    return s[~s.index.duplicated(keep="last")], trades, pos, ic, dates


def metrics(nav, trades):
    years = (pd.Timestamp(str(nav.index[-1])) - pd.Timestamp(str(nav.index[0]))).days / 365.25
    years = max(years, 0.5)
    ann = nav.iloc[-1] ** (1 / years) - 1
    dd = float((nav / nav.cummax() - 1).min())
    vol = float(nav.pct_change().dropna().std() * np.sqrt(244))
    sharpe = ann / vol if vol > 0 else 0.0
    se = float(np.sqrt((1 + sharpe ** 2 / 2) / years))
    rets = [t["ret"] for t in trades]
    return {
        "stat": {
            "ann": round(ann * 100, 1), "mdd": round(dd * 100, 1),
            "vol": round(vol * 100, 1), "sharpe": round(sharpe, 2),
            "se": round(se, 2),
            "calmar": round(ann / abs(dd), 2) if dd else 0.0,
        },
        "years": round(years, 1), "n": len(trades),
        "win": round(sum(1 for x in rets if x > 0) / len(rets) * 100, 0) if rets else 0,
        "avg": round(float(np.mean(rets)), 2) if rets else 0,
    }


def main():
    # 先把尾部补到今天（hfq 的历史值不变，只追加）。限流/断网时沿用旧数据，
    # 不能因为补不到最新一根就跑不出回测。
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import fetch_fin
        print("数据最新到", fetch_fin.refresh())
    except Exception as e:
        print("补尾巴失败，用本地数据继续：", str(e)[:80])

    C, V = load()
    S = score_of(C, V)
    ic = index_close(C)
    ok = ic.notna() & S.notna().any(axis=1) & C.notna().sum(axis=1).ge(2)
    C, S, ic = C.loc[ok].loc[BEG:], S.loc[ok].loc[BEG:], ic.loc[ok].loc[BEG:]

    nav, trades, pos, icf, dates = simulate(C, S, ic)
    m = metrics(nav, trades)
    st = m["stat"]
    print("%s ~ %s · %d 笔 · 年化 %+.1f%% · 回撤 %+.1f%% · SR %.2f (±%.2f) · 胜率 %.0f%%"
          % (nav.index[0], nav.index[-1], m["n"], st["ann"], st["mdd"],
             st["sharpe"], st["se"], m["win"]))

    # 年度收益：按净值曲线的自然年切，不是按交易笔数
    n = nav.copy()
    n.index = pd.to_datetime(n.index)
    y = n.resample("YE").last()
    y = pd.concat([pd.Series([1.0], index=[n.index[0]]), y])
    yearly = {str(k.year): round(float(v), 1)
              for k, v in (y.pct_change().dropna() * 100).items()}

    hist = {
        "stat": st,
        "yearly": yearly,
        "range": [str(nav.index[0])[:10], str(nav.index[-1])[:10]],
        "curve": [[str(d)[:10], round(float(v), 3)] for d, v in nav.items()],
        "trades": m["n"],
        "stop": STOP_PCT, "hold": HOLD_DAYS, "gate": GATE, "gate250": GATE250,
    }
    (DATA_DIR / "fin_history.json").write_text(
        json.dumps(hist, ensure_ascii=False), encoding="utf-8")

    # 历史机会表：一笔一次，倒序（最近的在上）
    items = []
    for t in reversed(trades):
        items.append({
            "date": t["date"], "vs20": t["vs20"], "vs250": t["vs250"],
            "due": t["sell"],
            "picks": t["picks"],
            "ret": round(t["ret"], 2),
            "mkt": t["mkt"],
            "why": t["why"],
        })
    if pos is not None:      # 还拿在手里的那笔
        items.insert(0, {
            "date": pos["date"], "vs20": round(pos["vs20"], 2),
            "vs250": round(pos["vs250"], 2), "due": "",
            "picks": [{"code": c, "name": name_of(c), "board": board_of(c),
                       "score": round(float(pos["score"][c]), 0),
                       "buy": round(float(pos["buy"][c]), 2),
                       "sell": None, "ret": None} for c in pos["picks"]],
            "ret": None, "mkt": None, "why": "",
        })

    rets = [t["ret"] for t in trades]
    mkts = [t["mkt"] for t in trades]
    tr = {
        "gate": GATE, "gate250": GATE250, "hold": HOLD_DAYS,
        "summary": {
            "n": len(items), "settled": len(trades),
            "win": sum(1 for x in rets if x > 0),
            "avg": round(float(np.mean(rets)), 2) if rets else 0,
            "med": round(float(np.median(rets)), 2) if rets else 0,
            "best": round(float(max(rets)), 1) if rets else 0,
            "worst": round(float(min(rets)), 1) if rets else 0,
            "avg_mkt": round(float(np.mean(mkts)), 2) if mkts else 0,
        },
        "range": [str(nav.index[0])[:10], str(nav.index[-1])[:10]],
        "items": items,
    }
    (DATA_DIR / "fin_trades.json").write_text(
        json.dumps(tr, ensure_ascii=False), encoding="utf-8")

    print("年度：", "  ".join(f"{k}:{v:+.1f}" for k, v in yearly.items()))
    print("机会表 %d 条（已结算 %d，胜 %d，均 %+.2f%%）"
          % (len(items), tr["summary"]["settled"], tr["summary"]["win"], tr["summary"]["avg"]))
    print("已写入 fin_history.json / fin_trades.json")


if __name__ == "__main__":
    main()
