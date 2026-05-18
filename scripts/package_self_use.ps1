param(
    [string]$OutputDir = "",
    [switch]$IncludeData
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "release"
}

$ReleaseRoot = New-Item -ItemType Directory -Force -Path $OutputDir
$PackageName = "Mnemox-local-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
$Staging = Join-Path $ReleaseRoot.FullName $PackageName
$ZipPath = Join-Path $ReleaseRoot.FullName "$PackageName.zip"

function Copy-TreeClean {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /XD __pycache__ .pytest_cache /XF *.pyc | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed from $Source to $Destination with exit code $LASTEXITCODE"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $normalized = $Content -replace "(`r`n|`n|`r)", "`r`n"
    [System.IO.File]::WriteAllText($Path, $normalized, $utf8NoBom)
}

Write-Host "[1/4] Building frontend..."
Push-Location $FrontendDir
try {
    npm run build
}
finally {
    Pop-Location
}

if (Test-Path $Staging) {
    Remove-Item -Recurse -Force $Staging
}
New-Item -ItemType Directory -Force -Path $Staging | Out-Null

Write-Host "[2/4] Copying runtime files..."
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "backend") | Out-Null
Copy-TreeClean (Join-Path $BackendDir "app") (Join-Path $Staging "backend\app")
Copy-TreeClean (Join-Path $BackendDir "alembic") (Join-Path $Staging "backend\alembic")
Copy-Item (Join-Path $BackendDir "requirements.txt") (Join-Path $Staging "backend\requirements.txt")
Copy-Item (Join-Path $BackendDir "env.example") (Join-Path $Staging "backend\env.example")
Copy-Item (Join-Path $BackendDir "alembic.ini") (Join-Path $Staging "backend\alembic.ini")
Copy-Item (Join-Path $BackendDir "init_db.py") (Join-Path $Staging "backend\init_db.py")
Copy-Item (Join-Path $BackendDir "run_migrations.py") (Join-Path $Staging "backend\run_migrations.py")

Copy-TreeClean (Join-Path $FrontendDir "dist") (Join-Path $Staging "frontend\dist")

if ($IncludeData) {
    Copy-TreeClean (Join-Path $Root "data") (Join-Path $Staging "data")
}
else {
    New-Item -ItemType Directory -Force -Path (Join-Path $Staging "data") | Out-Null
}

Write-Host "[3/4] Writing launcher scripts..."
$StartScript = @'
@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "APP_NAME=Mnemox"
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "VENV_DIR=%ROOT%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"

cd /d "%ROOT%"

echo ====================================
echo        Mnemox 本地软件版
echo ====================================
echo.

call :find_python
if errorlevel 1 goto :fail

if not exist "%PYTHON_EXE%" (
    echo [1/4] 创建本地 Python 环境...
    %PY_LAUNCHER% -m venv "%VENV_DIR%"
    if errorlevel 1 goto :fail
)

if not exist "%VENV_DIR%\.deps-ready" (
    echo [2/4] 安装后端依赖，首次运行可能需要几分钟...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r "%BACKEND_DIR%\requirements.txt"
    if errorlevel 1 goto :fail
    echo ready>"%VENV_DIR%\.deps-ready"
) else (
    echo [OK] 依赖已安装。
)

if not exist "%BACKEND_DIR%\.env" (
    echo [3/4] 创建本地配置...
    for /f "delims=" %%s in ('"%PYTHON_EXE%" -c "import secrets; print(secrets.token_urlsafe(48))"') do set "DEV_SECRET=%%s"
    > "%BACKEND_DIR%\.env" (
        echo DATABASE_URL=sqlite+aiosqlite:///../data/study.db
        echo SECRET_KEY=!DEV_SECRET!
        echo RAG_ENABLED=False
        echo SERVE_FRONTEND=True
        echo FRONTEND_DIST_DIR=frontend/dist
        echo HOST=127.0.0.1
        echo PORT=%PORT%
        echo DEBUG=False
        echo ENVIRONMENT=development
        echo CORS_ORIGINS=["http://127.0.0.1:%PORT%","http://localhost:%PORT%"]
        echo MATERIAL_UPLOAD_MAX_MB=200
    )
) else (
    echo [OK] backend\.env 已存在，保留你的配置。
)

if not exist "%ROOT%data" mkdir "%ROOT%data" >nul 2>nul

echo [4/4] 启动 Mnemox...
call :kill_port %PORT%
start "%APP_NAME%-Backend" cmd /k "cd /d ""%BACKEND_DIR%"" && call ""%VENV_DIR%\Scripts\activate.bat"" && python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%"

set "READY=0"
for /L %%i in (1,1,45) do (
    if "!READY!"=="0" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%URL%/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
        if !errorlevel! EQU 0 (
            set "READY=1"
        ) else (
            echo     等待启动 %%i/45 ...
            timeout /t 1 /nobreak >nul
        )
    )
)

if "%READY%"=="0" (
    echo [WARN] 服务没有在 45 秒内通过健康检查，请查看 Mnemox-Backend 窗口。
) else (
    echo [OK] 已启动: %URL%
    start "" "%URL%"
)

echo.
echo 关闭方式：运行 stop_mnemox.bat，或关闭 Mnemox-Backend 窗口。
echo.
pause
exit /b 0

:find_python
set "PY_LAUNCHER="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PY_LAUNCHER=py -3"
)
if not defined PY_LAUNCHER (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_LAUNCHER=python"
)
if not defined PY_LAUNCHER (
    echo [ERROR] 未检测到 Python 3.10+。请先安装 Python，并勾选 Add Python to PATH。
    exit /b 1
)
exit /b 0

:kill_port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%~1 " ^| findstr "LISTENING"') do (
    echo [INFO] 关闭端口 %~1 上的 PID %%p ...
    taskkill /PID %%p /F >nul 2>nul
)
exit /b 0

:fail
echo.
echo [ERROR] 启动失败，请查看上面的错误信息。
pause
exit /b 1
'@
Write-Utf8NoBom -Path (Join-Path $Staging "start_mnemox.bat") -Content $StartScript

$StopScript = @'
@echo off
setlocal EnableExtensions
chcp 65001 >nul

echo 正在停止 Mnemox...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo 关闭 PID %%p ...
    taskkill /PID %%p /F >nul 2>nul
)
echo 完成。
pause
'@
Write-Utf8NoBom -Path (Join-Path $Staging "stop_mnemox.bat") -Content $StopScript

$Readme = @'
# Mnemox 本地软件包

双击 `start_mnemox.bat` 启动。首次运行会创建 `.venv` 并安装后端依赖，之后会直接打开 `http://127.0.0.1:8000`。

数据默认保存在 `data/study.db`，配置保存在 `backend/.env`。需要 AI 功能时，可以在应用设置页里填写模型提供商和 API Key。

关闭时运行 `stop_mnemox.bat`，或直接关闭 `Mnemox-Backend` 窗口。
'@
Write-Utf8NoBom -Path (Join-Path $Staging "README.md") -Content $Readme

Write-Host "[4/4] Creating zip..."
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $ZipPath -Force

Write-Host "[OK] Package folder: $Staging"
Write-Host "[OK] Zip package:    $ZipPath"
