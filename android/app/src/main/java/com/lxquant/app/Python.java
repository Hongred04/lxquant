package com.lxquant.app;

import android.content.Context;
import android.system.Os;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 把 assets 里的 Python 运行时铺到 files/py，然后让动态链接器把 libpython3.12.so
 * 拉进来，最后在「真的」Python 里跑 lxqboot。
 *
 * 目录布局（home = files/py）：
 *   lib/python312.zip      标准库 .pyc
 *   lib/lib-dynload/*.so   59 个 C 扩展
 *   site/                  numpy / pandas / _native
 *   cache/lxquant/*.pyc    项目代码
 *   lxqboot.py             启动脚本
 *   web/                   手机版网页
 *   data/                  运行时数据
 *
 * 关键点（踩过的坑都写在这）：
 *
 * 1. 必须在 Py_InitializeEx 之前设 PYTHONHOME。
 *    CPython 的 getpath 在 Py_InitializeEx 内部就按 PYTHONHOME 算 sys.path：
 *      [<home>/lib/python312.zip, <home>/lib/python3.12, <home>/lib-dynload]
 *    然后 import encodings —— 找不到就是 fatal error，进程直接 abort，
 *    Java 连异常都接不住。所以路径必须是这个布局，环境变量必须在
 *    nInit() 之前设好。Java 改不了自己的 envp，但 android.system.Os.setenv
 *    走的是 libc setenv，改的就是本进程的 environ，CPython 读得到。
 *
 * 2. 不能自己 dlopen libpython3.12.so：
 *    在 Android 上 System.load()/dlopen() 一个 .so 只是把它映射进来，
 *    JNI_OnLoad 之外它不会自动 registerNatives；而且 libpython 没有任何
 *    JNI 入口，我们也没法用反射拿 handle。所以这里用一个「胶水库」liblxq.so：
 *    它的 DT_NEEDED 里写着 libpython3.12.so，System.loadLibrary("lxq") 之后
 *    动态链接器会把 libpython 一起映射到同一个 link namespace，
 *    Python 的扩展模块（lib-dynload/*.so 里那些 _ssl、_socket）就能解析到符号。
 *
 * 3. 不能 fork 子进程：CPython 初始化之后 fork 出来的子进程在 bionic 上很容易
 *    卡在 atexit / 线程状态上。所以服务直接跑在 Java 传进来的线程里。
 *
 * 4. 解压必须有版本戳：升级 APK 时 assets 变了，但 files/py 还在，
 *    所以要写一个 .stamp 记录 build id。
 */
public class Python {

    private static final String TAG = "lxquant";
    private static final String STAMP = ".stamp";

    public interface Listener {
        void onLine(String line);
        void onError(String msg);
    }

    private final Context ctx;
    private final File home;      // files/py
    private final Listener cb;
    private volatile boolean stopFlag = false;

    public Python(Context ctx, File home, Listener cb) {
        this.ctx = ctx.getApplicationContext();
        this.home = home;
        this.cb = cb;
    }

    // ------------------------------------------------------------------ 主流程
    public void start() throws Exception {
        String buildId = buildId();
        File stamp = new File(home, STAMP);
        String cur = readText(stamp);
        boolean need = !buildId.equals(cur)
                || !new File(home, "lxqboot.py").exists()
                || !new File(home, "lib/python312.zip").isFile()
                || !new File(home, "lib/python3.12/lib-dynload").isDirectory()
                || !new File(home, "site/numpy").isDirectory()
                || !new File(home, "site/certifi/cacert.pem").isFile()
                || !new File(home, "web/index.html").isFile();
        if (need) {
            line("首次运行：解压运行时…");
            extractAssets(home);
            writeText(stamp, buildId);
            line("解压完成");
        } else {
            line("运行时已就绪");
        }

        File lib = new File(home, "lib");
        File web = new File(home, "web");
        // 数据目录必须放在 home 外面！
        // extractAssets() 的第一步是 delTree(home)，升级 APK 时会把 home 整个删掉重建。
        // 放在 files/data（与 files/py 平级）用户数据才不会在升级时丢失。
        File data = new File(home.getParentFile(), "data");
        if (!data.isDirectory() && !data.mkdirs()) {
            throw new IOException("无法创建数据目录 " + data);
        }

        String homePath = home.getAbsolutePath();
        String libPath = lib.getAbsolutePath();
        String sitePath = new File(home, "site").getAbsolutePath();
        String cachePath = new File(home, "cache").getAbsolutePath();
        String dataPath = data.getAbsolutePath();
        String webPath = web.getAbsolutePath();

        // 1) 先把环境变量设好。必须在 nInit() 之前 —— 解释器一初始化就去读它们。
        setenv("PYTHONHOME", homePath);
        setenv("PYTHONPATH", sitePath + ":" + cachePath);
        setenv("PYTHONDONTWRITEBYTECODE", "1");
        setenv("PYTHONUTF8", "1");
        setenv("PYTHONUNBUFFERED", "1");
        setenv("LXQ_MOBILE", "1");
        setenv("LXQ_HOME", homePath);
        setenv("LXQ_LIB", libPath);
        setenv("LXQ_WEB", webPath);
        setenv("LXQ_DATA", dataPath);
        setenv("LXQ_PORT", "8765");
        // CA 根证书。Android 上 OpenSSL 的默认路径 /usr/local/ssl/cert.pem 不存在，
        //    信任库是空的，所有 HTTPS 行情源都会 SSLCertVerificationError。
        //    证书随包放在 site/certifi/cacert.pem，OpenSSL 认 SSL_CERT_FILE 这个变量。
        //    这里设一遍，lxqboot._setup_ssl() 里再兜一遍（两边都设，谁先到都不怕）。
        setenv("SSL_CERT_FILE", new File(home, "site/certifi/cacert.pem").getAbsolutePath());
        // 关掉 Python 写 pyc 到只读目录的尝试
        setenv("HOME", homePath);
        setenv("TMPDIR", cachePath);
        line("环境变量就绪");

        // 2) 这时候才把 liblxq.so（连带 libpython3.12.so）加载进来
        PyApi.setHome(homePath);
        PyApi.nInit();
        // 解释器已经初始化好了，告诉 PyApi 别再走 exec() 里的兜底初始化
        // （否则下面第一个 eval/exec 会再调一次 Py_InitializeEx）
        PyApi.markInited();
        line("已加载 libpython3.12 + liblxq");

        String ver = PyApi.eval("__import__('sys').version");
        line("Python " + (ver != null && ver.length() > 12 ? ver.split(" ")[0] : ver));

        // 3) 再装 sys.path 的兜底项 + 启动服务
        PyApi.exec("import sys\n"
                + "for _p in (" + pyq(cachePath) + ", " + pyq(sitePath) + ", "
                + pyq(libPath) + ", " + pyq(homePath) + "):\n"
                + "    if _p not in sys.path:\n"
                + "        sys.path.insert(0, _p)\n"
                + "del _p\n"
                + "import lxqboot\n"
                + "lxqboot.boot(background=True)\n");
        line("已启动本地服务");
    }

    /** 把路径包成 Python 字面量。Windows 上不会用到，但反斜杠/单引号都转义掉更安全。 */
    private static String pyq(String s) {
        if (s == null) return "''";
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    /** 用 libc setenv 改本进程的 environ，CPython 读得到。 */
    private void setenv(String k, String v) {
        try {
            Os.setenv(k, v, true);
        } catch (Throwable t) {
            Log.w(TAG, "setenv 失败 " + k + " = " + v + " : " + t);
        }
    }

    public void stop() {
        stopFlag = true;
        // 不做强制关闭：进程退出时内核会回收；强行停线程反而容易把 socket 弄成
        // 半开状态，下次启动端口被占。
    }

    // ------------------------------------------------------------------ 解压
    private String buildId() {
        try {
            java.io.InputStream in = ctx.getAssets().open("build_info.json");
            byte[] b = new byte[4096];
            int n = in.read(b);
            in.close();
            org.json.JSONObject o = new org.json.JSONObject(new String(b, 0, n, "UTF-8"));
            return o.optString("version", "1") + "-" + o.optString("python", "3.12")
                    + "-L" + o.optInt("layout", 1);
        } catch (Exception e) {
            return "1-3.12-L1";
        }
    }

    /**
     * 铺 assets。
     *
     * 布局必须精确匹配 CPython 的 getpath.py（3.12），否则 Py_InitializeEx
     * 在 import encodings 时就 fatal error：
     *
     *   STDLIB_SUBDIR        = "lib/python3.12"
     *   PLATSTDLIB_LANDMARK  = "lib/python3.12/lib-dynload"   (getpath.py:180)
     *   ZIP_LANDMARK         = "lib/python312.zip"            (getpath.py:183)
     *
     * PYTHONHOME=<home> 时 prefix=exec_prefix=<home>、stdlib_dir=None，
     * 最后（getpath.py:667,705-726）拼出：
     *   sys.path = [PYTHONPATH...] + [<home>/lib/python312.zip]
     *              + [<home>/lib/python3.12] + [<home>/lib/python3.12/lib-dynload]
     *
     * 注意两点：
     *  - python312.zip 必须是**一个 zip 文件**放在 lib/ 下，不能摊开。
     *  - 扩展模块必须在 lib/python3.12/lib-dynload/，不是 lib/lib-dynload/。
     */
    private void extractAssets(File home) throws IOException {
        delTree(home);
        File lib = new File(home, "lib");
        File dynload = new File(home, "lib/python3.12/lib-dynload");
        if (!dynload.mkdirs() && !dynload.isDirectory()) {
            throw new IOException("无法创建 " + dynload);
        }

        // 1) 标准库：整个 zip 原样落到 <home>/lib/python312.zip（getpath 会把它挂到 sys.path）
        copyAsset("python312.zip", new File(lib, "python312.zip"));

        // 2) 同一个 zip 里的 lib-dynload/*.so 要摊到 <home>/lib/python3.12/lib-dynload/
        //    （zip 里的 .pyc 已经在上面那个 zip 里了，不用再解一遍）
        unzipEntryPrefix("python312.zip", "lib-dynload/", dynload);

        // 3) 其余一切（site/ cache/ web/ lxqboot.py data/）摊到 <home>/
        unzipAsset("pyarm.zip", home, true);
    }

    /** 把 assets 里的文件原样复制出来。 */
    private void copyAsset(String name, File dst) throws IOException {
        File parent = dst.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("mkdir " + parent);
        }
        InputStream in;
        try {
            in = ctx.getAssets().open(name);
        } catch (IOException e) {
            throw new IOException("assets 里没有 " + name, e);
        }
        try {
            OutputStream os = new FileOutputStream(dst);
            try {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            } finally {
                try { os.close(); } catch (Exception ignored) {}
            }
        } finally {
            try { in.close(); } catch (Exception ignored) {}
        }
        line("  " + name + " → " + dst.getName() + " (" + dst.length() + " B)");
    }

    /** 只解 zip 里某个前缀下的条目，并把前缀剥掉后铺到 outDir。 */
    private void unzipEntryPrefix(String name, String prefix, File outDir) throws IOException {
        String base = outDir.getAbsolutePath();
        if (!base.endsWith("/")) base = base + "/";
        final byte[] buf = new byte[1 << 16];
        ZipInputStream zin;
        try {
            zin = new ZipInputStream(ctx.getAssets().open(name));
        } catch (IOException e) {
            throw new IOException("assets 里没有 " + name, e);
        }
        int count = 0;
        try {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                String rel = e.getName();
                if (!e.isDirectory() && rel.startsWith(prefix)) {
                    String sub = rel.substring(prefix.length());
                    if (sub.isEmpty() || sub.contains("..")) {
                        zin.closeEntry();
                        continue;
                    }
                    File f = new File(base + sub);
                    File parent = f.getParentFile();
                    if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                        throw new IOException("mkdir " + parent);
                    }
                    OutputStream os = new FileOutputStream(f);
                    try {
                        int n;
                        while ((n = zin.read(buf)) > 0) os.write(buf, 0, n);
                    } finally {
                        try { os.close(); } catch (Exception ignored) {}
                    }
                    // 扩展模块要被 dlopen，必须可执行
                    //noinspection ResultOfMethodCallIgnored
                    f.setExecutable(true, false);
                    //noinspection ResultOfMethodCallIgnored
                    f.setReadable(true, false);
                    count++;
                }
                zin.closeEntry();
            }
        } finally {
            try { zin.close(); } catch (Exception ignored) {}
        }
        line("  " + prefix + " → " + count + " 个扩展");
    }

    /**
     * @param flat true 表示 zip 里的相对路径直接拼到 outDir 下
     */
    private void unzipAsset(String name, File outDir, boolean flat) throws IOException {
        String base = outDir.getAbsolutePath();
        if (!base.endsWith("/")) base = base + "/";
        final byte[] buf = new byte[1 << 16];
        ZipInputStream zin = null;
        try {
            zin = new ZipInputStream(ctx.getAssets().open(name));
        } catch (IOException e) {
            Log.w(TAG, "assets 里没有 " + name);
            return;
        }
        try {
            ZipEntry e;
            int count = 0;
            while ((e = zin.getNextEntry()) != null) {
                String rel = e.getName();
                if (rel.startsWith("/") || rel.contains("..")) {
                    zin.closeEntry();
                    continue;
                }
                File f = new File(base + rel);
                if (e.isDirectory()) {
                    f.mkdirs();
                    zin.closeEntry();
                    continue;
                }
                File parent = f.getParentFile();
                if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                    throw new IOException("mkdir " + parent);
                }
                OutputStream os = new FileOutputStream(f);
                try {
                    int n;
                    while ((n = zin.read(buf)) > 0) os.write(buf, 0, n);
                } finally {
                    try { os.close(); } catch (Exception ignored) {}
                }
                // 所有 .so 都要能 mmap(PROT_EXEC) 才能 dlopen。
                // 除了 lib/lib-dynload/*.so，还有 site/numpy/*.so、site/pandas/*.so
                // （共 65 个），漏一个就 import 失败。
                if (rel.endsWith(".so")) {
                    //noinspection ResultOfMethodCallIgnored
                    f.setExecutable(true, false);
                    //noinspection ResultOfMethodCallIgnored
                    f.setReadable(true, false);
                }
                zin.closeEntry();
                if ((++count % 400) == 0) line("解压中… " + count);
            }
            line("  " + name + " → " + count + " 个文件");
        } finally {
            try { zin.close(); } catch (Exception ignored) {}
        }
    }

    private static void delTree(File f) {
        if (f == null || !f.exists()) return;
        if (f.isDirectory()) {
            File[] kids = f.listFiles();
            if (kids != null) for (File k : kids) delTree(k);
        }
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    private String readText(File f) {
        try {
            java.io.InputStream in = new java.io.FileInputStream(f);
            byte[] b = new byte[256];
            int n = in.read(b);
            in.close();
            return new String(b, 0, Math.max(n, 0), "UTF-8").trim();
        } catch (Exception e) {
            return "";
        }
    }

    private void writeText(File f, String s) {
        try {
            OutputStream os = new FileOutputStream(f);
            os.write(s.getBytes("UTF-8"));
            os.close();
        } catch (Exception ignored) {
        }
    }

    private void line(String s) {
        if (cb != null) cb.onLine(s);
    }
}
