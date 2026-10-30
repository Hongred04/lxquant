"""回测必须可复现 —— 同一批交易，怎么打乱顺序都得给出同一个分。

这是踩过的最贵的坑：robust_score 原来只按 buy_date 排序，同一天几只票
买入的先后取决于多线程完成顺序，于是分折切点漂移，同一批交易连跑三次
拿到 -1.01 / -1.01 / -0.79。**结论不可复现，比结论是负的更糟** ——
你没法知道自己看到的是策略的表现还是线程调度的噪声。
"""
import random

from lxquant import backtest


def _trades():
    """20 笔交易，故意让同一天有多只票 —— 正是会暴露排序不稳的形态。"""
    out = []
    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    for i in range(20):
        out.append({
            "code": f"{600000 + i:06d}",
            "buy_date": days[i % len(days)],
            "signal_date": days[i % len(days)],
            "ret": [3.1, -1.2, 0.0, 5.4, -2.5, 1.8, 0.6, -0.9, 2.2, 4.4,
                    1.1, -3.3, 0.2, 2.9, -1.7, 6.1, 0.4, -0.5, 1.5, 3.8][i],
        })
    return out


def test_same_trades_any_order_same_score():
    base = backtest.robust_score(_trades())
    rnd = random.Random(42)
    for _ in range(5):
        ts = _trades()
        rnd.shuffle(ts)
        got = backtest.robust_score(ts)
        assert (got["robust"], got["median"], got["worst"]) == \
               (base["robust"], base["median"], base["worst"]), \
               f"打乱顺序后分数变了：{base} -> {got}"


def test_same_day_trades_are_split_deterministically():
    """同一天的几笔必须固定落在同一折里，否则折间对比没有意义。"""
    a = backtest.robust_score(_trades())
    b = backtest.robust_score(list(reversed(_trades())))
    assert [f["n"] for f in a["folds"]] == [f["n"] for f in b["folds"]]
    assert [(f["from"], f["to"]) for f in a["folds"]] == \
           [(f["from"], f["to"]) for f in b["folds"]]


def test_folds_cover_all_trades():
    r = backtest.robust_score(_trades(), k=5)
    assert sum(f["n"] for f in r["folds"]) == 20, r["folds"]
    assert len(r["folds"]) == 5


def test_empty_trades_gives_warning_not_crash():
    r = backtest.robust_score([])
    assert r["robust"] is None
    assert r["warn"], "空交易应给出 warn，界面才能解释为什么是 —"


def test_too_few_trades_degrades_gracefully():
    r = backtest.robust_score(_trades()[:3], k=5)
    assert r["robust"] is not None
    assert "不足" in r["warn"] or r["warn"], r
