# -*- coding: utf-8 -*-
"""
选股引擎：并发抓取 → 计算 → 过滤 → 评分排序。
"""
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from . import analyzer, datasource as ds, extdata as ext, indicators as ind, store
from . import strategies as strats


# ---------------------------------------------------------------- 基础过滤
def prefilter(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    d = df.copy()
    if params.get("exclude_st", True):
        d = d[~d["name"].str.contains(r"ST|退", case=False, na=False)]
    if params.get("exclude_bj", True):
        d = d[~d["code"].str.startswith(("8", "4", "9"))]
    if params.get("exclude_kcb"):
        d = d[~d["code"].str.startswith("688")]
    if params.get("exclude_cyb"):
        d = d[~d["code"].str.startswith(("300", "301"))]
    d = d[d["price"].between(float(params.get("min_price", 0)),
                             float(params.get("max_price", 1e9)))]
    if params.get("min_turnover_amt", 0):
        d = d[d["amount"] >= float(params["min_turnover_amt"])]
    d = d[d["price"] > 0]
    # 上市不足 N 个交易日的新股：快照里没有上市日期，靠下面的日线长度兜底
    # （analyzer 发现日线不足 30 根会抛异常，计入 stats.failed）
    return d.reset_index(drop=True)


def balance_pool(df: pd.DataFrame, limit: int, mode: str = "all") -> pd.DataFrame:
    """
    抽样控制：mode=all 全部；mode=balanced 按成交额分位网格抽样。

    ★ 原来这里是 np.linspace 等距抽样，结果是「样本量」滑块换的不是样本量，
      而是换了一整批股票：limit=20 与 limit=40 的池子只重合 4/17。
      同一套参数 limit=60 回测 +1.58%、limit=200 只有 +0.12%，纯粹是抽样运气。

    改成"固定置换 + 取前 N 个"后有三个性质：
      1) 可复现：同一个 limit 永远给同一批股票；
      2) 严格包含：limit=20 的股票一定全部出现在 limit=40 里（取的是同一个
         置换的前缀），改样本量才是真的"加样本"，不是换一批票；
      3) 分层：置换用 Van der Corput 序列生成，按成交额排序后的名次被打散，
         取前 N 个天然覆盖大中小盘，不会只剩大票或只剩小票。
    """
    if len(df) <= limit:
        return df.reset_index(drop=True)
    if mode == "all":
        return df.reset_index(drop=True)
    d = df.sort_values("amount", ascending=False, na_position="last")
    d = d.reset_index(drop=True)
    n = len(d)
    if limit <= 1:
        return d.iloc[:max(limit, 1)].reset_index(drop=True)

    # Van der Corput（基 2）：把 0..n-1 均匀打散。这个序列只跟 n 有关，
    # 跟 limit 无关，所以不同 limit 拿到的都是同一个置换的前缀 → 天然嵌套。
    def vdc(k: int) -> float:
        v, denom = 0.0, 1.0
        while k:
            k, r = divmod(k, 2)
            denom *= 2
            v += r / denom
        return v

    order = sorted(range(n), key=lambda k: (vdc(k + 1), k))
    idx = sorted(order[:limit])
    return d.iloc[idx].sort_values("amount", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- 单只处理
def _intraday_arg(params: dict):
    """算出这次扫描该用哪个分钟周期，返回 (scale, datalen)。

    不需要取分钟线时返回 None（need_k5=False 的场景）。
    30 分钟线 200 根 = 25 个交易日、28KB，与 5 分钟线 1023 根算出的均价线逐列相同，
    但解析量和网络体积都只有 1/5。
    """
    try:
        sc = store.pick_scale(str(params.get("tail_from", "14:30")),
                              params.get("preview_at"))
    except Exception:
        sc = 30
    sc = int(sc)
    dl = 1023 if sc == 5 else max(200, 30 * 8 * 26 // sc)
    return sc, dl


def _one(code, name, params, weights, rt_map, need_k5=True, deep=True, errs=None, scale=None):
    try:
        d = store.get_daily(code)
        if d is None or len(d) < 60:
            return None
        k5 = None
        if need_k5:
            sc = scale or _intraday_arg(params)
            try:
                k5 = store.get_intraday(code, sc[0], sc[1])
            except Exception as e:  # noqa: BLE001
                if errs is not None:
                    errs.setdefault("k5", set()).add(type(e).__name__ + ":" + str(e)[:40])
                k5 = None
        a = analyzer.analyze(code, name, params, daily=d, k5=k5, rt=rt_map.get(code))
        a["score"] = analyzer.score(a, weights, params)
        _clean(a)
        return a
    except Exception as e:  # noqa: BLE001
        if errs is not None:
            errs.setdefault("all", set()).add(type(e).__name__ + ":" + str(e)[:40])
        return None


def _clean(a: dict) -> None:
    """剥离体积大的原始字段，保留前端需要的图数据（图表数据可重建）。"""
    a.pop("chips", None)
    ch = a.get("chip") or {}
    ch.pop("chips", None)
    # 只保留最近 60 个 5 分钟点的迷你走势，便于列表展示
    a.pop("_k5", None)


# ---------------------------------------------------------------- 主流程
def run_screen(params: dict, weights: dict, limit: int = 400, mode: str = "balanced",
               progress=None, stop_flag=None, preview_at: str | None = None) -> dict:
    """
    两段式选股：
      阶段1 粗筛 —— 拿全市场快照，用 K 线数据算"连续站上均价线"和筹码；
      阶段2 精算 —— 通过初筛的个股做完整评分与买点规划。
    返回 {count, items, stats, scanned, elapsed}
    """
    t0 = time.time()
    log = progress or (lambda *a, **k: None)
    # 尾盘前试算（14:00~14:30）：今天尚未定型，用"截至现在"的价与均价线先挑出要盯的
    params = dict(params)
    if preview_at:
        params["preview_at"] = preview_at
    else:
        params.pop("preview_at", None)

    log(phase="list", msg="获取全市场行情快照…", pct=2)
    snap = store.get_list()
    pool = prefilter(snap, params)
    total = len(pool)
    log(phase="list", msg=f"全市场 {len(snap)} 只，基础过滤后 {total} 只", pct=5)

    cand = balance_pool(pool, limit, mode)
    n = len(cand)
    # 挑一个够用又最省的分钟周期：tail_from / preview_at 正好落在 30 分钟线的收盘时刻
    # （10:00 10:30 11:00 11:30 13:30 14:00 14:30 15:00）上时，30 分钟线算出的均价线
    # 与 5 分钟线逐列相同，但数据量只有 1/5 —— 默认的 14:30 正是这样一个时刻。
    _sc = _intraday_arg(params)

    rt_map = {}
    try:
        for i in range(0, len(cand), 90):
            chunk = cand["code"].iloc[i:i + 90].tolist()
            for _, row in ds.realtime(chunk).iterrows():
                rt_map[row["code"]] = row.to_dict()
    except Exception:
        pass

    # 流通股本并发预热：analyze 里是逐只串行调用的（每只一次东方财富请求），
    # 600 只串行要 3 分钟。先在这里并发拉进内存缓存，正式扫描时就全是内存命中。
    workers = int(params.get("workers", 48))
    if bool(params.get("real_turnover", True)):
        try:
            log(phase="scan", msg=f"预热股本数据（{n} 只）…", pct=6)
            got = ext.prefetch_shares(cand["code"].tolist(), workers=min(workers, 12))
            if got:
                log(phase="scan", msg=f"股本数据就绪（{got} 只）", pct=7)
        except Exception:
            pass

    log(phase="scan", msg=f"开始扫描 {n} 只个股…（{'%d 分钟线' % _sc[0]}）", pct=8)

    results, watch, done, fails = [], [], 0, 0
    errs = {}
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, r.code, r.name, params, weights, rt_map, True, True, errs, _sc): r.code
                for r in cand.itertuples()}
        for f in as_completed(futs):
            if stop_flag is not None and stop_flag():
                for x in futs:
                    x.cancel()
                break
            done += 1
            try:
                a = f.result()
            except Exception:
                a = None
            if a is None:
                fails += 1
            else:
                results.append(a)
                # 只差最后一两个条件的，作为"观察池"展示，避免命中 0 只时界面空白
                c = a["checks"]
                # 「差最后一项」的口径要随策略的关卡数变：单关策略只有 0/1，不能拿 2 去卡
                gk = [g.key for g in strats.get_current(params).gate_list(params)]
                n_all = len(gk) or 1
                n_ok = sum(1 for k in gk if c.get(k))
                if n_ok >= max(1, n_all - 1):
                    a["watch"] = _miss_note(a, params)
                    watch.append(a)
                elif c.get("tail_watch"):
                    # 尾盘前试算挑中的：今天还差一点，14:30 前值得盯着
                    tf = str(params.get("tail_from", "14:30"))
                    a["watch"] = (f"试算已经达标，等 {tf} 再确认一次" if tf != "close"
                                  else "试算已经达标，等收盘确认")
                    watch.append(a)
            if done % 5 == 0 or done == n:
                el = max(time.time() - t1, 0.1)
                eta = int(el / done * (n - done)) if done else 0
                log(phase="scan", msg=f"已扫描 {done}/{n} · 预计还需 {eta}s",
                    pct=8 + int(80 * done / max(n, 1)))

    items = _apply_filters(results, params)
    watch = [w for w in watch if w["code"] not in {i["code"] for i in items}]

    def _sur(x):
        # 尾盘口径下用"压着尾盘那一刻算出来的溢价"，按收盘价算的 avg_surplus 在这套规则里不作数
        av = x["avg"]
        v = av.get("tail_surplus") if str(params.get("entry_mode", "tail")) == "tail" else None
        return v if v is not None else (av.get("avg_surplus") or 0)

    items.sort(key=lambda x: (-x["score"], -_sur(x)))
    watch.sort(key=lambda x: (-x["score"], -_sur(x)))

    # ---- 市场状态开关（market_state）----
    # 这套规则是"超跌反转"，只在大盘真弱（指数在 MA20 下方）时才有胜算。
    # 市场状态不匹配时不产生可买名单，但把"本来会选中的"放进观察池，
    # 免得用户看到空表以为软件坏了。见 market_state 的模块说明。
    ms, gated = {}, False
    try:
        from . import market_state
        ms = market_state.state()
        # gated 表示"市场状态不匹配"，跟这次有没有选出票无关 ——
        # 界面要能看出「现在不该玩这套规则」，而不是等空表才解释
        gated = not market_state.allow(params, ms)
    except Exception:
        ms, gated = {}, False
    if gated and items:
        reason = ""
        try:
            reason = market_state.why(params, ms)
        except Exception:
            reason = "市场状态不匹配"
        for a in items:
            a["watch"] = reason
            a["gated"] = True
            watch.append(a)
        items = []
        watch.sort(key=lambda x: (-x["score"], -_sur(x)))

    for i, a in enumerate(items, 1):
        a["rank"] = i
        a["plan"] = analyzer.plan_targets(a["price"], a, params)
    for i, a in enumerate(watch[:30], 1):
        a["rank"] = i
        a["plan"] = analyzer.plan_targets(a["price"], a, params)

    from collections import Counter
    # 漏斗按当前策略的关卡动态生成：换方案界面上自动跟着变，不用改前端
    cur = strats.get_current(params)
    gate_keys = [g.key for g in cur.gate_list(params)]
    funnel = {k: sum(1 for a in results if (a.get("checks") or {}).get(k)) for k in gate_keys}
    funnel.update({
        "ma_close": sum(1 for a in results if (a.get("checks") or {}).get("close_ma")),
        "streak": dict(Counter(min(a["avg"]["streak"], 6) for a in results)),
        "tail_from": params.get("tail_from", "14:30"),
        "entry_mode": params.get("entry_mode", "tail"),
        "tail_watch": sum(1 for a in results if a["checks"].get("tail_watch")),
        "preview_at": params.get("preview_at"),
        "strategy": cur.key,
        "gates": [{"key": g.key, "label": g.label} for g in cur.gate_list(params)],
    })
    log(phase="done", msg=f"命中 {len(items)} 只", pct=100)
    if errs:
        log(phase="warn", msg="失败样例：" + "; ".join(
            f"{k}×{len(v)} {list(v)[0]}" for k, v in errs.items())[:300])
    return {
        "items": items,
        "watch": watch[:30],
        "funnel": funnel,
        "stats": {
            "universe": int(len(snap)), "after_filter": int(total),
            "scanned": n, "failed": fails, "hit": len(items),
            "elapsed": round(time.time() - t0, 1),
            "mode": mode, "limit": limit,
            "basis": basis_label(params),
            # 市场状态：让界面能看到"现在该不该玩这套规则"，以及为什么被拦下
            "market": (ms or None),
            "gated": gated,
            # 把这次实际用的条件一起带走：详情页要用同一套参数重算，
            # 否则会出现"名单里 75 分、点进去 0 分"的自相矛盾
            "params": dict(params),
            "weights": dict(weights or {}),
        },
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def basis_label(params: dict) -> str:
    """这次名单是按什么口径算出来的：tail（尾盘定型）/ preview（没定型）/ close（收盘）。

    entry_mode=tail 时不能一律标 tail：只要现在还没到 tail_from（默认 14:30），
    用的就是"截至此刻"的均价线，名单还会变 —— 标成 tail 会让记忆页把一份
    上午 10 点的半成品当成当天的正式名单存下来（这个坑已经踩过：
    13:06 的记录 basis 写的是 tail，实际是盘中试算）。
    """
    if params.get("preview_at"):
        return "preview"
    if str(params.get("entry_mode", "tail")) != "tail":
        return "close"
    tf = str(params.get("tail_from", "14:30") or "")
    if len(tf) != 5 or tf[2] != ":":
        return "tail"                     # 'close' 之类，全天口径不用等
    return "tail" if time.strftime("%H:%M") >= tf else "preview"


_CHK_NAME = {"ma": "平均成本", "tail": "尾盘的那条平均成本线", "close_ma": "收盘价对平均成本",
             "chip": "套牢盘", "pos": "价格位置", "bottom": "底部横盘", "trend": "趋势"}
_NOTE_KEYS = ("ma", "chip", "pos", "bottom", "trend")      # ma 已按 entry_mode 归并


def _miss_note(a, params):
    """人话版"还差什么"：直接用策略给的 why，策略换了自己会说。"""
    rows = a.get("gates") or []
    miss = [g["why"] for g in rows if not g["ok"] and g.get("why")]
    if miss:
        return "、".join(miss)
    # 策略没给说明时退回到老的写法，至少不至于空着
    c = a["checks"]
    out = []
    for k, label in (("ma", "站上平均成本"), ("chip", "套牢盘少"),
                     ("pos", "位置低"), ("bottom", "底部横盘"), ("trend", "趋势向上")):
        if k in c and not c[k]:
            out.append(f"{label}没达到")
    return "、".join(out) or "差一点"


def _apply_filters(results, params):
    """按当前策略的关卡过滤。关卡表来自策略插件，实盘和回测共用同一份。"""
    keys = [g.key for g in strats.get_current(params).gate_list(params)]
    return [a for a in results
            if all(a.get("checks", {}).get(k) for k in keys)]


# ---------------------------------------------------------------- 宽松扫描（演示/监控）
def run_scan(params: dict, weights: dict, limit: int = 60, mode: str = "balanced",
             progress=None) -> dict:
    """
    只做"连续站上均价线"这一层的扫描，用于盘中盯盘和参数调试，
    可以看到哪些股票资金在流入，但不强制筹码/低位条件。
    """
    t0 = time.time()
    log = progress or (lambda *a, **k: None)
    snap = store.get_list()
    pool = prefilter(snap, params)
    cand = balance_pool(pool, limit, mode)
    rt_map = {}
    try:
        for i in range(0, len(cand), 90):
            for _, row in ds.realtime(cand["code"].iloc[i:i + 90].tolist()).iterrows():
                rt_map[row["code"]] = row.to_dict()
    except Exception:
        pass
    items, done = [], 0
    n = len(cand)
    _sc = _intraday_arg(params)
    workers = int(params.get("workers", 48))
    # 股本也并发预热一遍：不预热的话每只股票在 analyze 里串行发一次请求
    if bool(params.get("real_turnover", True)):
        try:
            ext.prefetch_shares(cand["code"].tolist(), workers=min(workers, 12))
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, r.code, r.name, params, weights, rt_map,
                          True, True, None, _sc): r.code
                for r in cand.itertuples()}
        for f in as_completed(futs):
            done += 1
            a = f.result()
            if a is not None:
                a["passed"] = sum(1 for v in a["checks"].values() if v)
                items.append(a)
            if done % 5 == 0 or done == n:
                log(phase="scan", msg=f"已扫描 {done}/{n}", pct=8 + int(88 * done / max(n, 1)))
    items.sort(key=lambda x: (-x["passed"], -(x["avg"]["avg_surplus"] or -9)))
    log(phase="done", msg=f"{n} 只扫描完成", pct=100)
    return {"items": items, "stats": {"scanned": n, "elapsed": round(time.time() - t0, 1)},
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
