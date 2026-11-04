# -*- coding: utf-8 -*-
"""拉大金融板块的**全历史**日线（腾讯，分段回退到上市首日）。

为什么要单独一个脚本
--------------------
`lxquant/datasource.py` 的腾讯接口是给实时选股用的，只请求「最近 N 根」
（`param=sh601398,day,,,640,qfq`），640 根 = 2.6 年，回测根本不够。
腾讯其实支持带日期区间，按两年一段往回翻可以一直翻到上市第一天：

    https://ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh601398,day,2008-01-01,2009-12-31,640,qfq

这个写法不是我试出来的，是从 GitHub 上 `akfamily/akshare`（18k star）的
`akshare/stock/quote/stock_hist_tx.py` 学的：它用 `_TX_YEARS_PER_REQUEST = 2`
按两年步进，理由写在注释里 —— 两年约 490 个交易日，低于单次 640 条上限。
本脚本照抄这个步长，只是去掉了 akshare 那层 pandas 依赖包装，直接 urllib 拉。

数据口径
--------
`qfq` = 前复权，基准是**今天**。这意味着任何一个历史价格都不是当时的真实成交价，
但「相邻两日的比值」是真实的 —— 回测只用比值，所以没问题；界面上不要拿它显示
「当年股价」，会差出十倍（工行 2008 年前复权价 3.17，实际成交 8.14）。

成交量的单位是「手」，且复权不改成交量。本脚本不换算成股 —— 因子只用
log(volume) 做 20 日相关系数，组内同比例缩放不影响相关系数。

用法
----
    ./runtime/python.exe tools/fetch_fin.py            # 增量：只补缺失的票
    ./runtime/python.exe tools/fetch_fin.py --force    # 全量重拉
输出 `data/fin_long.pkl`（gitignore，可重抓）。
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lxquant.config import DATA_DIR          # noqa: E402
from lxquant.finance import POOL             # noqa: E402

OUT = DATA_DIR / "fin_long.pkl"
COLS = ["date", "open", "close", "high", "low", "volume"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 一次两年 ≈ 490 个交易日，低于腾讯单次 640 根的上限（同 akshare 的步长）
STEP = 2
BEG_YEAR = 1991          # 平安银行 1991-04 上市，其余票更晚，多请求几次无所谓
END_YEAR = 2026

# 顺序有讲究：ifzq / web.ifzq 对 hfq 会返回 WAF 的 501 页面
# （HTML 跳转到 waf.tencent.com/501page.html），proxy.finance.qq.com 才是通的。
HOSTS = (
    "https://proxy.finance.qq.com/ifzqgtimg",
    "https://ifzq.gtimg.cn",
    "https://web.ifzq.gtimg.cn",
)
ADJUST = "hfq"           # 见下：qfq 在长历史上会算出负价


def sym(code: str) -> str:
    return ("sh" if code.startswith("6") else "sz") + code


def _get(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "ignore")
    # WAF 拦截返回的是 HTML 跳转页（状态码 200 或 501），不是 JSON。
    # 直接 json.loads 会抛 JSONDecodeError，看着像"数据格式坏了"，其实是限流。
    if body.lstrip()[:1] == "<":
        raise RuntimeError("WAF 501（腾讯限流，等几分钟再试）")
    return json.loads(body)


def _chunk(code: str, y0: int, y1: int):
    """拉 [y0, y1] 这段。返回 (rows, err)。"""
    s = sym(code)
    last = ""
    for host in HOSTS:
        url = (f"{host}/appstock/app/fqkline/get?"
               f"param={s},day,{y0}-01-01,{y1}-12-31,640,{ADJUST}")
        try:
            j = _get(url)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            continue
        if not isinstance(j, dict) or j.get("code") not in (0, "0", None):
            last = f"code={j.get('code')} msg={j.get('msg')}"
            continue
        node = (j.get("data") or {}).get(s) or {}
        rows = node.get(f"{ADJUST}day") or node.get("day") or []
        return rows, ""
    return [], last or "empty"


def _norm(rows, code):
    if not rows:
        raise RuntimeError("no rows")
    df = pd.DataFrame([r[:6] for r in rows], columns=COLS)
    df["code"] = code
    df["date"] = df["date"].astype(str).str[:10]
    for c in ("open", "close", "high", "low", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = (df.drop_duplicates(subset=["date"], keep="last")
            .dropna(subset=["close"])
            .sort_values("date")
            .reset_index(drop=True))
    if (df["close"] <= 0).any():
        raise RuntimeError(f"{code} 有非正价格")
    return df[["date", "code", "open", "high", "low", "close", "volume"]]


def fetch(code: str):
    rows = []
    for y in range(BEG_YEAR, END_YEAR + 1, STEP):
        part, err = _chunk(code, y, min(y + STEP - 1, END_YEAR))
        if err:
            raise RuntimeError(f"{code} {y}-{y + STEP - 1} {err}")
        rows.extend(part)
    return _norm(rows, code)


def fetch_tail(code: str):
    """只拉最后两年，给已有的票补最新的 bar。

    为什么可以只补尾巴：后复权的基准是**上市首日**，历史值不会因为新的分红而改写
    （前复权才会 —— 每次分红都要把全部历史重算一遍，这也是它不适合做长历史的原因之一）。
    """
    part, err = _chunk(code, END_YEAR - STEP + 1, END_YEAR)
    if err:
        raise RuntimeError(f"{code} tail {err}")
    return _norm(part, code)


def refresh(codes=None, quiet=True):
    """把 data/fin_long.pkl 的尾巴补到今天。失败不抛，返回补到的最新日期。"""
    if not OUT.exists():
        return ""
    old = pd.read_pickle(OUT)
    have = set(old["code"].astype(str))
    todo = [c for c in (codes or have) if c in have]
    if not todo:
        return str(old["date"].max())[:10]

    got, t0 = {}, time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_tail, c): c for c in todo}
        for fu in as_completed(futs):
            c = futs[fu]
            try:
                got[c] = fu.result()
            except Exception as e:
                if not quiet:
                    print(f"  tail 失败 {c}: {str(e)[:60]}")
    if not got:
        print("  tail 全部失败（多半是腾讯 WAF 501），沿用旧数据")
        return str(old["date"].max())[:10]

    fresh = pd.concat(list(got.values()), ignore_index=True)
    # 用新拉的覆盖同 code+date 的旧行（分红后 qfq 会变，hfq 不会，但覆盖无害）
    merged = pd.concat([old, fresh], ignore_index=True)
    merged = (merged.drop_duplicates(subset=["code", "date"], keep="last")
                    .sort_values(["code", "date"]).reset_index(drop=True))
    merged.to_pickle(OUT)
    return str(merged["date"].max())[:10]


def main():
    force = "--force" in sys.argv
    codes = [(c, n, b) for b, items in POOL.items() for c, n in items]
    old = {}
    if OUT.exists() and not force:
        try:
            d = pd.read_pickle(OUT)
            for c, g in d.groupby("code"):
                old[str(c)] = g
            print(f"已有 {len(old)} 只，增量补齐")
        except Exception:
            old = {}

    todo = [(c, n, b) for c, n, b in codes if c not in old]
    print(f"共 {len(codes)} 只，要全量拉 {len(todo)} 只")
    if old and not force:
        print("已有数据先补尾巴…")
        print("  最新到", refresh())

    done, bad, t0 = {}, [], time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, c): (c, n, b) for c, n, b in todo}
        for k, fu in enumerate(as_completed(futs), 1):
            c, n, b = futs[fu]
            try:
                done[c] = fu.result()
            except Exception as e:
                bad.append((c, n, str(e)[:90]))
            if k % 10 == 0 or k == len(futs):
                print(f"  {k}/{len(futs)} 用时 {time.time() - t0:.0f}s 失败 {len(bad)}")

    if bad:
        print("失败：")
        for c, n, e in bad:
            print(f"  {c} {n} {e}")

    frames = list(old.values()) + list(done.values())
    if not frames:
        print("一只都没拿到")
        return 1
    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.drop_duplicates(subset=["code", "date"], keep="last")
    all_df = all_df.sort_values(["code", "date"]).reset_index(drop=True)
    all_df.to_pickle(OUT)

    print(f"\n落盘 {OUT}  {len(all_df):,} 行 / {all_df['code'].nunique()} 只")
    span = all_df.groupby("code")["date"].agg(["min", "max", "count"])
    print(f"日期跨度 {span['min'].min()} ~ {span['max'].max()}")
    print(f"每只天数 中位 {int(span['count'].median())} 最少 {span['count'].min()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
