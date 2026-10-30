# -*- coding: utf-8 -*-
"""市场状态：判断当前环境适不适合「低价超跌反转」这套玩法

为什么要有这一块
----------------
2022-06~2026-10 的 165 笔回测显示，这套策略赚钱和亏钱的分水岭**不在个股，
而在大盘所处的位置**：

    指数在 MA20 下方超过 1%（真弱势）：60 笔  胜率 52%  均 +1.51%
    指数在 MA20 上方或贴近        ：69 笔  胜率 25%  均 -1.27%

因为它是**超跌反转**，赚的是恐慌盘砸出来的错杀价。大盘真弱的时候，
错杀才成片出现、反弹才有空间；大盘已经站上均线、情绪转暖时，
超跌股反而是没人要的品种，买进去就是接盘——止损单反复打，把本金磨掉。

量能（成交量放大/缩小）反而**不是**有效判据：按量能比（20 日均量/120 日均量）
分组，组间收益差不到 1 个百分点，没有分辨力。真正的判据是**指数相对自身均线
的位置**。这一点和直觉相反（直觉是"放量牛市跑输"），但数据就是这么显示的。

用法
----
    ms = market_state.state()      # 取最新交易日的状态
    if not market_state.allow(params):   # 市场状态不匹配，暂停买入
        ...

阈值来自历史拟合（vs20 < -1%），不是物理常数；界面会把 vs20 的实际值显示出来，
让你能自己判断当前该不该信它。
"""
import threading
import time

# metrics() 会被回测的 10 个线程同时调用（每只票都要逐日判市场状态）。
# 没有锁时，冷启动那一次会各自重建一遍：一边建一边有人读到半成品，
# 表现为「同一组参数连跑两次，交易笔数不一样」（实测 13 笔 / 14 笔）。
# 加锁后只有第一个线程真正构建，其余等它建完直接用。
_METRICS_LOCK = threading.Lock()

from . import datasource as ds

_MEM = {"at": 0.0, "data": None, "metrics": None}
TTL = 30 * 60          # 指数日线半小时内不重拉


def index_daily():
    """上证指数日线（open/close/high/low/volume），进程内缓存半小时"""
    now = time.time()
    if _MEM["data"] is not None and now - _MEM["at"] < TTL:
        return _MEM["data"]
    df = ds.index_daily("sh000001")
    _MEM["data"] = df
    _MEM["at"] = now
    _MEM["metrics"] = None
    return df


def metrics():
    """每个交易日的市场状态指标（从第 120 根起，因为要 120 日均量）"""
    index_daily()
    got = _MEM["metrics"]
    if got is not None:
        return got
    # 双检锁：多数情况走上面那条快路径，只有冷启动会进临界区
    with _METRICS_LOCK:
        if _MEM["metrics"] is not None:
            return _MEM["metrics"]
        df = _MEM["data"]
        out = {}
        dates = df["date"].astype(str).str.slice(0, 10).tolist()
        closes = df["close"].astype(float).tolist()
        vols = [float(v or 0) for v in df["volume"].tolist()]
        for i in range(120, len(dates)):
            ma20 = sum(closes[i-19:i+1]) / 20
            ma60 = sum(closes[i-59:i+1]) / 60
            v20 = sum(vols[i-19:i+1]) / 20
            v120 = sum(vols[i-119:i+1]) / 120
            out[dates[i]] = {
                "vs20": (closes[i] / ma20 - 1) * 100 if ma20 else 0.0,
                "vs60": (closes[i] / ma60 - 1) * 100 if ma60 else 0.0,
                "ret20": (closes[i] / closes[i-20] - 1) * 100 if closes[i-20] else 0.0,
                "volr": (v20 / v120) if v120 else 1.0,
                "close": closes[i],
            }
        _MEM["metrics"] = out
        return out


def state(pct: float | None = None) -> dict:
    """最新交易日的市场状态。返回 {date, vs20, vs60, ret20, volr, mode, note}

    pct 是放行阈值（负几个百分点）。mode 必须按**同一个 pct** 判定，
    否则会出现"界面显示适合买入、实际被拦下"的自相矛盾：
    比如阈值调到 2% 而 vs20 是 -1.5% 时，按写死的 -1% 会标成 weak（绿），
    但 allow() 用 -2% 判，结果是拒绝。
    """
    p = 1.0 if pct is None else max(0.0, float(pct))
    m = metrics()
    if not m:
        return {"date": "", "vs20": 0.0, "vs60": 0.0, "ret20": 0.0, "volr": 1.0,
                "mode": "unknown", "note": "取不到指数数据，无法判断市场状态", "gate_pct": p}
    date = sorted(m)[-1]
    s = dict(m[date])
    s["date"] = date
    s["gate_pct"] = p
    s["mode"] = "weak" if s["vs20"] < -p else ("strong" if s["vs20"] > p else "mid")
    # 只给「位置 + 放不放行」两个事实。以前每条后面都跟一句解释性的判断
    # （"超跌反转的主场""买进去容易变接盘"），但放不放行本来就由程序执行了，
    # 用户看到数字和结论就够，多余的解释只会让状态条变长、还要花时间读。
    if s["mode"] == "weak":
        s["note"] = f"MA20 下方 {abs(s['vs20']):.1f}% · 放行"
    elif s["mode"] == "strong":
        s["note"] = f"MA20 上方 {s['vs20']:.1f}% · 不放行"
    else:
        s["note"] = f"贴着 MA20（{s['vs20']:+.1f}%）· 不放行"
    return s


def gate_on(params: dict | None = None) -> bool:
    """开关是否打开。

    不能直接 bool()：参数可能是从 JSON / 表单进来的字符串，
    bool("false") 是 True —— 用户明明关了开关，程序当成开着。
    """
    v = (params or {}).get("market_gate", True)
    if isinstance(v, bool):
        return v
    if v is None:
        return True
    return str(v).strip().lower() not in ("0", "false", "off", "no", "")


def gate_pct(params: dict | None = None) -> float:
    """放行阈值（负几个百分点）。

    这里**不能写 `... or 1.0`**：用户把阈值调到 0（"只要大盘在均线下方就买"）
    时 0 是假值，会被 or 吞成 1.0 —— 参数页的说明就变成了谎话。
    """
    v = (params or {}).get("market_gate_pct", 1.0)
    try:
        return max(0.0, float(v))
    except Exception:
        return 1.0


def allow(params: dict | None = None, st: dict | None = None) -> bool:
    """市场状态是否放行买入。params.market_gate=False 时永远放行。"""
    if not gate_on(params):
        return True
    if st is None:
        try:
            st = state(gate_pct(params))
        except Exception:
            return True
    if st.get("mode") == "unknown":
        return True
    return float(st.get("vs20", 0.0)) < -gate_pct(params)


def allow_on(date: str, params: dict | None = None) -> bool:
    """某一天的市场状态是否放行（回测逐日判定用；查不到当天就放行）"""
    if not gate_on(params):
        return True
    try:
        st = metrics().get(str(date)[:10])
    except Exception:
        return True
    if not st:
        return True
    return float(st.get("vs20", 0.0)) < -gate_pct(params)


def why(params: dict | None = None, st: dict | None = None) -> str:
    """被 gate 拦下时，告诉用户一句人话"""
    pct = gate_pct(params)
    try:
        st = st or state(pct)
    except Exception:
        return ""
    return (f"市场状态不匹配：大盘相对 MA20 是 {st.get('vs20', 0):+.1f}%，"
            f"要求低于 -{pct:.1f}%（指数真弱时超跌反转才有效）。"
            f"下面这批是本来会选中的，先放进观察池。")
