"""记忆账本的写入保护 —— 这是「账不能算错」的最后一道闸。

出过两次真实事故，都必须钉住：
  ① 14:45 定型后，自动扫描每 5 分钟还在跑，一路把买入价改成 14:55/15:00 的价；
  ② 2026-10-29 17:05 页面在盘后自动补扫，force=True 把 40 只定型名单覆盖成 5 只。

所以这里测的不是"能不能写"，而是**什么时候不许写**。
全部用 1999 年的假日期，跑完删掉，不碰真实账本。
"""
import os

from lxquant import memory

D1 = "1999-03-01"
D2 = "1999-03-02"
D3 = "1999-03-03"
D4 = "1999-03-04"


def _old(date, at, code="600000"):
    return {
        "date": date, "at": at, "basis": "tail", "price_at": "14:45",
        "params": {"strategy": "oversold_bounce"},
        "items": [{"code": code, "name": "旧票", "price": 10.0, "score": 60.0}],
        "watch": [], "hit_count": 1, "runs": 2,
        "stats": {"basis": "tail", "hit": 1},
    }


def _new(at, code="000001", basis="tail"):
    return {
        "items": [{"code": code, "name": "新票", "price": 20.0, "score": 70.0}],
        "watch": [],
        "stats": {"basis": basis, "hit": 1,
                  "params": {"strategy": "oversold_bounce"}},
        "generated_at": at,
    }


def _cleanup(*dates):
    for d in dates:
        try:
            os.remove(memory._path(d))
        except OSError:
            pass


def test_after_close_force_cannot_overwrite_tail():
    """盘后重扫（17:04）不许覆盖盘中定型（14:45）的名单 —— 连 force 也不行。"""
    _cleanup(D1)
    memory._write(D1, _old(D1, D1 + " 14:45:28", code="600000"))
    try:
        memory.save_result(_new(D1 + " 17:04:00"), date=D1, force=True)
        got = memory._read(D1)
        assert got["items"][0]["code"] == "600000", \
            f"定型名单被盘后重扫覆盖了：{got['items'][0]}"
        assert got["runs"] == 3, f"runs 应该 +1 记一次运行，实际 {got.get('runs')}"
    finally:
        _cleanup(D1)


def test_intraday_force_still_allows_correction():
    """盘中手动重扫纠错要保留：14:45 定型，14:52 发现名单有误，force 应能改。"""
    _cleanup(D2)
    memory._write(D2, _old(D2, D2 + " 14:45:28", code="600000"))
    try:
        memory.save_result(_new(D2 + " 14:52:00"), date=D2, force=True)
        got = memory._read(D2)
        assert got["items"][0]["code"] == "000001", "盘中纠错被误拦了"
    finally:
        _cleanup(D2)


def test_after_hours_record_can_be_overwritten_again():
    """本身就是盘后记的记录（手工纠错过的），允许再被覆盖 —— 否则改错了就永远改不回来。"""
    _cleanup(D3)
    memory._write(D3, _old(D3, D3 + " 20:15:00", code="600000"))
    try:
        memory.save_result(_new(D3 + " 21:00:00"), date=D3, force=True)
        got = memory._read(D3)
        assert got["items"][0]["code"] == "000001", "盘后记录不该被保护"
    finally:
        _cleanup(D3)


def test_plain_rescan_without_force_is_ignored():
    """非 force 的自动重扫：同一天已有 tail 名单，刷新时间但不动名单。"""
    _cleanup(D4)
    memory._write(D4, _old(D4, D4 + " 14:45:28", code="600000"))
    try:
        memory.save_result(_new(D4 + " 14:55:00"), date=D4)
        got = memory._read(D4)
        assert got["items"][0]["code"] == "600000", "非 force 重扫不该改变名单"
        assert got["at"].endswith("14:45:28"), "定型时刻不该被改写"
    finally:
        _cleanup(D4)


def test_preview_result_is_never_saved():
    """盘中试算（basis=preview）不占位置：那种名单每 5 分钟变一次。"""
    d = "1999-03-05"
    _cleanup(d)
    try:
        memory.save_result(_new(d + " 10:30:00", basis="preview"), date=d)
        assert not os.path.exists(memory._path(d)), "preview 结果被记账了"
    finally:
        _cleanup(d)


def test_empty_result_is_never_saved():
    """一只都没选出时不写文件 —— 但要注意：这正是不写记忆的合法情况，
    所以「当天跑没跑过」的判重不能只靠记忆文件（auto._has_final_today 另有兜底）。"""
    d = "1999-03-06"
    _cleanup(d)
    try:
        memory.save_result({"items": [], "watch": [],
                            "stats": {"basis": "tail"}, "generated_at": d + " 14:46:00"},
                           date=d)
        assert not os.path.exists(memory._path(d)), "空名单不该写文件"
    finally:
        _cleanup(d)
