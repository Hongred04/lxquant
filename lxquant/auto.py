# -*- coding: utf-8 -*-
"""
自动选股调度器 —— 打开软件就开始干活，不用手动点。

时间轴（A 股，周一至周五）：
    09:35  开盘后扫一遍，把候选池备好（含 14:00 前的竞价、开盘量能）
    09:35 ~ 15:00  每 auto_every 秒自动重扫一次（默认 5 分钟）
    14:00  preview_at 之后（试算窗口）：今天用"截至现在"的价与均价线挑出要盯的
    14:50  尾盘终极扫：给出可直接下单的名单
    15:00  收盘后停手

安全约束：
  · 非交易日（adata 交易日历 / 随包 calendar.csv）不跑
  · 同一时刻只允许一个扫描任务，避免把接口打爆
  · 用户手动点了「立即选股」时自动模式让路
  · 休息时段（09:35-15:00 之外）不占网络，只有在你打开页面时才会读上次结果
"""
import threading
import time
from datetime import datetime

from . import config, screener

_STATE = {
    "running": False,        # 调度线程是否在跑
    "busy": False,           # 当前是否有自动扫描在执行
    "last_run": None,        # 上次自动扫描的时间
    "last_reason": "",
    "next_run": None,
    "runs": 0,
    "final_done": "",        # 已完成尾盘终极扫的日期
    "hold": False,           # 用户手动运行中，自动模式暂停
    "last_error": "",
}
_LOCK = threading.Lock()
_THREAD = None


def _hm(t: str) -> int:
    """'14:30' -> 1430"""
    try:
        a, b = str(t).split(":")[:2]
        return int(a) * 100 + int(b)
    except Exception:
        return 0


def _now_hm(now: datetime) -> int:
    return now.hour * 100 + now.minute


def in_hours(cfg_params: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    rng = str(cfg_params.get("auto_hours") or "09:35-15:00")
    try:
        a, b = rng.split("-")
        return _hm(a) <= _now_hm(now) <= _hm(b)
    except Exception:
        return 9 * 100 + 35 <= _now_hm(now) <= 15 * 100


def is_trade_day(now: datetime | None = None) -> bool:
    from . import extdata as ext
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    try:
        r = ext.is_trade_day(now.strftime("%Y-%m-%d"))
        return True if r is None else bool(r)   # 日历取不到就按"是"处理
    except Exception:
        return True


def _preview_at(params: dict, now: datetime) -> str | None:
    """下午 preview_at 之后、还没到 tail_from 时，返回试算时点，让今天用"截至现在"试算。"""
    tag = str(params.get("tail_from") or "14:30")
    pv = str(params.get("preview_at") or "").strip()
    if not pv or pv.lower() in ("off", "none", "0", "false") or tag == "close":
        return None
    if _hm(pv) <= 0:
        return None
    if _hm(pv) <= _now_hm(now) < _hm(tag):
        return pv
    return None


def _run_once(reason: str, store: bool = True, limit: int | None = None,
              late: bool = False) -> None:
    """跑一次自动选股，结果写进 server 的 _last_screen。

    limit：0 = 不受 auto_every 限制、必须真跑一次（尾盘终极扫用）；
           None / 其它数字 = 距上次不足 auto_every 就跳过（只刷新计时，不覆盖名单）。
    store：True 才覆盖已存下来的名单，False 只更新内存里的结果。
    late：收盘之后才补跑的（白天没开软件）。名单是用收盘价判定的，
          和 14:45 实盘那份不是一个口径，要如实标给用户看。
    """
    from . import server
    cfg = config.load_config()
    p = cfg["params"]
    now = datetime.now()
    every = int(p.get("auto_every", 300) or 0)
    with _LOCK:
        last = _STATE["last_run"]
    if limit is None and every > 0 and last and str(last)[:10] == now.strftime("%Y-%m-%d"):
        try:
            lt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if (now - lt).total_seconds() < every:
                # 离上次太近，这次不扫；把计时刷新一下，免得主循环每 5 秒醒一次
                with _LOCK:
                    _STATE["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
                return
        except Exception:
            pass
    lim = int(p.get("auto_limit", 600) or 600) if limit in (None, 0) else int(limit)
    mode = "balanced" if lim < 4000 else "all"
    pv = _preview_at(p, now)
    with _LOCK:
        _STATE["busy"] = True
        _STATE["last_reason"] = reason + (f"（尾盘前试算 @ {pv}）" if pv else "")
    try:
        j = server.new_job("auto")
        r = screener.run_screen(p, cfg["weights"], limit=lim, mode=mode,
                                progress=j.progress, preview_at=pv)
        r["auto"] = {"reason": reason, "at": now.strftime("%Y-%m-%d %H:%M:%S"),
                     "preview_at": pv, "limit": lim, "late": bool(late)}
        if store:
            server._last_screen["result"] = r
            try:
                server._write_screen_csv(r)
                server._save_last_screen(r)
            except Exception:
                pass
        # 选股记忆：自动选股也要记一笔。界面上写的是"自动的、手动的都算"，
        # 但以前只有手动点「立即选股」才走 memory.save_result，自动扫描全漏了 —
        # 结果记忆页里只有你偶尔手点的那几天，看起来像"软件很少选股"。
        # 试算（还没定型的名单）由 save_result 内部按 basis 挡掉，这里不用判断。
        if store:
            try:
                from . import memory
                memory.save_result(r)
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            _STATE["last_error"] = f"{type(e).__name__}: {e}"
            _STATE["busy"] = False
        return
    with _LOCK:
        _STATE["busy"] = False
    # 结果写进去了，才算"跑过"；失败时不动 last_run，
    # 这样下一轮还是 due，会自动重试（配合 _fail 退避，不会疯狂重试）
    with _LOCK:
        _STATE["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
        _STATE["runs"] += 1
        _STATE["last_error"] = ""
        _STATE["last_reason"] = (reason + " · " + _hit_info(reason))[:120]


def _hit_info(reason: str) -> str:
    """把自动扫描的结果浓缩成一句话，失败时也能让用户看到原因。"""
    try:
        from . import server
        r = server._last_screen.get("result") or {}
        st = r.get("stats") or {}
        if st:
            msg = (f"扫了 {st.get('scanned', 0)} 只，选出 {st.get('hit', 0)} 只"
                   f" · 用时 {st.get('elapsed', 0)} 秒")
            # 市场状态不匹配时，「选出 0 只」会让人以为是不符合条件的票太少，
            # 其实是主动停手 —— 必须说清楚，否则会反复点「立即选股」找票
            if st.get("gated"):
                ms = st.get("market") or {}
                try:
                    v = float(ms.get("vs20"))
                    msg += f"（大盘 {v:+.1f}% 对 MA20，市场状态不匹配，暂停买入）"
                except Exception:
                    msg += "（市场状态不匹配，暂停买入）"
            return msg
        return "扫描完成，但没有拿到数据"
    except Exception:  # noqa: BLE001
        return ""


_WATCH_LAST = [0.0]


def _watch_tick(now) -> None:
    """交易时段里每 3 分钟把自选股过一遍（买点卖点提醒靠它推进）。

    出错只打一行，绝不能让自选股的异常把整个自动选股循环带挂。
    """
    try:
        if not _STATE["running"]:
            return
        if time.time() - _WATCH_LAST[0] < 180:
            return
        from . import watchlist
        if not watchlist.list_all():
            return
        # 自选股用的是用户自己"自动选股时段"以外的口径：只要在工作日和盘中就行，
        # 因为他可能把自动选股调成了 10:00-11:00，但持仓跌破止损 14:30 一样得告诉他
        if not is_trade_day(now) or not (9 * 100 + 30 <= _now_hm(now) <= 15 * 100):
            return
        _WATCH_LAST[0] = time.time()
        watchlist.check()
    except Exception as e:  # noqa: BLE001
        print(f"[自选股] 提醒检查失败：{type(e).__name__}: {e}")


def _has_final_today(today: str) -> bool:
    """当天是否已经跑过定型扫（跑过就算，不管选出几只）。

    用来兜住"服务重启后 _STATE['final_done'] 丢失"的情况：
    没有这道检查，晚上重开软件会再跑一次全市场扫描（白烧半分多钟的网络和 CPU）。

    两个来源都要看：
      · 记忆文件 —— 有票的日子在这里；
      · last_screen —— **空名单的日子**（一只没选出）按设计不写记忆文件，
        但它确实已经跑过了。只看记忆的话，晚上重启会反复补扫空名单的日子。
    """
    try:
        from . import memory
        o = memory.get(today) or {}
        if o.get("basis") == "tail" and (o.get("items") or o.get("watch")):
            return True
    except Exception:
        pass
    try:
        from . import server
        r = server._load_last_screen() or {}
        if (str(r.get("generated_at") or "")[:10] == today
                and (r.get("stats") or {}).get("basis") == "tail"):
            return True
    except Exception:
        pass
    return False


def _final_reason(p: dict, now: datetime, done_today: bool) -> str:
    """今天该不该跑尾盘扫；返回原因（空串 = 不跑）。

    纯函数，方便单测（不碰时钟以外的状态）。

    为什么不再要求"必须在 09:35-15:00 窗口内"：
      以前这段判断在 in_hours 之内，15:00 一到主循环就 continue，
      于是**白天没开软件的日子，晚上打开只能看到昨天** —— 当天没有任何记录。
      而记忆页、回测样本全靠这个记录累积，少一天就少一天。
      现在放宽到"当天未定型 + 已过 auto_final"，收盘后、甚至半夜打开也会补一份，
      标注为「收盘后补扫」：名单是按收盘价判定的，买入价仍锚定 14:45 的分时
      （盘后分时数据还在），两者口径差要在界面上说清楚。
    """
    if not bool(p.get("auto_final_enabled", True)):
        return ""
    # 总开关关掉 = 用户明确不希望软件自己扫。补扫也不该越过这条线，
    # 否则"关了自动选股，半夜还在偷偷跑"会让人摸不着头脑。
    if not bool(p.get("auto_scan", True)):
        return ""
    if not is_trade_day(now):
        return ""
    final_at = str(p.get("auto_final") or "14:50")
    if _hm(final_at) <= 0 or _now_hm(now) < _hm(final_at):
        return ""
    if done_today:
        return ""
    # 15:05 之前仍在"当天尾盘"的意义上；之后就是补扫
    return "尾盘终极扫" if _now_hm(now) <= 15 * 100 + 5 else "收盘后补扫"


def _loop():
    """调度主循环：没到点就多睡，到点前后每 30 秒看一眼。"""
    time.sleep(4)          # 等服务起来
    _fail = 0              # 连续异常计数，用来做退避
    while _STATE["running"]:
        if _STATE["hold"] or _STATE["busy"]:
            # 用户在手动跑，先让路；这段时间不要碰 config / 日历 / 网络
            # 用户在手动跑全市场扫描，先让路；这段时间不要碰 config / 日历 / 网络
            if _STATE["busy"]:
                pass
            else:
                # 只是用户按了"暂停自动选股"：全市场别扫了，自选股还是要看
                _watch_tick(datetime.now())
            time.sleep(10)
            continue
        wait = 30
        try:
            cfg = config.load_config()
            p = cfg["params"]
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # ★ 尾盘扫 / 收盘后补扫：放在时段判断之前。
            #   原来这段在 in_hours 之后，15:00 一过就永远到不了 ——
            #   白天没开软件的日子，晚上打开也补不上当天的名单。
            done = (_STATE["final_done"] == today) or _has_final_today(today)
            fin = _final_reason(p, now, done)
            if fin:
                with _LOCK:
                    _STATE["final_done"] = today
                    _STATE["next_run"] = None
                # limit=0：不受 auto_every 限制，必须真跑一次
                _run_once(fin, limit=0, late=(fin != "尾盘终极扫"))
                time.sleep(60)
                continue

            if not p.get("auto_scan", True) or not is_trade_day(now) or not in_hours(p, now):
                with _LOCK:
                    _STATE["next_run"] = None
                # 自选股那几只不受"自动选股总开关"影响：用户亲手加的票，
                # 关掉自动选股只是不扫全市场了，不代表不用看他的持仓
                _watch_tick(now)
                time.sleep(30)
                continue

            every = int(p.get("auto_every", 300) or 0)

            last = _STATE["last_run"]
            # 当天的"开盘首扫 / 尾盘确认"跑过就行；跨天自动失效，否则第二天白天
            # 一整天都不会再主动扫（只剩 14:50 那一次）
            fresh = bool(last) and str(last)[:10] == today
            due = True
            if every > 0 and fresh:
                try:
                    lt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                    due = (now - lt).total_seconds() >= every
                except Exception:
                    due = True
            # 下次时间只在前端轮询时才用得上，没到点就别刷着改
            if due:
                with _LOCK:
                    _STATE["next_run"] = None
                # 今天还没跑过（含隔了一夜）→ 开盘首扫；否则是盘中例行重扫
                reason = "盘中重扫" if fresh else "开盘首扫"
                if 14 * 100 + 28 <= _now_hm(now) <= 14 * 100 + 52:
                    reason = "尾盘确认"
                # 开盘首扫 / 尾盘确认 必须真跑（limit=0 跳过"太近了"的判断），
                # 其它例行重扫交给 _run_once 自己看距上次够不够 auto_every
                _run_once(reason, limit=0 if reason != "盘中重扫" else None)
                continue
            # 自选股买点卖点：每 3 分钟看一次（watchlist.check 自己也有 3 分钟节流）
            _watch_tick(now)
            nxt = now.timestamp() + every if every > 0 else None
            with _LOCK:
                _STATE["next_run"] = (datetime.fromtimestamp(nxt).strftime("%H:%M")
                                      if nxt else None)
            # 离下次还有几十秒，睡足一点，别每 30 秒空转去读配置
            if nxt:
                wait = max(5, min(30, int(nxt - now.timestamp()) + 1))
            _fail = 0
        except Exception as e:  # noqa: BLE001
            # 以前这里静默吞掉，出错时前端完全看不到；记下来并退避
            _fail += 1
            with _LOCK:
                _STATE["last_error"] = f"{type(e).__name__}: {e}"
            wait = min(300, 30 * _fail)
        time.sleep(wait)


def start():
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STATE["running"] = True
    _THREAD = threading.Thread(target=_loop, daemon=True, name="lxquant-auto")
    _THREAD.start()


def hold(on: bool):
    """用户手动操作时让自动模式让路。"""
    with _LOCK:
        _STATE["hold"] = bool(on)


def refresh():
    """参数改了就马上重算一次排期，不用等主循环那 30 秒的睡眠。"""
    try:
        p = config.load_config()["params"]
    except Exception:
        return
    now = datetime.now()
    active = bool(p.get("auto_scan", True)) and is_trade_day(now) and in_hours(p, now)
    with _LOCK:
        if not active or not _STATE["last_run"]:
            _STATE["next_run"] = None
            return
        every = int(p.get("auto_every", 300) or 0)
        if every <= 0:
            _STATE["next_run"] = None
            return
        try:
            lt = datetime.strptime(_STATE["last_run"], "%Y-%m-%d %H:%M:%S")
            # 上次是昨天（或更早）就当作"已经到期"，让主循环尽快扫一次
            rest = 0 if lt.date() != now.date() else every - (now - lt).total_seconds()
        except Exception:
            _STATE["next_run"] = None
            return
        _STATE["next_run"] = (datetime.fromtimestamp(now.timestamp() + rest).strftime("%H:%M")
                              if rest > 0 else None)


def status() -> dict:
    cfg = config.load_config()["params"]
    now = datetime.now()
    with _LOCK:
        st = {
            "running": bool(_STATE["running"] and _THREAD and _THREAD.is_alive()),
            "busy": _STATE["busy"],
            "hold": _STATE["hold"],
            "last_run": _STATE["last_run"],
            "last_reason": _STATE["last_reason"],
            "next_run": _STATE["next_run"],
            "runs": _STATE["runs"],
            "last_error": _STATE["last_error"],
        }
    return {
        "enabled": bool(cfg.get("auto_scan", True)),
        **st,
        "trade_day": is_trade_day(now),
        "in_hours": in_hours(cfg, now),
        "limit": int(cfg.get("auto_limit", 600) or 600),
        "every": int(cfg.get("auto_every", 300) or 0),
        "hours": str(cfg.get("auto_hours") or "09:35-15:00"),
        "final_at": str(cfg.get("auto_final") or "14:50"),
        "final_enabled": bool(cfg.get("auto_final_enabled", True)),
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
