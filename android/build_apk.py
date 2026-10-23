# -*- coding: utf-8 -*-
"""量价选股 APK 构建脚本（不依赖 Gradle）。

资源用官方 aapt2 编译（rescomp2.py）。曾经尝试用纯 Python 手写 AXML 和
resources.arsc 以绕开工具链，但产出的 ResTable_package 结构非法
（`aapt2 dump badging` 报 `corrupt ResTable_package chunk`），APK 是坏的。
aapt2 在 build-tools/35.0.0 里可直接运行，只要满足两个条件：
    - 工作目录在可写工作区内，且 **cwd 切过去 + 全用相对路径**；
    - `compile -o <目录>` 的目录必须已存在。

流程：
    1. aapt2 compile/link -> AndroidManifest.xml + resources.arsc + res/*.xml
    2. javac        -> .class
    3. d8           -> classes.dex
    4. python zipfile -> 组装 APK（资源、dex、assets、jniLibs）
    5. zipalign     -> 4 字节对齐
    6. apksigner    -> 签名 + 校验

用法：
    python build_apk.py             # 全量构建 + 签名
    python build_apk.py --no-sign   # 只出未签名 APK
"""
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APKTOOLS = r"G:\数据文件\DeepSeek\_apk"
sys.path.insert(0, APKTOOLS)

SDK = r"G:\数据文件\DeepSeek\_sdk"
BT = os.path.join(SDK, "build-tools", "35.0.0")
JDK = os.path.join(SDK, "jdk", "jdk-17.0.2")
ANDROID_JAR = os.path.join(SDK, "platforms", "android-35", "android.jar")
JAVA = os.path.join(JDK, "bin", "java.exe")
JAVAC = os.path.join(JDK, "bin", "javac.exe")
KEYTOOL = os.path.join(JDK, "bin", "keytool.exe")

SRC = os.path.join(HERE, "app", "src", "main")
RES = os.path.join(SRC, "res")
ASSETS = os.path.join(SRC, "assets")
JNILIBS = os.path.join(SRC, "jniLibs")
MANIFEST = os.path.join(HERE, "AndroidManifest.xml")
# 关键：JVM（javac/d8/apksigner）在本机只被允许写入「会话工作区」G:\数据文件\DeepSeek\，
# 写到别处会报 "拒绝访问"。所以中间产物一律放工作区内。
BUILD = os.path.join(APKTOOLS, "apkbuild")
OUT = os.path.join(HERE, "dist")
ANDROID_JAR_ASCII = os.path.join(APKTOOLS, "tmp", "android.jar")
VERSION = "1.9.0"
VERSION_CODE = 3
MIN_SDK = 26
PACKAGE = "com.lxquant.app"
APK_NAME = "lxquant-%s.apk" % VERSION
KS = os.path.join(APKTOOLS, "signkey.ks")
KS_PASS = "lxquant2024"
KS_ALIAS = "lxquant"


def run(*args, **kw):
    cmd = [str(a) for a in args]
    print("  $", " ".join(cmd))
    env = dict(os.environ)
    env["JAVA_TOOL_OPTIONS"] = "-Duser.language=en -Duser.country=US"
    env["JAVA_HOME"] = JDK
    env["PATH"] = os.path.join(JDK, "bin") + os.pathsep + env.get("PATH", "")
    kw.setdefault("env", env)
    p = subprocess.run(cmd, capture_output=True, **kw)
    so = p.stdout.decode("mbcs", "replace") if isinstance(p.stdout, bytes) else (p.stdout or "")
    se = p.stderr.decode("mbcs", "replace") if isinstance(p.stderr, bytes) else (p.stderr or "")
    if p.returncode != 0:
        if so.strip():
            print(so.strip()[:4000], file=sys.stderr)
        if se.strip():
            print(se.strip()[:4000], file=sys.stderr)
        raise SystemExit("FAILED: %s (rc=%d)" % (cmd[0], p.returncode))
    if so.strip():
        print(so.strip()[:2000])
    return p


def fresh(p):
    if os.path.isdir(p):
        shutil.rmtree(p)
    os.makedirs(p)


def main():
    sign = "--no-sign" not in sys.argv
    t0 = time.time()
    fresh(BUILD)
    os.makedirs(OUT, exist_ok=True)

    # ---------------- 1. 资源 ----------------
    # 必须用官方 aapt2。之前手写 AXML/arsc 产出的 resources.arsc 结构非法，
    # `aapt2 dump badging` 报 `corrupt ResTable_package chunk`，装到手机上是坏的。
    print("[1/6] 编译资源（aapt2）")
    import rescomp2
    r = rescomp2.compile_res(RES, MANIFEST, os.path.join(BUILD, "res"),
                             package=PACKAGE, min_sdk=MIN_SDK, target_sdk=34)
    print("      manifest %d B, resources.arsc %d B, 其余 %d 个"
          % (len(r["manifest"]), len(r["arsc"]), len(r["files"])))

    # ---------------- 2. Java ----------------
    print("[2/6] 编译 Java")
    # 把 android.jar 复制到 ASCII 路径，避免 javac 对中文路径报 Illegal byte sequence
    os.makedirs(os.path.dirname(ANDROID_JAR_ASCII), exist_ok=True)
    if not os.path.exists(ANDROID_JAR_ASCII):
        shutil.copy2(ANDROID_JAR, ANDROID_JAR_ASCII)
    classes = os.path.join(BUILD, "classes")
    os.makedirs(classes)
    java_files = []
    for root, _, files in os.walk(os.path.join(SRC, "java")):
        for f in files:
            if f.endswith(".java"):
                java_files.append(os.path.join(root, f))
    if not java_files:
        raise SystemExit("没有 .java 源文件：%s" % os.path.join(SRC, "java"))

    rsp = os.path.join(BUILD, "javac.rsp")

    def _f(p):
        # javac 的 @argfile：反斜杠是转义符 → 一律正斜杠 + 双引号。
        # 另外 javac 按系统 ANSI(GBK) 读 rsp，所以文件必须用 mbcs 编码写。
        return '"%s"' % os.path.abspath(p).replace("\\", "/")

    with open(rsp, "w", encoding="mbcs", errors="replace") as fh:
        fh.write("-d %s\n" % _f(classes))
        fh.write("-encoding UTF-8\n")
        fh.write("--release 17\n")
        fh.write("-classpath %s\n" % _f(ANDROID_JAR_ASCII))
        fh.write("-nowarn\n")
        fh.write("-Xlint:none\n")
        for j in java_files:
            fh.write("%s\n" % _f(j))
    run(JAVAC, "@" + rsp)

    # ---------------- 3. dex ----------------
    print("[3/6] 生成 classes.dex")
    dexs = os.path.join(BUILD, "dex")
    os.makedirs(dexs)
    class_files = []
    for root, _, files in os.walk(classes):
        for f in files:
            if f.endswith(".class"):
                class_files.append(os.path.join(root, f))
    if not class_files:
        raise SystemExit("没有 .class 生成")
    run(JAVA, "-cp", os.path.join(BT, "lib", "d8.jar"),
        "com.android.tools.r8.D8",
        "--release",
        "--min-api", str(MIN_SDK),
        "--output", dexs,
        "--lib", ANDROID_JAR_ASCII,
        *class_files)
    dex_files = sorted(f for f in os.listdir(dexs) if f.endswith(".dex"))
    print("      %s (%.1f KB)" % (", ".join(dex_files),
                                  sum(os.path.getsize(os.path.join(dexs, f)) for f in dex_files) / 1024.0))

    # ---------------- 4. 组装 APK ----------------
    print("[4/6] 组装 APK")
    raw = os.path.join(BUILD, "unsigned-unaligned.apk")
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # 4.1 manifest + resources.arsc（必须在最前面，且 arsc 不能压缩会更快，这里压缩也无妨）
        z.writestr("AndroidManifest.xml", r["manifest"], zipfile.ZIP_STORED)
        z.writestr("resources.arsc", r["arsc"], zipfile.ZIP_STORED)
        # 4.2 其余 XML 资源
        for name, data in sorted(r["files"].items()):
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
        # 4.3 dex
        for f in dex_files:
            z.write(os.path.join(dexs, f), f, zipfile.ZIP_DEFLATED)
        # 4.4 assets
        if os.path.isdir(ASSETS):
            for fn in sorted(os.listdir(ASSETS)):
                p = os.path.join(ASSETS, fn)
                if os.path.isfile(p):
                    z.write(p, "assets/" + fn, zipfile.ZIP_DEFLATED)
        # 4.5 原生库：必须 STORED（4 字节对齐由 zipalign 负责）
        if os.path.isdir(JNILIBS):
            for abi in sorted(os.listdir(JNILIBS)):
                d = os.path.join(JNILIBS, abi)
                if not os.path.isdir(d):
                    continue
                for fn in sorted(os.listdir(d)):
                    if fn.endswith(".so"):
                        z.write(os.path.join(d, fn), "lib/%s/%s" % (abi, fn),
                                zipfile.ZIP_STORED)
    print("      未对齐 APK %.1f MB" % (os.path.getsize(raw) / 1048576.0))

    # ---------------- 5. zipalign ----------------
    print("[5/6] zipalign")
    aligned = os.path.join(BUILD, "aligned.apk")
    run(os.path.join(BT, "zipalign.exe"), "-p", "-f", "4", raw, aligned)

    # ---------------- 6. 签名 ----------------
    # 注意：apksigner 也是 JVM 工具，只允许写工作区，所以先签在工作区，再拷到 dist。
    sink = os.path.join(BUILD, "signed.apk")
    if sign:
        print("[6/6] 签名")
        if not os.path.exists(KS):
            print("      生成签名密钥")
            run(KEYTOOL, "-genkeypair", "-keystore", KS, "-alias", KS_ALIAS,
                "-keyalg", "RSA", "-keysize", "2048", "-validity", "36500",
                "-storepass", KS_PASS, "-keypass", KS_PASS,
                "-dname", "CN=LXQuant, OU=App, O=LXQuant, L=CN, ST=CN, C=CN")
        run(os.path.join(BT, "apksigner.bat"), "sign",
            "--ks", KS, "--ks-pass", "pass:" + KS_PASS,
            "--ks-key-alias", KS_ALIAS, "--key-pass", "pass:" + KS_PASS,
            "--min-sdk-version", str(MIN_SDK),
            "--out", sink, aligned)
        run(os.path.join(BT, "apksigner.bat"), "verify", "--verbose", sink)
        final = os.path.join(OUT, APK_NAME)
    else:
        final = os.path.join(OUT, "lxquant-unsigned.apk")
        shutil.copy2(aligned, sink)
    os.makedirs(OUT, exist_ok=True)
    shutil.copy2(sink, final)

    print()
    print("APK : %s" % final)
    print("大小: %.1f MB" % (os.path.getsize(final) / 1048576.0))
    print("耗时: %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
