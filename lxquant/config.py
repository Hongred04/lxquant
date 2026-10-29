# -*- coding: utf-8 -*-
"""全局配置：默认策略参数 + 用户可覆盖的配置持久化。"""
import json
import os
import re
from pathlib import Path

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_HHMM_RANGE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")

ROOT = Path(__file__).resolve().parent.parent
# 数据目录：桌面版用 ROOT/data；安卓版由 LXQ_DATA 指到 App 私有目录（解压出来的包是只读的）
DATA_DIR = Path(os.environ.get("LXQ_DATA") or (ROOT / "data")).resolve()
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "export"
for _d in (DATA_DIR, CACHE_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"

# ---------------------------------------------------------------- 默认参数
DEFAULT_PARAMS = {
    # ---- 策略方案（换一套选股逻辑只要改这里，见 lxquant/strategies/）----
    "strategy": "oversold_bounce",   # 5 折稳健分唯一为正的策略（+3.08），见 backtest.robust_score  # 用哪个方案；data/strategies/ 里的新方案也会出现在界面上

    # ---- 分时均价线 ----
    "ma_days": 3,              # 连续多少天收盘价站上分时均价线
    "ma_ratio": 1.000,         # 收盘价 >= 当日均价线 * 该系数（1.000 = 只要站上）
    "ma_tol": 0.0,             # 允许其中 N 天"轻微不达标"（容忍度，0 = 全部必须达标）
    "tail_from": "14:45",      # 尾盘口径的判定时刻＝实际下单时刻：记进记忆的买入价必须是这个时点的价
    "entry_mode": "tail",      # tail: 尾盘口径为准(推荐) | close: 以收盘价站上均价线为准
    "preview_at": "14:00",     # 尾盘前试算：14:00 后按"截至现在"的均价线先挑出要盯的（空=不启用）

    # ---- 自动化：打开就扫、盘中定时扫、尾盘终极扫 ----
    "auto_scan": True,         # 打开软件自动选一次
    "auto_limit": 600,         # 自动模式扫描只数（600 只约 20 秒，全市场约 3 分钟）
    "auto_hours": "09:35-15:00",  # 自动盯盘时段，非交易时段不开工
    "auto_every": 300,         # 盘中自动重扫间隔（秒），0 = 不自动轮询
    "auto_final": "14:45",     # 尾盘终极扫的时刻（给出可直接下单的名单）
    "auto_final_enabled": True,

    # ---- 筹码低位 ----
    "chip_window": 120,        # 筹码分布统计窗口（交易日）
    "chip_bins": 70,           # 价格分箱数
    "chip_decay": 0.985,       # 固定衰减系数（仅当真实换手率不可用时的兜底）
    "real_turnover": True,     # 启用真实换手率（流通股本口径，参考 adata）
    "turnover_intensity": 1.0, # 换手强度：1.0=当日换手多少就置换多少旧筹码
    "profit_cap": 0.25,        # 获利盘上限：获利筹码占比 <= 25%
    "pos_cap": 0.30,           # 价格分位上限：现价在 120 日区间中的位置 <= 30%

    # ---- 低位横盘 / 底部结构 ----
    "bottom_enable": True,     # 是否启用"低位横盘"过滤
    "bottom_days": 20,         # 观察最近多少个交易日
    "bottom_amp": 0.40,        # 该区间振幅上限（最高/最低 - 1 <= 40%）
    "bottom_slope": 0.12,      # 20 日线性回归斜率归一化上限（温和不暴涨）

    # ---- 个股过滤 ----
    "min_price": 2.5,          # 最低股价
    "max_price": 300.0,        # 最高股价
    "min_turnover_amt": 0.0,   # 最低成交额（元），0 = 不限制
    "exclude_st": True,        # 排除 ST / *ST / 退市
    "exclude_kcb": False,      # 排除科创板 688
    "exclude_cyb": False,      # 排除创业板 300/301
    "exclude_bj": True,        # 排除北交所 8/4/9 开头
    "exclude_new": 60,         # 上市不足 N 个交易日的新股排除（0=不排除）

    # ---- 均线趋势 ----
    "ma_trend_enable": False,  # 站上 MA20（趋势过滤，默认关闭：低位策略与趋势过滤天然冲突，可作可选加分项）
    "ma_trend_period": 20,

    # ---- 市场状态开关 ----
    # 这套规则是「超跌反转」，只在大盘真弱时才有胜算（165 笔回测：
    # 指数在 MA20 下方 1% 以上时胜率 52%、均 +1.51%；在 MA20 上方时胜率 25%、均 -1.27%）。
    # 所以市场状态不匹配时，宁可不出名单，也不要把钱送进接盘位。
    "market_gate": True,       # 开关：不匹配时只出观察池、不出可买名单
    "market_gate_pct": 1.0,    # 放行条件：上证指数比 MA20 低几个百分点

    # ---- 性能 ----
    # 并发线程数。改成"每线程一条长连接 + gzip"之后，24~32 是关键点：
    # 实测 240 只 30 分钟线，12→134 只/秒、24→200、32→194、48→165。
    # 48 以上反而变慢（线程只是互相排队），所以别再往上加。
    "workers": 32,

    # ---- 回测成本（不填这笔钱，回测永远是"微微赚钱"，实盘必亏）----
    "cost_on": True,           # 回测是否扣成本（关掉只是为了做对比实验）
    "commission": 0.00025,     # 佣金率，双边各收一次（万 2.5）
    "min_comm": 5.0,           # 单笔最低佣金（元）
    "stamp": 0.0005,           # 印花税，仅卖出收取（2023-08-28 起由万 10 减半为万 5）
    "transfer": 0.00001,       # 过户费，双边（万分之 0.1）
    "slippage": 0.001,         # 滑点，每边千分之一
    "notional": 20000.0,       # 假设单笔金额，用于摊薄"最低 5 元佣金"

    # ---- 买卖点 ----
    "buy_rule": "pullback",    # buy_rule: next_open | next_open_break | pullback
    "buy_pullback": 0.015,     # 回踩买：次日最低价 <= 信号日收盘 * (1+该值) 视为成交
    "buy_chase_max": 0.05,     # 高开超过该幅度则不追
    "stop_loss": 0.06,         # 最大止损幅度（现价 × -6%）
    "min_stop": 0.025,         # 最小止损空间：止损至少离现价 -2.5%，避免被日内噪声打掉
    "take_profit": 0.15,       # 止盈：收盘价 >= 信号日收盘 * (1+该值)
    "max_hold": 10,            # 最长持有交易日
    "sell_mode": "atr",        # atr: 跟踪止盈(高点回撤)  |  fixed: 固定止盈止损
    "trail_drawdown": 0.07,    # 跟踪止盈：从持仓最高点回撤 7% 离场
    "ma_exit": 0,              # 收盘跌破 MA{n} 离场（0 = 不启用）
}

# ---------------------------------------------------------------- 评分权重
DEFAULT_WEIGHTS = {
    "surplus": 25.0,     # 收盘价高于均价线的幅度（资金强度）
    "profit": 25.0,      # 获利盘越低分越高
    "position": 25.0,    # 价格分位越低分越高
    "bottom": 15.0,      # 低位横盘结构
    "trend": 10.0,       # 站上 MA20 等趋势项
}


def _norm(params: dict) -> dict:
    """把界面传来的"自然写法"归一化：'off'/'0'/空 = 关闭；数字字符串转成数。"""
    p = dict(params or {})
    pv = str(p.get("preview_at") or "").strip()
    p["preview_at"] = "" if pv.lower() in ("off", "0", "none", "close", "-", "") else pv
    ah = str(p.get("auto_hours") or "").strip()
    p["auto_hours"] = ah if _HHMM_RANGE.match(ah) else DEFAULT_PARAMS["auto_hours"]
    af = str(p.get("auto_final") or "").strip()
    p["auto_final"] = af if _HHMM.match(af) else DEFAULT_PARAMS["auto_final"]
    tf = str(p.get("tail_from") or "").strip()
    if tf.lower() not in ("close", "收盘"):
        p["tail_from"] = tf if _HHMM.match(tf) else DEFAULT_PARAMS["tail_from"]
    for k in ("auto_limit", "auto_every", "ma_days", "ma_tol", "chip_window", "chip_bins",
              "bottom_days", "ma_trend_period", "max_hold", "ma_exit"):
        if k in p:
            try:
                p[k] = int(float(p[k]))
            except Exception:
                p[k] = DEFAULT_PARAMS.get(k, p[k])
    if p.get("auto_limit") is not None:
        p["auto_limit"] = max(100, min(6000, int(p["auto_limit"] or DEFAULT_PARAMS["auto_limit"])))
    if p.get("auto_every") is not None:
        p["auto_every"] = max(0, int(p["auto_every"]))
    for k in ("auto_scan", "auto_final_enabled", "market_gate"):
        if k in p:
            v = p[k]
            p[k] = v if isinstance(v, bool) else str(v).strip().lower() not in ("0", "false", "off", "no", "")
    # 市场状态阈值：上证指数比 MA20 低几个百分点才放行（0~5 之间）
    if "market_gate_pct" in p:
        # 上限给到 20：阈值越大越保守（要求大盘跌得更狠才买），
        # 留出空间让人试"只在极端弱势时出手"，别写死 5 挡住
        try:
            p["market_gate_pct"] = max(0.0, min(20.0, float(p["market_gate_pct"])))
        except Exception:
            p["market_gate_pct"] = DEFAULT_PARAMS["market_gate_pct"]
    return p


def load_config() -> dict:
    cfg = {"params": dict(DEFAULT_PARAMS), "weights": dict(DEFAULT_WEIGHTS)}
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["params"].update(raw.get("params") or {})
            cfg["weights"].update(raw.get("weights") or {})
        except Exception:
            pass
    cfg["params"] = _norm(cfg["params"])
    return cfg


def save_config(cfg: dict) -> None:
    # 落盘前归一化一次，免得界面上选"不试算"存成 "off" 又在下一次读取时被当成时间
    out = {
        "params": _norm({**DEFAULT_PARAMS, **(cfg.get("params") or {})}),
        "weights": {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})},
    }
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def reset_config() -> dict:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    return load_config()
