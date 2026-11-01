"""东财涨停池的字段解析与补全。

这块是唯一"外部口径"的数据，字段名全是缩写（p/fbt/zbc/hybk），
写错一个字母不会报错，只会让界面上显示出一个荒谬的数字。
所以单独测解析和补全，不联网。
"""
from lxquant import emotion

RAW = {
    "c": "603703", "n": "盛洋科技", "p": 11950, "zdp": 10.0368,
    "amount": 91126637, "ltsz": 4959036334.0, "hs": 1.8376,
    "lbc": 2, "fbt": 92500, "lbt": 92500,
    "fund": 242852202, "zbc": 0, "hybk": "光学光电",
    "zttj": {"days": 2, "ct": 2},
}


def test_norm_fields():
    x = emotion._norm(RAW)
    assert x["code"] == "603703" and x["name"] == "盛洋科技"
    assert x["lbc"] == 2
    assert x["board"] == "光学光电"
    assert x["fbt"] == "09:25:00", x["fbt"]          # 92500 → 09:25:00
    assert abs(x["price"] - 11.95) < 1e-6, x["price"]  # 11950 → 11.95（东财 ×1000）
    assert x["fund"] == 242852202


def test_norm_handles_missing():
    x = emotion._norm({"c": "000001", "n": "A"})
    assert x["lbc"] == 0 and x["board"] == "" and x["fbt"] == ""
    assert x["price"] == 0


def test_enrich_adds_board_and_same_board_count(monkeypatch=None):
    """信号股今天收阴不在涨停池里，板块要从**前一日**池子取；
    同板块今天几只涨停要看**今日**池子。"""
    prev = [{"code": "002708", "name": "光洋股份", "lbc": 4,
             "board": "汽车零部", "zbc": 1, "fbt": "09:30:00"}]
    today = [
        {"code": "600001", "board": "汽车零部", "lbc": 1},
        {"code": "600002", "board": "汽车零部", "lbc": 2},
        {"code": "600003", "board": "半导体", "lbc": 1},
    ]
    saved = emotion.zt_pool
    emotion.zt_pool = lambda d, force=False: (prev if d == "2026-10-29" else today)
    try:
        items = [{"code": "002708", "name": "光洋股份", "streak": 4}]
        out = emotion.enrich(items, "2026-10-30", "2026-10-29")
    finally:
        emotion.zt_pool = saved
    assert out[0]["board"] == "汽车零部"
    assert out[0]["n_board"] == 2, out[0]        # 今日同板块 2 只涨停
    assert out[0]["zbc"] == 1
    assert out[0]["lbc_em"] == 4
    assert "flag" not in out[0], "口径一致时不该有告警"


def test_enrich_flags_streak_mismatch():
    """官方连板数和自算不一致 → 以官方为准并留痕（说明日线有缺口）"""
    prev = [{"code": "002708", "lbc": 5, "board": "汽车零部"}]
    saved = emotion.zt_pool
    emotion.zt_pool = lambda d, force=False: (prev if d == "2026-10-29" else [])
    try:
        items = [{"code": "002708", "streak": 4}]
        out = emotion.enrich(items, "2026-10-30", "2026-10-29")
    finally:
        emotion.zt_pool = saved
    assert out[0]["streak"] == 5, "应以官方连板数为准"
    assert "不一致" in out[0]["flag"]


def test_stats_counts_boards():
    pool = [{"board": "A", "lbc": 2, "zbc": 0}, {"board": "A", "lbc": 3, "zbc": 2},
            {"board": "B", "lbc": 1, "zbc": 0}]
    s = emotion.stats(pool)
    assert s["n"] == 3 and s["max_lbc"] == 3
    assert s["boards"][0] == {"name": "A", "n": 2}
    assert emotion.stats([])["n"] == 0
