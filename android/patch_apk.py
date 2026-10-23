# -*- coding: utf-8 -*-
"""把新的 pyarm.zip 换进已有 APK，重新对齐 + 签名

Java 层（dex / 资源 / so）今天没动过，所以不做完整重建（那需要 aapt2 + JDK17 +
android.jar），而是复用现有 APK 的其余条目，只替换 assets/pyarm.zip。
这样风险最小：不会因为重编资源/清单把一个能装的包弄坏。
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJ = Path(r"C:\Users\macro\Desktop\量价选股")
WORK = Path(r"G:\数据文件\work\2026-10-23-10-47-19")
BT = WORK / "apk_tools" / "android-15"
JAVA = Path(r"C:\Program Files\Java\jdk-9.0.1\bin\java.exe")
KEYTOOL = Path(r"C:\Program Files\Java\jdk-9.0.1\bin\keytool.exe")

SRC_APK = HERE / "dist" / "lxquant-1.9.0.apk"
NEW_PY = WORK / "pyarm.zip"
KS = HERE / "signkey.ks"
UNSIGNED = WORK / "lxquant-unsigned.apk"
ALIGNED = WORK / "lxquant-aligned.apk"
FINAL = WORK / "lxquant-1.9.0-new.apk"
KS_PASS = "lxquant2024"
ALIAS = "lxquant"

WORK.mkdir(parents=True, exist_ok=True)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd[:4]), "…" if len(cmd) > 4 else "")
    p = subprocess.run([str(c) for c in cmd], capture_output=True, **kw)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    if p.returncode != 0:
        print(out[:2000])
        raise SystemExit(f"FAILED rc={p.returncode}: {cmd[0]}")
    if out.strip():
        print("   ", out.strip()[:500].replace("\n", "\n    "))
    return p


print("[1/4] 生成签名密钥")
if not KS.exists():
    run([KEYTOOL, "-genkeypair", "-v", "-keystore", KS, "-alias", ALIAS,
         "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
         "-storepass", KS_PASS, "-keypass", KS_PASS,
         "-dname", "CN=LXQuant, OU=App, O=LXQuant, L=CN, ST=CN, C=CN"])
else:
    print("    已有密钥，复用")

print("[2/4] 替换 assets/pyarm.zip")
src = zipfile.ZipFile(SRC_APK)
new_py = NEW_PY.read_bytes()
print(f"    原包 {len(src.namelist())} 个条目，新 pyarm {len(new_py)/1048576:.1f} MB")
n_repl = 0
with zipfile.ZipFile(UNSIGNED, "w") as out:
    for info in src.infolist():
        data = src.read(info.filename)
        if info.filename == "assets/pyarm.zip":
            data = new_py
            n_repl += 1
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        out.writestr(zi, data)
src.close()
print(f"    替换 {n_repl} 处")
if n_repl != 1:
    raise SystemExit("没找到 assets/pyarm.zip，路径不对")

print("[3/4] 对齐（zipalign -p 4）")
run([BT / "zipalign.exe", "-f", "-p", "4", UNSIGNED, ALIGNED])

print("[4/4] 签名")
if FINAL.exists():
    FINAL.unlink()
run([JAVA, "-jar", BT / "lib" / "apksigner.jar", "sign",
     "--ks", KS, "--ks-pass", f"pass:{KS_PASS}", "--ks-key-alias", ALIAS,
     "--v1-signing-enabled", "true", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
     "--out", FINAL, ALIGNED])
run([JAVA, "-jar", BT / "lib" / "apksigner.jar", "verify", "--print-certs", FINAL])

size = FINAL.stat().st_size / 1048576
print(f"\n完成 {FINAL}  {size:.1f} MB")
