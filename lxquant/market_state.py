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
import time

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


def state() -> dict:
    """最新交易日的市场状态。返回 {date, vs20, vs60, ret20, volr, mode, note}"""
    m = metrics()
    if not m:
        return {"date": "", "vs20": 0.0, "vs60": 0.0, "ret20": 0.0, "volr": 1.0,
                "mode": "unknown", "note": "取不到指数数据，无法判断市场状态"}
    date = sorted(m)[-1]
    s = dict(m[date])
    s["date"] = date
    s["mode"] = "weak" if s["vs20"] < -1.0 else ("strong" if s["vs20"] > 1.0 else "mid")
    if s["mode"] == "weak":
        s["note"] = (f"大盘在 MA20 下方 {abs(s['vs20']):.1f}% —— 超跌反转的主场，错杀盘多、反弹空间大")
    elif s["mode"] == "strong":
        s["note"] = (f"大盘在 MA20 上方 {s['vs20']:.1f}% —— 情绪已经转暖，超跌股没人接，"
                     "买进去容易变接盘")
    else:
        s["note"] = (f"大盘贴着 MA20（{s['vs20']:+.1f}%）—— 这套规则历史上在这种环境最吃亏"
                     "（胜率 20%、均 -1.6%），建议观望")
    return s


def allow(params: dict | None = None, st: dict | None = None) -> bool:
    """市场状态是否放行买入。params.market_gate=False 时永远放行。"""
    p = params or {}
    if not bool(p.get("market_gate", True)):
        return True
    if st is None:
        try:
            st = state()
        except Exception:
            return True
    if st.get("mode") == "unknown":
        return True
    pct = float(p.get("market_gate_pct", 1.0) or 1.0)
    return float(st.get("vs20", 0.0)) < -pct


def allow_on(date: str, params: dict | None = None) -> bool:
    """某一天的市场状态是否放行（回测逐日判定用；查不到当天就放行）"""
    p = params or {}
    if not bool(p.get("market_gate", True)):
        return True
    try:
        st = metrics().get(str(date)[:10])
    except Exception:
        return True
    if not st:
        return True
    pct = float(p.get("market_gate_pct", 1.0) or 1.0)
    return float(st.get("vs20", 0.0)) < -pct


def why(params: dict | None = None, st: dict | None = None) -> str:
    """被 gate 拦下时，告诉用户一句人话"""
    p = params or {}
    try:
        st = st or state()
    except Exception:
        return ""
    pct = float(p.get("market_gate_pct", 1.0) or 1.0)
    return (f"市场状态不匹配：大盘相对 MA20 是 {st.get('vs20', 0):+.1f}%，"
            f"要求低于 -{pct:.1f}%（指数真弱时超跌反转才有效）。"
            f"下面这批是本来会选中的，先放进观察池。")
