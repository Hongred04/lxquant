# -*- coding: utf-8 -*-
"""持仓跟踪：把「40 天后卖」这句话变成能看的进度。

为什么单独一个模块：
    策略本身一年只给两三次机会，但一次要拿 40 个交易日。这 40 天里软件
    如果什么都不说，用户就会开始怀疑、提前卖、或者忘了它 —— 三种都亏钱。
    所以它至少要能回答四个问题：买了没、第几天、还剩几天、现在赚多少。

刻意做得很窄：
    - 只能记「按规则买的那两票」，不开放手工加仓/改价，否则这里会变成
      一个半吊子持仓管理工具，和策略本身脱节。
    - 不记股数，只记买入价。收益按比例算，用户实际买多少股不影响结论。
"""
from __future__ import annotations

import json
import os
import time

from .config import DATA_DIR

POS = DATA_DIR / "fin_pos.json"
VERSION = 1
HOLD = 40           # 和 finance.HOLD_DAYS 一致


def _load() -> dict:
    try:
        if not POS.exists():
            return {}
        d = json.loads(POS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and int(d.get("v") or 0) == VERSION else {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    d = dict(d, v=VERSION)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = POS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, POS)


def _trading_days(start: str, n: int) -> str:
    """start 之后的第 n 个交易日（按工作日近似，不含法定节假日）。

    节假日会让真实到期日往后挪一两天。这里不硬编码节假日表 ——
    那表每年都要维护，错一次比差两天更糟。界面上写「预计到期」，
    到了那天提示用户自己看一眼行情。
    """
    import pandas as pd
    rng = pd.bdate_range(start=pd.Timestamp(start), periods=n + 1)
    return str(rng[-1])[:10]


def _last_price(code: str) -> float:
    try:
        from . import store
        df = store.get_kline(code, "day", 30)
        if df is None or not len(df):
            return 0.0
        return float(df["close"].astype(float).iloc[-1])
    except Exception:
        return 0.0


def open_pos(date: str = "", note: str = "") -> dict:
    """按当前的选股结果记一笔买入。"""
    from . import finance

    st = finance.load() or {}
    picks = st.get("picks") or []
    if len(picks) < 2:
        return {"ok": False, "msg": "还没有选出两只票，先等选股结果"}

    d = date or time.strftime("%Y-%m-%d")
    items = []
    for p in picks:
        px = _last_price(p["code"]) or float(p["price"])
        items.append({"code": p["code"], "name": p["name"], "board": p["board"],
                      "buy": round(px, 2), "entry_score": p.get("score")})

    # 已有一笔持仓就不覆盖 —— 覆盖会让「上次什么时候买的」消失，
    # 而那个日期正是这笔交易唯一不可再生的信息。
    cur = _load()
    if cur.get("active"):
        return {"ok": False, "msg": "已经有一笔在持有中，先平掉再记新的"}

    _save({"active": {"buy_date": d, "due_date": _trading_days(d, HOLD),
                      "items": items, "note": note,
                      "opened_at": time.strftime("%Y-%m-%d %H:%M:%S")},
           "history": cur.get("history") or []})
    return {"ok": True, **view()}


def close_pos() -> dict:
    """平掉当前持仓，落进历史。收益按最后一次收盘价算。"""
    cur = _load()
    act = cur.get("active")
    if not act:
        return {"ok": False, "msg": "当前没有持仓"}
    row = _settle(act)
    hist = (cur.get("history") or [])[:50]
    hist.insert(0, row)
    _save({"active": None, "history": hist})
    return {"ok": True, **view()}


def _settle(act: dict) -> dict:
    rows = []
    for it in act.get("items") or []:
        cur = _last_price(it["code"]) or float(it["buy"])
        rows.append({**it, "now": round(cur, 2),
                     "ret": round((cur / float(it["buy"]) - 1) * 100, 1)
                     if float(it["buy"]) > 0 else 0.0})
    avg = round(sum(r["ret"] for r in rows) / len(rows), 1) if rows else 0.0
    return {"buy_date": act.get("buy_date"), "due_date": act.get("due_date"),
            "items": rows, "ret": avg, "note": act.get("note", "")}


def view() -> dict:
    d = _load()
    act = d.get("active")
    out = {"ready": True, "active": None, "history": (d.get("history") or [])[:12],
           "hold_days": HOLD}
    if not act:
        return out

    s = _settle(act)
    # 已过交易日：用工作日近似算，和到期日同一套口径，两边不会自相矛盾
    try:
        import pandas as pd
        bd = len(pd.bdate_range(start=pd.Timestamp(act["buy_date"]),
                                end=pd.Timestamp(time.strftime("%Y-%m-%d")))) - 1
    except Exception:
        bd = 0
    bd = max(0, bd)
    s["held"] = bd
    s["left"] = max(0, HOLD - bd)
    s["pct"] = round(min(100.0, bd / HOLD * 100), 1)
    s["due"] = s["left"] <= 0
    out["active"] = s
    return out
