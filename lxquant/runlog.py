# -*- coding: utf-8 -*-
"""运行日志：把服务在干什么、哪里出错，按天写到 data/logs/。

为什么要有这个
--------------
2026-10-30 早上 09:58 之后服务停了，查不出任何原因 —— 是正常关闭、崩溃、
还是被谁 kill 掉，全靠猜。同一天还遇到腾讯接口整片 501、回测结果不可复现，
如果当时有行式日志，定位时间能从一个小时压到两分钟。

设计取舍
--------
* **一行一条**，固定格式 ``时间 级别 事件 key=value ...``：
  grep / awk 直接能用，不需要解析 JSON；
* 按天切文件、保留 14 天，不让它无限长；
* 写失败绝不抛异常 —— 磁盘满、目录没权限，不能把选股带崩；
* 只记"做了什么、结果如何"，不记行情明细，避免文件暴涨；
* 高频事件（每只票都可能触发的降级）用 ``log_once`` 节流，
  只记状态变化，不刷屏。
"""
from __future__ import annotations

import os
import threading
import time
import traceback

from .config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
KEEP_DAYS = 14                 # 保留最近 14 天，够回溯两个交易周
_LOCK = threading.Lock()
_INITED = [False]
_LAST_ONCE = {}                # log_once 的节流表：{key: 上次记录的时间戳}


def _path(day: str | None = None):
    d = day or time.strftime("%Y-%m-%d")
    return LOG_DIR / f"run-{d}.log"


def _clean(v) -> str:
    """字段值压成单行：换行/制表符会把"一行一条"的格式打散。"""
    s = str(v)
    for ch in ("\r", "\n", "\t"):
        s = s.replace(ch, " ")
    return s[:300]


def log(level: str, event: str, **fields):
    """写一条日志。任何失败都静默 —— 日志坏了不能影响主流程。"""
    try:
        parts = [time.strftime("%Y-%m-%d %H:%M:%S"), level.upper()[:5].ljust(5), event]
        for k, v in fields.items():
            if v is None:
                continue
            parts.append(f"{k}={_clean(v)}")
        line = " ".join(parts) + "\n"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with open(_path(), "a", encoding="utf-8", newline="") as f:
                f.write(line)
            if not _INITED[0]:
                _INITED[0] = True
                _prune_locked()
    except Exception:
        pass


def log_once(key: str, event: str, ttl: float = 60.0, level: str = "INFO", **fields):
    """同类事件在 ttl 秒内只记一次。

    数据源降级、单只票取数失败这类事，一次扫描里可能重复几百遍 ——
    全记下来会把日志撑爆，真正有用的信息反而被埋掉。这里只记"第一次/状态变化"。
    """
    now = time.time()
    if now - _LAST_ONCE.get(key, 0.0) < ttl:
        return
    _LAST_ONCE[key] = now
    log(level, event, **fields)


def info(event: str, **fields):
    log("INFO", event, **fields)


def warn(event: str, **fields):
    log("WARN", event, **fields)


def error(event: str, **fields):
    log("ERROR", event, **fields)


def exc(event: str, **fields):
    """记一次异常，附完整堆栈（压成一行，保留最关键的帧）。"""
    tb = traceback.format_exc()
    # 只留最后 5 帧：完整堆栈动辄几十行，真正有用的通常在最里面
    lines = [x.strip() for x in tb.strip().splitlines() if x.strip()]
    brief = " | ".join(lines[-5:])
    log("ERROR", event, trace=tb[-1200:].replace("\n", " ⏎ "), **fields)
    return brief


def _prune_locked():
    """删掉超过 KEEP_DAYS 天的日志。调用方必须已持有 _LOCK。"""
    try:
        cutoff = time.time() - KEEP_DAYS * 86400
        for f in LOG_DIR.glob("run-*.log"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def tail(n: int = 120, day: str | None = None) -> list:
    """读最近 n 行（给界面/接口用）。读不到就返回空表，不抛异常。"""
    try:
        p = _path(day)
        if not p.exists():
            return []
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [x.rstrip("\n") for x in lines[-max(1, min(int(n), 2000)):]]
    except Exception:
        return []


def recent_errors(n: int = 20, days: int = 2) -> list:
    """最近几天里的 ERROR 行（界面只展示异常，不刷正常流水）。"""
    out = []
    try:
        for i in range(max(1, days)):
            day = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            for line in tail(2000, day):
                if " ERROR " in line:
                    out.append(line)
    except Exception:
        pass
    return out[-n:]


def install_hooks():
    """把未捕获异常也写进日志。

    两个钩子缺一不可：主线程崩了走 excepthook，后台线程（自动调度、
    扫描任务）崩了走 threading.excepthook —— 而自动扫描恰恰跑在线程里，
    没有第二个钩子，线程里炸了就等于什么都没发生。
    """
    try:
        import sys
        import threading as _th

        def _hook(exc_type, exc, tb):
            try:
                log("ERROR", "uncaught",
                    where=f"{exc_type.__name__}",
                    err=str(exc)[:200],
                    trace="".join(traceback.format_exception(exc_type, exc, tb))[-1200:]
                    .replace("\n", " ⏎ "))
            except Exception:
                pass
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = _hook

        def _thook(args):
            try:
                log("ERROR", "uncaught.thread",
                    thread=getattr(args.thread, "name", "?"),
                    where=getattr(args.exc_type, "__name__", "?"),
                    err=str(getattr(args, "exc_value", ""))[:200],
                    trace="".join(traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback))[-1200:]
                    .replace("\n", " ⏎ "))
            except Exception:
                pass

        _th.excepthook = _thook
    except Exception:
        pass


def status() -> dict:
    """给接口/界面看的概况：目录、今天多少条、最近一次异常。"""
    try:
        p = _path()
        n = 0
        if p.exists():
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
        errs = recent_errors(1)
        # 字段名避开 "lines"：接口里既要给行数又要给内容，
        # 同名会让后写的 tail() 结果把行数覆盖掉（第一版就踩了）。
        return {"ok": True, "dir": str(LOG_DIR), "file": str(p),
                "line_count": n, "keep_days": KEEP_DAYS,
                "last_error": errs[-1] if errs else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}
