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

from . import limitup, ovnbt
from .config import DATA_DIR

# ---------------------------------------------------------------- 参数
# 全部放模块里，不进 config.json：这些是策略定义的一部分，不是"可调旋钮"。
# 改它们等于换一个策略，必须重新回测，所以不给设置页开开关。
MIN_STREAK = 3          # 前面至少 3 个连板才叫"龙头"，1~2 个板的首阴样本质量差
YIN_MAX = 0.99          # 收盘 ≤ 开盘 × 0.99：实体阴线至少 1%，避免十字星误判
HISTORY_KEEP = 15       # 连板历史保留天数（≥ MIN_STREAK 就够，留余量）
# ---- 执行方式：和「选股」页同一套节奏 ----
#   D 日 14:40   扫出今天的首阴，**当场按当时价买入**（不用等到明天 9:25）
#   D+1 日 14:50 按当时的价卖出（T+1 满足）
# 这是用户指定的操作方式：一天只在尾盘动一次，不需要早上盯集合竞价。
BUY_AT = "14:40"        # 选股 + 买入
SELL_AT = "14:50"       # 次日卖出（尾盘）
LATE_AFTER = "15:00"    # 这之后才跑 = 补记（用收盘价，标记 late）
TODAY_CLOSE = "15:00"

# A 股 T+1：买入当天不许卖出。这是交易所规则，不是可配置项。
# 早期版本按"次日开盘买、当天收盘卖"实现，那是 T+0，实盘不存在 ——
# 实测 354 个首阴样本：T+0 口径 +1.66%，T+1 口径（次日开盘买、第三日卖）
# 只有 -0.04%（中位 -1.65%、盈亏比 0.99）。也就是说那 +1.66% 完全来自
# "当天买当天卖"这一段，而这一段拿不到。这条线目前没有实盘价值，
# 留在这里是为了样本积累与规则重设计，界面上有明确标注。
MIN_HOLD_DAYS = 1

DIR = DATA_DIR / "overnight"
STATE = DIR / "state.json"
TRADES = DIR / "trades.jsonl"

_REBUILT = [None]       # 本进程内已重建到哪一天（避免同一天反复扫缓存）


# ---------------------------------------------------------------- 状态读写
def _blank():
    return {"limitup": {}, "pending": [], "signals": [], "marks": {}}


def _load() -> dict:
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(s, dict):
            return _blank()
    except Exception:
        return _blank()
    # 老版本把这个键叫 open（当时当成"持仓"，默认买了）。语义改成"信号"后更名，
    # 顺手把老记录的 exec 补成 None —— 当时的"持仓"其实没人确认过是否真的买了。
    if "open" in s:
        legacy = s.pop("open") or []
        for it in legacy:
            it.setdefault("exec", None)
        s.setdefault("signals", [])
        s["signals"] = list(legacy) + list(s.get("signals") or [])
    for k, v in _blank().items():
        s.setdefault(k, v)
    # 自愈：老记录可能没算 gap（早期版本的 do_open 不算）。
    # 只要开盘价和信号日收盘都在，就补出来 —— 手工修数据迟早会漏。
    for it in s.get("signals") or []:
        if it.get("gap") is None and it.get("open") and it.get("signal_close"):
            it["gap"] = round((it["open"] / it["signal_close"] - 1) * 100, 2)
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
def do_settle(day: str, snap=None) -> int:
    """按 day 那天的收盘价平掉持仓。收盘仍一字跌停的顺延到下一日。

    `day` 不一定是"今天"：周末打开软件时是上周五，开盘前是上一个交易日。
    """
    st = _load()
    if not st["signals"]:
        st["marks"]["settle"] = day
        _save(st)
        return 0
    if snap is None:
        from . import store
        snap = store.get_list()
    idx = {str(r["code"]): r for _, r in snap.iterrows()}

    keep, closed = [], 0
    for it in st["signals"]:
        # ★ T+1：买入当天不能卖，最早下一个交易日。少了这一句，整个账本就是
        #   T+0 口径，收益全是假的（实测高估 1.7 个百分点/笔）。
        held = _days_between(it.get("buy_date"), day)
        if held is None or held < MIN_HOLD_DAYS:
            keep.append(it)
            continue
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
        bp = float(it.get("buy_price") or it.get("open") or 0)
        ret = (px / bp - 1) * 100 if bp else 0.0
        sc = it.get("signal_close") or 0
        ex = it.get("exec")            # None=未确认 / True=买了 / False=没买
        _append_trade({
            "signal_date": it["signal_date"], "buy_date": it["buy_date"],
            "sell_date": day, "code": it["code"], "name": it.get("name", ""),
            "streak": it.get("streak"),
            # 买入价 = 次日开盘价；信号日收盘也留着 —— 两者相除就是"低开幅度"，
            # 而低开幅度是这套策略最核心的自变量（实测：低开越深，反弹越强）。
            "signal_close": sc, "open": it["open"], "close": round(px, 3),
            "buy_price": bp,
            "gap": round((bp / sc - 1) * 100, 2) if sc else None,
            "hold_days": _days_between(it["buy_date"], day),
            # ret 是**影子收益**：按规则"开盘买、收盘卖"会拿到多少，与是否真下手无关。
            # 这样没买的信号也进得了统计 —— 否则样本全被"我那天没空"削掉。
            "ret": round(ret, 2), "status": "settled", "exec": ex,
            "exec_at": it.get("exec_at") or "",
            "board": it.get("board") or "", "n_board": it.get("n_board"),
            "zbc": it.get("zbc"), "fbt": it.get("fbt") or "",
            "captured_at": it.get("captured_at") or "", "on_time": it.get("on_time"),
            "deferred": it.get("deferred") or 0, "flag": it.get("flag") or "",
        })
        closed += 1
    st["signals"] = keep
    st["marks"]["settle"] = day
    _save(st)
    return closed


def do_scan(day: str, snap=None) -> list:
    """扫 day 的收盘/当前快照，找出首阴，**当场按快照价记为买入**。

    和旧版的根本区别：不再生成"明日待买"。用户的实际操作是
    「14:40 看着盘选出票、当场买、第二天尾盘卖」，
    所以选股和买入必须在同一天完成，买入价用**当时的价格**，
    不是次日开盘价、也不是收盘价。

    `day` 是信号日 = 买入日；周末补跑时传最近一个交易日。
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
        px = float(r.get("price") or 0)          # 当前价（14:40 就是 14:40 的价）
        op = float(r.get("open") or 0)
        if pc <= 0 or px <= 0 or op <= 0:
            continue
        chg = px / pc - 1
        if abs(chg) > 0.21:                       # 除权/异常，不参与
            continue
        if limitup.is_limit_up(code, chg, nm):
            prev_s = int(hist.get(prev_day, {}).get(code, 0)) if prev_day else 0
            today_lu[code] = prev_s + 1
            continue
        # ---- 首阴：昨天连板 ≥3，今天第一根实体阴线（用当前价判，不等收盘）
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
            "buy_price": round(px, 3),
        })

    # 补齐日线反推不出来的东西：板块归属、同板块今日涨停数、炸板次数
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

    # ---- 当场买入（同一天同一只不重复记；重复跑只更新价格）
    hm = datetime.now().strftime("%H:%M")
    late = hm >= LATE_AFTER
    have = {(str(x.get("code")), str(x.get("buy_date"))) for x in st["signals"]}
    n_new = 0
    for it in fresh:
        key = (str(it["code"]), day)
        if key in have:
            for x in st["signals"]:
                if (str(x.get("code")), str(x.get("buy_date"))) == key:
                    x["buy_price"] = it["buy_price"]
                    x["signal_close"] = it["signal_close"]
                    x["captured_at"] = hm
                    x["late"] = late
            continue
        st["signals"].append({
            "code": it["code"], "name": it["name"],
            "signal_date": day, "buy_date": day,        # 选股与买入同一天
            "streak": it["streak"], "signal_close": it["signal_close"],
            "open": it["open"],                          # 当日开盘（算振幅用）
            "buy_price": it["buy_price"],                # ★ 14:40 的实际买入价
            "gap": None, "deferred": 0,
            "board": it.get("board") or "", "n_board": it.get("n_board"),
            "zbc": it.get("zbc"), "fbt": it.get("fbt") or "",
            "lbc_em": it.get("lbc_em"),
            "captured_at": hm, "late": late,
            "exec": None, "exec_at": "",
            "flag": "",
        })
        n_new += 1

    st["pending"] = []          # 旧概念，保留字段但不再使用
    st["marks"]["scan"] = day
    _save(st)
    return st["signals"]


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
    if _is_td(today) and now.strftime("%H:%M") >= SELL_AT:
        return today
    d = now.date()
    for _ in range(12):
        d -= timedelta(days=1)
        s = d.strftime("%Y-%m-%d")
        if _is_td(s):
            return s
    return ""


def tick(now: datetime | None = None) -> str:
    """调度入口。一天只在尾盘动两次：

        D   14:40 之后   扫今天的首阴 → 当场按当时价买入
        D+1 14:50 之后   卖掉所有 buy_date < 今天的持仓

    幂等：marks 记着今天做过哪几步，重复调用不重复记账。
    15:00 之后才跑 = 补记（用收盘价），记 late=True，方便事后区分。
    """
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = now.strftime("%H:%M")
    if not _is_td(today):
        return ""

    st = _load()
    acted = []

    # ---- 先卖（T+1：只卖 buy_date 严格早于今天的）
    if hm >= SELL_AT and st["marks"].get("settle") != today:
        n = do_settle(today)
        acted.append(f"sell:{n}")

    # ---- 再买（扫今天的首阴并当场记）
    if hm >= BUY_AT and st["marks"].get("scan") != today:
        sig = do_scan(today)
        today_new = [x for x in sig if str(x.get("buy_date")) == today]
        acted.append(f"buy:{len(today_new)}")

    return " ".join(acted)


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
    ("fbt", "首封时间"), ("signal_close", "信号日尾盘价"),
    ("buy_price", "买入价(14:40)"), ("open", "当日开盘"),
    ("gap", "低开幅度%"), ("close", "卖出价"), ("ret", "影子收益%"),
    ("hold_days", "持天数"), ("exec", "我买了吗"), ("exec_at", "标记时刻"),
    ("captured_at", "记录时刻"), ("on_time", "是否准时"),
    ("status", "状态"), ("deferred", "顺延天数"), ("flag", "备注"),
]

# 导出时把内部值换成中文：这文件是给人用 Excel 看的，
# True/False/None 到了表格里既难读也难筛选。
_VALUE_CN = {
    "exec": {True: "买了", False: "没买", None: "未标"},
    "status": {"settled": "已结算", "gap": "开盘价没抓到"},
    "on_time": {True: "准时", False: "补记", None: ""},
}


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
            if k in _VALUE_CN:
                v = _VALUE_CN[k].get(v, v)
            if v is None or v == "":
                row.append("")
            elif isinstance(v, str) and ("," in v or '"' in v):
                row.append('"' + v.replace('"', '""') + '"')
            else:
                row.append(str(v))
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 视图 / 统计
def _agg(rows: list) -> dict:
    """一组已结算信号的统计。空组返回 None 字段，界面显示「—」。"""
    r = sorted(float(t.get("ret") or 0) for t in rows)
    if not r:
        return {"n": 0, "avg": None, "med": None, "win_rate": None,
                "payoff": None, "best": None, "worst": None}
    win = [x for x in r if x > 0]
    loss = [x for x in r if x < 0]
    return {
        "n": len(r),
        "avg": round(sum(r) / len(r), 2),
        "med": round(r[len(r) // 2], 2),
        "win_rate": round(len(win) / len(r) * 100, 1),
        "payoff": (round(sum(win) / len(win) / abs(sum(loss) / len(loss)), 2)
                   if win and loss and sum(loss) else None),
        "best": round(r[-1], 2), "worst": round(r[0], 2),
    }


def stats() -> dict:
    """两套口径，**别混着讲**：

    - `signal`：全部信号（含没买的、还没标买没买的）。影子收益，衡量**规则本身**。
      没买也留下 —— 否则样本会被"那几天没空"悄悄削掉，看起来比实际好。
    - `real`：只有你标记了"买了"的。衡量**你实际执行的结果**。
    - `skipped` / `unconfirmed`：没买 / 还没标的笔数，用来算执行率。
    - `gaps`：开盘价没抓到（软件整天没开）的笔数 —— 样本缺口，不是执行记录。
    """
    ts = _read_trades()
    settled = [t for t in ts if t.get("status") == "settled"]
    gaps = [t for t in ts if t.get("status") == "gap"]
    real = [t for t in settled if t.get("exec") is True]
    skipped = [t for t in settled if t.get("exec") is False]
    unsure = [t for t in settled if t.get("exec") is None]

    out = _agg(settled)
    out.update({
        "signal": _agg(settled),
        "real": _agg(real),
        "skipped": len(skipped),
        "unconfirmed": len(unsure),
        "gaps": len(gaps),
        "total": len(ts),
        # 执行率只看"已经表过态的"（买了 + 没买），未确认的不进分母 ——
        # 否则刚生成那一天就会被算成 0%，毫无意义。
        "exec_rate": (round(len(real) / (len(real) + len(skipped)) * 100, 1)
                      if (real or skipped) else None),
    })

    by = {}
    for t in settled:
        m = str(t.get("buy_date") or "")[:7]
        if m:
            by.setdefault(m, []).append(float(t.get("ret") or 0))
    out["by_month"] = [{"month": m, "n": len(v),
                        "avg": round(sum(v) / len(v), 2)}
                       for m, v in sorted(by.items())]
    return out


def mark_exec(code: str, buy_date: str, exec_: bool | None) -> int:
    """标记某个信号「我买了 / 我没买 / 还没说」。返回改动的条数。

    为什么让用户点：软件不可能知道你下没下单，期货商接口、券商柜台的成交回报都拿不到。
    猜（"软件开着你肯定买了"）会把账本搞脏，而账本干净是这套东西唯一的价值。

    `buy_date` 为空时，改的是"当前所有还没结算的信号"——省得一天一只只点。
    """
    n = 0
    now_hm = time.strftime("%H:%M")

    st = _load()
    for it in st.get("signals") or []:
        if code and str(it.get("code")) != str(code):
            continue
        if buy_date and str(it.get("buy_date")) != str(buy_date):
            continue
        it["exec"] = exec_
        it["exec_at"] = now_hm
        n += 1
    if n:
        _save(st)

    # 已经结算落库的也要能改（第二天才想起来标「那天其实没买」）
    if n == 0:
        ts = _read_trades()
        hit = False
        for t in ts:
            if t.get("status") not in ("settled", "gap"):
                continue
            if code and str(t.get("code")) != str(code):
                continue
            if buy_date and str(t.get("buy_date")) != str(buy_date):
                continue
            t["exec"] = exec_
            t["exec_at"] = now_hm
            hit = True
            n += 1
        if hit:
            with open(TRADES, "w", encoding="utf-8") as f:
                for t in ts:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return n


def _pending_ctx(st: dict, now: datetime | None = None) -> dict:
    """给界面判断「今天是什么状态」。**文案只认这里，别在别处写死"待买/明日"**。

    执行方式改成"尾盘选股即买入"之后，状态只剩三种：
      bought   今天已经买入了 N 只（14:40 那一步做过了）
      holding  今天没新信号，但手里还有昨天买的没卖
      empty    扫过了，今天一只都没选出来
      no_scan  今天还没扫过

    `buy_date == signal_date`（同一天选、同一天买），所以"能不能卖"看
    `next_trade_day(buy_date)` 是否 <= 今天 —— 那是 T+1 的最早可卖日。
    """
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    marks = st.get("marks") or {}
    sigs = st.get("signals") or []

    mine = [x for x in sigs if str(x.get("buy_date") or "") == today]
    scan = str(marks.get("scan") or "")
    if mine:
        return {"phase": "bought", "date": today, "n": len(mine),
                "scan": scan, "today": today}
    holding = [x for x in sigs if str(x.get("buy_date") or "") < today]
    if holding:
        return {"phase": "holding", "date": today, "n": len(holding),
                "scan": scan, "today": today}
    return {"phase": "empty" if scan == today else "no_scan",
            "date": today, "n": 0, "scan": scan, "today": today}


def view() -> dict:
    """给界面用的一份快照"""
    st = _load()
    emo = st.get("emotion") or {}
    last_emo = {"date": max(emo), **emo[max(emo)]} if emo else None
    # 每笔持仓补一个「最早哪天能卖」：T+1 下就是买入日的下一个交易日。
    # 前端不该自己加一天（会撞周末），更不该让人以为能当天卖。
    sigs = []
    for it in st["signals"]:
        x = dict(it)
        x["sell_from"] = next_trade_day(it.get("buy_date") or "")
        sigs.append(x)
    return {
        "pending": st["pending"], "signals": sigs,
        "emotion": last_emo, "pending_ctx": _pending_ctx(st),
        "marks": st["marks"], "stats": stats(),
        "recent": _read_trades()[-40:][::-1],
        # 规则本身的历史收益率曲线（全市场回测），和账本完全是两件事：
        # 这条线算的是"按这套规则做，历史上赚不赚钱"，含没买的信号。
        # 可能第一次打开时还没算完（要 30 秒），那时 ready=false，
        # 界面显示"正在算"，后台线程算完写进 data/overnight/curve.json。
        "curve": ovnbt.view(),
        "params": {"min_streak": MIN_STREAK, "yin_max": YIN_MAX,
                   "buy_at": BUY_AT, "sell_at": SELL_AT,
                   "min_hold_days": MIN_HOLD_DAYS},
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
