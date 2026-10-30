"""准入判定的分级结论 —— 这是"这套策略能不能用"的唯一出口，必须先测它。

重点不是"能跑"，而是**边界不能错**：
  · 样本不足时不能给结论（否则 3 笔交易也能"通过"）；
  · 最差一折为负时绝不能 pass（这是核心门槛，一票否决）；
  · 中间档（watch）必须真的能区分"有一段会亏"和"整体不行"。
"""
from lxquant import verdict


def _s(count, worst, med, robust, payoff, avg=1.0):
    return {"count": count, "worst": worst, "median": med,
            "robust": robust, "payoff": payoff, "avg_ret": avg}


def test_insufficient_when_too_few_trades():
    v = verdict.judge(_s(12, 2.0, 3.0, 2.5, 2.0))
    assert v["level"] == "insufficient", v
    assert v["pass"] is False
    # 样本不够时，即使其它指标很漂亮也不能给"可以当默认"
    assert "样本" in v["label"]


def test_empty_summary_is_insufficient_not_crash():
    v = verdict.judge({})
    assert v["level"] == "insufficient", v
    assert len(v["checks"]) == 5


def test_pass_requires_positive_worst_fold():
    v = verdict.judge(_s(60, 0.8, 2.5, 1.8, 2.2))
    assert v["level"] == "pass", v
    assert v["pass"] is True


def test_fail_when_worst_fold_blows_through():
    # 实测过的真实数字：最差折 -4.93%，亏超 3% 的容忍线
    v = verdict.judge(_s(54, -4.93, -1.66, -2.97, 1.81))
    assert v["level"] == "fail", v
    # 最差折这条必须是红灯，不能是黄灯
    by = {c["key"]: c for c in v["checks"]}
    assert by["worst_fold"]["level"] == "no", by["worst_fold"]


def test_watch_when_only_one_segment_loses():
    # 当前默认策略的真实画像：期望为正，但有一段亏 2.56%
    v = verdict.judge(_s(65, -2.56, 0.19, -0.91, 2.46, avg=2.56))
    assert v["level"] == "watch", v
    assert "会亏" in v["label"] or "能用" in v["label"]
    # 三态：最差折是黄灯（容忍范围内），不是红灯 —— 否则会出现
    # 「结论写着能用、下面一片红叉」的自相矛盾
    by = {c["key"]: c for c in v["checks"]}
    assert by["worst_fold"]["level"] == "watch", by["worst_fold"]
    assert by["robust"]["level"] == "watch", by["robust"]


def test_watch_when_payoff_below_one():
    v = verdict.judge(_s(60, 0.5, 1.2, 0.9, 0.7))
    assert v["level"] == "watch", v
    by = {c["key"]: c for c in v["checks"]}
    assert by["payoff"]["ok"] is False


def test_watch_when_median_fold_negative():
    v = verdict.judge(_s(60, 0.5, -0.3, 0.2, 1.5))
    assert v["level"] == "watch", v


def test_rules_are_exposed_for_ui():
    """前端要能写清"按什么标准判的"，门槛必须跟着结论一起返回。"""
    r = verdict.judge(_s(60, 0.5, 1.2, 0.9, 1.5))["rules"]
    for k in ("min_trades", "min_worst_fold", "min_median_fold",
              "min_robust", "min_payoff", "watch_worst_fold", "watch_robust"):
        assert k in r, f"rules 缺 {k}"


def test_nan_and_none_do_not_crash():
    """summary 里出现 NaN/None 时不能抛异常（回测没分折时就是 None）。"""
    v = verdict.judge({"count": 60, "worst": None, "median": float("nan"),
                       "robust": None, "payoff": None})
    assert v["level"] in ("fail", "watch", "insufficient"), v
