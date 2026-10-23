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
    return _covers(df, _want_date())


def _covers(df, want: str) -> bool:
    """缓存最后一根的日期 >= want？判断不了就当它还行，交给上层兜底。"""
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
        return s >= want
    except Exception:
        return True


def _daily_want_date() -> str:
    """日线缓存"应该覆盖到"的日期 —— 盘中要放宽到上一个交易日。

    新浪的日线在盘中**不返回当天那一根**（今天这根要收盘后才吐出来）。
    所以盘中拿"今天"去卡日线缓存，永远比不过：每一只票、每一次扫描都会重拉一遍，
    而重拉回来的还是同一份（最后一根是昨天）的数据。全市场一圈就是 4900 次白跑的请求，
    实测每只 318ms，光这一项就占掉扫描时间的四分之一。
    今天的价格另有来源（实时行情 rt + 分钟线），日线只负责历史结构（筹码、位置、趋势），
    因此盘中口径放宽到"上一个交易日"是等价的，不是妥协。
    """
    if _in_session() and _now_hm() >= "09:35":
        prev = (_dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            return ext.last_trade_day(prev) or prev
        except Exception:
            return prev
    return _want_date()


# ---------------------------------------------------------------- 文件操作
def _p(name: str) -> Path:
    return CACHE_DIR / name


def _fresh(path: Path, ttl: int) -> bool:
    try:
        return path.exists() and (time.time() - path.stat().st_mtime) < ttl
    except OSError:
        return False


def _dump(obj, path: Path):
    # 缓存只是加速用：磁盘满了 / 目录无权限（安卓私有目录被清）也不能把整次选股带崩
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(obj, f, protocol=4)
        tmp.replace(path)
    except (OSError, pickle.PickleError, RecursionError):
        pass


def _load(path: Path):
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError, ValueError):
        raise


# ---------------------------------------------------------------- 股票列表
def get_list(force=False):
    p = _p("stock_list.pkl")
    if not force and _fresh(p, LIST_TTL):
        try:
            df = _load(p)
            if df is not None and len(df) >= 1000:
                return df
        except Exception:
            pass
    try:
        df = ds.stock_list()
    except Exception:
        # 拉不到完整的就用旧快照顶着：一份两小时前的全市场名单，
        # 也远好过"只有 100 只"的半截数据（那会让池子直接变 0 只）
        if p.exists():
            try:
                old = _load(p)
                if old is not None and len(old) >= 1000:
                    return old
            except Exception:
                pass
        raise
    _dump(df, p)
    return df


# ---------------------------------------------------------------- 日线
def get_daily_cached(code, count=320):
    """只读盘上的日线缓存，绝不联网。盘上没有就返回 None。

    给「回看历史」这类场景用：它只需要选出来那天到最近一个收盘日的价格，
    今天这根还没收盘，追不追都不影响结论。而盘中 get_daily 会因为
    "缓存最后一根不是今天"判定过期，每只票都重新联网抓一次，
    回看一页几十只票要等 40 秒。宁可用旧一天的收盘价，也别让人干等。
    """
    code = ds.norm(code)
    p = _p(f"d_{code}.pkl")
    try:
        if not p.exists():
            return None
        df = _load(p)
        if df is None or len(df) < min(count, 60):
            return None
        return df
    except Exception:
        return None


def get_daily(code, count=320, force=False):
    code = ds.norm(code)
    p = _p(f"d_{code}.pkl")
    if not force and _fresh(p, DAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if len(df) >= min(count, 60) and _covers(df, _daily_want_date()):
                return df
            # 缓存连"上一个交易日"都没覆盖到 → 确实缺数据，重新取
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


def get_kline(code, period: str = "day", count: int = 640, force=False):
    """日 / 周 / 月前复权 K 线（详情页画图用，不走 5 分钟线那套均价策略的数据）。

    缓存键带周期号：kd_600519.pkl / kw_600519.pkl / km_600519.pkl。
    有效期沿用日线那套（盘中 6 小时 / 非交易时段 6 小时）—— 画图不需要逐笔精确，
    但最后一根必须覆盖到"此刻应有的最新交易日"，否则今天的新 K 线就画不出来。
    """
    code = ds.norm(code)
    period = period if period in ("day", "week", "month") else "day"
    p = _p(f"k{period[0]}_{code}.pkl")
    if not force and _fresh(p, DAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if len(df) >= 30 and _today_ok(df):
                return df
        except Exception:
            pass
    try:
        df = ds.tencent_kline(code, period, count)
    except Exception:
        if p.exists():
            return _load(p)            # 拉不到就用旧缓存兜底，宁可晚一天也别画不出图
        if period == "day":
            return get_daily(code, min(int(count), 300))   # 腾讯挂了退回新浪日线
        raise
    _dump(df, p)
    return df


def get_daily_long(code, count=1023, force=False):
    """长历史**前复权**日线（最多 1023 根 ≈ 4.2 年），只给回测和模拟账户用。

    和 get_daily 分开两条缓存（dl_ vs d_）的理由：
      * 选股要的是不复权（要和实盘 14:30 的价对上），一根都不许动；
      * 回测跨好几年，必须前复权，否则一次 10 送 4 就在账上多出 -29%。
    混用一个缓存键会互相覆盖，所以各存各的。
    """
    code = ds.norm(code)
    p = _p(f"dl_{code}.pkl")
    if not force and _fresh(p, DAY_TTL if _in_session() else IDLE_TTL):
        try:
            df = _load(p)
            if len(df) >= 200 and _covers(df, _daily_want_date()):
                return df
        except Exception:
            pass
    try:
        df = ds.daily_long(code, count)
    except Exception:
        if p.exists():
            return _load(p)          # 取不到就用旧缓存，宁可旧一天也别让回测跑不动
        raise
    _dump(df, p)
    return df


def get_kline_cached(code, period: str = "day", count: int = 640):
    """只读盘上的前复权 K 线缓存，绝不联网。盘上没有就返回 None。

    给「回看历史涨跌」用：算跨期收益必须用前复权价，否则中途送转分红会把
    涨跌幅算成暴跌（10 送 3 就是 -23%）。但回看一页要看上百只票，
    不能让每只都去联网 —— 先由 memory 那边并发预热，这里只负责读。
    """
    code = ds.norm(code)
    period = period if period in ("day", "week", "month") else "day"
    p = _p(f"k{period[0]}_{code}.pkl")
    try:
        if not p.exists():
            return None
        df = _load(p)
        if df is None or len(df) < 30:
            return None
        return df
    except Exception:
        return None


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


_CI_CACHE = {"at": 0.0, "val": None}


def cache_info() -> dict:
    """缓存目录概况。

    这里以前对每个 .pkl 各 stat 两遍（算总大小、再算最新修改日），
    一万五千个文件要 10 秒；而 /api/config 每次请求都调它，
    手机打开时会卡在「正在读取…」。现在只 stat 一遍并缓存 3 秒。
    """
    now = time.time()
    if _CI_CACHE["val"] is not None and now - _CI_CACHE["at"] < 3.0:
        return dict(_CI_CACHE["val"])
    try:
        files = list(CACHE_DIR.glob("*.pkl"))
    except OSError:
        files = []
    size = 0
    newest = 0.0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        size += st.st_size
        if st.st_mtime > newest:
            newest = st.st_mtime
    # 用最新那个缓存文件的修改日期当"数据更新到"；界面原来显示的是本机日期，
    # 周末/节假日打开会显示当天，让人误以为行情是新的
    last = ""
    if newest > 0:
        try:
            last = _dt.fromtimestamp(newest).strftime("%Y-%m-%d")
        except Exception:
            last = ""
    val = {"files": len(files), "size_mb": round(size / 1048576, 2),
           "last_update": last, "dir": str(CACHE_DIR)}
    _CI_CACHE["at"] = now
    _CI_CACHE["val"] = dict(val)
    return val
