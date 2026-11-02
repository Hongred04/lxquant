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

TODAY = "2026-11-02"
NEXT = "2026-11-03"


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
        pending = overnight.do_scan(TODAY, snap)
        assert len(pending) == 1, pending
        assert pending[0]["code"] == "600000"
        assert pending[0]["streak"] == 3
        assert pending[0]["signal_close"] == 10.5


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


def test_open_records_open_price_once():
    with Env(HIST):
        st = overnight._load()
        st["pending"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                          "streak": 3, "signal_close": 10.5}]
        overnight._save(st)
        snap = _snap([_row("600000", "浦发银行", 10.8, 10.2, 10.5)])
        assert overnight.do_open(NEXT, snap) == 1
        st = overnight._load()
        assert st["open"][0]["open"] == 10.2
        assert st["pending"] == []
        # 再调一次不能重复记
        assert overnight.do_open(NEXT, snap) == 0


def test_settle_computes_return():
    with Env(HIST):
        st = overnight._load()
        st["open"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                       "buy_date": NEXT, "streak": 3, "open": 10.0, "deferred": 0, "flag": ""}]
        overnight._save(st)
        snap = _snap([_row("600000", "浦发银行", 10.5, 10.0, 10.0)])
        assert overnight.do_settle(NEXT, snap) == 1
        t = overnight._read_trades()
        assert len(t) == 1
        assert abs(t[0]["ret"] - 5.0) < 0.01, t[0]
        assert overnight.stats()["n"] == 1


def test_stuck_limit_down_is_deferred_not_closed():
    """收盘仍一字跌停 → 卖不掉，顺延，不能假装当天平仓"""
    with Env(HIST):
        st = overnight._load()
        st["open"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                       "buy_date": NEXT, "streak": 3, "open": 10.0, "deferred": 0, "flag": ""}]
        overnight._save(st)
        # 一字跌停：开=收=最高=最低=9.0，昨收 10.0
        snap = _snap([_row("600000", "浦发银行", 9.0, 9.0, 10.0, high=9.0, low=9.0)])
        assert overnight.do_settle(NEXT, snap) == 0
        st = overnight._load()
        assert len(st["open"]) == 1, "应该顺延，而不是被平掉"
        assert st["open"][0]["deferred"] == 1
        assert overnight._read_trades() == []


def test_missed_signal_is_recorded():
    """昨天出了名单，今天开盘没执行 → 如实记一笔「错过」，不能当没发生"""
    with Env(HIST):
        st = overnight._load()
        st["pending"] = [{"code": "600000", "name": "浦发银行", "signal_date": TODAY,
                          "streak": 3, "signal_close": 10.5}]
        overnight._save(st)
        overnight.do_scan(NEXT, _snap([_row("600001", "B", 10.0, 10.0, 10.0)]))
        t = overnight._read_trades()
        assert len(t) == 1 and t[0]["status"] == "missed", t
        s = overnight.stats()
        assert s["missed"] == 1 and s["n"] == 0


def test_tick_is_idempotent_in_one_day():
    """调度每 60 秒探一次，同一个 15:05 不能重复记账"""
    from datetime import datetime
    # 注意：这里的连板必须 ≥3，否则根本不是首阴 —— 复用 HIST（只有 2 板）会测不到东西
    hist = {"2026-10-29": {"600000": 2}, "2026-10-30": {"600000": 3}, TODAY: {}}
    with Env(hist):
        snap = _snap([_row("600000", "浦发银行", 10.5, 11.0, 11.0)])
        # 用固定快照替换 store.get_list，避免联网
        import lxquant.store as store_mod
        saved = store_mod.get_list
        store_mod.get_list = lambda *a, **k: snap
        try:
            at = datetime(2026, 11, 2, 15, 6)
            overnight.tick(at)
            first = overnight._load()["pending"]
            overnight.tick(at)
            second = overnight._load()["pending"]
            assert len(first) == len(second) == 1
            # 再来一次也不该多出成交记录
            assert overnight._read_trades() == []
        finally:
            store_mod.get_list = saved


def test_ref_day_uses_last_closed_session():
    """周六日打开软件，也要拿周五的数据出名单，不能把日期挂到周末"""
    from datetime import datetime
    assert overnight.ref_day(datetime(2026, 11, 1, 10, 0)) == "2026-10-30"   # 周日
    assert overnight.ref_day(datetime(2026, 10, 31, 22, 0)) == "2026-10-30"  # 周六
    assert overnight.ref_day(datetime(2026, 11, 2, 9, 0)) == "2026-10-30"    # 周一开盘前
    assert overnight.ref_day(datetime(2026, 11, 2, 15, 30)) == "2026-11-02"  # 周一收盘后


def test_trade_record_keeps_signal_evidence():
    """成交记录必须自带信号日的全部证据 —— 否则事后没法验证
    「弱板是不是更差」「低开越深是不是弹得越猛」。"""
    with Env(HIST):
        st = overnight._load()
        st["pending"] = [{
            "code": "002708", "name": "光洋股份", "signal_date": TODAY,
            "streak": 4, "signal_close": 20.0, "board": "汽车零部",
            "n_board": 3, "zbc": 17, "fbt": "09:25:00", "lbc_em": 4,
        }]
        overnight._save(st)

        # 次日开盘 19.0（低开 5%），当天收盘 19.6
        overnight.do_open(NEXT, _snap([_row("002708", "光洋股份", 19.0, 19.0, 20.0)]))
        held = overnight._load()["open"][0]
        assert held["board"] == "汽车零部" and held["zbc"] == 17, held

        overnight.do_settle(NEXT, _snap([_row("002708", "光洋股份", 19.6, 19.0, 20.0)]))
        t = overnight._read_trades()[0]
        assert t["signal_close"] == 20.0
        assert abs(t["gap"] - (-5.0)) < 0.01, t["gap"]          # 低开幅度 = 19/20-1
        assert t["board"] == "汽车零部" and t["zbc"] == 17
        assert t["hold_days"] == 0                              # 同日买同日卖
        assert abs(t["ret"] - 3.16) < 0.05, t["ret"]            # 19.6/19-1


def test_export_csv_headers_and_rows():
    with Env(HIST):
        overnight._append_trade({
            "signal_date": TODAY, "buy_date": NEXT, "sell_date": NEXT,
            "code": "002708", "name": "光洋股份", "streak": 4,
            "board": "汽车零部", "n_board": 0, "zbc": 17,
            "signal_close": 20.0, "open": 19.0, "gap": -5.0,
            "close": 19.6, "ret": 3.16, "hold_days": 0,
            "status": "done", "deferred": 0, "flag": "",
        })
        csv = overnight.export_csv()
        lines = [x for x in csv.strip().split("\n") if x]
        assert "代码" in lines[0] and "低开幅度%" in lines[0], lines[0]
        assert len(lines) == 2
        assert "002708" in lines[1] and "汽车零部" in lines[1]


def test_export_csv_quotes_commas():
    with Env(HIST):
        overnight._append_trade({"code": "000001", "name": 'A,B"公司',
                                 "status": "missed", "flag": "x,y"})
        csv = overnight.export_csv()
        row = csv.strip().split("\n")[1]
        assert '"A,B""公司"' in row, row


def test_next_trade_day_skips_weekend():
    """周五收盘生成的名单，下一个买入日是周一 —— 不是"明天"（周六）"""
    assert overnight.next_trade_day("2026-10-30") == "2026-11-02"
    assert overnight.next_trade_day("2026-10-29") == "2026-10-30"


def test_pending_ctx_offsets():
    """界面文案全靠 offset：0=今天买 / 1=之后买 / -1=已过期。错一个就会写出"明天"却指向今天。"""
    from datetime import datetime as _dt
    with Env(HIST):
        st = overnight._load()
        st["pending"] = [{"code": "600000", "signal_date": "2026-10-30"}]
        st["open"] = []
        overnight._save(st)

        # 周五晚上生成 → 买入日是下周一
        c1 = overnight._pending_ctx(st, _dt(2026, 10, 30, 16, 0))
        assert (c1["phase"], c1["buy_date"], c1["offset"]) == ("waiting", "2026-11-02", 1)

        # 周一早上 8 点 → 今天买
        c2 = overnight._pending_ctx(st, _dt(2026, 11, 2, 8, 0))
        assert (c2["buy_date"], c2["offset"]) == ("2026-11-02", 0)

        # 周二才打开 → 已经过期
        c3 = overnight._pending_ctx(st, _dt(2026, 11, 3, 10, 0))
        assert c3["offset"] == -1, c3


def test_pending_ctx_bought_today():
    """已经买进去了，就不能再写"明天没有符合条件的票" """
    today = __import__("time").strftime("%Y-%m-%d")
    with Env(HIST):
        st = overnight._load()
        st["pending"] = []
        st["open"] = [{"code": "600000", "buy_date": today}]
        overnight._save(st)
        assert overnight._pending_ctx(st)["phase"] == "bought"


def test_pending_ctx_no_scan_vs_having_none():
    """'还没扫过' 和 '扫过但没有票' 是两件事，文案不能混"""
    with Env(HIST):
        st = overnight._load()
        st["pending"] = []
        st["open"] = []
        st["marks"] = {}
        overnight._save(st)
        assert overnight._pending_ctx(st)["phase"] == "no_scan"

        st["marks"] = {"scan": __import__("time").strftime("%Y-%m-%d")}
        overnight._save(st)
        assert overnight._pending_ctx(st)["phase"] == "fresh"
