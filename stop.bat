@echo off
chcp 65001 >nul
echo ====================================
echo 🛑 停止学习助手系统
echo ====================================
echo.

echo 正在查找运行中的服务...
echo.

REM 停止 Python 后端进程
tasklist | find /i "python.exe" >nul
if %errorlevel% equ 0 (
    echo 🔴 停止后端服务 (Python)...
    taskkill /F /IM python.exe /T >nul 2>&1
    echo ✅ 后端已停止
) else (
    echo ℹ️  未发现运行中的后端服务
)

echo.

REM 停止 Node.js 前端进程
tasklist | find /i "node.exe" >nul
if %errorlevel% equ 0 (
    echo 🔴 停止前端服务 (Node.js)...
    taskkill /F /IM node.exe /T >nul 2>&1
    echo ✅ 前端已停止
) else (
    echo ℹ️  未发现运行中的前端服务
)

echo.
echo ====================================
echo ✅ 所有服务已停止
echo ====================================
echo.
pause
