# -*- coding: utf-8 -*-
"""东财涨停池 —— 补齐日线反推不出来的三样东西。

我们从日线自己数连板，只能得到"连续几天收盘涨停"。有三样拿不到：

  ① **板块归属**（hybk）：判断"是不是板块龙头"的唯一可行依据。
     没有板块，`连板数` 只是数字；有了板块才能算"这个板块今天几只涨停、它排第几"。
  ② **炸板次数**（zbc）：涨停被打开过几次。连板股炸板多的，封板质量差。
  ③ **封板时间**（fbt）/ 封单额（fund）：越早封、封单越大，资金越坚决。

这三样都只能取官方盘后统计，K 线里反推不出来。

数据源：东方财富涨停池（push2ex），params 与 akshare 的 stock_zt_pool_em 一致。
实测 `date` 参数有效（不同日期返回不同总数），可以回补历史。

降级策略：任何失败都返回空，调用方必须能在"没有板块信息"的情况下继续工作 ——
这条线是锦上添花，不是必需品。
"""
from __future__ import annotations

import json
import time
from collections import Counter

from .config import CACHE_DIR

URL_ZT = "https://push2ex.eastmoney.com/getTopicZTPool"
UT = "7eea3edcaed734bea9cbfc24409ed989"
_HEAD = {"Referer": "https://quote.eastmoney.com/"}


def _cache(date: str):
    return CACHE_DIR / f"zt_{date}.json"


def _norm(x: dict) -> dict:
    """把东财的短字段名转成可读的名字，顺便把时间/价格还原成正常量纲。

    fbt=92500 → 09:25:00；p=11950 → 11.95（东财价格是 ×1000 的整数）。
    """
    fbt = str(int(x.get("fbt") or 0)).zfill(6)
    return {
        "code": str(x.get("c") or ""),
        "name": x.get("n") or "",
        "lbc": int(x.get("lbc") or 0),          # 连板数（官方口径）
        "board": x.get("hybk") or "",           # 所属行业板块
        "zbc": int(x.get("zbc") or 0),          # 炸板次数
        "fbt": f"{fbt[:2]}:{fbt[2:4]}:{fbt[4:6]}" if fbt != "000000" else "",
        "fund": float(x.get("fund") or 0),      # 封单额（元）
        "hs": float(x.get("hs") or 0),          # 换手率 %
        "nmc": float(x.get("ltsz") or 0),       # 流通市值（元）
        "amount": float(x.get("amount") or 0),
        "price": float(x.get("p") or 0) / 1000.0,
        "chg": float(x.get("zdp") or 0),
    }


def zt_pool(date: str, force: bool = False) -> list:
    """某个交易日的涨停池。带磁盘缓存（按日期存），失败返回空列表。"""
    if not date:
        return []
    p = _cache(date)
    if not force and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("items") or []
        except Exception:
            pass
    from .datasource import _fetch
    url = (f"{URL_ZT}?ut={UT}&dpt=wz.ztzt&Pageindex=0&pagesize=200"
           f"&sort=fbt%3Aasc&date={date.replace('-', '')}&_={int(time.time())}")
    try:
        j = json.loads(_fetch(url, headers=_HEAD))
    except Exception:
        return []
    d = j.get("data") or {}
    items = [_norm(x) for x in (d.get("pool") or [])]
    items = [x for x in items if x["code"]]
    if items:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"date": date, "items": items},
                                    ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return items


def enrich(items: list, signal_date: str, prev_date: str) -> list:
    """给待买名单补上「板块 + 同板块今天几只涨停 + 炸板次数」。

    为什么用两个日期：
      · 信号股今天收的是阴线，**不在今天的涨停池里**，它的板块要从上一个
        交易日（它还在连板时）的池子里取；
      · 而"板块效应"要看**今天**这个板块有几只涨停 —— 今天还有同板块的票在涨停，
        说明这个题材没死，明天的反弹才有承接。
    """
    if not items:
        return items
    prev = {x["code"]: x for x in zt_pool(prev_date)}
    today = zt_pool(signal_date)
    by_board = Counter(x["board"] for x in today if x["board"])

    for it in items:
        code = str(it.get("code") or "")
        o = prev.get(code) or {}
        board = o.get("board") or ""
        it["board"] = board
        it["n_board"] = int(by_board.get(board, 0)) if board else 0
        it["zbc"] = int(o.get("zbc") or 0)
        it["fbt"] = o.get("fbt") or ""
        it["lbc_em"] = int(o.get("lbc") or 0)
        # 官方连板数与自算不一致时，以官方为准并留痕（说明我们的日线有缺口）
        if it["lbc_em"] and it.get("streak") and it["lbc_em"] != it["streak"]:
            it["flag"] = f"连板口径不一致（自算 {it['streak']} / 官方 {it['lbc_em']}）"
            it["streak"] = it["lbc_em"]
    return items


def stats(items: list) -> dict:
    """一天的涨停池概况，用来判断"今天是什么温度"。

    实测结论（435 个首阴样本）：低开越深，次日反弹越强。
    而低开深不深，取决于昨天是不是情绪冰点 —— 所以这几个数值得每天记一笔。
    """
    if not items:
        return {"n": 0, "max_lbc": 0, "boards": [], "zbc_avg": None}
    boards = Counter(x["board"] for x in items if x["board"])
    return {
        "n": len(items),
        "max_lbc": max((x["lbc"] for x in items), default=0),
        "zbc_avg": round(sum(x["zbc"] for x in items) / len(items), 2),
        "boards": [{"name": b, "n": n} for b, n in boards.most_common(6)],
    }
