# -*- coding: utf-8 -*-
"""
启动入口（自动寻找空闲端口，避免和其他服务撞车）

    python run.py                # 默认从 8777 开始找空闲端口，然后自动打开浏览器
    python run.py --port 9000
    python run.py --no-browser
"""
import argparse
import socket
import sys
import webbrowser

from lxquant.server import serve


def pick_port(start: int, tries: int = 30) -> int:
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit(f"从 {start} 起连续 {tries} 个端口都被占用，请用 --port 指定。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="lxquant 量价低位选股系统")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--auto-port", action="store_true", default=True,
                    help="端口被占用时自动往后找一个（默认开启）")
    a = ap.parse_args()

    port = a.port
    try:
        serve(host=a.host, port=port, open_browser=not a.no_browser)
    except OSError:
        port = pick_port(a.port + 1)
        print(f"端口 {a.port} 被占用，改用 {port}")
        if not a.no_browser:
            webbrowser.open(f"http://{a.host}:{port}/")
        serve(host=a.host, port=port, open_browser=False)
