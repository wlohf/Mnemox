@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ====================================
echo    启动学习助手系统
echo ====================================
echo.

REM 检查是否在正确的目录
if not exist "backend" (
    echo [ERROR] 未找到 backend 目录
    echo 请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

if not exist "frontend" (
    echo [ERROR] 未找到 frontend 目录
    echo 请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

REM 清理可能残留的旧进程（占用 8000 和 5173 端口）
echo [INFO] 检查端口占用情况...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] 端口 8000 被 PID %%a 占用，正在关闭...
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo [INFO] 端口 5173 被 PID %%a 占用，正在关闭...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [OK] 正在启动后端服务...
start "StudyAssistant-Backend" cmd /k "cd /d %~dp0backend && python -m app.main"

echo [INFO] 等待后端服务就绪...
set BACKEND_READY=0
for /L %%i in (1,1,30) do (
    if !BACKEND_READY! == 0 (
        powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8000/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
        if !errorlevel! == 0 (
            set BACKEND_READY=1
            echo [OK] 后端服务已就绪
        ) else (
            echo     ...等待中 %%i/30
            timeout /t 1 /nobreak >nul
        )
    )
)
if !BACKEND_READY! == 0 (
    echo [WARN] 后端服务未在30秒内就绪，仍继续启动...
)

echo [OK] 正在启动前端服务...
start "StudyAssistant-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ====================================
echo [OK] 启动完成！
echo ====================================
echo.
echo    后端地址: http://localhost:8000
echo    前端地址: http://localhost:5173
echo    API文档:  http://localhost:8000/docs
echo.
echo 提示：
echo    - 两个新窗口将自动打开
echo    - 后端窗口显示API日志
echo    - 前端窗口显示访问地址
echo    - 关闭窗口即可停止服务
echo.
echo 等待前端服务就绪后打开浏览器...
timeout /t 8 /nobreak >nul
start http://localhost:5173
echo.
echo 祝学习愉快！
echo.
pause
