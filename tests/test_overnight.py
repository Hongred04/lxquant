"""隔夜低吸的状态机 —— 这类"每天只该跑一次"的逻辑，错了很难发现。

重点测四件事：
  · 涨停阈值按板块分开（主板 10% / 创业板 20%），别拿 9.9% 一刀切；
  · 首阴判定要同时满足「昨日连板 ≥3」和「今日实体阴线」；
  · 幂等：同一天重复 tick 不能重复记账（调度每 60 秒就会探一次）；
  · 卖不掉的情况（收盘一字跌停）要顺延，不能假装当天已经平仓。
"""
import os
import shutil
import tempfile

import pandas as pd

from lxquant import limitup, overnight

TODAY = "2026-11-02"      # 信号日
NEXT = "2026-11-03"       # 买入日（D1）
DAY3 = "2026-11-04"       # 最早可卖日（D2，T+1）


# ---------------------------------------------------------------- 涨停口径
def test_limit_pct_by_board():
    assert limitup.limit_pct("600000") == 0.10          # 主板
    assert limitup.limit_pct("000001") == 0.10          # 主板
    assert limitup.limit_pct("300750") == 0.20          # 创业板
    assert limitup.limit_pct("688981") == 0.20          # 科创板
    assert limitup.limit_pct("430047") == 0.30          # 北交所
    assert limitup.limit_pct("600000", "*ST某某") == 0.05


def test_limit_up_tolerance():
    assert limitup.is_limit_up("600000", 0.0999)
    assert limitup.is_limit_up("600000", 0.0975)      # 四舍五入后 9.75%，仍算涨停
    assert not limitup.is_limit_up("600000", 0.0949)  # 差得远，不算
    # 创业板 9.9% 不是涨停 —— 这正是"一刀切"会漏掉的那批
    assert not limitup.is_limit_up("300001", 0.0999)
    assert limitup.is_limit_up("300001", 0.1998)


def test_tradeable_excludes_st_and_bj():
    assert limitup.tradeable("600000", "")
    assert limitup.tradeable("300001", "")
    assert not limitup.tradeable("600000", "ST某某")
    assert not limitup.tradeable("920000", "")       # 北交所
    assert not limitup.tradeable("600000", "某某退")


def test_streaks_counts_consecutive():
    assert limitup.streaks([True, True, False, True]) == [1, 2, 0, 1]
    assert limitup.streaks([]) == []


# ---------------------------------------------------------------- 状态机
def _snap(rows):
    return pd.DataFrame(rows)


def _row(code, name, px, op, prev, high=None, low=None):
    return {"code": code, "name": name, "price": px, "open": op,
            "high": high if high is not None else max(px, op),
            "low": low if low is not None else min(px, op),
            "prev_close": prev, "chg_pct": round((px / prev - 1) * 100, 3)}


class Env:
    """把状态文件指到临时目录，跑完删掉 —— 绝不碰真实账本"""

    def __init__(self, hist):
        self.hist = hist

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="ovn-")
        self._saved = (overnight.DIR, overnight.STATE, overnight.TRADES,
                       overnight.ensure_history)
        overnight.DIR = __import__("pathlib").Path(self.tmp)
        overnight.STATE = overnight.DIR / "state.json"
        overnight.TRADES = overnight.DIR / "trades.jsonl"
        overnight.ensure_history = lambda today: {k: dict(v) for k, v in self.hist.items()}
        return self

    def __exit__(self, *a):
        overnight.DIR, overnight.STATE, overnight.TRADES, overnight.ensure_history = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


HIST = {"2026-10-29": {"600000": 1}, "2026-10-30": {"600000": 2}, TODAY: {}}
# 3 连板夹具：do_scan 要求"昨天连板 ≥ MIN_STREAK(3)"，HIST 只有 2 连板，扫不出东西
HIST3 = {"2026-10-29": {"600000": 2}, "2026-10-30": {"600000": 3}, TODAY: {}}


def test_scan_finds_first_yin():
    """昨日连板 2 → 今天封板变 3；明天再看它收阴才是首阴。这里先验证历史更新。"""
    with Env(HIST):
        snap = _snap([_row("600000", "浦发银行", 11.0, 10.2, 10.0)])   # +10% 涨停
        pending = overnight.do_scan(TODAY, snap)
        st = overnight._load()
        assert st["limitup"][TODAY]["600000"] == 3, st["limitup"].get(TODAY)
        assert pending == [], "今天涨停，不可能是首阴"


def test_scan_picks_yin_after_streak():
    """昨日连板 3、今天收实体阴线 → 明日待买"""
    hist = {"2026-10-29": {"600000": 2}, "2026-10-30": {"600000": 3}, TODAY: {}}
    with Env(hist):
        snap = _snap([_row("600000", "浦发银行", 10.5, 11.0, 11.0)])   # 开 11 收 10.5
        sig = overnight.do_scan(TODAY, snap)
        mine = [x for x in sig if x["buy_date"] == TODAY]
        assert len(mine) == 1, sig
        assert mine[0]["code"] == "600000"
        assert mine[0]["streak"] == 3
        assert mine[0]["signal_close"] == 10.5


def test_scan_ignores_shallow_yin_and_low_streak():
    hist = {"2026-10-29": {"600000": 1, "600001": 3}, "2026-10-30": {"600000": 2, "600001": 4}, TODAY: {}}
    with Env(hist):
        snap = _snap([
            # 连板只有 2，不够 3
            _row("600000", "A", 10.5, 11.0, 11.0),
            # 连板 4，但只跌 0.3%（收 10.97 / 开 11.0），不算实体阴线
            _row("600001", "B", 10.97, 11.0, 11.0),
        ])
        assert overnight.do_scan(TODAY, snap) == []


def test_scan_buys_on_the_spot():
    """14:40 扫到首阴就当场买入：买入价 = 当前快照价，不是开盘价也不是收盘价。"""
    with Env(HIST3):
        st = overnight._load()
        st["signals"] = []
        overnight._save(st)
        # 当前价 10.20（14:40 的价），开盘 10.80 → 实体阴线
        snap = _snap([_row("600000", "浦发银行", 10.20, 10.80, 11.0)])
        sig = overnight.do_scan(TODAY, snap)
        mine = [x for x in sig if x["buy_date"] == TODAY]
        assert len(mine) == 1, sig
        assert abs(mine[0]["buy_price"] - 10.20) < 1e-6, mine[0]
        assert mine[0]["signal_date"] == mine[0]["buy_date"], "选股与买入必须同一天"


def test_scan_is_idempotent_for_same_day():
    """同一天重复扫不能重复记一笔，只更新价格。"""
    with Env(HIST3):
        snap = _snap([_row("600000", "浦发银行", 10.20, 10.80, 11.0)])
        overnight.do_scan(TODAY, snap)
        snap2 = _snap([_row("600000", "浦发银行", 10.05, 10.80, 11.0)])
        sig = overnight.do_scan(TODAY, snap2)
        mine = [x for x in sig if x["buy_date"] == TODAY]
        assert len(mine) == 1, f"重复记了 {len(mine)} 笔"
        assert abs(mine[0]["buy_price"] - 10.05) < 1e-6, "价格应更新为最新快照"


def test_settle_computes_return():
    with Env(HIST):
        st = overnight._load()
        st["signals"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                        "buy_date": NEXT, "streak": 3, "open": 10.0, "deferred": 0, "flag": ""}]
        overnight._save(st)
        # T+1：买入日 NEXT 当天不能卖，要到 DAY3
        snap = _snap([_row("600000", "浦发银行", 10.5, 10.0, 10.0)])
        assert overnight.do_settle(NEXT, snap) == 0, "买入当天就平了，违反 T+1"
        assert overnight.do_settle(DAY3, snap) == 1
        t = overnight._read_trades()
        assert len(t) == 1
        assert abs(t[0]["ret"] - 5.0) < 0.01, t[0]
        assert overnight.stats()["signal"]["n"] == 1


def test_stuck_limit_down_is_deferred_not_closed():
    """收盘仍一字跌停 → 卖不掉，顺延，不能假装当天平仓"""
    with Env(HIST):
        st = overnight._load()
        st["signals"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                        "buy_date": NEXT, "streak": 3, "open": 10.0, "deferred": 0, "flag": ""}]
        overnight._save(st)
        # 一字跌停：开=收=最高=最低=9.0，昨收 10.0
        # 注意是在 DAY3（可卖日）才跌停 —— NEXT 当天本来就卖不了，不算顺延
        snap = _snap([_row("600000", "浦发银行", 9.0, 9.0, 10.0, high=9.0, low=9.0)])
        assert overnight.do_settle(DAY3, snap) == 0
        st = overnight._load()
        assert len(st["signals"]) == 1, "应该顺延，而不是被平掉"
        assert st["signals"][0]["deferred"] == 1
        assert overnight._read_trades() == []


def test_tick_buys_then_sells_next_day():
    """完整一天：14:40 扫到就买；次日 14:50 卖掉。重复调不重复记账。"""
    from datetime import datetime
    import lxquant.store as store_mod

    with Env(HIST3):
        buy_snap = _snap([_row("600000", "浦发银行", 10.2, 10.8, 11.0)])
        sell_snap = _snap([_row("600000", "浦发银行", 10.9, 10.5, 10.2)])
        saved = store_mod.get_list
        try:
            store_mod.get_list = lambda *a, **k: buy_snap
            overnight.tick(datetime(2026, 11, 2, 14, 45))
            sig = overnight._load()["signals"]
            assert len(sig) == 1 and sig[0]["buy_date"] == TODAY, sig
            assert abs(sig[0]["buy_price"] - 10.2) < 1e-6

            overnight.tick(datetime(2026, 11, 2, 14, 52))
            assert len(overnight._load()["signals"]) == 1, "同一天重复买入了"

            store_mod.get_list = lambda *a, **k: sell_snap
            overnight.tick(datetime(2026, 11, 3, 14, 52))
            assert overnight._load()["signals"] == [], "应该已经卖掉"
            t = overnight._read_trades()
            assert len(t) == 1 and t[0]["sell_date"] == "2026-11-03", t
            assert abs(t[0]["ret"] - 6.86) < 0.1, t[0]["ret"]      # 10.9/10.2-1
        finally:
            store_mod.get_list = saved


def test_tick_does_not_sell_on_buy_day():
    """14:45 买、14:55 再跑一次，不能当天卖掉（T+1）"""
    from datetime import datetime
    import lxquant.store as store_mod

    with Env(HIST3):
        # 必须收实体阴线：10.20 < 10.80×0.99，否则扫不出信号
        snap = _snap([_row("600000", "浦发银行", 10.20, 10.80, 11.0)])
        saved = store_mod.get_list
        store_mod.get_list = lambda *a, **k: snap
        try:
            overnight.tick(datetime(2026, 11, 2, 14, 45))
            overnight.tick(datetime(2026, 11, 2, 14, 55))
            assert len(overnight._load()["signals"]) == 1, "当天就被卖了，违反 T+1"
            assert overnight._read_trades() == []
        finally:
            store_mod.get_list = saved


# ---------------------------------------------------------------- 信号 ≠ 成交
def test_scan_does_not_assume_you_bought():
    """扫完记账时 exec 必须是 None（还没说），不能默认"软件扫到 = 你买了"。

    这一条是账本的底线：一旦混进没下过单的"成交"，
    后面所有胜率、盈亏比都不可信，而干净样本是它唯一的价值。
    """
    with Env(HIST3):
        snap = _snap([_row("600000", "浦发银行", 10.20, 10.80, 11.0)])
        sig = overnight.do_scan(TODAY, snap)
        mine = [x for x in sig if x["buy_date"] == TODAY]
        assert mine[0]["exec"] is None, f"默认必须是「还没说」，实际 {mine[0]['exec']!r}"


def test_mark_exec_three_states():
    """买了 / 没买 / 取消标记 —— 三态都要能落库。"""
    with Env(HIST):
        st = overnight._load()
        st["signals"] = [{"code": "600000", "buy_date": TODAY, "open": 10.0}]
        overnight._save(st)

        assert overnight.mark_exec("600000", TODAY, True) == 1
        assert overnight._load()["signals"][0]["exec"] is True
        assert overnight._load()["signals"][0]["exec_at"], "标记时刻要记下来"

        overnight.mark_exec("600000", TODAY, False)
        assert overnight._load()["signals"][0]["exec"] is False

        overnight.mark_exec("600000", TODAY, None)
        assert overnight._load()["signals"][0]["exec"] is None, "要能撤销"


def test_mark_exec_can_fix_after_settlement():
    """第二天才想起来标「那天其实没买」—— 已落库的也要能改。"""
    with Env(HIST):
        overnight._append_trade({"signal_date": TODAY, "buy_date": NEXT, "code": "600000",
                                 "open": 10.0, "close": 10.5, "ret": 5.0,
                                 "status": "settled", "exec": None})
        assert overnight.mark_exec("600000", NEXT, False) == 1
        assert overnight._read_trades()[0]["exec"] is False


def test_stats_splits_signal_and_real():
    """没买的信号照样进「全部信号」，但不能进「实际买入」。

    用户原话：「我没买但是你要记录进去」——
    记录进来是为了统计规则，不是为了假装成交。两件事必须分开。
    """
    with Env(HIST):
        base = {"signal_date": TODAY, "buy_date": NEXT, "sell_date": NEXT,
                "status": "settled", "open": 10.0}
        overnight._append_trade({**base, "code": "A1", "ret": 3.0, "exec": True})
        overnight._append_trade({**base, "code": "A2", "ret": -2.0, "exec": True})
        overnight._append_trade({**base, "code": "B1", "ret": 9.0, "exec": False})
        overnight._append_trade({**base, "code": "B2", "ret": 1.0, "exec": None})

        s = overnight.stats()
        assert s["signal"]["n"] == 4, "全部信号应含没买和未标的"
        assert s["real"]["n"] == 2, "实际买入只算 exec=True"
        assert s["skipped"] == 1 and s["unconfirmed"] == 1
        assert abs(s["real"]["avg"] - 0.5) < 1e-6, s["real"]
        assert abs(s["signal"]["avg"] - 2.75) < 1e-6, s["signal"]
        # 执行率只对"表过态的"算：2 买 / (2 买 + 1 没买) = 66.7%，未标的不进分母
        assert abs(s["exec_rate"] - 66.7) < 0.1, s["exec_rate"]


def test_load_migrates_legacy_open_key():
    """老版本把信号存在 open 键里、且默认当成"买了"。
    升级后要迁到 signals，并把 exec 补成 None（当时没人确认过）。"""
    with Env(HIST):
        import json as _json
        overnight.STATE.write_text(_json.dumps({
            "pending": [], "open": [{"code": "600000", "buy_date": TODAY, "open": 10.0}],
            "marks": {}, "limitup": {},
        }), encoding="utf-8")
        st = overnight._load()
        assert "open" not in st, "老键要清掉，否则两处并存会不一致"
        assert st["signals"][0]["code"] == "600000"
        assert st["signals"][0]["exec"] is None


def test_scan_records_current_price_not_close():
    """买入价必须是**扫描那一刻的价**，不是开盘价。

    这是这套执行方式的核心：14:40 看到什么价就按什么价成交。
    用它和开盘价比，才知道当天是涨是跌（表格里那一列就是干这个的）。
    """
    with Env(HIST3):
        snap = _snap([_row("600000", "浦发银行", 9.50, 10.80, 11.0)])
        sig = overnight.do_scan(TODAY, snap)
        mine = [x for x in sig if x["buy_date"] == TODAY][0]
        assert abs(mine["buy_price"] - 9.50) < 1e-6
        assert abs(mine["open"] - 10.80) < 1e-6, "开盘价也要留着，用来算当天振幅"


# ---------------------------------------------------------------- T+1 硬约束
def test_settle_never_sells_on_buy_day():
    """A 股 T+1：买入当天不许卖。

    这是交易所规则。早期实现按"当天买、当天卖"结算，等于 T+0，
    把 354 个样本从 -0.04% 高估到 +1.66% —— 整个策略的结论都是假的。
    """
    with Env(HIST):
        st = overnight._load()
        st["signals"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                          "buy_date": NEXT, "streak": 3, "open": 10.0,
                          "deferred": 0, "exec": True}]
        overnight._save(st)

        # 买入当天结算：必须原样留着，一笔都不许平
        assert overnight.do_settle(NEXT, _snap([_row("600000", "浦发银行", 11.0, 10.0, 12.0)])) == 0
        assert len(overnight._load()["signals"]) == 1, "买入当天就被平掉了，违反 T+1"
        assert overnight._read_trades() == []

        # 下一个交易日才可以卖
        assert overnight.do_settle(DAY3, _snap([_row("600000", "浦发银行", 11.5, 10.0, 12.0)])) == 1
        t = overnight._read_trades()[0]
        assert t["sell_date"] == DAY3
        assert t["hold_days"] >= 1


def test_hold_days_is_recorded_not_zero():
    """持有的天数要如实记下来；如果一直是 0，说明又被写成 T+0 了。"""
    with Env(HIST):
        st = overnight._load()
        st["signals"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                          "buy_date": NEXT, "open": 10.0, "deferred": 0}]
        overnight._save(st)
        overnight.do_settle(DAY3, _snap([_row("600000", "浦发银行", 11.0, 10.0, 12.0)]))
        assert overnight._read_trades()[0]["hold_days"] >= 1
