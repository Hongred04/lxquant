# -*- coding: utf-8 -*-
"""本地磁盘缓存：日线 / 分钟线 / 股票列表。带 TTL，避免重复请求。

缓存有效性判断（这里以前是个大坑）
-----------------------------------
原来 `_today_ok` 硬要求"缓存最后一根的日期 >= 今天"。问题是：
  * 周末/节假日打开软件，数据永远停在周五，于是**每一只票的缓存都被判成过期**，
    400 只要重拉 400 次，本该 0 秒的事情变成 20 秒；
  * 5 分钟线的 index 是时间戳，日线的 index 是 0,1,2…（RangeIndex），
    `str(df.index[-1])[:10]` 对日线取到的是 "299" 这种行号，比较永远为假 ——
    日线缓存等于**从来没有命中过**。
现在的规则：拿"最近一个应该已经有数据的交易日"去比，并且优先读 `date` 列。
再配合"非交易时段 TTL 放宽到 6 小时"，周末重复扫全市场几乎全是缓存命中。
"""
import json
import pickle
import time
from datetime import datetime as _dt
from datetime import timedelta
from pathlib import Path

from . import datasource as ds
from . import extdata as ext
from .config import CACHE_DIR

DAY_TTL = 6 * 3600          # 日线缓存 6 小时
INTRADAY_TTL = 5 * 60       # 分钟线缓存 5 分钟（盘中）
IDLE_TTL = 6 * 3600         # 非交易时段：数据根本不会变，没理由重拉
LIST_TTL = 5 * 60           # 股票列表 5 分钟

# 分钟线周期候选（从粗到细）。越粗的周期，一根 K 线覆盖的时间越长，
# 同样的 datalen 能覆盖更多交易日，响应体也更小 —— 见 datasource.kline_scale 的说明。
SCALES = (60, 30, 15, 5)

_WANT = [0.0, ""]           # _want_date 的 60 秒记忆，避免每只票都去查日历


# ---------------------------------------------------------------- 时间口径
def _now_hm() -> str:
    return _dt.now().strftime("%H:%M")


def _in_session() -> bool:
    """现在是不是交易时段（粗略：工作日 + 09:15~15:10，节假日靠日历兜一层）"""
    now = _dt.now()
    if now.weekday() >= 5:
        return False
    if not ("09:15" <= now.strftime("%H:%M") <= "15:10"):
        return False
    try:
        if ext.is_trade_day(now.strftime("%Y-%m-%d")) is False:
            return False
    except Exception:
        pass
    return True


def _want_date() -> str:
    """盘面上"此刻应该已经有数据"的最后日期。

    盘中 = 今天；开盘前 / 周末 / 节假日 = 最近一个交易日。
    这样周末打开软件，缓存只需覆盖到上周五就算新鲜，不用把 4000 只票全部重拉。
    """
    now = time.time()
    if _WANT[1] and now - _WANT[0] < 60:
        return _WANT[1]
    today = _dt.now().strftime("%Y-%m-%d")
    want = today
    try:
        td = ext.is_trade_day(today)          # None = 判断不了，按交易日处理
        if td is False:
            want = ext.last_trade_day(today) or today
        elif _now_hm() < "09:35":
            # 还没开盘 / 刚开盘，今天不可能有完整的 K 线，缓存到上一个交易日就算新鲜
            prev = ( _dt.now() - timedelta(days=1) ).strftime("%Y-%m-%d")
            want = ext.last_trade_day(prev) or want
    except Exception:
        pass
    _WANT[0], _WANT[1] = now, want
    return want


def _today_ok(df) -> bool:
    """缓存里的最后一根，是不是已经覆盖到"此刻应有的最新交易日"。

    优先读 date 列：日线的 index 是 RangeIndex，拿 index 去比日期是错的
    （这正是之前日线缓存从来不命中的原因）。
    """
    try:
        if df is None or not len(df):
            return False
        d = None
        for col in ("date", "time"):
            if col in getattr(df, "columns", ()):
                d = df[col].iloc[-1]
                break
        if d is None:
            d = df.index[-1]
        s = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        return s >= _want_date()
    except Exception:
        return True          # 判断不了就当它还行，交给上层兜底


# ---------------------------------------------------------------- 文件操作
def _p(name: str) -> Path:
    return CACHE_DIR / name


def _fresh(path: Path, ttl: int) -> bool:
    try:
        return path.exists() and (time.time() - path.stat().st_mtime) < ttl
    except OSError:
        return False


def _dump(obj, path: Path):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=4)
    tmp.replace(path)


def _load(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------- 股票列表
def get_list(force=False):
    p = _p("stock_list.pkl")
    if not force and _fresh(p, LIST_TTL):
        try:
            return _load(p)
        except Exception:
            pass
    df = ds.stock_list()
    _dump(df, p)
    return df


# ---------------------------------------------------------------- 日线
def get_daily(code, count=320, force=False):
    code = ds.norm(code)
    p = _p(f"d_{code}.pkl")
    if not force and _fresh(p, DAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if len(df) >= min(count, 60) and _today_ok(df):
                return df
            # 缓存是昨天以前的 → 不管 TTL 多新，今天的数据还没进来，重新取
        except Exception:
            pass
    try:
        df = ds.daily(code, count)
    except Exception:
        if p.exists():
            return _load(p)
        raise
    # 数据源刚开盘时可能还没吐出今天的 K 线，此时缓存日期仍然「旧」，
    # 下一轮就会重新取 —— 所以照存不误，日期检查在读取端完成
    _dump(df, p)
    return df


# ---------------------------------------------------------------- 分钟线
def pick_scale(tail_from: str = "14:30", preview_at: str | None = None) -> int:
    """挑一个"够用又最省"的分钟周期。

    原则：30 分钟线的收盘时刻是 10:00 10:30 11:00 11:30 13:30 14:00 14:30 15:00。
    只要需要截取的时刻（tail_from / preview_at）**正好落在一个收盘时刻上**，
    用 30 分钟线算出来的 VWAP 与 5 分钟线逐位相同，但数据量只有 1/6。
    落不上就退到 15 / 5 分钟，保证结果和 5 分钟线一致。
    """
    pts = []
    for v in (tail_from, preview_at):
        s = str(v or "").replace(":", "").strip()
        if s.isdigit() and len(s) >= 4:
            pts.append(int(s[:4]))
    if not pts:
        return 30                    # tail_from='close' 之类，全天口径随便挑最粗的
    for sc in SCALES:
        if all(_aligned(p, sc) for p in pts):
            return sc
    return 5


def _aligned(hhmm: int, scale: int) -> bool:
    """这个时刻是不是 scale 分钟线的"收盘时刻"（新浪的 K 线以收盘时刻标记）

    A 股一天分两段：09:30-11:30 与 13:00-15:00，各自从半场起点整点对齐。
    """
    for start, end in ((930, 1130), (1300, 1500)):
        if not (start <= hhmm <= end):
            continue
        if hhmm == end:
            return True
        mins = (hhmm // 100) * 60 + hhmm % 100 - (start // 100) * 60 - start % 100
        return mins > 0 and mins % scale == 0
    return False


def get_intraday(code, scale: int = 30, count: int = 200, force=False):
    """任意周期的分钟线（缓存键带周期号，不同周期互不覆盖）。

    全市场扫描走这里：30 分钟线 25 个交易日只有 200 根，响应体 28KB，
    比 5 分钟线的 144KB 轻一个数量级，解析也快得多。
    """
    code = ds.norm(code)
    scale = int(scale or 30)
    p = _p(f"k{scale}_{code}.pkl")
    if not force and _fresh(p, INTRADAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if _today_ok(df):
                return df
            # 缓存停在昨天 → 今天开盘了还没刷新，不能拿去算今天的均价线
        except Exception:
            pass
    if scale == 5:
        return get_5min(code, 1023, force)
    try:
        df = ds.kline_scale(code, scale, count)
    except Exception:
        # 该周期取不到就退回 5 分钟线 —— 结果一样，只是重一点
        if scale != 5:
            return get_5min(code, 1023, force)
        raise
    _dump(df, p)
    return df


def get_5min(code, count=1023, force=False):
    """
    5 分钟线。速度快：新浪 1023 根（约 22 个交易日）；若接口抽风自动降级为腾讯 m5 320 根。
    注意：新浪单次请求较大，并发过高容易触发限流，这是失败的常见原因。

    详情页的"近 5 日分时"用这个（需要细颗粒度）；全市场扫描用 get_intraday。
    """
    code = ds.norm(code)
    p = _p(f"k5_{code}.pkl")
    if not force and _fresh(p, INTRADAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if _today_ok(df):
                return df
            # 缓存停在昨天 → 今天开盘了还没刷新，不能拿去算今天的均价线
        except Exception:
            pass
    try:
        df = ds.kline5(code, count, "sina")
    except Exception:
        try:
            df = ds.kline5(code, 320, "tencent")
        except Exception:
            if p.exists():
                return _load(p)          # 用过期缓存兜底，宁可旧数据也不失败
            raise
    _dump(df, p)
    return df


def clear_cache(kind: str | None = None) -> int:
    n = 0
    for f in CACHE_DIR.glob("*.pkl"):
        if kind and not f.name.startswith(kind):
            continue
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


def cache_info() -> dict:
    files = list(CACHE_DIR.glob("*.pkl"))
    size = sum(f.stat().st_size for f in files)
    # 用最新那个缓存文件的修改日期当"数据更新到"；界面原来显示的是本机日期，
    # 周末/节假日打开会显示当天，让人误以为行情是新的
    last = ""
    try:
        if files:
            last = _dt.fromtimestamp(max(f.stat().st_mtime for f in files)).strftime("%Y-%m-%d")
    except Exception:
        last = ""
    return {"files": len(files), "size_mb": round(size / 1048576, 2),
            "last_update": last, "dir": str(CACHE_DIR)}
