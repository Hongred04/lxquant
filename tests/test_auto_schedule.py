"""尾盘扫 / 收盘后补扫的触发时机。

这段逻辑出过错：原来把"该不该跑尾盘扫"写在 in_hours() 之后，
15:00 一过主循环就 continue，永远到不了那段代码 —— 结果是
**白天没开软件的日子，晚上打开只能看到昨天**，当天完全无记录。
所以边界必须逐条钉死。
"""
from datetime import datetime

from lxquant import auto

P = {"auto_final": "14:45", "auto_final_enabled": True, "auto_scan": True}


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def _r(s, done=False, **over):
    p = dict(P)
    p.update(over)
    return auto._final_reason(p, _d(s), done)


def test_before_final_time_does_nothing():
    assert _r("2026-10-30 12:49") == ""
    assert _r("2026-10-30 14:44") == ""


def test_exact_final_time_is_normal_scan():
    assert _r("2026-10-30 14:45") == "尾盘终极扫"
    # 15:05 前收盘价还没定死，仍算正常尾盘扫
    assert _r("2026-10-30 15:05") == "尾盘终极扫"


def test_after_close_is_backfill():
    """核心场景：晚上才打开软件，也要补记当天名单。"""
    assert _r("2026-10-30 15:06") == "收盘后补扫"
    assert _r("2026-10-30 20:15") == "收盘后补扫"
    assert _r("2026-10-30 23:59") == "收盘后补扫"


def test_already_done_today_is_skipped():
    assert _r("2026-10-30 20:15", done=True) == ""


def test_weekend_does_nothing():
    assert _r("2026-10-31 20:15") == ""      # 周六
    assert _r("2026-11-01 20:15") == ""      # 周日
    assert _r("2026-11-02 08:00") == ""      # 周一开盘前


def test_respects_both_switches():
    """用户关了自动选股，就不许自作主张补扫。"""
    assert _r("2026-10-30 20:15", auto_scan=False) == ""
    assert _r("2026-10-30 20:15", auto_final_enabled=False) == ""
