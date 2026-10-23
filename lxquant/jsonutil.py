# -*- coding: utf-8 -*-
"""JSON 落盘的小工具：numpy 类型安全序列化。"""
import json
import math


class Encoder(json.JSONEncoder):
    def default(self, o):
        try:
            import numpy as np
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                v = float(o)
                return v if math.isfinite(v) else None
            if isinstance(o, np.bool_):
                return bool(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
        except Exception:
            pass
        try:
            import pandas as pd
            if isinstance(o, pd.DataFrame):
                return o.to_dict("records")
            if isinstance(o, pd.Series):
                return o.to_dict()
            if isinstance(o, pd.Timestamp):
                return o.strftime("%Y-%m-%d")
        except Exception:
            pass
        return str(o)


def _clean(o):
    """把 NaN / Infinity 换成 None。

    这是必须的：json.dumps 默认 allow_nan=True，会原样写出 `NaN` / `Infinity`
    —— 那是非法 JSON，浏览器的 JSON.parse 直接抛异常，
    前端 `.then(r => r.json())` 一 reject，整页就白了。
    行情数据里 nan 很常见（停牌、除权当天、字段缺失），不能靠"应该不会有"兜着。
    """
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def dumps(obj, **kw):
    return json.dumps(_clean(obj), cls=Encoder, ensure_ascii=False, **kw)
