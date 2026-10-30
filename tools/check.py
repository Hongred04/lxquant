#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一条命令查完所有能自动查的东西。

    ./runtime/python.exe tools/check.py          # 查（默认）
    ./runtime/python.exe tools/check.py --fix    # 顺手把前端重新构建

为什么需要它：这个项目以前每次改完都是"临时写个脚本跑一下，看完删掉"，
于是同一类问题反复出现（稳健分抖动、参数 0 被吃掉、改了 app.js 看不到效果）。
把检查固定成一条命令，AI 改完能自己确认，人也不用记一堆步骤。

四步：
  1. Python 语法   compileall（比 ast.parse 快，且覆盖所有文件）
  2. 测试          python -m tests.run
  3. 前端语法      node --check（没装 node 就跳过，不算失败）
  4. 构建新鲜度    app.js 比 app.min.js 新 = 改了源文件但没构建（服务端发的是 .min！）

退出码 0 表示全过；非 0 表示有问题，可以直接接到 CI 或自动化里。
"""
import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PY = sys.executable
FIX = "--fix" in sys.argv
SKIP_TESTS = "--no-tests" in sys.argv

PASS, FAIL, SKIP = "ok  ", "FAIL", "skip"
results = []


def step(name, fn):
    t0 = time.time()
    try:
        code, detail = fn()
    except Exception as e:                       # noqa: BLE001
        code, detail = FAIL, f"{type(e).__name__}: {e}"
    results.append((code, name, detail, time.time() - t0))
    return code == PASS


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- 1) 语法
def chk_py_syntax():
    code, out = _run([PY, "-m", "compileall", "-q", "lxquant", "tests", "tools", "run.py"])
    if code == 0:
        return PASS, ""
    lines = [ln for ln in out.splitlines() if "Error" in ln or ".py" in ln][:6]
    return FAIL, "\n".join(lines)


# ---------------------------------------------------------------- 2) 测试
def chk_tests():
    if SKIP_TESTS:
        return SKIP, "按参数跳过"
    code, out = _run([PY, "-m", "tests.run"])
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or [""]
    if code == 0:
        return PASS, tail[0].strip()
    fails = [ln for ln in out.splitlines() if ln.strip().startswith("·") or "FAIL" in ln]
    return FAIL, "\n".join(fails[:8]) or tail[0].strip()


# ---------------------------------------------------------------- 3) JS 语法
def _node():
    for cand in ("node", "node.exe"):
        p = shutil.which(cand)
        if p:
            return p
    hits = sorted(glob.glob(os.path.expanduser(
        "~/.workbuddy/binaries/node/versions/*/node.exe")))
    return hits[-1] if hits else None


def chk_js():
    node = _node()
    if not node:
        return SKIP, "没找到 node，跳过（不影响 Python 侧）"
    code, out = _run([node, "--check", "web/app.js"])
    if code == 0:
        return PASS, os.path.basename(node)
    return FAIL, out.strip().splitlines()[0] if out.strip() else "语法错误"


# ---------------------------------------------------------------- 4) 构建新鲜度
PAIRS = [("web/app.js", "web/app.min.js"), ("web/style.css", "web/style.min.css")]


def chk_build():
    node = _node()
    stale = []
    for src, out in PAIRS:
        if not os.path.exists(src):
            continue
        if not os.path.exists(out) or os.path.getmtime(src) > os.path.getmtime(out) + 1:
            stale.append(src)
    if not stale:
        return PASS, "产物是最新的"
    if FIX:
        if not node:
            return FAIL, "产物落后，但没 node 不能构建：" + "、".join(stale)
        code, out = _run([node, "tools/build.js"])
        if code != 0:
            return FAIL, "构建失败：" + out.strip()[-200:]
        return PASS, "已重新构建：" + "、".join(os.path.basename(s) for s in stale)
    return FAIL, ("改了源码但没构建（服务端发的是 .min，改了等于没改）："
                  + "、".join(stale) + "\n         跑 node tools/build.js，或加 --fix")


def main():
    print("检查 " + ROOT)
    print("-" * 68)
    ok = True
    ok &= step("Python 语法", chk_py_syntax)
    ok &= step("测试", chk_tests)
    ok &= step("前端语法", chk_js)
    ok &= step("构建新鲜度", chk_build)

    print()
    for code, name, detail, dt in results:
        print(f"  {code}  {name:<10} {dt * 1000:6.0f}ms")
        if detail:
            for ln in str(detail).splitlines():
                print(f"          {ln}")
    print("-" * 68)
    if ok:
        print("全部通过")
        return 0
    print("有问题，见上面 FAIL 项")
    return 1


if __name__ == "__main__":
    sys.exit(main())
