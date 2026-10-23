package com.lxquant.app;

/** Python 端抛上来的异常，message 是完整的 traceback。 */
public class PythonError extends RuntimeException {
    public PythonError(String msg) {
        super(msg);
    }
}
