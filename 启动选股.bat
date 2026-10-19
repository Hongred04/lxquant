@echo off
chcp 936 >nul
title lxquant 量价低位选股
cd /d "%~dp0"

set "PY=%~dp0runtime\python.exe"
if exist "%PY%" goto run

set "PY=C:\Users\macro\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if exist "%PY%" goto run

set "PY=python"

:run
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo.
echo   ==========================================
echo      lxquant  量价低位选股
echo      策略: 连续3日尾盘站上均价线 + 筹码低位
echo   ==========================================
echo.
echo   正在启动, 浏览器会自动打开...
echo   关闭这个黑窗口即退出程序
echo.
"%PY%" run.py %*
if errorlevel 1 pause
