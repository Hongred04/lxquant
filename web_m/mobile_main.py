# -*- coding: utf-8 -*-
"""
安卓版启动入口：把同一套 lxquant 代码跑在手机本地。

用法（Java 侧用 ProcessBuilder 直接起进程，不用 shell）：
    argv[0] = python 可执行文件（或 libpython 宿主）
    argv[1] = 本文件
    argv[2] = data-dir        App 私有目录，参数 / 缓存 / 记忆都写这里
    argv[3] = port            127.0.0.1 上的端口

启动成功后往 stdout 打印一行 `LXQ-READY <port>`，Java 侧靠它判断服务起来了。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    data_dir = argv[1] if len(argv) > 1 else os.path.join(HERE, "data")
    port = int(argv[2]) if len(argv) > 2 else 8777

    os.environ["LXQ_MOBILE"] = "1"
    os.environ["LXQ_DATA"] = data_dir
    os.environ["LXQ_WEB"] = os.path.join(HERE, "web_m")
    # 安卓上 fopen 默认没有 /tmp，matplotlib 之类用不到；这里把缓存目录兜住
    os.makedirs(os.path.join(data_dir, "cache"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "export"), exist_ok=True)

    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    from lxquant import server as lxq_server

    srv = lxq_server._make_server("127.0.0.1", port)
    real_port = srv.server_address[1]
    try:
        from lxquant import auto as lxq_auto
        lxq_auto.start()
    except Exception:
        import traceback
        traceback.print_exc()

    print("LXQ-READY %d" % real_port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main(sys.argv)
