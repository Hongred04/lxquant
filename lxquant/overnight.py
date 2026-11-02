# -*- coding: utf-8 -*-
"""隔夜低吸（首阴套利）—— 与主策略完全独立的第二条线。

和主策略的区别，一句话说清：

    主策略：14:45 决策 → 按收盘价买 → 持有几天，跌破均价线才走。
    这条线：收盘后选「首阴」→ **次日开盘价买** → **当天收盘必须卖**，不隔夜。

为什么值得单独做（2025-08 ~ 2026-10，435 个样本的实测）：
  · 首阴次日平均低开 2.90%，以开盘价买入、当日收盘卖出，均值 +1.70%、盈亏比 1.63；
  · 同样的信号，如果按主策略"当天收盘买"，是 -1.28% —— 差一个晚上，期望翻过来；
  · 四折全正（+1.77 / +2.28 / +1.25 / +1.49），且低开越深反弹越强。

为什么必须独立账本（不能并进 data/memory/）：
  持有期只有 1 天，和主策略的"多日持有"混在一起算总账，两边都会失真。
  主策略记的是"14:45 买入"，这条线记的是"次日开盘买入"，买入时点完全不同。

执行前提（写在界面上，不允许含糊）：
  · 必须 **9:25 集合竞价** 挂单才能拿到开盘价；9:35 之后再买，5 分钟均价已经高
    0.45~0.95%，收益直接少一截；
  · 首 5 分钟最高价中位比开盘价高 3%，追价基本等于放弃这笔交易；
  · 跌停开盘能买到，但若收盘仍是一字跌停则**卖不掉**，会被动持仓过夜 ——
    状态机里按"顺延到下一日"处理，不假装当天已经平仓。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

from . import limitup
from .config import DATA_DIR

# ---------------------------------------------------------------- 参数
# 全部放模块里，不进 config.json：这些是策略定义的一部分，不是"可调旋钮"。
# 改它们等于换一个策略，必须重新回测，所以不给设置页开开关。
MIN_STREAK = 3          # 前面至少 3 个连板才叫"龙头"，1~2 个板的首阴样本质量差
YIN_MAX = 0.99          # 收盘 ≤ 开盘 × 0.99：实体阴线至少 1%，避免十字星误判
HISTORY_KEEP = 15       # 连板历史保留天数（≥ MIN_STREAK 就够，留余量）
# 集合竞价结束后才拿得到开盘价；**开盘价全天不变**，所以收盘前补记也是准的。
# 窗口放宽到 14:55 是为了收集样本：软件 11 点才打开，也能补上当天这条记录。
# 但会如实记下"几点抓的"，10:00 之后抓的标成补记 —— 验证执行率时要能区分。
OPEN_FROM, OPEN_TO = "09:26", "14:55"
ON_TIME_BY = "10:00"
SETTLE_AT = "15:05"     # 收盘价落定后才结算

DIR = DATA_DIR / "overnight"
STATE = DIR / "state.json"
TRADES = DIR / "trades.jsonl"

_REBUILT = [None]       # 本进程内已重建到哪一天（避免同一天反复扫缓存）


# ---------------------------------------------------------------- 状态读写
def _blank():
    return {"limitup": {}, "pending": [], "open": [], "marks": {}}


def _load() -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(s, dict):
            return _blank()
    except Exception:
        return _blank()
    for k, v in _blank().items():
        s.setdefault(k, v)
    return s


def _save(s: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def _append_trade(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(TRADES, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_trades() -> list:
    if not TRADES.exists():
        return []
    out = []
    try:
        for ln in TRADES.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 连板历史
def _probe_cache_date() -> str:
    """日线缓存更新到哪一天（拿一只主力票当探针，便宜且够用）"""
    try:
        import pandas as pd
        from .config import CACHE_DIR
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


def _rebuild_history(keep_from: str) -> dict:
    """从日线缓存重建「每天哪些票涨停、连板几」—— 一天只做一次，约 90 秒。

    为什么不维护增量：增量一旦漏掉一天（软件没开），后面所有连板数都是错的，
    而且错得看不出来。整段重建慢，但每次都是对的。
    """
    import glob
    import pandas as pd
    from . import store
    from .config import CACHE_DIR

    names = {}
    try:
        snap = store.get_list()
        names = dict(zip(snap["code"].astype(str), snap["name"].astype(str)))
    except Exception:
        pass

    hist: dict = {}
    for p in glob.glob(str(CACHE_DIR / "d_*.pkl")):
        code = p.split("d_")[-1].split(".pkl")[0]
        nm = names.get(code, "")
        if not limitup.tradeable(code, nm):
            continue
        try:
            df = pd.read_pickle(p)
        except Exception:
            continue
        if df is None or len(df) < 8:
            continue
        df = df.tail(HISTORY_KEEP + 2).copy()
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        if (df[["close", "open"]] <= 0).any().any():
            continue
        prev = df["close"].shift(1)
        chg = (df["close"] / prev - 1).tolist()
        dates = df["date"].tolist()
        lu = [limitup.is_limit_up(code, c, nm) if c == c else False for c in chg]
        # 除权日会造出假涨停/假跌停：单日幅度超过 21% 的一律当噪音
        lu = [False if (c == c and abs(c) > 0.21) else v for c, v in zip(chg, lu)]
        for d, s in zip(dates, limitup.streaks(lu)):
            if d < keep_from or s <= 0:
                continue
            hist.setdefault(d, {})[code] = s
    return hist


def ensure_history(today: str) -> dict:
    """确保连板历史覆盖到今天为止的最近几天。缺了就重建，不缺就直接用。"""
    st = _load()
    hist = st.get("limitup") or {}
    need = _recent_trade_days(today, MIN_STREAK + 2)
    missing = [d for d in need if d not in hist]

    cache_date = _probe_cache_date()
    stale = bool(cache_date) and cache_date > (st.get("marks", {}).get("history_asof") or "")
    if missing or stale or _REBUILT[0] != today:
        keep_from = need[0] if need else today
        fresh = _rebuild_history(keep_from)
        for d, m in fresh.items():
            hist.setdefault(d, {}).update(m)
        # 只留最近 HISTORY_KEEP 天
        for d in sorted(hist)[:-HISTORY_KEEP]:
            hist.pop(d, None)
        st["limitup"] = hist
        st.setdefault("marks", {})["history_asof"] = cache_date or today
        _save(st)
        _REBUILT[0] = today
    return st.get("limitup") or {}


def _recent_trade_days(today: str, n: int) -> list:
    """今天之前的 n 个交易日（倒推，跳过周末；节假日误差一天不影响使用）"""
    out, d = [], datetime.strptime(today, "%Y-%m-%d")
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
    return list(reversed(out))


# ---------------------------------------------------------------- 三步状态机
def do_open(today: str, snap=None) -> int:
    """次日开盘：把昨日 pending 变成持仓（买入价 = 集合竞价开盘价）。

    返回本次记录/跳过的笔数。当日只做一次（marks.open 挡住）。
    """
    st = _load()
    if not st["pending"] or st["marks"].get("open") == today:
        return 0
    if snap is None:
        from . import store
        snap = store.get_list()
    idx = {str(r["code"]): r for _, r in snap.iterrows()}

    got = 0
    for it in st["pending"]:
        r = idx.get(str(it["code"]))
        if r is None:
            continue
        o = float(r.get("open") or 0)
        if o <= 0:
            continue
        ltype = limitup.limit_pct(it["code"], it.get("name", ""))
        prev = float(r.get("prev_close") or 0) or it.get("signal_close") or o
        # 一字跌停开：能买，但当天大概率卖不掉 → 仍然记录，交给结算时判顺延
        one_word = (abs(float(r.get("high") or 0) - float(r.get("low") or 0)) < 1e-6
                    and o <= prev * (1 - ltype + limitup.TOL))
        # 信号日的证据必须整份带进来：板块、同板块涨停数、炸板次数、封板时间。
        # 只留买卖价的话，事后没法回答"弱板是不是更差""板块有承接是不是更好" ——
        # 而这两个问题正是这套策略接下来要验证的东西。
        st["open"].append({
            "code": str(it["code"]), "name": it.get("name", ""),
            "signal_date": it["signal_date"], "buy_date": today,
            "streak": it.get("streak"), "signal_close": it.get("signal_close"),
            "open": round(o, 3), "deferred": 0,
            "board": it.get("board") or "", "n_board": it.get("n_board"),
            "zbc": it.get("zbc"), "fbt": it.get("fbt") or "",
            "lbc_em": it.get("lbc_em"),
            # 抓取时刻：10:00 前算准时。补记的记录价格仍然准确（开盘价不变），
            # 但它证明不了"你那天真的在盘中做了决定"，统计执行率时要分开算。
            "captured_at": time.strftime("%H:%M"),
            "on_time": time.strftime("%H:%M") <= ON_TIME_BY,
            "flag": "一字跌停开盘" if one_word else "",
        })
        got += 1
    st["pending"] = []
    st["marks"]["open"] = today
    _save(st)
    return got


def do_settle(day: str, snap=None) -> int:
    """按 day 那天的收盘价平掉持仓。收盘仍一字跌停的顺延到下一日。

    `day` 不一定是"今天"：周末打开软件时是上周五，开盘前是上一个交易日。
    """
    st = _load()
    if not st["open"]:
        st["marks"]["settle"] = day
        _save(st)
        return 0
    if snap is None:
        from . import store
        snap = store.get_list()
    idx = {str(r["code"]): r for _, r in snap.iterrows()}

    keep, closed = [], 0
    for it in st["open"]:
        r = idx.get(it["code"])
        if r is None:
            keep.append(it)
            continue
        px = float(r.get("price") or 0)
        if px <= 0:
            keep.append(it)
            continue
        ltype = limitup.limit_pct(it["code"], it.get("name", ""))
        prev = float(r.get("prev_close") or 0)
        stuck = (prev > 0 and px <= prev * (1 - ltype + limitup.TOL)
                 and abs(float(r.get("high") or 0) - float(r.get("low") or 0)) < 1e-6)
        if stuck:
            it["deferred"] = int(it.get("deferred") or 0) + 1
            if it["deferred"] <= 3:
                keep.append(it)          # 卖不掉，顺延（最多扛 3 天）
                continue
            # 扛满 3 天也没跑掉：按收盘价强制结账，并如实标注
            it["flag"] = (it.get("flag") or "") + " 连续跌停未卖出"
        ret = (px / it["open"] - 1) * 100 if it["open"] else 0.0
        sc = it.get("signal_close") or 0
        _append_trade({
            "signal_date": it["signal_date"], "buy_date": it["buy_date"],
            "sell_date": day, "code": it["code"], "name": it.get("name", ""),
            "streak": it.get("streak"),
            # 买入价 = 次日开盘价；信号日收盘也留着 —— 两者相除就是"低开幅度"，
            # 而低开幅度是这套策略最核心的自变量（实测：低开越深，反弹越强）。
            "signal_close": sc, "open": it["open"], "close": round(px, 3),
            "gap": round((it["open"] / sc - 1) * 100, 2) if sc else None,
            "hold_days": _days_between(it["buy_date"], day),
            "ret": round(ret, 2), "status": "done",
            "board": it.get("board") or "", "n_board": it.get("n_board"),
            "zbc": it.get("zbc"), "fbt": it.get("fbt") or "",
            "captured_at": it.get("captured_at") or "", "on_time": it.get("on_time"),
            "deferred": it.get("deferred") or 0, "flag": it.get("flag") or "",
        })
        closed += 1
    st["open"] = keep
    st["marks"]["settle"] = day
    _save(st)
    return closed


def do_scan(day: str, snap=None) -> list:
    """扫 day 那天的收盘数据：更新涨停/连板，找出当天的「首阴」，作为**次日**待买。

    `day` 是信号日，不一定是"今天"（周末补跑时是上周五）。
    """
    st = _load()
    if snap is None:
        from . import store
        snap = store.get_list()

    hist = ensure_history(day)
    prev_days = [d for d in hist if d < day]
    prev_day = max(prev_days) if prev_days else ""

    today_lu = {}
    fresh = []
    for _, r in snap.iterrows():
        code = str(r["code"]); nm = str(r.get("name") or "")
        if not limitup.tradeable(code, nm):
            continue
        pc = float(r.get("prev_close") or 0)
        px = float(r.get("price") or 0)
        op = float(r.get("open") or 0)
        if pc <= 0 or px <= 0 or op <= 0:
            continue
        chg = px / pc - 1
        if abs(chg) > 0.21:                    # 除权/异常，不参与
            continue
        if limitup.is_limit_up(code, chg, nm):
            prev_s = int(hist.get(prev_day, {}).get(code, 0)) if prev_day else 0
            today_lu[code] = prev_s + 1
            continue
        # ---- 首阴：昨天连板 ≥3，今天第一根实体阴线
        if not prev_day:
            continue
        s = int(hist.get(prev_day, {}).get(code, 0))
        if s < MIN_STREAK:
            continue
        if px > op * YIN_MAX:
            continue
        fresh.append({
            "code": code, "name": nm, "signal_date": day,
            "streak": s, "signal_close": round(px, 2),
            "open": round(op, 2), "chg": round(chg * 100, 2),
        })

    # 补齐日线反推不出来的东西：板块归属、同板块今日涨停数、炸板次数。
    # 取不到就跳过 —— 名单本身不依赖它，只是少了"这是不是题材核心"的判断依据。
    emo = {}
    try:
        from . import emotion as _emo
        if fresh:
            _emo.enrich(fresh, day, prev_day)
        emo = _emo.stats(_emo.zt_pool(day))
    except Exception:
        pass

    hist[day] = today_lu
    for d in sorted(hist)[:-HISTORY_KEEP]:
        hist.pop(d, None)
    st["limitup"] = hist
    if emo:
        st.setdefault("emotion", {})[day] = emo
        for d in sorted(st["emotion"])[:-10]:
            st["emotion"].pop(d, None)

    # 昨天给的单子如果今天没执行（软件没开 / 没下单），如实记一笔"错过"。
    # 注意：同一天重复生成名单（手动补跑、或调度重入）不能算错过 ——
    # signal_date 等于本次 ref 的，说明是同一批，直接替换即可。
    for it in st["pending"]:
        if str(it.get("signal_date") or "") >= day:
            continue
        _append_trade({
            "signal_date": it["signal_date"], "buy_date": "", "sell_date": "",
            "code": it["code"], "name": it.get("name", ""),
            "streak": it.get("streak"), "signal_close": it.get("signal_close"),
            "open": None, "close": None, "gap": None, "hold_days": None,
            "ret": None, "status": "missed", "deferred": 0,
            "board": it.get("board") or "", "n_board": it.get("n_board"),
            "zbc": it.get("zbc"), "fbt": it.get("fbt") or "",
            "flag": "开盘时没记录成交（软件未运行或没下单）",
        })
    st["pending"] = sorted(fresh, key=lambda x: -int(x.get("streak") or 0))
    st["marks"]["scan"] = day
    _save(st)
    return st["pending"]


def _is_td(date_str: str) -> bool:
    """是不是交易日。日历拿不到时退化成"工作日"判断，不能因为网络问题就罢工。"""
    try:
        from .extdata import is_trade_day
        r = is_trade_day(date_str)
        if r is not None:
            return bool(r)
    except Exception:
        pass
    return datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5


def next_trade_day(date_str: str) -> str:
    """date_str 之后的第一个交易日。没有它，界面上"明天买"遇到周五就变成周六了。"""
    if not date_str:
        return ""
    try:
        from .extdata import trade_days
        ds = trade_days()
        if ds:
            later = sorted(d for d in ds if d > date_str)
            if later:
                return later[0]
    except Exception:
        pass
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    for _ in range(12):
        d += timedelta(days=1)
        if d.weekday() < 5:
            return d.isoformat()
    return ""


def ref_day(now: datetime | None = None) -> str:
    """最近一个**已经收盘**的交易日。

    为什么不能直接用 now 的日期：周日打开软件时"今天"不是交易日，
    用周日当信号日会把名单挂到错误的日期上；正确做法是拿上周五的收盘数据
    生成周一要用的名单。开盘前（09:30 前）同理，仍算前一天。
    """
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    if _is_td(today) and now.strftime("%H:%M") >= SETTLE_AT:
        return today
    d = now.date()
    for _ in range(12):
        d -= timedelta(days=1)
        s = d.strftime("%Y-%m-%d")
        if _is_td(s):
            return s
    return ""


def tick(now: datetime | None = None) -> str:
    """调度入口：按时间决定该做哪一步。幂等，重复调用无副作用。

    顺序是「先开盘买入，再结算+出名单」：
      · 开盘这一步必须用**真实今天**（周一 9:26 买的是周一的价）；
      · 结算和出名单用 ref_day（最近一个已收盘的交易日）——
        软件周六日打开也能补上周五那份名单，不会因为没开就断档。
    """
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = now.strftime("%H:%M")
    ref = ref_day(now)
    if not ref:
        return ""

    st = _load()
    acted = ""
    if _is_td(today) and OPEN_FROM <= hm < OPEN_TO and st["pending"] and st["marks"].get("open") != today:
        n = do_open(today)
        acted = f"open:{n}"

    st = _load()
    if st["marks"].get("settle") != ref:
        c = do_settle(ref)
        p = do_scan(ref)
        acted = (acted + " " if acted else "") + f"settle:{c} scan:{len(p)}"
    return acted


def _days_between(a: str, b: str) -> int | None:
    """两个交易日之间相差几天（自然日）。用不上日历，只用来记录"扛了多久"。"""
    try:
        d1 = datetime.strptime(str(a)[:10], "%Y-%m-%d")
        d2 = datetime.strptime(str(b)[:10], "%Y-%m-%d")
        return max((d2 - d1).days, 0)
    except Exception:
        return None


CSV_FIELDS = [
    ("signal_date", "信号日"), ("buy_date", "买入日"), ("sell_date", "卖出日"),
    ("code", "代码"), ("name", "名称"), ("streak", "连板"),
    ("board", "板块"), ("n_board", "同板块当日涨停数"), ("zbc", "炸板次数"),
    ("fbt", "首封时间"), ("signal_close", "信号日收盘"), ("open", "买入价(开盘)"),
    ("gap", "低开幅度%"), ("close", "卖出价"), ("ret", "收益%"),
    ("hold_days", "持天数"), ("captured_at", "记录时刻"), ("on_time", "是否准时"),
    ("status", "状态"), ("deferred", "顺延天数"), ("flag", "备注"),
]


def export_csv() -> str:
    """把账本导成 CSV（带 BOM，Excel 直接打开不乱码）。

    为什么要有这个：验证"弱板是不是更差""低开越深反弹越强"这类假设，
    在界面里点来点去没用，得拿一堆记录去分组算。CSV 是门槛最低的形式 ——
    Excel、pandas、甚至手机上的表格都能开。
    """
    ts = _read_trades()
    lines = [",".join(h for _, h in CSV_FIELDS)]
    for t in ts:
        row = []
        for k, _ in CSV_FIELDS:
            v = t.get(k)
            if v is None:
                row.append("")
            elif isinstance(v, str) and ("," in v or '"' in v):
                row.append('"' + v.replace('"', '""') + '"')
            else:
                row.append(str(v))
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 视图 / 统计
def stats() -> dict:
    ts = _read_trades()
    done = [t for t in ts if t.get("status") == "done"]
    missed = [t for t in ts if t.get("status") == "missed"]
    out = {"n": len(done), "missed": len(missed), "win_rate": None,
           "avg": None, "med": None, "payoff": None, "total": len(ts)}
    if done:
        r = sorted(float(t.get("ret") or 0) for t in done)
        win = [x for x in r if x > 0]
        loss = [x for x in r if x < 0]
        out.update({
            "win_rate": round(len(win) / len(r) * 100, 1),
            "avg": round(sum(r) / len(r), 2),
            "med": round(r[len(r) // 2], 2),
            "payoff": (round(sum(win) / len(win) / abs(sum(loss) / len(loss)), 2)
                       if win and loss and sum(loss) else None),
            "best": round(r[-1], 2), "worst": round(r[0], 2),
        })
    # 按月汇总，看是不是只靠某一段
    by = {}
    for t in done:
        m = str(t.get("buy_date") or "")[:7]
        if m:
            by.setdefault(m, []).append(float(t.get("ret") or 0))
    out["by_month"] = [{"month": m, "n": len(v),
                        "avg": round(sum(v) / len(v), 2)}
                       for m, v in sorted(by.items())]
    out["exec_rate"] = (round(len(done) / (len(done) + len(missed)) * 100, 1)
                        if (done or missed) else None)
    return out


def _pending_ctx(st: dict, now: datetime | None = None) -> dict:
    """这批待买「该在哪天买、现在算不算过期」。**界面文案只认这里，别再各自写"明日"**。

    写死"明日待买"会错两次：
      · 周一盘中打开，名单其实是**今天**要买的，而且 9:25 可能已经过了；
      · 周五收盘生成的名单，下周一才买，中间隔着周末 —— 在日历上"明天"是周六。
    所以统一算成 offset：0=今天 / 1=之后 / -1=已过期，前端只按这个选文案。
    """
    now = now or datetime.now()          # 可注入：测试要能固定"今天"，否则断言只能写成"0 或 1"
    today = now.strftime("%Y-%m-%d")
    ref = ref_day(now)
    marks = st.get("marks") or {}
    pend = st.get("pending") or []

    if pend:
        sig = str(pend[0].get("signal_date") or "")
        buy = next_trade_day(sig)
        off = 0 if buy == today else (1 if buy > today else -1)
        return {"phase": "waiting", "buy_date": buy, "offset": off,
                "signal_date": sig, "scan": marks.get("scan") or ""}

    # 没有待买：要分清"已经买进去了""扫过了确实没票""根本没扫过"——三种文案完全不同
    if any(str(o.get("buy_date") or "") == today for o in (st.get("open") or [])):
        return {"phase": "bought", "buy_date": today, "offset": 0,
                "signal_date": "", "scan": marks.get("scan") or ""}
    scan = str(marks.get("scan") or "")
    return {"phase": "fresh" if scan and scan >= ref else "no_scan",
            "buy_date": "", "offset": None, "signal_date": "",
            "scan": scan, "ref": ref, "today": today}


def view() -> dict:
    """给界面用的一份快照"""
    st = _load()
    emo = st.get("emotion") or {}
    last_emo = {"date": max(emo), **emo[max(emo)]} if emo else None
    return {
        "pending": st["pending"], "open": st["open"],
        "emotion": last_emo, "pending_ctx": _pending_ctx(st),
        "marks": st["marks"], "stats": stats(),
        "recent": _read_trades()[-40:][::-1],
        "params": {"min_streak": MIN_STREAK, "yin_max": YIN_MAX,
                   "open_from": OPEN_FROM, "settle_at": SETTLE_AT},
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
