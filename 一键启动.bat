@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "APP_NAME=Mnemox"
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "FRONTEND_URL=http://localhost:%FRONTEND_PORT%"
set "BACKEND_URL=http://localhost:%BACKEND_PORT%"
set "BACKEND_HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%"
set "VENV_DIR=%BACKEND_DIR%\venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PY_LAUNCHER="

cd /d "%ROOT%"

echo ====================================
echo        %APP_NAME% 一键本地体验
echo ====================================
echo.
echo 这个脚本会自动准备本地开发环境：
echo   1. 检查 Python 和 Node.js
echo   2. 创建 backend\.env 开发配置
echo   3. 安装后端/前端依赖
echo   4. 启动后端和 Web UI
echo.

if not exist "%BACKEND_DIR%" (
    echo [ERROR] 未找到 backend 目录，请在项目根目录运行。
    pause
    exit /b 1
)
if not exist "%FRONTEND_DIR%" (
    echo [ERROR] 未找到 frontend 目录，请在项目根目录运行。
    pause
    exit /b 1
)

call :find_python
if errorlevel 1 goto :fail

where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未检测到 Node.js。
    echo 请先安装 Node.js 18+ LTS: https://nodejs.org/
    goto :fail
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未检测到 npm。请确认 Node.js 安装完整并已加入 PATH。
    goto :fail
)

echo [OK] Python: %PY_CMD%
for /f "delims=" %%v in ('node -v 2^>nul') do echo [OK] Node.js: %%v
for /f "delims=" %%v in ('npm -v 2^>nul') do echo [OK] npm: %%v

echo.
echo [1/5] 准备后端虚拟环境...
if not exist "%PYTHON_EXE%" (
    %PY_LAUNCHER% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] 创建 Python 虚拟环境失败。
        goto :fail
    )
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] 虚拟环境 Python 不存在: "%PYTHON_EXE%"
    goto :fail
)

echo [2/5] 准备本地开发配置...
if not exist "%BACKEND_DIR%\.env" (
    for /f "delims=" %%s in ('%PY_LAUNCHER% -c "import secrets; print(secrets.token_urlsafe(48))"') do set "DEV_SECRET=%%s"
    if not defined DEV_SECRET (
        echo [ERROR] 生成本地 SECRET_KEY 失败。
        goto :fail
    )
    > "%BACKEND_DIR%\.env" (
        echo DATABASE_URL=sqlite+aiosqlite:///./data/study.db
        echo SECRET_KEY=!DEV_SECRET!
        echo DEFAULT_AI_PROVIDER=deepseek
        echo DEEPSEEK_API_KEY=
        echo DEEPSEEK_MODEL=deepseek-chat
        echo DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
        echo DEBUG=True
        echo ENVIRONMENT=development
        echo HOST=0.0.0.0
        echo PORT=%BACKEND_PORT%
        echo CORS_ORIGINS=["http://localhost:%FRONTEND_PORT%", "http://localhost:3000"]
        echo RAG_ENABLED=False
        echo MATERIAL_UPLOAD_MAX_MB=50
    )
    if errorlevel 1 (
        echo [ERROR] 创建 backend\.env 失败。
        goto :fail
    )
    echo [OK] 已自动创建 backend\.env。本地体验默认关闭 RAG，可进设置页再填 AI Key。
) else (
    echo [OK] backend\.env 已存在，保留你的配置。
)

if not exist "%BACKEND_DIR%\data" mkdir "%BACKEND_DIR%\data" >nul 2>nul

echo [3/5] 安装/检查后端依赖...
if exist "%VENV_DIR%\.mnemox-deps-ready" (
    echo [OK] 检测到后端依赖已安装，跳过 pip install。
) else (
    "%PYTHON_EXE%" -m pip install --upgrade pip >nul
    "%PYTHON_EXE%" -m pip install -r "%BACKEND_DIR%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] 后端依赖安装失败。请检查网络或 pip 源。
        goto :fail
    )
    echo ready>"%VENV_DIR%\.mnemox-deps-ready"
)

echo [4/5] 安装/检查前端依赖...
cd /d "%FRONTEND_DIR%"
if exist node_modules (
    echo [OK] 检测到前端依赖已安装，跳过 npm install。
) else (
    call npm install
    if errorlevel 1 (
        echo [ERROR] 前端依赖安装失败。请检查网络或 npm 源。
        cd /d "%ROOT%"
        goto :fail
    )
)
cd /d "%ROOT%"

echo [5/5] 释放端口并启动服务...
call :kill_port %BACKEND_PORT%
call :kill_port %FRONTEND_PORT%

echo [INFO] 正在启动后端窗口...
start "%APP_NAME%-Backend" cmd /k "cd /d ""%BACKEND_DIR%"" && call venv\Scripts\activate && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port %BACKEND_PORT%"

echo [INFO] 正在启动前端窗口...
start "%APP_NAME%-Frontend" cmd /k "cd /d ""%FRONTEND_DIR%"" && npm run dev -- --host 0.0.0.0 --port %FRONTEND_PORT%"

echo [INFO] 等待前端显示入口...
timeout /t 6 /nobreak >nul
start "" "%FRONTEND_URL%"

echo [INFO] 等待后端健康检查...
set "BACKEND_READY=0"
for /L %%i in (1,1,45) do (
    if "!BACKEND_READY!"=="0" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%BACKEND_HEALTH_URL%/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
        if !errorlevel! EQU 0 (
            set "BACKEND_READY=1"
            echo [OK] 后端已就绪: %BACKEND_URL%
        ) else (
            echo     等待后端启动 %%i/45 ...
            timeout /t 1 /nobreak >nul
        )
    )
)

if "%BACKEND_READY%"=="0" (
    echo [WARN] 后端 45 秒内未通过健康检查。请查看 %APP_NAME%-Backend 窗口错误。
)

echo.
echo ====================================
echo [OK] 已启动本地体验环境
echo ====================================
echo Web UI:   %FRONTEND_URL%
echo 后端 API: %BACKEND_URL%
echo API文档:  %BACKEND_URL%/docs
echo.
echo 如果页面打不开：
echo   1. 查看 %APP_NAME%-Backend 和 %APP_NAME%-Frontend 两个窗口里的报错
echo   2. 确认 Python/Node 版本和依赖安装是否成功
echo   3. 如需 AI 功能，在页面设置或 backend\.env 中填写 API Key
echo.
echo 关闭两个服务窗口即可停止服务，或运行 stop.bat。
echo.
pause
exit /b 0

:find_python
set "PY_CMD="
set "PY_LAUNCHER="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY_CMD=py -3"
        set "PY_LAUNCHER=py -3"
    )
)
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY_CMD=python"
        set "PY_LAUNCHER=python"
    )
)
if not defined PY_CMD (
    echo [ERROR] 未检测到 Python 3.10+。
    echo 请先安装 Python，并勾选 Add Python to PATH: https://www.python.org/downloads/
    exit /b 1
)
exit /b 0

:kill_port
set "PORT=%~1"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo [INFO] 端口 %PORT% 被 PID %%p 占用，正在关闭...
    taskkill /PID %%p /F >nul 2>nul
)
exit /b 0

:fail
echo.
echo ====================================
echo [FAILED] 启动失败
echo ====================================
echo 请复制上面的错误信息发给我，我可以继续帮你定位。
echo.
pause
exit /b 1
