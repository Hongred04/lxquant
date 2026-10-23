# -*- coding: utf-8 -*-
"""重打 pyarm.zip：把最新项目代码编译成 3.12 字节码，塞进安卓资源包

用法（必须用 Python 3.12，安卓端是 3.12.15）：
    python android/pack_py.py

前置：先把现有 APK 里的 assets/pyarm.zip 解到 android/build/py/（保留 site/ 依赖），
      或者首次用 android/app/src/main/assets/pyarm.zip 解包一份。
"""
import os
import py_compile
import shutil
import sys
import zipfile
from pathlib import Path

PROJ = Path(r"C:\Users\macro\Desktop\量价选股")
WORK = Path(r"G:\数据文件\work\2026-10-23-10-47-19\pyw")     # 已解包的旧版目录（保留 site/）
OUT = Path(r"G:\数据文件\work\2026-10-23-10-47-19\pyarm_new.zip")

if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"必须用 Python 3.12 编译（安卓端是 3.12.15），当前 {sys.version}")

# 1) 编译所有项目模块（含子包），unchecked-hash 才能被 zipimport 正确加载
cache = WORK / "cache" / "lxquant"
for old in cache.glob("*.pyc"):
    old.unlink()
for sub in ("", "strategies"):
    d = PROJ / "lxquant" / sub
    for src in sorted(d.glob("*.py")):
        dst = (cache / sub / (src.stem + ".pyc"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(src), cfile=str(dst), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        print("  compile", src.relative_to(PROJ), "->", dst.relative_to(WORK), dst.stat().st_size)

# 2) 交易日历（离线要用的数据文件）
cal_src = PROJ / "data" / "calendar.csv"
cal_dst = cache / "calendar.csv"
if cal_src.is_file():
    shutil.copy2(cal_src, cal_dst)
    print("  data  calendar.csv", cal_dst.stat().st_size)
elif cal_dst.is_file():
    print("  keep  calendar.csv", cal_dst.stat().st_size)
else:
    print("  !! 没有 calendar.csv")

# 3) 入口脚本（run.pyc）+ 启动胶水
py_compile.compile(str(PROJ / "run.py"), cfile=str(WORK / "cache" / "run.pyc"),
                   doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
print("  compile run.py")

# 4) 手机版前端
web = WORK / "web"
for f in ("index.html", "m.css", "m.js"):
    src = PROJ / "web_m" / f
    if src.is_file():
        shutil.copy2(src, web / f)
        print("  web  ", f, src.stat().st_size)

# 5) 版本号
boot = WORK / "lxqboot.py"
txt = boot.read_text(encoding="utf-8")
import re
m = re.search(r'APP_VERSION = "([^"]+)"', txt)
old = m.group(1) if m else "?"
txt = re.sub(r'APP_VERSION = "[^"]+"', 'APP_VERSION = "1.9.0"', txt)
boot.write_text(txt, encoding="utf-8")
print(f"  version {old} -> 1.9.0")

# 6) 打包：DEFLATE，路径用正斜杠
if OUT.exists():
    OUT.unlink()
names = []
for root, _, files in os.walk(WORK):
    for f in files:
        if f.endswith((".bak",)):
            continue
        p = Path(root) / f
        names.append(p.relative_to(WORK).as_posix())
names.sort()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for n in names:
        z.write(WORK / n, n)
print(f"\n打包完成 {OUT}  {OUT.stat().st_size/1024/1024:.1f} MB  {len(names)} 个文件")
