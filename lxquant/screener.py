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
    抽样控制：mode=all 全部；mode=balanced 按板块比例抽样，保证各板块都有代表。
    """
    if len(df) <= limit:
        return df
    if mode == "all":
        return df
    boards = [
        ("沪市主板", df["code"].str.startswith(("600", "601", "603", "605"))),
        ("深市主板", df["code"].str.startswith(("000", "001", "002", "003"))),
        ("创业板", df["code"].str.startswith(("300", "301"))),
        ("科创板", df["code"].str.startswith("688")),
    ]
    frames = []
    for name, mask in boards:
        sub = df[mask]
        if sub.empty:
            continue
        quota = max(1, int(limit * len(sub) / len(df)))
        # 按成交额均匀抽样，覆盖大中小盘
        idx = np.linspace(0, len(sub) - 1, min(quota, len(sub)), dtype=int)
        frames.append(sub.sort_values("amount", ascending=False).iloc[idx])
    out = pd.concat(frames).drop_duplicates("code")
    return out.head(limit).reset_index(drop=True)


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
            got = ext.prefetch_shares(cand["code"].tolist(), workers=min(workers, 32))
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
                if c["ma"] and sum(1 for k, v in c.items() if k != "tail_watch" and v) >= 3:
                    a["watch"] = _miss_note(a, params)
                    watch.append(a)
                elif c.get("tail_watch"):
                    # 尾盘前试算挑中的：今天还差一点，14:30 前值得盯着
                    tf = str(params.get("tail_from", "14:30"))
                    a["watch"] = (f"试算已经达标，等 {tf} 再确认一次" if tf != "close"
                                  else "试算已经达标，等收盘确认")
                    watch.append(a)
                elif c.get("tail") and c.get("chip") and c.get("pos"):
                    # 三条硬条件全过，只差横盘/趋势这类"软过滤"：放观察池，让人自己判断
                    a["watch"] = _miss_note(a, params)
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
    for i, a in enumerate(items, 1):
        a["rank"] = i
        a["plan"] = analyzer.plan_targets(a["price"], a, params)
    for i, a in enumerate(watch[:30], 1):
        a["rank"] = i
        a["plan"] = analyzer.plan_targets(a["price"], a, params)

    from collections import Counter
    funnel = {
        "ma": sum(1 for a in results if a["checks"]["ma"]),
        "ma_close": sum(1 for a in results if a.get("checks", {}).get("close_ma")),
        "chip": sum(1 for a in results if a["checks"]["chip"]),
        "pos": sum(1 for a in results if a["checks"]["pos"]),
        "bottom": sum(1 for a in results if a["checks"]["bottom"]),
        "trend": sum(1 for a in results if a["checks"]["trend"]),
        "streak": dict(Counter(min(a["avg"]["streak"], 6) for a in results)),
        "tail_from": params.get("tail_from", "14:30"),
        "entry_mode": params.get("entry_mode", "tail"),
        "tail_watch": sum(1 for a in results if a["checks"].get("tail_watch")),
        "preview_at": params.get("preview_at"),
    }
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
            # preview = 尾盘前试算（今天用的是"截至此刻"的价，还没定型）
            "basis": ("preview" if params.get("preview_at")
                      else ("tail" if str(params.get("entry_mode", "tail")) == "tail" else "close")),
            # 把这次实际用的条件一起带走：详情页要用同一套参数重算，
            # 否则会出现"名单里 75 分、点进去 0 分"的自相矛盾
            "params": dict(params),
            "weights": dict(weights or {}),
        },
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


_CHK_NAME = {"ma": "平均成本", "tail": "尾盘的那条平均成本线", "close_ma": "收盘价对平均成本",
             "chip": "套牢盘", "pos": "价格位置", "bottom": "底部横盘", "trend": "趋势"}
_NOTE_KEYS = ("ma", "chip", "pos", "bottom", "trend")      # ma 已按 entry_mode 归并


def _miss_note(a, params):
    """人话版"还差什么"：不报条件代号，直接说差多远。"""
    c, miss = a["checks"], []
    av = a["avg"]
    tail_mode = str(params.get("entry_mode", "tail")) == "tail"
    if not c.get("ma"):
        if tail_mode:
            pv = av.get("preview") or {}
            if pv:
                if not pv.get("today_ok"):
                    miss.append(f"今天的价还在平均成本下方 {abs(pv.get('surplus') or 0):.2f}%（{pv.get('at')}）")
                else:
                    miss.append(f"今天已站上，但前面只站上 {max(0, int(pv.get('hit') or 0) - 1)} 天")
            else:
                d = av.get("tail_detail") or []
                bad = [x for x in d if not x.get("ok")]
                if bad:
                    miss.append(f"{bad[0]['date'][5:]} 那天收在平均成本下方 {abs(bad[0]['surplus']):.2f}%")
                else:
                    miss.append(f"站上平均成本的天数不够（{av.get('tail_streak', 0)} 天）")
        else:
            miss.append(f"连续站上平均成本的天数不够（{av.get('streak', 0)} 天）")
    if not c.get("chip"):
        cap = float(params.get("profit_cap", 0.25)) * 100
        pr = (a["chip"].get("profit_ratio") or 0) * 100
        miss.append(f"上方套牢盘 {pr:.0f}%，要 ≤ {cap:.0f}%")
    if not c.get("pos"):
        cap = float(params.get("pos_cap", 0.30)) * 100
        miss.append(f"价格在区间 {a['pos'].get('pos', 0) * 100:.0f}% 位置，要 ≤ {cap:.0f}%")
    if not c.get("bottom"):
        b = a["bottom"] if isinstance(a.get("bottom"), dict) else {}
        amp = b.get("amp")
        miss.append(b.get("note") or
                    ("走势还没收敛（振幅偏大或有明显斜度）" if amp is None
                     else f"波动太大，近 20 日振幅 {amp * 100:.0f}%"))
    if not c.get("trend"):
        miss.append("低于 20 日均线")
    return "、".join(miss)


def _apply_filters(results, params):
    out = []
    trend_on = params.get("ma_trend_enable", False)   # 和 config.DEFAULT_PARAMS 保持一致
    bottom_on = params.get("bottom_enable", True)
    amp_cap = float(params.get("bottom_amp", 0.40))
    slope_cap = float(params.get("bottom_slope", 0.12))
    for a in results:
        c = a["checks"]
        if not c["ma"] or not c["chip"] or not c["pos"]:
            continue
        if trend_on and not c["trend"]:
            continue
        if bottom_on:
            b = a["bottom"]
            if not b.get("ok") or b.get("amp") is None:
                continue
            if b["amp"] > amp_cap or abs(b.get("slope") or 0) > slope_cap:
                continue
        out.append(a)
    return out


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
            ext.prefetch_shares(cand["code"].tolist(), workers=min(workers, 32))
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
