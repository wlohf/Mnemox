@echo off
setlocal EnableExtensions
chcp 65001 >nul

echo ====================================
echo        停止 Mnemox 本地服务
echo ====================================
echo.

call :kill_port 8000
call :kill_port 5173

echo.
echo [OK] 已尝试停止 8000/5173 端口上的 Mnemox 服务。
echo 如果还有残留窗口，直接关闭对应的 Backend/Frontend 窗口即可。
echo.
pause
exit /b 0

:kill_port
set "PORT=%~1"
set "FOUND=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set "FOUND=1"
    echo [INFO] 关闭端口 %PORT% 上的 PID %%p ...
    taskkill /PID %%p /F >nul 2>nul
)
if "%FOUND%"=="0" echo [INFO] 端口 %PORT% 未发现监听进程。
exit /b 0
