# -*- coding: utf-8 -*-
"""行情数据源（纯标准库，规避 requests/akshare 依赖问题）

实测可用的数据源（2026-10 本机）：
  * 新浪 hq.sinajs.cn 实时行情
  * 新浪 quotes.sina.cn 5 分钟 K 线（最多 1023 根，约 22 个交易日）
  * 新浪 vip.stock.finance.sina.com.cn 全市场股票列表
  * 腾讯 ifzq.gtimg.cn 日线(前复权) / 5 分钟 / 当日分时
东方财富、网易、qt.gtimg.cn 在本机被网络策略拦截。

关于速度（2026-10 实测，240 只 30 分钟线）
------------------------------------------------
以前每发一个请求就新建一条 TCP+TLS 连接、拿完就关（Connection: close），
还得不到压缩：单请求 263ms，48 线程峰值只有 74 只/秒。
改成"每线程一条长连接 + gzip"之后：单请求 75ms，24 线程 206 只/秒（2.8x），
而且线程数从 48 降到 24 反而更快 —— 握手成本太高时，堆线程只是互相排队。

  urllib + close      24 线程 49.7 只/秒 | 48 线程 73.9 只/秒 | 96 线程 63.7 只/秒
  长连接 + gzip        24 线程 206 只/秒 | 48 线程 185.7 只/秒 | 96 线程 121.8 只/秒

所以：_fetch 一律走 _CONN 里的线程本地连接池，只在出错时重连。
"""
import gzip
import http.client
import socket
import json
import re
import threading
import time
import urllib.parse
import zlib

import pandas as pd

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class DataError(RuntimeError):
    pass


# 每线程一条长连接：{ (scheme, netloc): HTTPConnection }
# http.client 的连接对象不是线程安全的，锁在池里共享会互相踩；一个线程一条最省事，
# 也不会像"共享一个 Session"那样把并发压成串行。
_CONN = threading.local()


def _pool() -> dict:
    p = getattr(_CONN, "pool", None)
    if p is None:
        p = _CONN.pool = {}
    return p


def _get_conn(key, timeout: float):
    c = _pool().get(key)
    if c is None:
        scheme, netloc = key
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        c = cls(netloc, timeout=timeout)
        _pool()[key] = c
    return c


def _drop_conn(key):
    c = _pool().pop(key, None)
    if c is None:
        return
    # 先 shutdown 再 close：直接 close 在 TLS 上偶尔会等对端回 close_notify，
    # 一个卡住就拖住整条线程（实测 80 次 close 能吃掉 10 秒）。
    try:
        s = getattr(c, "sock", None)
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        c.close()
    except Exception:
        pass


def _fetch(url: str, headers: dict | None = None, timeout: int = 15,
           retries: int = 3, encoding: str = "utf-8") -> str:
    """GET 一个 URL，返回解码后的文本。走线程本地长连接 + gzip。"""
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
    if headers:
        h.update(headers)
    u = urllib.parse.urlsplit(url)
    key = (u.scheme or "https", u.netloc)
    path = u.path + (("?" + u.query) if u.query else "")
    last = None
    for i in range(retries):
        try:
            c = _get_conn(key, timeout)
            c.request("GET", path, headers=h)
            r = c.getresponse()
            body = r.read()                     # 必须读完，否则这条连接不能复用
            enc = (r.getheader("Content-Encoding") or "").lower()
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            if r.status != 200:
                raise DataError(f"HTTP {r.status}")
            return body.decode(encoding, "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            _drop_conn(key)                     # 连接可能已经废了，下一次重连
            # 连接被对端回收（长时间扫描中间断一下）是常态，立刻重连重试，不用等
            if isinstance(e, (http.client.RemoteDisconnected, http.client.BadStatusLine,
                              ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
                continue
            time.sleep(0.35 * (i + 1))
    raise DataError(f"请求失败 {url[:90]} -> {type(last).__name__}: {last}")


# ---------------------------------------------------------------- 代码规范化
def norm(code: str) -> str:
    """任意写法 -> 6 位数字代码。支持 sh600519 / 600519.SH / 600519。"""
    c = str(code).strip().lower()
    c = re.sub(r"^(sh|sz|bj)", "", c)
    c = re.sub(r"\.(sh|sz|bj|ss)$", "", c)
    c = re.sub(r"\D", "", c)
    return c.zfill(6) if c else ""


def market(code: str) -> str:
    """返回 sh / sz / bj"""
    c = norm(code)
    if c.startswith(("60", "68", "51", "58", "56", "11", "90")):
        return "sh"
    if c.startswith(("00", "30", "12", "15", "16", "18", "20")):
        return "sz"
    if c.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


def full(code: str) -> str:
    c = norm(code)
    return f"{market(c)}{c}"


def is_stock(code: str) -> bool:
    c = norm(code)
    return c.startswith(("600", "601", "603", "605", "688", "000", "001",
                         "002", "003", "300", "301", "83", "87", "43", "92"))


# ---------------------------------------------------------------- 股票列表
_LIST_CACHE = (None, 0.0)      # (全市场清单, 拉到的时刻)


def stock_list(force: bool = False) -> pd.DataFrame:
    """全市场 A 股快照（代码 名称 现价 涨跌幅 成交量 成交额 换手率 市盈率 等）

    一页 100 只（num 传多大都只给 100），全市场 56 页，串行翻页约 6 秒，
    结果在内存里放 10 分钟：自选股输入框靠它按名字找股票，不然每敲一个字都得干等。
    选股要最新价会传 force=True 绕开缓存。

    试过并发翻页（8 页一批），被这个接口限流：同一批 56 页有时 1.2 秒、
    有时 33 秒（无报错，纯变慢），比稳定的 6 秒更难接受，所以保持串行。
    东财 clist（一次请求拿全市场）在本机被网络策略拦掉，也用不了。
    """
    if not force:
        old, at = _LIST_CACHE
        if old is not None and time.time() - at < 600:
            return old
    out, page, num = [], 1, 100
    base = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?page={p}&num={n}&sort=symbol&asc=1&node=hs_a"
            "&symbol=&_s_r_a=page")
    while True:
        txt = _fetch(base.format(p=page, n=num),
                     headers={"Referer": "https://finance.sina.com.cn/"})
        txt = txt.strip()
        if not txt or txt in ("null", "[]"):
            break
        try:
            rows = json.loads(txt)
        except Exception:
            rows = json.loads(re.sub(r"(\w+):", r'"\1":', txt))
        if not rows:
            break
        for r in rows:
            out.append({
                "code": norm(r.get("code") or r.get("symbol")),
                "name": r.get("name") or "",
                "price": _f(r.get("trade")),
                "chg_pct": _f(r.get("changepercent")),
                "open": _f(r.get("open")),
                "high": _f(r.get("high")),
                "low": _f(r.get("low")),
                "prev_close": _f(r.get("settlement")),
                "volume": _f(r.get("volume")),          # 股
                "amount": _f(r.get("amount")),          # 元
                "turnover": _f(r.get("turnoverratio")),  # %
                "pe": _f(r.get("per")),
                "pb": _f(r.get("pb")),
                "mktcap": _f(r.get("mktcap")),          # 万元
                "nmc": _f(r.get("nmc")),                # 流通市值 万元
                "volume_ratio": _f(r.get("volume_ratio") or 0),
            })
        if len(rows) < num:
            break
        page += 1
        if page > 90:
            break
    df = pd.DataFrame(out)
    if df.empty:
        raise DataError("股票列表获取失败")
    df = df[df["code"].str.len() == 6]
    df = df.reset_index(drop=True)
    # 完整性校验：A 股现在 5000+ 只，只有几百只说明翻页中途被限流打断了。
    # 以前不看这个，半截数据会被当成完整快照写进缓存 —— 后果很隐蔽：
    # 只拿到第一页 100 只（全是北交所），exclude_bj 一过滤 → 池子 0 只 →
    # 选股页、回测、模拟账户集体"没数据"，而且 5 分钟内一直是这个结果。
    if len(df) < 1000:
        raise DataError(f"股票列表不完整（只拿到 {len(df)} 只，可能被限流）")
    globals()["_LIST_CACHE"] = (df, time.time())   # 赋值要在 globals() 里，不然会变成局部变量
    return df


def _f(v):
    try:
        if v in (None, "", "-", "--"):
            return float("nan")
        return float(v)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------- 实时行情
def realtime(codes) -> pd.DataFrame:
    """新浪实时行情，一次最多 100 个代码。"""
    codes = [full(c) for c in codes]
    rows = []
    for i in range(0, len(codes), 90):
        chunk = codes[i:i + 90]
        txt = _fetch("https://hq.sinajs.cn/list=" + ",".join(chunk),
                     headers={"Referer": "https://finance.sina.com.cn/"})
        for line in txt.split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
            if not m:
                continue
            sym, body = m.group(1), m.group(2)
            p = body.split(",")
            if len(p) < 32:
                continue
            price, prev = _f(p[3]), _f(p[2])
            chg = (price / prev - 1) * 100 if prev else float("nan")
            rows.append({
                "code": norm(sym), "name": p[0], "open": _f(p[1]), "prev_close": prev,
                "price": price, "high": _f(p[4]), "low": _f(p[5]), "bid": _f(p[6]),
                "ask": _f(p[7]), "volume": _f(p[8]), "amount": _f(p[9]),
                "date": p[30], "time": p[31], "chg_pct": chg,
                "avg_price": (_f(p[9]) / _f(p[8])) if _f(p[8]) else float("nan"),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 日线
def _sina_kline(sym: str, scale: int, count: int) -> list:
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_s=/CN_MarketDataService"
           f".getKLineData?symbol={sym}&scale={scale}&ma=no&datalen={count}")
    txt = _fetch(url, headers={"Referer": "https://finance.sina.com.cn/"})
    a, b = txt.find("["), txt.rfind("]")
    if a < 0 or b < 0:
        raise DataError(f"{sym} K 线为空")
    return json.loads(txt[a:b + 1])


def _tencent_kline(sym: str, scale: str, count: int) -> list:
    """腾讯接口（目前部分网络会返回 501，仅作备用）"""
    kind, _, field = scale.partition(":")
    url = f"https://ifzq.gtimg.cn/appstock/app/{kind}?param={sym},{field},,{count},qfq"
    j = json.loads(_fetch(url, headers={"Referer": "https://gu.qq.com/"}))
    node = (j.get("data") or {}).get(sym) or {}
    for k in (f"qfq{field}", field, "day", "m5"):
        if node.get(k):
            return node[k]
    return []


# 腾讯 K 线的三个入口 —— 数据完全一样，但**可用性是独立波动的**。
# 2026-10-29 遇到过 ifzq.gtimg.cn 连续 5 次 501（直连、代理、换 UA 都一样），
# 第二天又全好了 —— 说明那是单入口限流/临时封禁，不是接口下线。
# 只挂死一个域名的做法，会在这种时候把整片功能打成"数据没跟上"。
# 轮换策略：按「上次成功的入口」优先，失败就换下一个，全会才报错。
TENCENT_HOSTS = (
    "https://ifzq.gtimg.cn",
    "https://web.ifzq.gtimg.cn",
    "https://proxy.finance.qq.com/ifzqgtimg",
)
_TENCENT_PREF = [0]        # 上次成功的入口下标（进程内记忆，省掉无谓的试错）


def _tencent_order() -> list:
    """按「上次成功优先」排出这一轮要试的入口顺序。"""
    n = len(TENCENT_HOSTS)
    p = _TENCENT_PREF[0] % n
    return [(p + i) % n for i in range(n)]


def _tencent_fetch(sym: str, kind: str, count: int, adjust: str) -> list:
    """按入口轮换取一次腾讯 K 线，返回原始行（date/open/close/high/low/volume 股）。

    adjust：'qfq' 前复权 / '' 不复权。三个入口数据一致，但可用性独立波动，
    某一个 501 时换下一个，全挂才抛错。
    """
    last_err = None
    for i in _tencent_order():
        host = TENCENT_HOSTS[i]
        # 两个端点分工不同：
        #   fqkline/get 带复权参数，param 末位必须是 qfq/hfq；
        #   kline/kline  是不复权长历史，param 不能带末位（带空值会直接 501）。
        n = min(int(count), 800)
        if adjust == "qfq":
            url = f"{host}/appstock/app/fqkline/get?param={sym},{kind},,,{n},qfq"
        else:
            url = f"{host}/appstock/app/kline/kline?param={sym},{kind},,,{n}"
        try:
            j = json.loads(_fetch(url, headers={"Referer": "https://gu.qq.com/"}))
            # 参数错误换入口也没用，直接抛，别浪费两次请求
            if str(j.get("msg") or "").lower() == "param error":
                raise DataError(f"{sym} {kind} 参数错误")
            node = (j.get("data") or {}).get(sym) or {}
            # 前复权的键带 qfq 前缀；不复权就是 day/week/month 本身
            arr = node.get(f"qfq{kind}") if adjust == "qfq" else None
            if not arr:
                arr = node.get(kind) or []
            rows = []
            for x in arr:
                if not isinstance(x, (list, tuple)) or len(x) < 6:
                    continue
                rows.append({
                    "date": str(x[0])[:10], "open": _f(x[1]), "close": _f(x[2]),
                    "high": _f(x[3]), "low": _f(x[4]), "volume": _f(x[5]) * 100,   # 手 -> 股
                })
            _TENCENT_PREF[0] = i          # 记住这个入口，下次先用它
            return rows
        except DataError:
            raise                          # 参数类错误不重试
        except Exception as e:             # 网络/501/解析失败 -> 换下一个入口
            last_err = e
            continue
    raise DataError(f"{sym} {kind} 三个入口都失败: "
                    f"{type(last_err).__name__}: {last_err}")


def tencent_kline(code: str, period: str = "day", count: int = 640) -> pd.DataFrame:
    """腾讯前复权 K 线：period = day / week / month。

    为什么要有这个：新浪的 K 线接口只能取到约 300 根日线（一年出头），
    详情页想画"日 / 周 / 月 K"就得往回看到好几年，周线月线更是没法从
    5 分钟线拼出来 —— 腾讯 fqkline 一次给到 640 根，周期原生就分开算好了。
    字段: date open close high low volume(股)

    两条路径：
      · 腾讯自带的 qfq 是**等差口径**（逐次减每股分红）。日线 640 根（约 2.5 年）
        分红累计还不够多，全为正，直接用；
      · 周/月线动辄十几年，高分红老股的早期价格会被减成负数
        （实测茅台月线 300 根里 178 根为负），这时改取**不复权**长历史，
        再用新浪的比例因子复权 —— 历史照样长，价格恒为正。
    """
    sym = full(code)
    kind = {"day": "day", "week": "week", "month": "month"}.get(str(period), "day")
    rows = _tencent_fetch(sym, kind, count, "qfq")
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} {period} K 线为空")
    if (df[["open", "close", "high", "low"]] <= 0).any().any():
        # 等差复权把历史减穿了 -> 用「不复权 × 比例因子」重做一遍
        raw = pd.DataFrame(_tencent_fetch(sym, kind, count, ""))
        if raw.empty:
            raise DataError(f"{code} {period} 不复权 K 线为空")
        df = apply_ratio_qfq(raw, qfq_factors(sym))
        if df is None or df.empty:
            raise DataError(f"{code} {period} 比例复权失败")
    df = df[(df["close"] > 0) & (df["high"] > 0)].drop_duplicates("date")
    if df.empty:
        raise DataError(f"{code} {period} K 线为空")
    return df.sort_values("date").reset_index(drop=True)


def daily(code: str, count: int = 260) -> pd.DataFrame:
    """
    不复权日线（新浪 scale=240，最多 1023 根 ≈ 4.2 年）。
    注意：分时均价线策略本质上是"价格 vs 当日 VWAP"，用不复权数据与实盘一致。
    字段: date open close high low volume(股) amount(元)

    以前这里写死 300 根 —— 那是想当然，实测 datalen 给到 1023 一样能返回
    （再大就报错）。选股只用最近 320 根，所以放开上限不影响实盘口径；
    回测要"穿越牛熊"，走下面的 daily_long。
    """
    sym = full(code)
    arr = _sina_kline(sym, 240, min(int(count), 1023))
    rows = []
    for x in arr:
        rows.append({
            "date": x["day"][:10], "open": _f(x["open"]), "close": _f(x["close"]),
            "high": _f(x["high"]), "low": _f(x["low"]), "volume": _f(x.get("volume")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} 日线为空")
    df["amount"] = df["volume"] * (df[["high", "low", "close"]].sum(axis=1) / 3)
    df = df.dropna(subset=["close"]).drop_duplicates("date")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- 长历史（回测用）
def qfq_factors(sym: str) -> list:
    """新浪复权因子 [(除权日, 因子)]，升序。

    新浪的 f 是"复权后 / 复权前"的累积系数，所以历史价要**除以**它才对
    （乘上去会凭空造出除权跳空 —— 实测 000001 乘完多出一个 -12% 的假跳空，
    除完 60 只主板票 8 处最大 38.7% 的跳空全部归零）。
    没有除权记录时返回空表，等于不复权。
    """
    try:
        txt = _fetch(f"https://finance.sina.com.cn/realstock/company/{sym}/qfq.js",
                     headers={"Referer": "https://finance.sina.com.cn/"})
        a = txt.find("{")
        if a < 0:
            return []
        # 响应尾部挂着 `/* base64… */` 注释块：用 rfind("}") 截取理论上会被
        # 注释里的大括号带偏（现在恰好不含，但没人保证下个月也不含）。
        # raw_decode 只吃第一个完整 JSON 对象，后面的注释原样忽略，稳。
        obj, _ = json.JSONDecoder().raw_decode(txt[a:])
        return sorted((x["d"], float(x["f"])) for x in (obj.get("data") or []))
    except Exception:
        return []


def index_daily(sym: str = "sh000001") -> pd.DataFrame:
    """指数日线（不复权，最多 1023 根）。给 market_state 判断市场状态用。

    注意 sym 要带市场前缀（sh000001 是上证指数，不带前缀的 000001 是平安银行）。
    """
    arr = _sina_kline(sym, 240, 1023)
    rows = [{
        "date": x["day"][:10], "open": _f(x["open"]), "close": _f(x["close"]),
        "high": _f(x["high"]), "low": _f(x["low"]), "volume": _f(x.get("volume")),
    } for x in arr]
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{sym} 指数日线为空")
    return df.dropna(subset=["close"]).drop_duplicates("date").sort_values(
        "date").reset_index(drop=True)


def apply_ratio_qfq(df: pd.DataFrame, fac: list) -> pd.DataFrame:
    """按新浪的**比例**复权因子把不复权 K 线换成年化前复权（以最后一根为基准）。

    为什么必须用比例而不是减法：腾讯的 qfq 是等差口径（每次分红从历史价里减掉
    固定的每股分红），高分红老股一路减下去会变成负数 —— 实测茅台月线 300 根里
    178 根是负的、格力 179 根负。比例复权永远为正，且相邻两天的比值就是真实
    涨跌幅，回测与画图都安全。
    """
    import bisect

    if df is None or not len(df):
        return df
    fdates = [x[0] for x in fac]

    def _fac(d: str) -> float:
        if not fac:
            return 1.0
        i = bisect.bisect_right(fdates, d) - 1
        return fac[i][1] if i >= 0 else 1.0

    out = df.copy()
    dates = out["date"].astype(str).str.slice(0, 10).tolist()
    base = _fac(dates[-1]) if dates else 1.0
    if not base:
        base = 1.0
    for col in ("open", "close", "high", "low"):
        out[col] = [float(v) / (_fac(d) / base) for v, d in zip(out[col].tolist(), dates)]
    return out


def daily_long(code: str, count: int = 1023) -> pd.DataFrame:
    """长历史日线（**前复权**，最多 1023 根 ≈ 4.2 年），回测和模拟账户用。

    为什么单独做一个：
      * 选股用的是不复权（要和实盘的 14:30 价对上），不能动它；
      * 但回测要跨好几年，中途必然遇到送转分红。用不复权序列算收益，
        一次 10 送 4 就会在账上凭空多出 -29%，整份回测直接作废。
    所以这里把新浪的不复权日线 × 新浪自己的复权因子，拼成前复权序列。
    两个接口都不需要额外依赖，一只票两次请求。
    字段与 daily() 一致，volume 不调整（筹码分布只看相对比例）。
    """
    import bisect

    sym = full(code)
    arr = _sina_kline(sym, 240, min(int(count), 1023))
    if not arr:
        raise DataError(f"{code} 日线为空")
    fac = qfq_factors(sym)
    rows = []
    for x in arr:
        rows.append({
            "date": str(x["day"])[:10],
            "open": _f(x["open"]), "close": _f(x["close"]),
            "high": _f(x["high"]), "low": _f(x["low"]),
            "volume": _f(x.get("volume")),          # 成交量不跟着调，筹码只看比例
        })
    df = pd.DataFrame(rows)
    df = apply_ratio_qfq(df, fac)
    df["amount"] = df["volume"] * (df[["high", "low", "close"]].sum(axis=1) / 3)
    df = df.dropna(subset=["close"]).drop_duplicates("date")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- 5 分钟线
def kline_scale(code: str, scale: int = 30, count: int = 200) -> pd.DataFrame:
    """
    任意分钟周期的 K 线（新浪 scale=5/15/30/60/240）。

    为什么全市场扫描用 30 分钟线而不是 5 分钟线：
      分时均价线就是当日 VWAP = 累计成交额 / 累计成交量，这两个数都是**可累加**的，
      所以只要"切分点"落在同一时刻，30 分钟线算出来的日 VWAP 与 14:30 尾盘 VWAP
      跟 5 分钟线**逐位相同**（本机实测 600519/601021/002415 差值 0.00000%）。
      而 30 分钟线一天只有 8 根，datalen=200 就覆盖 25 个交易日、
      响应体 28KB（5 分钟线 144KB），解析也快一个数量级。

    唯一要注意的：tail_from / preview_at 必须正好落在 30 分钟线的收尾时刻
    （10:00 10:30 11:00 11:30 13:30 14:00 14:30 15:00），否则要用更细的周期，
    这件事交给 store.pick_scale() 自动挑。
    """
    sym = full(code)
    if scale >= 240:
        return daily(code, count)
    arr = _sina_kline(sym, int(scale), min(int(count), 1023))
    rows = [{
        "time": x["day"][:16], "open": _f(x["open"]), "high": _f(x["high"]),
        "low": _f(x["low"]), "close": _f(x["close"]),
        "volume": _f(x.get("volume")), "amount": _f(x.get("amount")),
    } for x in arr]
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} {scale} 分钟线为空")
    df = df[df["close"] > 0].drop_duplicates("time")
    return df.sort_values("time").reset_index(drop=True)


def kline5(code: str, count: int = 1023, source: str = "sina") -> pd.DataFrame:
    """
    5 分钟 K 线（成交量单位：股，成交额单位：元）。
    新浪最大 datalen=1023 ≈ 22 个交易日，胜在快（~100KB）；腾讯 320 根仅 7 天且当前常 501。
    本机实测：100 并发拉 5 分钟线 96/96 成功，2.1s —— 这是全市场扫描的主力数据源。

    注意：全市场扫描现在走 kline_scale(scale=30)，见上面那段说明；
    这个 5 分钟版本留给详情页的"近 5 日分时走势"用，因为那里要更细的颗粒度。
    """
    sym = full(code)
    if source == "tencent":
        arr = _tencent_kline(sym, "kline/mkline", min(int(count), 800))
        rows = []
        for x in arr:
            t = str(x[0])
            rows.append({
                "time": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:00",
                "open": _f(x[1]), "close": _f(x[2]), "high": _f(x[3]),
                "low": _f(x[4]), "volume": _f(x[5]) * 100, "amount": _f(x[6]) * 100,
            })
    else:
        arr = _sina_kline(sym, 5, min(int(count), 1023))
        rows = [{
            "time": x["day"], "open": _f(x["open"]), "high": _f(x["high"]),
            "low": _f(x["low"]), "close": _f(x["close"]),
            "volume": _f(x.get("volume")), "amount": _f(x.get("amount")),
        } for x in arr]
    df = pd.DataFrame(rows)
    if df.empty:
        raise DataError(f"{code} 5 分钟线为空")
    df = df[df["close"] > 0].drop_duplicates("time")
    return df.sort_values("time").reset_index(drop=True)


def minute_today(code: str) -> pd.DataFrame:
    """当日分时。优先腾讯逐分钟，失败时用新浪 5 分钟线拼出当日折线。"""
    sym = full(code)
    try:
        url = f"https://ifzq.gtimg.cn/appstock/app/minute/query?code={sym}&r={time.time():.3f}"
        j = json.loads(_fetch(url, headers={"Referer": "https://gu.qq.com/"}))
        d = ((j.get("data") or {}).get(sym) or {}).get("data") or {}
        rows = []
        for line in d.get("data") or []:
            p = line.split()
            if len(p) < 4:
                continue
            t = p[0]
            rows.append({"time": f"{t[:2]}:{t[2:4]}", "price": _f(p[1]),
                         "volume": _f(p[2]) * 100, "amount": _f(p[3])})
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = d.get("date")
            return df
    except Exception:
        pass
    k = kline5(code, 60)
    last_date = str(k["time"].iloc[-1])[:10]
    k = k[k["time"].str.startswith(last_date)].copy()
    k["time"] = k["time"].str[11:16]
    tot = k["amount"].cumsum()
    vol = k["volume"].cumsum()
    k["price"] = k["close"]
    k["avg"] = (tot / vol).where(vol > 0)
    k["date"] = last_date
    return k[["time", "price", "volume", "amount", "date", "avg"]].reset_index(drop=True)
