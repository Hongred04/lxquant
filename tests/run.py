"""极简测试运行器（只用标准库，不依赖 pytest）。

为什么自己写：这个项目要求纯标准库运行（runtime/ 里只有一个裸 Python），
装 pytest 会破坏「拷到哪都能跑」这个前提。而需要测的都是纯函数，
assert + 一个循环就够了，pytest 的 fixture/参数化在这里都是负担。

用法：
    ./runtime/python.exe -m tests.run          # 全部
    ./runtime/python.exe -m tests.run verdict  # 只跑名字含 verdict 的
    ./runtime/python.exe tools/check.py        # 连语法和构建一起查（推荐）

约定：
  · 每个 tests/test_*.py 里，函数名以 test_ 开头的就是测试；
  · 直接 assert，失败信息写清「期望 vs 实际」，打日志不用 print；
  · **不许联网、不许改真实数据**：要写文件就用 1999-xx-xx 这种假日期，
    跑完删掉；要行情就自己造 DataFrame。测试必须是确定性的。
"""
import importlib
import os
import pkgutil
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _discover(pattern=None):
    """找到所有 test_*.py，按名字排序（顺序稳定，输出可比对）"""
    here = os.path.dirname(os.path.abspath(__file__))
    names = sorted(m.name for m in pkgutil.iter_modules([here])
                   if m.name.startswith("test_"))
    if pattern:
        names = [n for n in names if pattern in n]
    return names


def main(argv):
    pattern = argv[1] if len(argv) > 1 else None
    mods = _discover(pattern)
    if not mods:
        print("没有匹配的测试文件")
        return 1

    total = passed = failed = skipped = 0
    fails = []
    t_all = time.time()

    for mn in mods:
        try:
            mod = importlib.import_module(f"tests.{mn}")
        except Exception:
            print(f"\n{mn}  导入失败")
            traceback.print_exc()
            failed += 1
            total += 1
            fails.append((mn, "<import>", "见上方堆栈"))
            continue
        fns = [n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))]
        if not fns:
            continue
        print(f"\n{mn}")
        for fn in fns:
            total += 1
            t0 = time.time()
            try:
                getattr(mod, fn)()
                dt = time.time() - t0
                passed += 1
                print(f"  ok    {fn:<38} {dt * 1000:6.0f}ms")
            except AssertionError as e:
                failed += 1
                msg = str(e) or "断言失败（没给原因）"
                fails.append((mn, fn, msg))
                print(f"  FAIL  {fn:<38} {msg}")
            except Exception as e:                      # noqa: BLE001
                failed += 1
                msg = f"{type(e).__name__}: {e}"
                fails.append((mn, fn, msg))
                print(f"  ERR   {fn:<38} {msg}")

    dt = time.time() - t_all
    print("\n" + "-" * 64)
    if failed:
        print(f"失败 {failed} 项 / 共 {total} 项   ({dt:.2f}s)")
        for mn, fn, msg in fails:
            print(f"  · {mn}::{fn}\n      {msg}")
        return 1
    print(f"全部通过：{passed} 项   ({dt:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
