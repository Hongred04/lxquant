package com.lxquant.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.ServiceWorkerClient;
import android.webkit.ServiceWorkerController;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.HashMap;
import java.util.Map;

/**
 * 量价选股 · 安卓版
 *
 * 后台是一个跑在本机的 Python 服务（assets 里解出来到私有目录再启动），
 * 前台是一个 WebView 显示重新设计的手机界面。
 *
 * 为什么不用 https://appassets.androidplatform.net 那种方案：
 * 那样网页是安全上下文，里面的 fetch('/api/...') 会打到这个假域名上，
 * 必须自己在 WebView 里转发。这里直接用 http://127.0.0.1:端口，
 * fetch 天然就是同源的，一个字节都不用转发。
 */
public class MainActivity extends Activity {

    private static final String TAG = "lxquant";

    /** 网页里 fetch('/api/x') 会被拼成 http://127.0.0.1:PORT/api/x */
    private static final String BASE_URL = "http://127.0.0.1:8765/";

    private WebView web;
    private FrameLayout root;
    private TextView boot;
    private Python py;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean ready = false;
    private volatile String pyTail = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        root.setBackgroundColor(0xFF0B0E13);
        setContentView(root);

        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0E13);
        configureWebView(web);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        boot = new TextView(this);
        boot.setTextColor(0xFF9AA7B8);
        boot.setTextSize(15);
        boot.setPadding(dp(26), dp(26), dp(26), dp(26));
        boot.setText("正在启动…\n首次打开需要准备数据，请稍候");
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(120);
        root.addView(boot, lp);

        startPython();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    // ------------------------------------------------------------ WebView
    private void configureWebView(WebView w) {
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setTextZoom(100);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setMediaPlaybackRequiresUserGesture(false);
        if (Build.VERSION.SDK_INT >= 21) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
        w.addJavascriptInterface(new Bridge(), "Native");
        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                Log.i(TAG, "console: " + cm.message() + " @" + cm.lineNumber());
                return true;
            }
        });
        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (u != null && "127.0.0.1".equals(u.getHost())) return false;
                // 导出 CSV / 外部链接：交给系统
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) {
                }
                return true;
            }
        });
        if (Build.VERSION.SDK_INT >= 24) {
            try {
                ServiceWorkerController.getInstance().setServiceWorkerClient(new ServiceWorkerClient() {
                    @Override
                    public WebResourceResponse shouldInterceptRequest(WebResourceRequest request) {
                        return null;
                    }
                });
            } catch (Throwable ignored) {
            }
        }
    }

    /** 给网页留的原生能力（现在只用到震动/返回键相关） */
    private class Bridge {
        @JavascriptInterface
        public String ping() { return "pong"; }

        @JavascriptInterface
        public void exit() {
            ui.post(new Runnable() {
                public void run() { finish(); }
            });
        }
    }

    // ------------------------------------------------------------ Python
    private void startPython() {
        final File dir = new File(getFilesDir(), "py");
        py = new Python(this, dir, new Python.Listener() {
            @Override
            public void onLine(String line) {
                pyTail = (pyTail + line + "\n");
                if (pyTail.length() > 4000) pyTail = pyTail.substring(pyTail.length() - 4000);
                Log.i(TAG, "py: " + line);
                // 解压进度之类的阶段性信息显示在启动页上
                if (!ready && line != null && !line.trim().isEmpty()) {
                    final String s = line;
                    ui.post(new Runnable() {
                        public void run() {
                            if (!ready) boot.setText(s);
                        }
                    });
                }
            }

            @Override
            public void onError(final String msg) {
                Log.e(TAG, "python 出错: " + msg);
                ui.post(new Runnable() {
                    public void run() {
                        boot.setText("启动失败\n\n" + msg + "\n\n（这段信息在 logcat 里搜 lxquant 能看到）");
                    }
                });
            }
        });
        new Thread(new Runnable() {
            public void run() {
                try {
                    py.start();
                } catch (final Throwable t) {
                    ui.post(new Runnable() {
                        public void run() {
                            boot.setText("启动失败\n\n" + Log.getStackTraceString(t));
                        }
                    });
                    return;
                }
                // Python 的 stdout 在同一个进程里直接写 fd 1（logcat），
                // Java 侧读不到 "LXQ-READY"，所以这里自己轮询 /api/ping。
                waitForServer();
            }
        }, "py-boot").start();
    }

    /** 轮询本机服务，直到 /api/ping 通为止（最多等 120 秒）。 */
    private void waitForServer() {
        final long deadline = System.currentTimeMillis() + 120_000L;
        int tries = 0;
        while (System.currentTimeMillis() < deadline) {
            if (pingOnce()) {
                ui.post(new Runnable() {
                    public void run() { onServerReady(); }
                });
                return;
            }
            tries++;
            if (tries % 20 == 0) {
                final int t = tries;
                ui.post(new Runnable() {
                    public void run() {
                        if (!ready) boot.setText("行情引擎启动较慢…（已等待 " + (t / 2) + " 秒）");
                    }
                });
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException e) {
                return;
            }
        }
        ui.post(new Runnable() {
            public void run() {
                boot.setText("行情引擎没能起来\n\n日志：\n" + pyTail);
            }
        });
    }

    private boolean pingOnce() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(BASE_URL + "api/ping").openConnection();
            c.setConnectTimeout(1200);
            c.setReadTimeout(1500);
            return c.getResponseCode() == 200;
        } catch (Throwable e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void onServerReady() {
        ready = true;
        boot.setText("正在打开界面…");
        web.loadUrl(BASE_URL + "index.html");
        // 真机上第一次加载时 Python 可能还在热身，兜一层：3 秒后如果界面还是空的就再刷一次
        ui.postDelayed(new Runnable() {
            public void run() {
                if (!ready) return;
                boot.setVisibility(View.GONE);
            }
        }, 500);
    }

    @Override
    public void onBackPressed() {
        if (web != null) {
            web.evaluateJavascript(
                    "(function(){var s=document.querySelector('#sheet');var m=document.querySelector('#modal');" +
                    "if(s&&!s.hidden){window.closeStock&&closeStock();return 'sheet';}" +
                    "if(m&&!m.hidden){window.closeModal&&closeModal();return 'modal';}" +
                    "if(window.S&&window.S.view!=='screen'){go('screen');return 'view';}" +
                    "return 'exit';})()", value -> {
                        if (value == null || value.contains("exit")) {
                            moveTaskToBack(true);
                        }
                    });
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (py != null) py.stop();
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
