# -*- coding: utf-8 -*-
"""收益曲线：把「模拟账户跑一遍」的结果缓存下来，界面打开就有图。

为什么要有这一层：跑一次要读几十只股票的日线、再逐日撮合，十几秒起步。
用户打开这一页想看的是"这条曲线长什么样"，不是进度条。所以：

    build()  跑一次 portfolio.run()，把结果写进 data/equity.json
    view()   只读那个文件（几毫秒）

口径和「模拟账户」完全一致 —— 这里不重算任何东西，就是 `portfolio.run`
的产物加一层落盘。要是哪天改了撮合逻辑，记得把 CACHE_VERSION 也改掉，
否则旧曲线会装作新口径。

和日志/记忆的区别：这条曲线记的是**如果按规则拿一笔钱真买真卖**会剩多少，
不是"选出来的票后来涨没涨"（那是 `memory.py` 的活）。
"""
from __future__ import annotations

import json
import os
import time

from .config import DATA_DIR

# 改了 portfolio 的撮合口径就加一版，旧缓存会自动作废，不会拿旧结果冒充新的。
CACHE_VERSION = 1

DIR = DATA_DIR
CACHE = DIR / "equity.json"

# 界面上能调的三个参数，其余走默认（界面上不摆，摆了也没人真去改）
DEFAULTS = {
    "initial_cash": 1_000_000.0,
    "max_pos": 5,
    "pos_pct": 0.2,
    "lookback": 1000,
    "limit": 40,
    "commission": 2.5e-4,
    "stamp": 1e-3,
    "slippage": 0.001,
}


def _pct_curve(pts: list) -> list:
    """[[日期, 百分比], ...] —— 已经是这个口径就直接返回，别二次换算。"""
    return pts or []


def save(r: dict, params: dict) -> dict:
    """把一次模拟结果落盘。只留界面要用的字段，trades 已经在上游截到 300 条。"""
    if not r or not r.get("ok"):
        return r
    data = {
        "v": CACHE_VERSION,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": params,
        "summary": r.get("summary") or {},
        "curve": _pct_curve(r.get("curve")),
        "coverage": r.get("coverage") or {},
        "trades": r.get("trades") or [],
        "scanned": r.get("scanned"),
        "candidates": r.get("candidates"),
        "elapsed": r.get("elapsed"),
    }
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE)      # 原子替换：跑到一半被关掉不会留下半个 JSON
    return data


def load() -> dict | None:
    try:
        if not CACHE.exists():
            return None
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return None
        # 口径变了就当作没有：宁可让用户重跑一次，也不能拿旧数字冒充
        if int(d.get("v") or 0) != CACHE_VERSION:
            return None
        return d
    except Exception:
        return None


def latest_day() -> str:
    """日线缓存更新到哪一天（拿 000001 当探针，和别处同一套办法）"""
    try:
        import pandas as pd
        from .config import CACHE_DIR
        df = pd.read_pickle(CACHE_DIR / "d_000001.pkl")
        return str(df["date"].iloc[-1])[:10]
    except Exception:
        return ""


def view() -> dict:
    """前端要的全部内容。没有缓存时 ready=false，界面显示"点一下算一遍"。"""
    d = load()
    if not d:
        return {"ready": False, "built_at": "", "stale": False,
                "summary": None, "curve": [], "trades": [],
                "coverage": {}, "params": {}, "defaults": DEFAULTS}

    curve = d.get("curve") or []
    asof = str(curve[-1][0]) if curve else ""
    today = latest_day()
    return {
        "ready": bool(curve),
        "built_at": d.get("built_at") or "",
        "asof": asof,
        # 缓存之后行情又走了几天：曲线不是最新的，界面上要说一句，别让人以为算过了就等于最新
        "stale": bool(today and asof and asof < today),
        "summary": d.get("summary") or {},
        "curve": curve,
        "trades": d.get("trades") or [],
        "coverage": d.get("coverage") or {},
        "params": d.get("params") or {},
        "scanned": d.get("scanned"),
        "candidates": d.get("candidates"),
        "elapsed": d.get("elapsed"),
        "defaults": DEFAULTS,
    }
