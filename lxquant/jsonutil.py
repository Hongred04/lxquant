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


def dumps(obj, **kw):
    return json.dumps(obj, cls=Encoder, ensure_ascii=False, **kw)
