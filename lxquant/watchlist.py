# -*- coding: utf-8 -*-
"""自选股 + 买点卖点提醒。

用户要的是："我盯着的这几只，什么时候该买、什么时候该卖，告诉我一声。"

这里不自己发明一套指标，全部复用选股那五关算出来的东西（streak / avg_surplus /
profit_ratio / pos / plan），这样"提醒我买"和"软件选出来的"是同一套口径，
不会出现"软件说能买、提醒又说不能买"互相打架的情况。

规则（都写在一处，免得以后各改各的）
------------------------------------
买点 —— 下面几条里满足任意一条就响：
  near   差一点：五关只差一关，且差的不是"连续站上平均成本"。这种时候提醒你，
         等它再站上一天就是标准的买点。
  ma     站上成本：五关全过（软件选股里会直接进"能买"名单）。
  pull   跌到支撑：价格回到 20 日均线附近（-1%~+2%）并且之前没在 MA 下面。
         这是低吸的位置。
卖点 —— 满足任意一条就响：
  stop   跌破止损：价格跌到 plan.stop 或以下（这是纪律，不是建议）。
  target 到目标价：价格涨到 plan.target（"参考目标"）附近。
  ma     掉破成本：从站上平均成本变成掉到下面（连续天数的 streak 归零）。
  trail  回撤止盈：赚了 8% 以上，又从最高点回落 5%。

每条提醒都有"同一件事几天内不重复"的地方（见 COOLDOWN）：
买点 1 天，卖点类型 1 天；止损不设冷却（它很重要，每次都要说）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime as _dt
from datetime import timedelta

from .config import DATA_DIR

WATCH_FILE = DATA_DIR / "watchlist.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
_LOCK = threading.RLock()
_ALERTS_KEEP = 200

# 每种提醒：冷却多久（分钟）不重复说。0 = 每次都报
COOLDOWN = {
    # 止损原来写 0（"很重要，每次都要说"），可 check() 每 3 分钟跑一轮，
    # 一只票一旦跌破止损，每轮都会生成新 sig、再弹一张卡 —— 这就是
    # "一打开软件就一堆提醒弹出来"的来源。改成 6 小时：止损照样立刻报，
    # 但不会没完没了地重复弹。
    "sell.stop": 6 * 60,
    "sell.target": 24 * 60,
    "sell.ma": 24 * 60,
    "sell.trail": 24 * 60,
    "buy.ma": 24 * 60,
    "buy.near": 12 * 60,
    "buy.pull": 24 * 60,
}
TEXT = {
    "buy.near": ("买点", "五关只差一关，再等一天可能就能买"),
    "buy.ma": ("买点", "五个条件全过了，按规则可以买"),
    "buy.pull": ("买点", "价格回到 20 日均线附近，是低吸的位置"),
    "sell.stop": ("卖点", "跌破止损价，别扛，按纪律走"),
    "sell.target": ("卖点", "到了参考目标价，可以考虑卖一半"),
    "sell.ma": ("卖点", "掉到了平均成本下面，先出来看"),
    "sell.trail": ("卖点", "从高点回落不少了，锁住利润"),
}


# ---------------------------------------------------------------- 读写
def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load() -> dict:
    """{"items": {code: {...}}, "alerts": [...], "seen": {sig: 时间}}"""
    raw = _read(WATCH_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("items", {})
    raw.setdefault("alerts", [])
    raw.setdefault("seen", {})
    raw.setdefault("check_at", "")
    return raw


def save(w: dict) -> None:
    with _LOCK:
        w["alerts"] = (w.get("alerts") or [])[:_ALERTS_KEEP]
        _write(WATCH_FILE, w)


# ---------------------------------------------------------------- 增删
def add(code: str, name: str = "", note: str = "") -> dict:
    from . import datasource as ds
    raw = str(code or "").strip()
    # 允许直接给名字/部分名字：找到唯一一只就用它，找到多个就报错让你填代码
    if not (raw.isdigit() and len(raw) == 6):
        got = find(raw, 3)
        if not got:
            raise ValueError(f"没找到「{raw}」这只股票")
        if len(got) > 1:
            raise ValueError("「%s」对上了好几只：%s，填代码更准。"
                             % (raw, "、".join(x["name"] for x in got)))
        code, name = got[0]["code"], name or got[0]["name"]
    code = ds.norm(str(code or "").strip())
    if not code or not code.isdigit() or len(code) != 6:
        raise ValueError("股票代码不对（要 6 位数字）")
    # 名字缺了（或只有一个「—」）就补上真名，界面上别显示成一个横杠
    if not name or str(name).strip() in ("", "—", "-"):
        name = _name_of(code) or name
    with _LOCK:
        w = load()
        it = w["items"].get(code) or {}
        it.update({"code": code, "name": name or it.get("name") or "", "added_at": it.get("added_at")
                   or _dt.now().strftime("%Y-%m-%d %H:%M")})
        if note:
            it["note"] = note
        w["items"][code] = it
        save(w)
        return it


def remove(code: str) -> bool:
    from . import datasource as ds
    code = ds.norm(str(code or "").strip())
    with _LOCK:
        w = load()
        ok = w["items"].pop(code, None) is not None
        save(w)
        return ok


def update(code: str, **fields) -> dict:
    from . import datasource as ds
    code = ds.norm(str(code or "").strip())
    with _LOCK:
        w = load()
        it = w["items"].get(code)
        if not it:
            raise ValueError("自选股里没有这只")
        for k in ("cost", "stop", "target", "note"):
            if k in fields:
                v = fields[k]
                if k == "note":
                    it[k] = str(v or "")[:200]
                else:
                    it[k] = _num(v)
        save(w)
        return it


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except Exception:
        return None


def _stock_df():
    """全市场清单（数据源内部有缓存，别重复拉）。拿不到就返回 None。"""
    from . import datasource as ds
    try:
        return ds.stock_list()
    except Exception:
        return None


def _name_of(code: str) -> str:
    df = _stock_df()
    if df is None:
        return ""
    row = df[df["code"].astype(str) == code]
    return str(row.iloc[0]["name"]) if len(row) else ""


def find(q: str, limit: int = 8) -> list:
    """按名字或代码找股票：填「茅台」就能找到 600519。

    先用「填的是不是 6 位代码」直接问一次实时行情（最快，也最常用）；
    不够 6 位才去拉全市场清单按名字筛。
    """
    from . import datasource as ds
    q = str(q or "").strip()
    if not q:
        return []
    if q.isdigit() and len(q) == 6:
        try:
            r = ds.realtime([q]).to_dict("records")
            if r:
                code, name = str(r[0]["code"]), _name_of(q) or q
                return [{"code": code, "name": name, "price": r[0].get("price"),
                         "chg_pct": r[0].get("chg_pct")}]
        except Exception:
            pass
    df = _stock_df()
    if df is None:
        return []
    codes = df["code"].astype(str)
    names = df["name"].astype(str).fillna("")
    hit = df[names.str.contains(q, na=False) | codes.str.startswith(q)]
    out = []
    for r in hit.sort_values("amount", ascending=False).head(limit).itertuples():
        out.append({"code": str(r.code), "name": str(r.name), "price": r.price, "chg_pct": r.chg_pct})
    return out


def list_all() -> list:
    w = load()
    return [w["items"][c] for c in w["items"]]


# ---------------------------------------------------------------- 提醒
def list_alerts(limit: int = 30) -> list:
    w = load()
    return (w.get("alerts") or [])[:limit]


def ack(sig: str = "", all_: bool = False) -> int:
    """标记已读：sig 指定一条，"all" 清空全部"""
    with _LOCK:
        w = load()
        before = len(w.get("alerts") or [])
        if all_ or sig == "all":
            w["alerts"] = []
        else:
            w["alerts"] = [a for a in (w.get("alerts") or []) if a.get("sig") != sig]
        save(w)
        return before - len(w["alerts"])


def _push(w: dict, kind: str, code: str, it: dict, extra: dict) -> dict:
    """把一条提醒写进队列。同一件事在冷却期内不重复写。"""
    tag, msg = TEXT.get(kind, ("提醒", ""))
    now = _dt.now()
    last = w["seen"].get(code + "|" + kind)
    cool = COOLDOWN.get(kind, 24 * 60)
    if cool and last:
        try:
            if now - _dt.strptime(last, "%Y-%m-%d %H:%M") < timedelta(minutes=cool):
                return {}
        except Exception:
            pass
    # sig 里带上冷却窗口的起点，而不是"今天"：
    # 写成"今天"的话，昨天弹过、用户没关的那条，今天会换个 sig 再生成一条，
    # 队列里就攒出同一天两三条一模一样的提醒（"每次打开都弹"）。同一个冷却
    # 窗口内永远是同一个 sig，队列里也就永远只有一条。
    if cool:
        win = now - timedelta(minutes=cool)
        sig = f"{code}|{kind}|{win.strftime('%Y-%m-%d %H:%M')}"
    else:
        sig = f"{code}|{kind}|{now.strftime('%Y-%m-%d %H:%M')}"
    w["seen"][code + "|" + kind] = now.strftime("%Y-%m-%d %H:%M")
    al = {"sig": sig, "kind": "buy" if tag == "买点" else "sell", "why": kind.split(".")[-1],
          "tag": tag, "code": code, "name": it.get("name") or "",
          "msg": extra.pop("msg", msg), "at": now.strftime("%m-%d %H:%M"),
          "ts": int(now.timestamp()), **extra}
    w["alerts"] = [al] + [a for a in (w.get("alerts") or []) if a.get("sig") != sig]
    return al


# ---------------------------------------------------------------- 判断
def _judge(code: str, it: dict) -> list:
    """对一只股票跑一遍规则，返回 (hits, analyzer 结果)。

    hits 是 [(kind, 数字)]；数字全部来自 analyzer.analyze + score + plan_targets，
    和选股页同一套口径。
    """
    from . import analyzer, config, datasource as ds, store

    cfg = config.load_config()
    p, wgt = cfg["params"], cfg["weights"]
    d = store.get_daily(code)
    # 名称先补：demo 里默认名字是「—」，真正的名字到 analyze 之后才知道
    known = (it.get("name") or "").strip()
    if known in ("", "—", "-"):
        it["name"] = _name_of(code) or known
    try:
        k5 = store.get_5min(code)
    except Exception:
        k5 = None
    rt = None
    try:
        r = ds.realtime([code])
        if not r.empty:
            rt = r.iloc[0].to_dict()
    except Exception:
        pass
    a = analyzer.analyze(code, it.get("name") or "", p, daily=d, k5=k5, rt=rt)
    a["score"] = analyzer.score(a, wgt, p)
    a["plan"] = analyzer.plan_targets(a["price"], a, p)
    if a.get("name"):
        it["name"] = a["name"]

    price = float(a.get("price") or 0)
    av = a.get("avg") or {}
    chk = a.get("checks") or {}
    tr = a.get("trend") or {}
    chip = a.get("chip") or {}
    # 成本：用户自己填的优先，否则用筹码分布算出来的平均成本
    cost = it.get("cost") or chip.get("avg_cost") or av.get("today_avg") or 0
    base = {"price": round(price, 3) if price else None,
            "vs_cost": round((price / cost - 1) * 100, 2) if (cost and price) else None,
            "chg_pct": a.get("chg_pct")}
    hits = []

    def hit(kind, **kw):
        hits.append((kind, {**base, **kw}))

    # ---- 卖点优先：已经在手里的，先看该不该走
    plan = a.get("plan") or {}
    stop = it.get("stop") or plan.get("stop")
    target = it.get("target") or plan.get("target")
    if stop and price and price <= float(stop):
        hit("sell.stop", stop=round(float(stop), 2),
            msg=f"{fmt(price)} 跌破 {fmt(stop)}，按纪律走")
    elif target and price and price >= float(target) * 0.99:
        hit("sell.target", target=round(float(target), 2),
            msg=f"{fmt(price)} 到参考目标 {fmt(target)} 了")
    else:
        # 掉破成本：价格确实在平均成本下面，而且站上成本的天数已经归零
        streak = (av.get("tail_streak") if str(p.get("entry_mode", "tail")) == "tail"
                  else av.get("streak")) or 0
        if cost and price and price < float(cost) * 0.98 and streak == 0:
            hit("sell.ma", msg=f"{fmt(price)} 掉到平均成本 {fmt(cost)} 下面了")
        # 回撤止盈：先得赚够 8%，再从记录过的高点回落 5%
        hi = it.get("hi") or 0
        if cost and hi and price:
            best = float(hi) / float(cost) - 1
            back = price / float(hi) - 1
            if best >= 0.08 and back <= -0.05:
                hit("sell.trail", back=round(back * 100, 2),
                    msg=f"从 {fmt(hi)} 回落 {abs(back) * 100:.1f}%，先锁一半利润")

    # ---- 买点
    if not hits:
        sc = float(a.get("score") or 0)
        # 五关（和界面上"五关"一致）：站上成本 / 筹码 / 位置 / 结构 / 趋势
        miss = [k for k in ("ma", "chip", "pos", "bottom", "trend") if not chk.get(k)]
        if sc >= 60 and not miss:
            hit("buy.ma", score=round(sc, 1), msg="五个条件全过了，按规则可以买")
        elif sc >= 45 and len(miss) <= 1 and "ma" not in miss:
            hit("buy.near", score=round(sc, 1),
                msg="五关只差一关，再等一天可能就够格了")
        # 低吸位：回到 20 日均线附近
        ma20 = tr.get("ma20")
        if ma20 and price and 0.99 * float(ma20) <= price <= 1.02 * float(ma20):
            hit("buy.pull", ma20=round(float(ma20), 2),
                msg=f"{fmt(price)} 回到 20 日均线 {fmt(ma20)} 附近，可以低吸")
    return hits, a


def fmt(v) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "—"


def check(force: bool = False) -> dict:
    """把所有自选股过一遍，命中的写进提醒队列。返回这次的结果摘要。

    盘中别跑太勤：默认 3 分钟内重复调用直接返回上次结果（force=True 才真跑）。
    """
    with _LOCK:
        w = load()
        last = w.get("check_at") or ""
        if not force and last:
            try:
                if _dt.now() - _dt.strptime(last, "%Y-%m-%d %H:%M:%S") < timedelta(minutes=3):
                    return {"ok": True, "skipped": True, "alerts": w.get("alerts")[:10]}
            except Exception:
                pass

        rows, new, err = [], [], []
        for code, it in list(w["items"].items()):
            try:
                hits, a = _judge(code, it)
            except Exception as e:
                err.append(f"{code}: {e}")
                continue
            for kind, extra in hits:
                al = _push(w, kind, code, it, dict(extra))
                if al:
                    new.append(al)
            # 记一下这只票的状态：界面上要显示，判断回撤止盈也要用记录过的高点
            price = float(a.get("price") or 0) or None
            if price:
                it["hi"] = max(float(it.get("hi") or 0), price)
            it["last"] = {"price": round(price, 3) if price else None,
                          "score": round(float(a.get("score") or 0), 1),
                          "chg_pct": a.get("chg_pct"),
                          "checks": a.get("checks"),
                          "plan": a.get("plan")}
            rows.append({"code": code, "name": it.get("name"), "last": it.get("last") or {},
                         "hits": [k for k, _ in hits]})
        w["check_at"] = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        save(w)
        return {"ok": True, "checked_at": w["check_at"], "new": new,
                "alerts": w.get("alerts")[:30], "rows": rows, "errors": err}


def clear_alerts() -> int:
    with _LOCK:
        w = load()
        n = len(w.get("alerts") or [])
        w["alerts"] = []
        save(w)
        return n
