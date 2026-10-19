# -*- coding: utf-8 -*-
"""
选股记忆：把每天选出来的名单记下来，过几天回头看它涨没涨。

为什么要这块：
  软件每天都在说"这几只可以买"，但没人回头对过账 —— 到底准不准？
  这个模块每天收盘前后把当天的名单落一份到 data/memory/YYYY-MM-DD.json，
  之后用不复权收盘价算每只票从"选出那天"到"今天"涨了多少，
  一年下来就能看出这套规则是真有用还是看着像有用。

存的东西（一天一个文件，只留关键字段，不存整个分析对象）：
  date        选股那天
  at          这份名单是什么时候生成的
  basis       tail（尾盘口径）/ close（收盘口径）
  params      当时的关键参数（ma_days、chip_decay 等），以后改参数了也说得清是哪套规则选出来的
  items       [{code, name, price, score, stop, target, note}]  price 是选出当天的价
  watch       只差一项的（同一套字段，多一个 gap 表示差几关）
  hit_count   当天几只
  stats       漏斗里几个关键数字（scanned / hit / funnel）

回看（review）：
  对每一天、每一只票，取它到今天为止的收盘价，算：
    then   选出当天的价
    last   最新收盘价
    ret    涨了百分之多少
    best   这期间最高涨到多少（判断有没有摸到止盈）
    worst  最低跌到多少（判断有没有踩到止损）
    days   过去了几个交易日
  然后汇总成：一共选了 N 只、到今天赚钱的几只、平均涨幅、最好的和最惨的。

注意：这里只做记录和回看，不参与选股判断，也不联网重算分时数据，
      只用日线收盘价 —— 便宜、稳定、不依赖行情接口是否还在。
"""
import json
import time
import traceback
from pathlib import Path

from . import config

MEM_DIR = config.DATA_DIR / "memory"
MAX_KEEP = 400                        # 最多留 400 个交易日，再多就删最老的


# ---------------------------------------------------------------- 文件
def _dir() -> Path:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    return MEM_DIR


def _path(date: str) -> Path:
    return _dir() / f"{date}.json"


def _read(date: str):
    try:
        f = _path(date)
        if not f.is_file():
            return None
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(date: str, obj):
    try:
        f = _path(date)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(f)
    except Exception:
        traceback.print_exc()


def days() -> list:
    """已经记下来的所有日期，从新到旧"""
    try:
        fs = sorted((p for p in _dir().glob("*.json") if p.stem[:4].isdigit()),
                    key=lambda p: p.stem, reverse=True)
        return [p.stem for p in fs]
    except Exception:
        return []


def _trim():
    """太多就删最老的，免得一年后目录里堆几千个文件"""
    try:
        ds = days()
        for d in ds[MAX_KEEP:]:
            _path(d).unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------- 记录
def save_result(r: dict, date: str | None = None):
    """把一次选股结果记下来。

    r 是 screener.run_screen() 的返回值；同一天跑多次（自动选股每 5 分钟一次）
    只保留"最后一次"，因为最终名单以收盘前那次为准。
    """
    if not isinstance(r, dict):
        return
    items = r.get("items") or []
    watch = r.get("watch") or []
    if not items and not watch:
        return                    # 一只都没有的空白结果不占位置
    date = date or time.strftime("%Y-%m-%d")
    old = _read(date) or {}
    stats = r.get("stats") or {}
    params = stats.get("params") or {}

    def _brief(a, gap=None):
        b = {
            "code": a.get("code"), "name": a.get("name"),
            "price": a.get("price"), "score": a.get("score"),
        }
        plan = a.get("plan") or {}
        if plan.get("stop") is not None:
            b["stop"] = plan.get("stop")
        if plan.get("target") is not None:
            b["target"] = plan.get("target")
        if gap is not None:
            b["gap"] = gap
        return b

    # 「只差一项」的算 gap：五关里还差几关
    KEYS = ("ma", "chip", "pos", "bottom", "trend")
    wl = []
    for a in watch:
        try:
            checks = (a.get("checks") or {})
            gap = sum(1 for k in KEYS if not checks.get(k))
        except Exception:
            gap = None
        wl.append(_brief(a, gap))

    obj = {
        "date": date,
        "at": r.get("generated_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "basis": stats.get("basis") or "",
        "params": {
            "ma_days": params.get("ma_days"),
            "chip_decay": params.get("chip_decay"),
            "profit_cap": params.get("profit_cap"),
            "pos_cap": params.get("pos_cap"),
            "tail_from": params.get("tail_from"),
            "stop_loss": params.get("stop_loss"),
            "take_profit": params.get("take_profit"),
        },
        "items": [_brief(a) for a in items],
        "watch": wl,
        "hit_count": len(items),
        "stats": {
            "scanned": stats.get("scanned"),
            "hit": stats.get("hit"),
            "universe": stats.get("universe"),
            "after_filter": stats.get("after_filter"),
            "elapsed": stats.get("elapsed"),
            "funnel": r.get("funnel") or {},
        },
        # 同一天跑了很多次：记下跑了多少次，方便知道哪次是最终的
        "runs": int(old.get("runs") or 0) + 1,
    }
    _write(date, obj)
    _trim()


def get(date: str):
    return _read(date)


def list_days(n: int = 60) -> list:
    """给前端用的日历：每天只要一句摘要，不带明细"""
    out = []
    for d in days()[:n]:
        o = _read(d) or {}
        out.append({
            "date": d,
            "at": o.get("at"),
            "hit": o.get("hit_count", 0),
            "watch": len(o.get("watch") or []),
            "scanned": (o.get("stats") or {}).get("scanned"),
            "names": [x.get("name") for x in (o.get("items") or [])][:6],
        })
    return out


# ---------------------------------------------------------------- 回看
def _closes(code: str):
    """拿这只票的日线收盘价（走 store 的缓存，不会额外打接口）"""
    from . import store
    df = store.get_daily(code, 320)
    if df is None or len(df) == 0:
        return {}
    m = {}
    for _, row in df.iterrows():
        try:
            m[str(row["date"])[:10]] = float(row["close"])
        except Exception:
            continue
    return m


def _calc(code: str, then: float, date: str):
    """算出"选出那天之后"这只票的走势。

    当天刚选出来的票还没有收盘价（日线缓存里最新一根就是昨天），
    这时候返回 pending —— 前端显示「等今天收盘」，而不是骗一个 0%。
    """
    cl = _closes(code)
    if not cl:
        return None
    ds = sorted(d for d in cl if d >= date)
    if not ds:
        return None
    if not then:
        then = cl[ds[0]]
    try:
        then = float(then)
    except Exception:
        return None
    if then <= 0:
        return None
    vals = [cl[d] for d in ds]
    last = vals[-1]
    if len(ds) == 1 and ds[0] == date and date == max(cl):
        pass                       # 只有选出当天那一根，也算一天（收盘口径可以直接看）
    return {
        "last": round(last, 2),
        "ret": round((last / then - 1) * 100, 2),
        "best": round((max(vals) / then - 1) * 100, 2),
        "worst": round((min(vals) / then - 1) * 100, 2),
        "days": len(ds) - 1,          # 选出那天算 0 天
        "to": ds[-1],
    }


def _pending(a: dict, date: str):
    """还没有收盘价的（今天刚选的）—— 也给一行，只是没有涨跌幅"""
    c = a.get("code")
    if not c:
        return None
    try:
        px = float(a["price"]) if a.get("price") else None
    except Exception:
        px = None
    return {
        "code": c, "name": a.get("name"), "score": a.get("score"),
        "then": round(px, 2) if px else None,
        "stop": a.get("stop"), "target": a.get("target"), "gap": a.get("gap"),
        "last": round(px, 2) if px else None,
        "ret": None, "best": None, "worst": None, "days": 0, "to": date,
        "pending": True, "sold_stop": False, "sold_target": False,
    }


def _calc_row(a: dict, date: str):
    """把一条记录算成一行可回看的结果"""
    c = a.get("code")
    if not c:
        return None
    r = _calc(c, a.get("price"), date)
    if not r:
        return _pending(a, date)
    stop, target = a.get("stop"), a.get("target")
    px = None
    try:
        px = float(a["price"]) if a.get("price") else None
    except Exception:
        px = None
    r.update({
        "code": c, "name": a.get("name"), "score": a.get("score"),
        "then": round(px, 2) if px else None,
        "stop": stop, "target": target, "gap": a.get("gap"),
        "sold_stop": bool(px and stop and r["worst"] <= (float(stop) / px - 1) * 100),
        "sold_target": bool(px and target and r["best"] >= (float(target) / px - 1) * 100),
    })
    return r


def _sum_rows(rows: list):
    rows = [r for r in rows if r.get("ret") is not None]
    if not rows:
        return None
    n = len(rows)
    win = sum(1 for r in rows if r["ret"] > 0)
    return {
        "n": n,
        "win": win,
        "win_rate": round(win / n * 100, 1),
        "avg": round(sum(r["ret"] for r in rows) / n, 2),
        "best": max(rows, key=lambda r: r["ret"]),
        "worst": min(rows, key=lambda r: r["ret"]),
        "avg_days": round(sum(r["days"] for r in rows) / n, 1),
        "hit_stop": sum(1 for r in rows if r["sold_stop"]),
        "hit_target": sum(1 for r in rows if r["sold_target"]),
    }


def review(date: str | None = None, code: str | None = None, limit: int = 120):
    """回看某一天的名单（不传就回看最近有记录的那天）现在怎么样了。

    返回 {
      date, at, hit,
      rows:[{code,name,then,last,ret,best,worst,days,sold_stop,sold_target}],
      sum:{n, win, avg, best, worst, avg_days},
      watch_rows / watch_sum   只差一项的那批，也用同样的口径算一遍
    }
    sold_stop / sold_target：这期间最低价跌破了止损价 / 最高价摸到了止盈价 ——
    相当于"如果你按软件给的止损止盈做，这笔已经了结了"。
    """
    if not date:
        ds = days()
        if not ds:
            return {"date": None, "rows": [], "sum": None, "watch_rows": [],
                    "note": "还没有记录 —— 从今天起，每次选股都会自动记一笔"}
        date = ds[0]
    o = _read(date)
    if not o:
        return {"date": date, "rows": [], "sum": None, "watch_rows": [],
                "note": f"{date} 没有记录"}

    def _pick(src):
        out = []
        for a in src[:limit]:
            if code and a.get("code") != code:
                continue
            r = _calc_row(a, date)
            if r:
                out.append(r)
        return out

    rows = _pick(o.get("items") or [])
    wrows = _pick(o.get("watch") or [])
    return {
        "date": date,
        "at": o.get("at"),
        "basis": o.get("basis"),
        "hit": o.get("hit_count", 0),
        "rows": rows,
        "sum": _sum_rows(rows),
        "watch_rows": wrows,
        "watch_sum": _sum_rows(wrows),
    }


def overview(n: int = 30):
    """把这些天放在一起看：这套选股到底准不准。

    只统计"选出来并且今天已经有收盘价"的票；越早的记录 days 越大，越可信。
    另外按"选出后第 N 天"分组，看是不是拿得越久越好。
    """
    ds = days()[:n]
    total = []
    per_day = []
    for d in ds:
        rv = review(d)
        allrows = [x for x in (rv["rows"] or []) + (rv.get("watch_rows") or [])
                   if x.get("ret") is not None]
        if not allrows:
            continue
        per_day.append({
            "date": d,
            "n": len(allrows),
            "hit": len(rv["rows"] or []),
            "avg": round(sum(x["ret"] for x in allrows) / len(allrows), 2),
            "win_rate": round(sum(1 for x in allrows if x["ret"] > 0) / len(allrows) * 100, 1),
            "days": allrows[0]["days"],
        })
        total.extend(allrows)
    s = None
    if total:
        n2 = len(total)
        win = sum(1 for r in total if r["ret"] > 0)
        s = {
            "n": n2,
            "days_recorded": len(per_day),
            "win": win,
            "win_rate": round(win / n2 * 100, 1),
            "avg": round(sum(r["ret"] for r in total) / n2, 2),
            "med": round(sorted(r["ret"] for r in total)[n2 // 2], 2),
            "hit_stop": sum(1 for r in total if r["sold_stop"]),
            "hit_target": sum(1 for r in total if r["sold_target"]),
        }
    return {"days": per_day, "sum": s,
            "note": "" if total else "还没有可以回看的记录 —— 至少要有一天选出了票，并且之后有收盘价"}
