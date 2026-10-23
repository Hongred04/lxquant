package com.lxquant.app;

import java.io.File;

/**
 * 直接对着 liblxq.so 的 JNI 入口。
 *
 * liblxq.so 是手工用 aarch64 机器码拼出来的（见 _apk/mklib.py），
 * 它的 DT_NEEDED 是 libpython3.12.so，所以 System.loadLibrary("lxq")
 * 会顺带把 CPython 一起映射进来。
 *
 * 由于我们不能编译 C，Python 侧和 Java 侧的桥全部靠 PyRun_SimpleString + 字符串：
 *   - exec(code)  ->  Java_com_lxquant_app_PyApi_nExec
 *   - eval(code)  ->  先 exec 把结果写进模块变量，再用 python_get() 取回
 *
 * Java 对象传给 Python 通过一个静态字段 + PythonCallback 接口。
 */
public final class PyApi {

    static {
        System.loadLibrary("lxq");
    }

    private PyApi() {}

    // ---------------------------------------------------------------- native
    public static native boolean nPing();
    public static native boolean nAlive();
    public static native void nInit();
    public static native void nExec(String code);

    // ---------------------------------------------------------------- java->py
    /**
     * 首次调用会初始化解释器并装好 sys.path。出错抛 PythonError。
     *
     * 正常情况下 Python.start() 已经先调过 nInit()（因为 PYTHONHOME 必须在那之前
     * 用 Os.setenv 设好），这里只是兜底：万一有人直接调 exec()。
     */
    public static void exec(String code) {
        boolean first;
        synchronized (PyApi.class) {
            first = !inited;
        }
        if (first) {
            nInit();
            String h = HOME;
            if (h == null) h = "";
            // 注意：PYTHONHOME/PYTHONPATH 已经在 Python.start() 里用 Os.setenv 设过，
            // getpath 已经把 lib/python312.zip、lib/lib-dynload、site、cache 都算进
            // sys.path 了。这里只做去重兜底，不改变优先级。
            nExec("import sys\n"
                    + "for _p in ('" + esc(h) + "/cache', '" + esc(h) + "/site',"
                    + " '" + esc(h) + "/lib', '" + esc(h) + "'):\n"
                    + "    if _p not in sys.path:\n"
                    + "        sys.path.insert(0, _p)\n"
                    + "del _p\n"
                    + "import lxqboot\n"
                    + "lxqboot.install_java()\n");
            synchronized (PyApi.class) {
                inited = true;
            }
        }
        nExec(code);
    }

    /** Python.start() 用：只把 inited 置位，不重复跑初始化脚本。 */
    static void markInited() {
        synchronized (PyApi.class) {
            inited = true;
        }
    }

    /** 执行代码并返回 str 结果。 */
    public static String eval(String expr) {
        exec("__lxq_r = (" + expr + ")");
        String out = pyGet("__lxq_r");
        exec("__lxq_r = None");
        return out;
    }

    /**
     * 取 Python 侧变量的 str() 值。
     *
     * liblxq.so 是手写机器码，让它返回 jstring 要构造 Java 对象，代价太高；
     * 所以 lxqboot.set_out() 把结果写到 <home>/cache/.out，这里读回来。
     */
    public static String pyGet(String name) {
        String h = HOME;
        if (h == null || h.isEmpty()) return "";
        File f = new File(h, "cache/.out");
        // 先删掉旧值，避免 Python 侧失败时读到上一次的残留
        //noinspection ResultOfMethodCallIgnored
        f.delete();
        try {
            exec("import lxqboot as _b\n_b.set_out(" + name + ")\n");
        } catch (Throwable t) {
            return "";
        }
        try {
            java.io.InputStream in = new java.io.FileInputStream(f);
            byte[] b = new byte[1 << 20];
            int n = 0, r;
            while (n < b.length && (r = in.read(b, n, b.length - n)) > 0) n += r;
            in.close();
            return new String(b, 0, n, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    // ---------------------------------------------------------------- 环境
    private static volatile String HOME = "";

    public static void setHome(String home) {
        HOME = home;
    }

    public static String getHome() {
        return HOME;
    }

    // ---------------------------------------------------------------- 回调
    public interface Callback {
        String call(String json);
    }

    private static volatile Callback CB;

    public static void setCallback(Callback cb) {
        CB = cb;
    }

    /** 由 Python 侧通过 ctypes 回调，参数/返回值都是 JSON 字符串。 */
    public static String onCall(String json) {
        Callback cb = CB;
        if (cb == null) return "null";
        try {
            return cb.call(json);
        } catch (Throwable t) {
            return "{\"error\":\"" + esc(t.toString()) + "\"}";
        }
    }

    private static volatile String OUT;

    /** 由 Python 侧写回，配合 pyGet 使用。 */
    public static void setOut(String s) {
        OUT = s;
    }

    private static boolean inited = false;

    private static String esc(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("'", "\\'");
    }
}
