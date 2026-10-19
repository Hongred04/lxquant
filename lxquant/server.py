# -*- coding: utf-8 -*-
"""零依赖 HTTP 服务器（Windows 下 select 不支持管道的限制，改用 ThreadingHTTPServer）。"""
import json
import os
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import analyzer, backtest, config, datasource as ds, store
from . import indicators as ind
from . import extdata as ext
from .jsonutil import dumps

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# ---------------------------------------------------------------- 任务状态
class Job:
    def __init__(self, kind: str):
        self.kind = kind
        self.state = "running"      # running | done | error | cancelled
        self.pct = 0
        self.msg = "准备中…"
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self._stop = False
        self.lock = threading.Lock()

    def progress(self, phase=None, msg=None, pct=None):
        with self.lock:
            if msg is not None:
                self.msg = msg
            if pct is not None:
                self.pct = max(0, min(100, int(pct)))

    def stop(self):
        self._stop = True

    def stopped(self):
        return self._stop

    def as_dict(self):
        with self.lock:
            return {
                "id": self.id, "kind": self.kind, "state": self.state,
                "pct": self.pct, "msg": self.msg,
                "elapsed": round((self.finished or time.time()) - self.started, 1),
                "error": self.error,
                "summary": self._brief(),
            }

    def _brief(self):
        r = self.result
        if not r:
            return None
        s = r.get("stats") or r.get("summary") or {}
        out = {k: s[k] for k in ("hit", "scanned", "elapsed", "count", "win_rate",
                                 "avg_ret", "pnl") if k in s}
        out["generated_at"] = r.get("generated_at")
        return out


JOBS: dict[str, Job] = {}
JOB_SEQ = [0]
_last_screen = {"result": None}


def new_job(kind: str) -> Job:
    JOB_SEQ[0] += 1
    j = Job(kind)
    j.id = f"{kind}-{JOB_SEQ[0]}-{int(time.time())}"
    JOBS[j.id] = j
    # 只保留最近 12 个任务
    if len(JOBS) > 12:
        for k in list(JOBS)[:-12]:
            JOBS.pop(k, None)
    return j


def start_job(kind: str, fn, *args, **kwargs) -> Job:
    j = new_job(kind)

    def runner():
        try:
            res = fn(j, *args, **kwargs)
            j.result = res
            j.state = "done"
            j.pct = 100
        except Exception as e:  # noqa: BLE001
            j.state = "error"
            j.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            j.finished = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return j


# ---------------------------------------------------------------- 任务实现
def job_screen(j: Job, params, weights, limit, mode, preview_at=None):
    from . import screener
    r = screener.run_screen(
        params, weights, limit=limit, mode=mode, progress=j.progress,
        stop_flag=j.stopped, preview_at=preview_at)
    _last_screen["result"] = r
    _write_screen_csv(r)
    _save_last_screen(r)
    try:                                   # 选股记忆：一天一条，回头看准不准
        from . import memory
        memory.save_result(r)
    except Exception:
        traceback.print_exc()
    return r


def _last_screen_file():
    return config.DATA_DIR / "last_screen.json"


def _save_last_screen(r):
    """把最近一次结果落到 data/last_screen.json。

    以前只放在内存里，软件一关再开就是一张空表 —— 明明上次已经选好了，
    用户却得干等一次全市场扫描。现在重开直接读这份。
    """
    try:
        f = _last_screen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        traceback.print_exc()


def _load_last_screen():
    try:
        f = _last_screen_file()
        if not f.is_file():
            return None
        r = json.loads(f.read_text(encoding="utf-8"))
        return r if isinstance(r, dict) and r.get("items") is not None else None
    except Exception:
        return None


def _write_screen_csv(r):
    """把选股结果落到 data/export/选股结果_最新.csv（另存一份历史）"""
    try:
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["排名", "代码", "名称", "现价", "涨跌幅%", "把握度", "连续站在平均成本上方(天)",
                    "高出平均成本%", "上方套牢盘%", "价格在区间的位置%", "20日波动%", "止损价", "止盈价", "备注"])
        for a in r.get("items") or []:
            pl = a.get("plan") or {}
            w.writerow([a.get("rank"), a["code"], a["name"], a["price"], a.get("chg_pct"),
                        a["score"], a["avg"]["streak"],
                        # 尾盘口径下"高出平均成本"要用 tail_surplus（和界面/排序一致），缺失才回退
                        (a["avg"].get("tail_surplus") if a["avg"].get("tail_surplus") is not None
                         else a["avg"].get("avg_surplus")),
                        round((a["chip"].get("profit_ratio") or 0) * 100, 1),
                        round((a["pos"].get("pos") or 0) * 100, 1),
                        round((a["bottom"].get("amp") or 0) * 100, 1),
                        pl.get("stop"), pl.get("target"), "能买"])
        for a in r.get("watch") or []:
            pl = a.get("plan") or {}
            w.writerow([a.get("rank"), a["code"], a["name"], a["price"], a.get("chg_pct"),
                        a["score"], a["avg"]["streak"],
                        (a["avg"].get("tail_surplus") if a["avg"].get("tail_surplus") is not None
                         else a["avg"].get("avg_surplus")),
                        round((a["chip"].get("profit_ratio") or 0) * 100, 1),
                        round((a["pos"].get("pos") or 0) * 100, 1),
                        round((a["bottom"].get("amp") or 0) * 100, 1),
                        pl.get("stop"), pl.get("target"), a.get("watch", "")])
        txt = "\ufeff" + buf.getvalue()
        (config.EXPORT_DIR / "选股结果_最新.csv").write_text(txt, encoding="utf-8")
        (config.EXPORT_DIR / f"选股结果_{time.strftime('%Y%m%d_%H%M%S')}.csv").write_text(
            txt, encoding="utf-8")
        files = sorted(config.EXPORT_DIR.glob("选股结果_2*.csv"))
        for f in files[:-20]:
            f.unlink(missing_ok=True)
    except Exception:
        traceback.print_exc()


def job_scan(j: Job, params, weights, limit, mode):
    from . import screener
    r = screener.run_scan(params, weights, limit=limit, mode=mode, progress=j.progress)
    return r


def job_backtest(j: Job, params, weights, limit, mode, codes, lookback):
    r = backtest.run_backtest(params, weights, codes=codes, limit=limit, mode=mode,
                              lookback=lookback, progress=j.progress)
    j.result_extra = True
    _save_export("backtest", r)
    return r


def job_portfolio(j: Job, params, weights, limit, mode, codes, lookback,
                  initial_cash, max_pos, pos_pct, commission, stamp, slippage):
    from . import portfolio
    r = portfolio.run(params, weights, codes=codes, limit=limit, mode=mode,
                      lookback=lookback, initial_cash=initial_cash, max_pos=max_pos,
                      pos_pct=pos_pct, commission=commission, stamp=stamp,
                      slippage=slippage, progress=j.progress)
    j.result_extra = True
    _save_export("portfolio", r)
    return r


def _save_export(kind: str, r):
    try:
        p = config.EXPORT_DIR / f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        txt = dumps(r)
        p.write_text(txt, encoding="utf-8")
        # 只保留最近 20 个导出
        files = sorted(config.EXPORT_DIR.glob(f"{kind}_*.json"))
        for f in files[:-20]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------- 详情
def stock_detail(code: str, params=None, weights=None):
    cfg = config.load_config()
    params = params or cfg["params"]
    weights = weights or cfg["weights"]
    code = ds.norm(code)
    snap = store.get_list()
    row = snap[snap["code"] == code]
    name = row["name"].iloc[0] if not row.empty else ""
    d = store.get_daily(code)
    try:
        k5 = store.get_5min(code)
    except Exception:
        k5 = None
    rt = None
    try:
        r = ds.realtime([code])
        if not r.empty:
            rt = r.iloc[0].to_dict()
    except Exception:
        pass
    a = analyzer.analyze(code, name, params, daily=d, k5=k5, rt=rt)
    a["score"] = analyzer.score(a, weights, params)
    a["plan"] = analyzer.plan_targets(a["price"], a, params)
    # 日线（用于 K 线图）
    dd = d.tail(180).copy()
    dd["ma5"] = d["close"].rolling(5).mean().tail(180)
    dd["ma10"] = d["close"].rolling(10).mean().tail(180)
    dd["ma20"] = d["close"].rolling(20).mean().tail(180)
    a["daily"] = [{
        "date": r0.date, "open": round(float(r0.open), 3), "close": round(float(r0.close), 3),
        "high": round(float(r0.high), 3), "low": round(float(r0.low), 3),
        "volume": float(r0.volume),
        "ma5": None if r0.ma5 != r0.ma5 else round(float(r0.ma5), 3),
        "ma10": None if r0.ma10 != r0.ma10 else round(float(r0.ma10), 3),
        "ma20": None if r0.ma20 != r0.ma20 else round(float(r0.ma20), 3),
    } for r0 in dd.itertuples()]
    # 筹码分布图（与 analyzer 一致的模型：真实换手率优先）
    _tr = None
    if bool(params.get("real_turnover", True)):
        try:
            _w = int(params.get("chip_window", 120))
            _tr = ext.turnover_series(code, d["date"].tolist()[-_w:], d["volume"].tolist()[-_w:])
        except Exception:
            _tr = None
    cd = ind.chip_distribution(d, a["price"], int(params.get("chip_window", 120)),
                               int(params.get("chip_bins", 70)),
                               float(params.get("chip_decay", 0.985)),
                               turnover=_tr.values if _tr is not None else None,
                               intensity=float(params.get("turnover_intensity", 1.0)))
    a["chip"]["chips"] = cd.get("chips", [])
    a["chip"]["real_turnover"] = cd.get("real_turnover")
    a["chip"]["avg_turnover"] = cd.get("avg_turnover")
    # 当日分时
    try:
        a["intraday"] = ind.intraday_curve(ds.minute_today(code))
    except Exception:
        a["intraday"] = {"points": [], "avg": []}
    # 5 分钟近期成交（近 5 日）
    if k5 is not None and not k5.empty:
        kk = k5.tail(240)
        a["k5"] = [{"t": r0.time[5:16], "c": round(float(r0.close), 3),
                    "v": float(r0.volume)} for r0 in kk.itertuples()]
    else:
        a["k5"] = []
    # 历史同类信号（近 250 日）
    try:
        bt = backtest.backtest_one(code, name, params, lookback=250)
        a["history"] = bt.get("trades", [])[:12]
    except Exception:
        a["history"] = []
    # 技术指标快照（参考 QUANTAXIS QAIndicator 的口径）
    try:
        from . import ta
        a["ta"] = ta.snapshot(d)
    except Exception:
        a["ta"] = {}
    a["trend_img"] = None
    return a


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "lxquant/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静默
        pass

    # ---------- 工具
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, dumps(obj).encode("utf-8"))

    def _err(self, msg, code=400):
        self._json({"ok": False, "error": str(msg)}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- 静态文件
    def _static(self, path: str):
        rel = unquote(path.lstrip("/")) or "index.html"
        if rel in ("", "/"):
            rel = "index.html"
        f = (WEB / rel).resolve()
        if not str(f).startswith(str(WEB.resolve())) or not f.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ext = f.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
            ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
        }.get(ext, "application/octet-stream")
        self._send(200, f.read_bytes(), ctype)

    # ---------- 路由
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if p == "/" or p.startswith("/static") or p.endswith((".js", ".css", ".svg", ".ico", ".png", ".html")):
                return self._static(p.replace("/static/", "/") if p.startswith("/static") else p)
            if p == "/api/config":
                return self._json({"ok": True, **config.load_config(),
                                   "cache": store.cache_info(), "version": "1.8.3"})
            if p == "/api/job":
                j = JOBS.get(q.get("id", ""))
                if not j:
                    return self._err("任务不存在", 404)
                return self._json({"ok": True, **j.as_dict()})
            if p == "/api/job/result":
                j = JOBS.get(q.get("id", ""))
                if not j:
                    return self._err("任务不存在", 404)
                return self._json({"ok": True, "state": j.state, "result": j.result,
                                   "error": j.error})
            if p == "/api/auto":
                from . import auto
                from datetime import datetime as _dt
                cfg = config.load_config()
                return self._json({"ok": True, **auto.status(),
                                   "preview_now": auto._preview_at(cfg["params"], _dt.now()),
                                   "tail_from": cfg["params"].get("tail_from", "14:30")})
            if p == "/api/last":
                demo = q.get("demo")
                if demo:
                    # 演示模式：读取 data/demo/<name>.json（仅用于离线预览界面）
                    f = (config.DATA_DIR / "demo" / f"{os.path.basename(demo)}.json")
                    if f.is_file():
                        return self._json({"ok": True, "result": json.loads(
                            f.read_text(encoding="utf-8"))})
                    return self._err("演示数据不存在", 404)
                r = _last_screen.get("result")
                if r is None:
                    r = _load_last_screen()      # 软件重开过：读上次存下来的名单
                    if r is not None:
                        _last_screen["result"] = r
                return self._json({"ok": True, "result": r})
            if p == "/api/memory":
                # 选股记忆：有哪几天、每天选了谁、回头看涨没涨
                from . import memory
                d = q.get("date")
                if q.get("review") or d:
                    return self._json({"ok": True, **memory.review(d, q.get("code") or None)})
                if q.get("overview"):
                    return self._json({"ok": True, **memory.overview(int(q.get("n") or 30))})
                return self._json({"ok": True, "days": memory.list_days(int(q.get("n") or 60))})
            if p == "/api/detail":
                code = q.get("code", "")
                if not code:
                    return self._err("缺少 code")
                # 详情页必须用「选出这份名单时」的那套条件重算：
                # 否则用户改过参数后，点进老名单里的股票会满屏 ✗（名单里 75 分、点进去 0 分）
                _r = None
                demo = q.get("demo")
                if demo:
                    # 演示模式：条件从演示文件里取，别拿当前设置去套一份旧名单
                    _f = config.DATA_DIR / "demo" / f"{os.path.basename(demo)}.json"
                    if _f.is_file():
                        try:
                            _r = json.loads(_f.read_text(encoding="utf-8"))
                        except Exception:
                            _r = None
                if _r is None:
                    _r = _last_screen.get("result")
                    if _r is None:
                        _r = _load_last_screen()
                        if _r is not None:
                            _last_screen["result"] = _r
                _st = (_r or {}).get("stats") or {}
                return self._json({"ok": True, "data": stock_detail(
                    code, _st.get("params"), _st.get("weights"))})
            if p == "/api/quote":
                codes = [c for c in q.get("codes", "").split(",") if c]
                return self._json({"ok": True, "rows": ds.realtime(codes).to_dict("records")})
            if p == "/api/watch":
                from . import watchlist
                w = watchlist.load()
                return self._json({"ok": True, "items": [w["items"][c] for c in w["items"]],
                                   "check_at": w.get("check_at") or "",
                                   "alerts": (w.get("alerts") or [])[:10]})
            if p == "/api/alerts":
                from . import watchlist
                return self._json({"ok": True, "alerts": watchlist.list_alerts(20)})
            if p == "/api/export":
                kind = q.get("kind", "screen")
                r = _last_screen.get("result")
                if not r:
                    return self._err("还没有结果可导出")
                import csv
                import io
                buf = io.StringIO()
                items = r.get("items") or []
                w = csv.writer(buf)
                w.writerow(["排名", "代码", "名称", "现价", "涨跌幅%", "把握度",
                            "连续站在平均成本上方(天)", "高出平均成本%", "上方套牢盘%",
                            "价格在区间的位置%", "20日波动%", "止损价", "止盈价", "备注"])

                def _row(a, note):
                    av = a.get("avg") or {}
                    return [a.get("rank"), a.get("code"), a.get("name"), a.get("price"),
                            a.get("chg_pct"), a.get("score"), av.get("streak"),
                            (av.get("tail_surplus") if av.get("tail_surplus") is not None
                             else av.get("avg_surplus")),
                            round(((a.get("chip") or {}).get("profit_ratio") or 0) * 100, 1),
                            round(((a.get("pos") or {}).get("pos") or 0) * 100, 1),
                            round(((a.get("bottom") or {}).get("amp") or 0) * 100, 1),
                            (a.get("plan") or {}).get("stop"),
                            (a.get("plan") or {}).get("target"), note]

                for a in items:
                    w.writerow(_row(a, "能买"))
                # 「值得盯着」也要导出来：没有能买的股票时，只导 items 会得到一个空表
                for a in (r.get("watch") or []):
                    w.writerow(_row(a, a.get("watch") or "值得盯着"))
                data = ("\ufeff" + buf.getvalue()).encode("utf-8")
                name = f"选股结果_{time.strftime('%Y%m%d_%H%M')}.csv"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{__import__('urllib.parse', fromlist=['x']).quote(name)}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            return self._err("未知接口 " + p, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._err(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):
        p = urlparse(self.path).path
        b = self._body()
        try:
            if p == "/api/config":
                cfg = config.load_config()
                cfg["params"].update(b.get("params") or {})
                cfg["weights"].update(b.get("weights") or {})
                config.save_config(cfg)
                # 立刻让自动调度用上新参数，不用等下一轮
                try:
                    from . import auto
                    auto.refresh()
                except Exception:
                    pass
                return self._json({"ok": True, **config.load_config()})
            if p == "/api/config/reset":
                cfg = config.reset_config()
                try:
                    from . import auto
                    auto.refresh()
                except Exception:
                    pass
                return self._json({"ok": True, **cfg})
            if p == "/api/cache/clear":
                n = store.clear_cache(b.get("kind"))
                return self._json({"ok": True, "removed": n, "cache": store.cache_info()})
            if p == "/api/screen":
                cfg = config.load_config()
                # 前端不传 limit 就走参数里设好的自动扫描只数
                lim = int(b.get("limit", 0) or 0)
                if lim <= 0:
                    lim = int(cfg["params"].get("auto_limit", 600) or 600)
                # 4000 以上视为"全市场"，前端不用再区分模式
                if lim >= 4000:
                    mode = "all"
                else:
                    mode = "balanced"
                # 手动扫描期间的让路由前端调 /api/auto/hold 控制，这里不再重复设置，
                # 否则一旦任务起不来，自动模式会被永久挂起
                j = start_job("screen", job_screen, cfg["params"], cfg["weights"],
                              lim, mode, b.get("preview_at") or None)
                return self._json({"ok": True, "job": j.as_dict(), "limit": lim})
            if p == "/api/scan":
                cfg = config.load_config()
                j = start_job("scan", job_scan, cfg["params"], cfg["weights"],
                              int(b.get("limit", 60)), b.get("mode", "balanced"))
                return self._json({"ok": True, "job": j.as_dict()})
            if p == "/api/backtest":
                cfg = config.load_config()
                j = start_job("backtest", job_backtest, cfg["params"], cfg["weights"],
                              int(b.get("limit", 40)), b.get("mode", "balanced"),
                              b.get("codes") or None, int(b.get("lookback", 250)))
                return self._json({"ok": True, "job": j.as_dict()})
            if p == "/api/portfolio":
                cfg = config.load_config()
                j = start_job("portfolio", job_portfolio, cfg["params"], cfg["weights"],
                              int(b.get("limit", 40)), b.get("mode", "balanced"),
                              b.get("codes") or None, int(b.get("lookback", 250)),
                              float(b.get("initial_cash", 1000000)),
                              int(b.get("max_pos", 5)),
                              float(b.get("pos_pct", 0.2)),
                              float(b.get("commission", 2.5e-4)),
                              float(b.get("stamp", 1e-3)),
                              float(b.get("slippage", 0.001)))
                return self._json({"ok": True, "job": j.as_dict()})
            if p == "/api/job/stop":
                j = JOBS.get(b.get("id", ""))
                if j:
                    j.stop()
                    j.state = "cancelled"
                return self._json({"ok": True})
            if p == "/api/auto/hold":
                from . import auto
                auto.hold(bool(b.get("on", True)))
                return self._json({"ok": True, **auto.status()})
            # ---------- 自选股 / 买点卖点提醒
            if p == "/api/watch/add":
                from . import watchlist
                return self._json({"ok": True, "item": watchlist.add(
                    b.get("code", ""), b.get("name") or "", b.get("note") or "")})
            if p == "/api/watch/remove":
                from . import watchlist
                return self._json({"ok": True, "removed": watchlist.remove(b.get("code", ""))})
            if p == "/api/watch/update":
                from . import watchlist
                return self._json({"ok": True, "item": watchlist.update(
                    b.get("code", ""), **{k: b.get(k) for k in ("cost", "stop", "target", "note")
                                          if k in b})})
            if p == "/api/watch/check":
                from . import watchlist
                return self._json({"ok": True, **watchlist.check(force=bool(b.get("force")))})
            if p == "/api/alerts/ack":
                from . import watchlist
                return self._json({"ok": True,
                                   "cleared": watchlist.ack(b.get("sig") or "",
                                                            all_=bool(b.get("all")))})
            return self._err("未知接口 " + p, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._err(f"{type(e).__name__}: {e}", 500)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """浏览器取消请求（ConnectionReset/ConnectionAborted）是常态，不要刷屏堆栈。"""
        import sys
        et = sys.exc_info()[0]
        if et and issubclass(et, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(host="127.0.0.1", port=8777, open_browser=True):
    srv = _Server((host, port), Handler)
    url = f"http://{host}:{port}/"
    print("=" * 56)
    print("  lxquant 量价低位选股系统已启动")
    print(f"  访问地址: {url}")
    print("  自动选股已开启：开盘自动扫、盘中定时扫、14:50 尾盘终极扫")
    print("  打开页面后什么都不用点，软件会自己把名单推上来")
    print("  按 Ctrl+C 或关闭窗口停止")
    print("=" * 56)
    try:
        from . import auto
        auto.start()
    except Exception:
        traceback.print_exc()
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()
