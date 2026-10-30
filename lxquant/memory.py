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
import math
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
def _tail_prices(codes, hm: str) -> dict:
    """取这些票当天 hm 时刻的价格（<= hm 的最后一根分时），返回 {code: price}。

    为什么要单独取：盘后（甚至晚上）打开软件时，行情快照给的是**收盘价**，
    而用户实际是 14:45 下的单。两者差 0.3%~1% 很常见，直接拿收盘价当买入价，
    回看的涨跌幅就从一开始是错的。取不到就返回空，调用方保持原价。
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import datasource as ds

    def one(c):
        try:
            df = ds.minute_today(c)
            if df is None or len(df) == 0:
                return c, None
            sub = df[df["time"].astype(str) <= hm]
            if len(sub) == 0:
                return c, None
            p = float(sub["price"].iloc[-1])
            return c, (p if p > 0 else None)
        except Exception:
            return c, None

    out = {}
    try:
        with ThreadPoolExecutor(max_workers=12) as ex:
            for c, p in ex.map(one, codes):
                if p:
                    out[c] = p
    except Exception:
        pass
    return out


def save_result(r: dict, date: str | None = None, force: bool = False):
    """把一次选股结果记下来。

    r 是 screener.run_screen() 的返回值。
    只有**尾盘定型**（basis == tail）的名单才记账 —— 也就是过了 tail_from（默认 14:45）
    之后跑出来的那份。这保证了记下来的买入价是"你实际下单那一刻"的价，
    而不是上午打开软件时随手跑出来的价。
    """
    if not isinstance(r, dict):
        return
    items = r.get("items") or []
    watch = r.get("watch") or []
    if not items and not watch:
        return                    # 一只都没有的空白结果不占位置
    stats = r.get("stats") or {}
    # 盘中试算（还没到 tail_from，或 14:00~14:30 的 preview）不记账：
    # 那份名单每 5 分钟就变一次，"当天留了几只"会跟着抖；
    # 而且试算的记录会被当成那天的正式名单，回头看的时候全是错的。
    # 只记"定型了"的名单 —— 口径判断统一在 screener.basis_label()。
    if stats.get("basis") == "preview":
        return
    date = date or time.strftime("%Y-%m-%d")
    old = _read(date) or {}
    # 同一天已经有一份「尾盘定型」的名单了，就别再让后面的自动重扫覆盖它。
    # 你 14:45 下手，而自动扫描还在每 5 分钟跑一次（14:50、14:55…），
    # 每次都是 tail 口径 —— 一路覆盖下来，记忆里的买入价会变成 14:55 的价，
    # 回看的涨跌幅跟你实际成交价就对不上了。
    # 手动点「立即选股」仍然可以强制刷新（force=True），方便名单有误时纠错。
    if (not force and old.get("basis") == "tail"
            and stats.get("basis") == "tail"
            and (old.get("items") or old.get("watch"))):
        old["runs"] = int(old.get("runs") or 0) + 1
        _write(date, old)
        return
    # ★ 盘后重扫**连 force 也不许覆盖**盘中定型的名单。
    #   盘后行情快照给的是收盘价，跟 14:45 实盘可买的那份是两个口径，
    #   选出的名单会大幅缩水（实测 2026-10-29：17:04 页面自动补扫只选出 5 只，
    #   force=True 直接把 14:45 定型的 40 只覆盖没了）。
    #   判据用「两边各自的时刻」而不是当前时钟：定型名单产生于 15:00 之前、
    #   新结果产生于 15:00 之后 → 口径不同，拒绝覆盖。这样任何时候都拦得住，
    #   而盘后手工纠错过的记录（at 也在盘后）仍允许被再次覆盖。
    #   真要强行纠错只能手动改 data/memory/ 下的文件（刻意为之，防止顺手点一下就毁了账）。
    def _hm_of(s: str) -> str:
        return str(s or '')[11:16]

    _new_at = str(r.get("generated_at") or '') or time.strftime("%Y-%m-%d %H:%M:%S")
    _old_hm = _hm_of(old.get("at"))
    if (force and old.get("basis") == "tail"
            and (old.get("items") or old.get("watch"))
            and _old_hm and _old_hm < "15:00"
            and _hm_of(_new_at) >= "15:00"):
        old["runs"] = int(old.get("runs") or 0) + 1
        _write(date, old)
        return
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

    # 「只差一项」的算 gap：还差几关。关卡表要跟着当前策略走 ——
    # 以前这里写死五关，换成两关的自定义策略后 gap 会恒等于 3 以上，
    # 和选股页上「差最后一项」的说法对不上。
    try:
        from . import strategies as strats
        KEYS = [g.key for g in strats.get_current(params).gate_list(params)]
    except Exception:
        KEYS = ("ma", "chip", "pos", "bottom", "trend")
    wl = []
    for a in watch:
        checks = (a.get("checks") or {})
        gap = sum(1 for k in KEYS if not checks.get(k))
        wl.append(_brief(a, gap))

    items_brief = [_brief(a) for a in items]
    # 把买入价锚定到「实际下单时刻」＝ tail_from（默认 14:45）。
    # 盘后甚至晚上才打开软件时，快照里给的是**收盘价**，跟 14:45 的成交价差 0.3%~1%，
    # 直接存下来会让后面所有回看的涨跌幅从起点就偏。
    hm = str((stats.get("params") or {}).get("tail_from") or "14:45")
    price_at = ""
    if items_brief and len(hm) == 5 and hm[2] == ":":
        got = _tail_prices([b["code"] for b in items_brief], hm)
        if got:
            n_ok = 0
            for b in items_brief:
                old_p, new_p = b.get("price"), got.get(b["code"])
                if not new_p or not old_p:
                    continue
                ratio = new_p / old_p
                b["price"] = round(new_p, 3)
                # 止损/止盈是按原价算的档位，按同一比例缩放，保持相对关系不变
                for k in ("stop", "target"):
                    if isinstance(b.get(k), (int, float)):
                        b[k] = round(b[k] * ratio, 3)
                b["price_at"] = hm
                n_ok += 1
            # 只有**每一只**都换到了分时价，顶层才敢标「取自 14:45」。
            # 部分成功（有的票当天停牌、分时取不到）时留空 ——
            # 否则前端会说"买入价取自 14:45"，实际混着收盘价，看涨跌幅会被误导。
            price_at = hm if n_ok == len(items_brief) else ""

    obj = {
        "date": date,
        "at": r.get("generated_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "basis": stats.get("basis") or "",
        # 买入价取自哪个时刻的分时（空 = 取不到分时，用的快照价）
        "price_at": price_at,
        "params": {
            # 记下是哪套策略选的 —— 换过策略之后，不同策略的成绩不能混在一起比。
            # 之前的记录没这个字段，只能靠时间线猜（见 2026-10-29 的清理）。
            "strategy": params.get("strategy"),
            "ma_days": params.get("ma_days"),
            "chip_decay": params.get("chip_decay"),
            "profit_cap": params.get("profit_cap"),
            "pos_cap": params.get("pos_cap"),
            "tail_from": params.get("tail_from"),
            "stop_loss": params.get("stop_loss"),
            "take_profit": params.get("take_profit"),
        },
        "items": items_brief,
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
def _series(code: str, memo: dict | None = None):
    """拿这只票的两套收盘价：前复权（算涨跌幅用）+ 不复权（换算记录价用）。

    为什么必须前复权：回看算的是"选出那天到今天涨了多少"，中间一旦送转分红，
    不复权序列会出现除权跳空（10 送 3 当天就是 -23%），涨幅直接变成"暴跌"，
    还会把整张成绩单的胜率和平均值带偏。前复权序列的相邻比值才是真实收益。

    但记录里存的 price 是当时的实盘价（不复权），所以要拿同一天的
    前复权/不复权收盘价比值当复权因子，把记录价换算过去，两边才能相除。

    前复权走 store 的前复权缓存，取不到就整套退回不复权（会失真，但不会报错、
    不会因为行情接口挂了就让记忆页打不开）。预热由 _prefetch 负责，
    这里只读盘。
    """
    if memo is not None and code in memo:
        return memo[code]
    from . import store
    out = {"qfq": {}, "raw": {}}

    def _fill(df, key):
        if df is None or len(df) == 0:
            return
        try:
            # 用 tolist 批量塞，别 iterrows：320 行 × 上百只票，
            # iterrows 逐行走 Python 要 1 秒以上，批量转换只要几毫秒
            dates = df["date"].astype(str).str.slice(0, 10).tolist()
            closes = df["close"].astype(float).tolist()
            out[key].update(zip(dates, closes))
        except Exception:
            pass

    try:
        _fill(store.get_daily_cached(code, 320), "raw")     # 只读盘，不联网
    except Exception:
        pass
    if not out["raw"]:
        try:
            _fill(store.get_daily(code, 320), "raw")        # 盘上没有才去抓
        except Exception:
            pass
    try:
        _fill(store.get_kline_cached(code, "day"), "qfq")   # 只读盘，不联网
    except Exception:
        pass
    # 腾讯的前复权日线**盘中就带当天那一根**（新浪的不带），两套口径不一致。
    # 回看要的是"选出那天到最近一个收盘日"，所以盘中把今天这根未收盘的剔掉，
    # 否则记忆页的数字会随盘中价格跳动，隔一分钟刷新一次就不一样了。
    today = time.strftime("%Y-%m-%d")
    if time.strftime("%H:%M") < "15:05":
        out["raw"].pop(today, None)
        out["qfq"].pop(today, None)
    if not out["qfq"]:
        out["qfq"] = dict(out["raw"])                       # 没有前复权就退回不复权
    if memo is not None:
        memo[code] = out
    return out


def _prefetch(codes, memo: dict | None, workers: int = 16):
    """并发把一批票的前复权日线落进缓存（只补缺的，有的不重拉）。

    串行取的话，一页一百多只票每只一次腾讯请求，要十几秒；
    并发预热之后 _series 全是读盘，回看还是秒开。
    失败一律忽略 —— 拿不到前复权就按不复权算，和以前一样能用。
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import store
    from .config import CACHE_DIR

    today = time.strftime("%Y-%m-%d")
    # 「此刻应该覆盖到的最后一个交易日」。收盘后就是今天；
    # 盘中/开盘前要放宽，否则今天这根还没吐出来，每次都会重拉一遍。
    try:
        want = store._want_date()
    except Exception:
        want = today

    todo = []
    for c in codes:
        if not c:
            continue
        if memo is not None and c in memo:
            continue
        p = CACHE_DIR / f"kd_{c}.pkl"
        if not p.is_file() or p.stat().st_size <= 0:
            todo.append(c)
            continue
        # ★ 判断依据必须是**数据本身的最后一根**，不能是文件 mtime。
        #   mtime 只说明"今天写过这个文件"，不代表里面装的是今天的数据：
        #   2026-10-29 实测，09:03 那次刷新写进去的最后一根是 10-28，
        #   之后腾讯前复权接口整片 501，文件再没更新过 —— mtime 却一直算"今天"，
        #   于是这里永远跳过、回看永远 days=0 / 0%，界面看起来像「都没收盘」。
        try:
            df = store.get_kline_cached(c, "day")
            last = ""
            if df is not None and len(df):
                last = str(df["date"].iloc[-1])[:10] if "date" in df.columns else ""
            if last and last >= want:
                continue
        except Exception:
            pass
        todo.append(c)
    if not todo:
        return

    def _one(c):
        try:
            store.get_kline(c, "day", 640)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_one, todo))


def _price(v):
    """记录里的价格可能是 None / nan（当时没取到行情）—— 统一清成 None。

    nan 的坑：`if nan` 在 Python 里是 True，`round(nan, 2)` 还是 nan，
    然后 json 写出 `NaN`（非法），前端 JSON.parse 直接抛异常，整页白。
    """
    try:
        x = float(v)
    except Exception:
        return None
    return x if (math.isfinite(x) and x > 0) else None


def _calc(code: str, then: float, date: str, memo: dict | None = None):
    """算出"选出那天之后"这只票的走势。

    当天刚选出来的票还没有收盘价（日线缓存里最新一根就是昨天），
    这时候返回 None，由 _calc_row 转成 pending —— 前端显示「等今天收盘」，
    而不是骗一个 0%。
    """
    s = _series(code, memo)
    cl = s["qfq"]
    if not cl:
        return None
    ds = sorted(d for d in cl if d >= date)
    if not ds:
        return None
    base = ds[0]
    px = _price(then)
    if not px:
        px = cl[base]
    else:
        # 记录价是不复权的实盘价，用当天的复权因子换算到前复权口径
        r0 = s["raw"].get(base) or s["raw"].get(date)
        q0 = cl.get(base)
        if r0 and q0:
            px = px * q0 / r0
    if not px or px <= 0:
        return None
    vals = [cl[d] for d in ds]
    last = vals[-1]
    # 展示用的"现价"要真实价格（不复权），否则除过权的票会显示成复权后的历史价
    last_raw = s["raw"].get(ds[-1]) or last
    return {
        "last": round(last_raw, 2),
        "ret": round((last / px - 1) * 100, 2),
        "best": round((max(vals) / px - 1) * 100, 2),
        "worst": round((min(vals) / px - 1) * 100, 2),
        "days": len(ds) - 1,          # 选出那天算 0 天
        "to": ds[-1],
    }


def _pending(a: dict, date: str):
    """还没有收盘价的（今天刚选的）—— 也给一行，只是没有涨跌幅"""
    c = a.get("code")
    if not c:
        return None
    px = _price(a.get("price"))
    return {
        "code": c, "name": a.get("name"), "score": a.get("score"),
        "then": round(px, 2) if px else None,
        "stop": a.get("stop"), "target": a.get("target"), "gap": a.get("gap"),
        "last": round(px, 2) if px else None,
        "ret": None, "best": None, "worst": None, "days": 0, "to": date,
        "pending": True, "sold_stop": False, "sold_target": False,
    }


def _calc_row(a: dict, date: str, memo: dict | None = None):
    """把一条记录算成一行可回看的结果"""
    c = a.get("code")
    if not c:
        return None
    r = _calc(c, a.get("price"), date, memo)
    if not r:
        return _pending(a, date)
    stop, target = a.get("stop"), a.get("target")
    # 注意：这里的 px 是**不复权**的记录价，因为 stop / target 也是当时的不复权价；
    # 而 r["worst"] / r["best"] 是前复权口径算出来的涨跌幅 —— 两边都是"比例"，可以直接比。
    px = _price(a.get("price"))
    fstop = _price(stop)
    ftgt = _price(target)
    r.update({
        "code": c, "name": a.get("name"), "score": a.get("score"),
        "then": round(px, 2) if px else None,
        "stop": stop, "target": target, "gap": a.get("gap"),
        "sold_stop": bool(px and fstop and r["worst"] <= (fstop / px - 1) * 100),
        "sold_target": bool(px and ftgt and r["best"] >= (ftgt / px - 1) * 100),
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


def review(date: str | None = None, code: str | None = None, limit: int = 120,
           memo: dict | None = None):
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
        # 优先落在「最近一个真选出过票」的那天。
        # 直接取 ds[0] 会踩到"当天一只没选出"的记录：点进去 KPI 全是「—」、
        # 表格只有一行「没有票」，看起来像功能坏了，其实只是那天没信号。
        date = ds[0]
        for d in ds:
            o = _read(d) or {}
            if o.get("items"):
                date = d
                break
    o = _read(date)
    if not o:
        return {"date": date, "rows": [], "sum": None, "watch_rows": [],
                "note": f"{date} 没有记录"}

    def _pick(src):
        out = []
        for a in src[:limit]:
            if code and a.get("code") != code:
                continue
            r = _calc_row(a, date, memo)
            if r:
                out.append(r)
        return out

    # 先把这批票的前复权日线并发预热到缓存，_calc 里就只剩读盘（见 _prefetch）
    src_all = (o.get("items") or []) + (o.get("watch") or [])
    _prefetch([a.get("code") for a in src_all if a.get("code")], memo)

    rows = _pick(o.get("items") or [])
    wrows = _pick(o.get("watch") or [])
    return {
        "date": date,
        "at": o.get("at"),
        "basis": o.get("basis"),
        # 买入价取自哪个时刻的分时（空 = 当时取不到，用的快照价）
        "price_at": o.get("price_at"),
        "hit": o.get("hit_count", 0),
        "rows": rows,
        "sum": _sum_rows(rows),
        "watch_rows": wrows,
        "watch_sum": _sum_rows(wrows),
    }


def overview(n: int = 30):
    """把这些天放在一起看：这套选股到底准不准。

    只统计**真正走过后面的行情**的票：days > 0。
    days == 0 的是"当天选出、当天收盘就回看"的记录，那时 then 和 last
    是同一根收盘价，涨跌幅恒等于 0 —— 这种行既说明不了任何问题，
    又会把整张成绩单往 0 拉。实测一天 117 只这样的记录，就能把
    胜率从 6.9% 稀释成 1.4%、中位数打成 0.0，看起来像"这套规则完全没用"。
    单日页（review）仍然照常显示它们，只是不进总账。
    """
    ds = days()[:n]
    total = []
    per_day = []
    waiting = []    # 有记录、但还没走完一个交易日的日子（不该算成绩）
    memo = {}       # 同一只票连着几天被选出来时，只读一次前复权/不复权日线
    for d in ds:
        o = _read(d) or {}
        if o.get("basis") == "preview":
            # 盘中试算的名单（新版本已经不再写入，这里兜历史遗留）：
            # 那份名单没定型，不该进总账，但单日页仍然可以点开看
            waiting.append(d)
            continue
        rv = review(d, limit=5000, memo=memo)

        def _graded(rows):
            """只留下已经走过至少一个交易日的行：days==0 时 then 和 last 是同一根收盘价，
            涨跌幅恒为 0，混进来只会把成绩往 0 拉。"""
            return [x for x in rows
                    if x.get("ret") is not None and (x.get("days") or 0) > 0]

        # 当天选出、但买入价取自 14:45 分时的：then 和 last 是两个不同的价，
        # ret 是"尾盘买入 → 收盘"的真实盈亏，不是 0。
        # 这一类**要显示**（否则收盘后打开，成绩单最后一行还停在昨天，
        # 看起来像今天根本没出结果），但**不进总账** —— 一天的走势代表不了
        # 这套规则准不准，混进累计胜率会把结论拉偏。
        today_px = bool(rv.get("price_at"))

        def _same_day(rows):
            return [x for x in rows
                    if x.get("ret") is not None and (x.get("days") or 0) <= 0]

        # 「能买」和「值得买（差一点）」必须**分开算**：
        # 前者是真正达标的票，后者只是差一两关的观察对象，混在一起算胜率，
        # 等于用没达标的票去评价规则准不准 —— 既低估也说不清。
        hitrows = _graded(rv["rows"] or [])
        watchrows = _graded(rv.get("watch_rows") or [])
        # 当天口径（days=0）的行，仅在有真实买入时点时才拿出来展示
        t_hit = _same_day(rv["rows"] or []) if today_px else []
        t_watch = _same_day(rv.get("watch_rows") or []) if today_px else []
        allrows = hitrows + watchrows
        if not allrows and not (t_hit or t_watch):
            waiting.append(d)
            continue

        def _stat(rows):
            if not rows:
                return {"n": 0, "avg": None, "win": None}
            return {"n": len(rows),
                    "avg": round(sum(x["ret"] for x in rows) / len(rows), 2),
                    "win": round(sum(1 for x in rows if x["ret"] > 0) / len(rows) * 100, 1)}

        hs, ws = _stat(hitrows), _stat(watchrows)
        # 当天还没走完：用它自己的「尾盘→收盘」口径
        ths, tws = _stat(t_hit), _stat(t_watch)
        partial = not allrows
        per_day.append({
            "date": d,
            # total = 当天记了多少只（不与"有没有行情可评"挂钩）
            # 之前只给了 n，前端把它当"记了几只"显示，于是出现
            # 「记了 101 只 / 其中能买 117 只」这种自相矛盾的行 —— 两个口径混在一起了。
            "total": int(o.get("hit_count") or 0) + len(o.get("watch") or []),
            "n": len(allrows) if not partial else len(t_hit) + len(t_watch),
            "hit": len(rv["rows"] or []),
            # 能买（进总账）
            "hit_n": hs["n"] if not partial else ths["n"],
            "hit_avg": hs["avg"] if not partial else ths["avg"],
            "hit_win": hs["win"] if not partial else ths["win"],
            # 值得买（只看不进总账）
            "watch_n": ws["n"] if not partial else tws["n"],
            "watch_avg": ws["avg"] if not partial else tws["avg"],
            "watch_win": ws["win"] if not partial else tws["win"],
            # 兼容旧字段：一律按「能买」口径，别再让两批混算
            "avg": hs["avg"] if not partial else ths["avg"],
            "win_rate": hs["win"] if not partial else ths["win"],
            "days": (hitrows or watchrows)[0]["days"] if not partial else 0,
            # 这一天还没走完（当天选、当天回看）：数字是"尾盘→收盘"，不是多日走势
            "partial": partial,
            "price_at": rv.get("price_at") if partial else None,
        })
        # 总账只累加能买：这批票才代表"规则的信号"（当天的 partial 行不进）
        total.extend(hitrows)
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
    return {"days": per_day, "sum": s, "waiting": waiting,
            "note": "" if total else "还没有可以回看的记录 —— 至少要有一天选出了票，并且之后有收盘价"}
