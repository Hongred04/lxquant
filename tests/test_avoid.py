# -*- coding: utf-8 -*-
"""避雷打分的口径测试。

这套东西最容易错的地方不是公式，是**方向**和**边界**：
  · ma60 是「均线÷价格」，值低才代表涨过了 —— 写成价格的倒数就全反了；
  · std20 / corr20 是「越低越好」，取 1-rank 之后再取最小，中间少一个反号就点错人；
  · pct 刚好落在剔除线上时算不算剔？必须和 build 里的 drop_n 用同一口径。

这些错了界面上看不出异常 —— 名字后面照样有个「避」，只是标的全是好票。
"""
from lxquant import avoid


def test_why_points_at_the_worst_factor():
    """点名要点最差的那一项，不是第一项。"""
    # 记录格式 [pct, r_ma, r_std, r_corr]，各项都是 0~100 的百分位
    assert avoid._why([5, 3, 50, 50]) == avoid.WHY["ma60"], "ma60 分位 3 最低，该点它"
    assert avoid._why([5, 90, 95, 50]) == avoid.WHY["std20"], \
        "r_std=95 表示波动在全市场前 95%，反号后 = 5，该点它"
    assert avoid._why([5, 90, 50, 97]) == avoid.WHY["corr20"], \
        "r_corr=97 表示价量同向极强，反号后 = 3，该点它"


def test_why_survives_missing_factor():
    """某项因子缺失（-1）时不能崩，也不能把它当最差项。"""
    got = avoid._why([5, -1, 50, 98])
    assert got == avoid.WHY["corr20"], f"应只从有效项里挑最差，实际 {got}"
    assert avoid._why([5, -1, -1, -1]) == "综合分数偏低"


def _fake_cache(**kw):
    d = {"v": avoid.CACHE_VERSION, "asof": "1999-01-01", "pool": 100,
         "drop": 0.40, "items": {}}
    d.update(kw)
    return d


def test_annotate_boundary_and_missing():
    """剔除线是「小于等于」。刚好 40 的算剔，41 的不算，池里没有的不给标记。"""
    orig = avoid.load
    avoid.load = lambda: _fake_cache(items={
        "A": [40, 50, 50, 50],      # 正好踩线 → 剔
        "B": [41, 50, 50, 50],      # 差一点 → 留
        "C": [10, 10, 50, 50],      # 明显差 → 剔
    })
    try:
        r = avoid.annotate(["A", "B", "C", "ZZZZZZ"])
    finally:
        avoid.load = orig
    assert r["items"]["A"]["drop"] is True, "pct=40 落在最差 40% 内，应算剔除"
    assert r["items"]["B"]["drop"] is False, "pct=41 在 40% 之外，不该标"
    assert "ZZZZZZ" not in r["items"], "池子里没有的代码不能凭空给个标记"
    assert r["hit"] == 3, f"查得到 3 只，实际 {r['hit']}"
    assert r["n"] == 2, f"该标红 2 只，实际 {r['n']}"


def test_annotate_without_cache_is_not_ready():
    """没有缓存时必须明确说 ready=False，让界面显示「正在算」而不是「都不该躲」。"""
    orig = avoid.load
    avoid.load = lambda: None
    try:
        r = avoid.annotate(["A"])
    finally:
        avoid.load = orig
    assert r["ready"] is False
    assert r["n"] == 0 and r["hit"] == 0
    assert r["items"] == {}


def test_view_without_cache():
    orig = avoid.load
    avoid.load = lambda: None
    try:
        v = avoid.view()
    finally:
        avoid.load = orig
    assert v["ready"] is False, "没缓存时 view 不能报 ready"


def test_cache_version_guards_old_file():
    """口径改了（CACHE_VERSION 变了）就当没有缓存，不能拿旧百分位冒充新算法。

    写到临时文件再改 avoid.CACHE 指过去 —— 不能碰真实的 data/avoid.json：
    测试中途崩掉会把线上缓存留成半个 JSON。
    """
    import json
    import tempfile
    from pathlib import Path

    orig = avoid.CACHE
    tmp = Path(tempfile.gettempdir()) / "lxq_test_avoid_cache.json"
    try:
        tmp.write_text(json.dumps({"v": avoid.CACHE_VERSION - 1, "items": {}}),
                       encoding="utf-8")
        avoid.CACHE = tmp
        assert avoid.load() is None, "旧版本缓存必须被作废"

        tmp.write_text(json.dumps({"v": avoid.CACHE_VERSION, "items": {}}),
                       encoding="utf-8")
        assert avoid.load() is not None, "版本号一致就该读出来"
    finally:
        avoid.CACHE = orig
        if tmp.exists():
            tmp.unlink()
