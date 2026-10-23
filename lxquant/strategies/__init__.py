# -*- coding: utf-8 -*-
"""策略注册中心。

想换方案，两种办法：
  1) 内置方案：在 data/strategies/ 放一个 .py（不用改程序任何代码，重启就生效）
  2) 界面上「我的 → 参数设置 → 策略方案」直接切

每个策略文件的写法见本文件末尾的模板。
"""
import importlib
import importlib.util
import os
import sys
import traceback

from .base import Ctx, Facts, Gate, Strategy  # noqa: F401  (对外导出)

HERE = os.path.dirname(os.path.abspath(__file__))
_REGISTRY: dict = {}
_ERRORS: dict = {}
_LOADED_USER: set = set()


def _register(cls):
    if not getattr(cls, "key", None):
        return
    _REGISTRY[cls.key] = cls


def _load_builtin():
    for fn in sorted(os.listdir(HERE)):
        if not fn.endswith(".py") or fn.startswith("_") or fn in ("base.py", "__init__.py"):
            continue
        mod = fn[:-3]
        try:
            m = importlib.import_module("." + mod, __name__)
        except Exception:                                   # noqa: BLE001
            _ERRORS[mod] = traceback.format_exc(limit=3)
            continue
        for v in vars(m).values():
            if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy:
                _register(v)


def _user_dir() -> str:
    """用户策略目录：data/strategies（安卓上就是 App 私有目录下）。"""
    try:
        from .. import config
        d = str(config.DATA_DIR / "strategies")
    except Exception:                                       # noqa: BLE001
        d = os.path.join(os.path.dirname(HERE), "data", "strategies")
    os.makedirs(d, exist_ok=True)
    return d


def load_user() -> dict:
    """把 data/strategies/*.py 都加载进来。改了文件调一次就生效，不用重启。

    文件被删掉或改名，对应方案也要从清单里消失（不然界面上会留一个点进去就报错的幽灵）。
    """
    out = {}
    d = _user_dir()
    files = set()
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(d, fn)
        files.add(fn)
        modname = "lxqstrategy_" + fn[:-3]
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        stamp = (path, mtime)
        if stamp in _LOADED_USER:
            continue
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            _ERRORS[fn] = "无法加载"
            continue
        m = importlib.util.module_from_spec(spec)
        sys.modules[modname] = m
        try:
            spec.loader.exec_module(m)
        except Exception:                                   # noqa: BLE001
            _ERRORS[fn] = traceback.format_exc(limit=3)
            continue
        found = 0
        for v in vars(m).values():
            if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy:
                v._user_file = fn
                _register(v)
                out[v.key] = v
                found += 1
        if not found:
            _ERRORS[fn] = "文件里没有 Strategy 子类"
        _LOADED_USER.add(stamp)
    _purge_missing(files)
    return out


def _purge_missing(files: set) -> None:
    """把来源文件已经不在的用户方案从注册表里摘掉，并清掉它们的加载记录。"""
    gone = [k for k, cls in _REGISTRY.items()
            if getattr(cls, "_user_file", None) and cls._user_file not in files]
    for k in gone:
        _REGISTRY.pop(k, None)
    if gone:
        _LOADED_USER.difference_update(
            {s for s in _LOADED_USER if os.path.basename(s[0]) not in files})
        for fn in list(_ERRORS):
            if fn.endswith(".py") and fn not in files:
                _ERRORS.pop(fn, None)


def get(key: str | None) -> Strategy:
    """按 key 拿策略实例；拿不到就退回第一个内置的。"""
    if key and key not in _REGISTRY:
        load_user()
    cls = _REGISTRY.get(key or "") or _REGISTRY.get("ma_cost_low")
    if cls is None and _REGISTRY:
        cls = next(iter(_REGISTRY.values()))
    if cls is None:                                         # 极端兜底：一个都没有
        from .ma_cost_low import MaCostLow
        cls = MaCostLow
    return cls()


def all_strategies() -> list:
    """给界面用的清单：[{key, name, desc, user, gates:[{key,label,hint}]}]"""
    load_user()
    out = []
    for k, cls in _REGISTRY.items():
        inst = cls()
        out.append({
            "key": k, "name": cls.name, "desc": cls.desc,
            "user": bool(getattr(cls, "_user_file", "")),
            "file": getattr(cls, "_user_file", ""),
            "gates": [{"key": g.key, "label": g.label, "hint": g.hint,
                       "cost": g.cost, "on": True if not g.enable_key else None}
                      for g in cls.gates],
            "weights": dict(cls.weights or {}),
        })
    out.sort(key=lambda x: (x["user"], x["key"]))
    return out


def errors() -> dict:
    return dict(_ERRORS)


def new_file(name: str = "") -> str:
    """在 data/strategies 里放一份模板，返回路径。已经有就换个编号，不覆盖。"""
    d = _user_dir()
    stem = "".join(c for c in (name or "") if c.isalnum() or c in "-_") or "my_strategy"
    if stem[0].isdigit():
        stem = "s_" + stem
    path = os.path.join(d, stem + ".py")
    k = 2
    while os.path.exists(path):
        path = os.path.join(d, "%s_%d.py" % (stem, k))
        k += 1
    text = TEMPLATE.replace('key = "my_strategy"', 'key = "%s"' % os.path.basename(path)[:-3])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def current_key(params: dict) -> str:
    return str((params or {}).get("strategy") or "ma_cost_low")


def get_current(params: dict) -> Strategy:
    return get(current_key(params))


_load_builtin()


# ---------------------------------------------------------------- 模板
TEMPLATE = '''# -*- coding: utf-8 -*-
"""我的策略：改这一行写清楚它想抓什么。

放好这个文件（不用改程序），打开软件 →「我的 → 参数设置」里就能选到它。
改完存盘，回到界面点一下「重新扫描」就生效，不用重启。
"""
import numpy as np
from lxquant.strategies.base import Ctx, Facts, Gate, Strategy
from lxquant import indicators as ind


def _gate_shape(f, ctx, p):
    """例子：最近 N 天涨跌幅不超过某个范围。"""
    n = int(p.get("my_lookback", 20))
    cap = float(p.get("my_rise_cap", 0.15))
    d = ctx.hist
    if len(d) <= n:
        return {"ok": False, "why": "数据不够"}
    chg = float(d["close"].iloc[-1]) / float(d["close"].iloc[-1 - n]) - 1.0
    if chg <= cap:
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "近 %d 天涨了 %.1f%%，要 ≤ %.0f%%" % (n, chg * 100, cap * 100)}


class MyStrategy(Strategy):
    key = "my_strategy"                 # 唯一标识，别和别的重名
    name = "我的策略"                    # 界面上显示的名字
    desc = "一句话说清楚这套逻辑在赌什么。"

    gates = [
        Gate("shape", "涨得不多", "最近一段时间没有暴涨", _gate_shape, cost=1),
        # 想加第二关：
        # Gate("chip", "套牢盘少", "...", _gate_chip, cost=3),
    ]

    def facts(self, ctx: Ctx, p: dict) -> Facts:
        d = ctx.hist
        return Facts({
            # 只有被 gate 引用到的键才会真的算，所以可以放心多写
            "close": lambda: float(d["close"].iloc[-1]),
        })

    def score(self, f, checks, p):
        # 不写就用默认的「过了几关给几分」
        return super().score(f, checks, p)
'''
