"""参数取值：0 必须是 0，不能被"默认值"顶掉。

`p.get("turn_min", 0.5) or 0.5` 这个写法让 0 变成 0.5 ——
面板上把旋钮拧到 0，程序里根本没生效，而且界面上看不出来。
这类 bug 不会报错、不会崩，只会让你得出错误的策略结论。
"""
import inspect
import os
import re

from lxquant.strategies import oversold_bounce as ob


def test_pnum_keeps_zero():
    assert ob._pnum({"turn_min": 0}, "turn_min", 0.5) == 0.0
    assert ob._pnum({"turn_min": 0.0}, "turn_min", 0.5) == 0.0
    assert ob._pnum({"drop_pct": 0}, "drop_pct", 0.20) == 0.0


def test_pnum_uses_default_only_when_absent():
    assert ob._pnum({}, "turn_min", 0.5) == 0.5
    assert ob._pnum({"turn_min": None}, "turn_min", 0.5) == 0.5
    assert ob._pnum({"turn_min": ""}, "turn_min", 0.5) == 0.5


def test_pnum_accepts_string_numbers():
    """配置从 JSON 读进来，可能是字符串。"""
    assert ob._pnum({"turn_min": "0.7"}, "turn_min", 0.5) == 0.7
    assert ob._pnum({"turn_min": "0"}, "turn_min", 0.5) == 0.0


def test_pnum_survives_garbage():
    assert ob._pnum({"turn_min": "abc"}, "turn_min", 0.5) == 0.5
    assert ob._pnum({"turn_min": []}, "turn_min", 0.5) == 0.5


def test_no_or_default_pattern_left_in_strategy():
    """回归闸：`p.get(..., 数字) or 数字` 这种写法会把 0 吃掉，不许再出现。

    行为测试要联网拉行情才能暴露这个问题，太慢；这里直接盯源码形态。
    如果哪天真的需要 `or` 语义，就写成显式的 `if v is None`，别用一行简写。
    """
    # 只认真正的反模式：从参数里取数字，再用 `or` 兜同一个数字。
    # 不能笼统匹配 "or 数字" —— `sum(...) or 100.0` 是合法的除零保护。
    pat = re.compile(r'p\.get\(\s*["\'][a-z_]+["\']\s*,\s*[0-9.]+\s*\)\s*or\s*[0-9.]+')
    bad = [ln.strip() for ln in inspect.getsource(ob).splitlines()
           if pat.search(ln) and not ln.strip().startswith("#")]
    assert not bad, "把 0 吃掉的老写法（0 是合法取值，不能用 or 兜默认值）：\n" + "\n".join(bad)


def test_strategy_has_pnum_helper_available():
    """_pnum 必须留在模块级，别的策略复用时能直接 import。"""
    p = os.path.join(os.path.dirname(ob.__file__), "oversold_bounce.py")
    assert os.path.exists(p)
    assert callable(ob._pnum)
