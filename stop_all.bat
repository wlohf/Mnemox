@echo off
chcp 65001 >nul
echo ====================================
echo   停止所有服务
echo ====================================
echo.

echo 正在停止服务...

:: 停止 Node.js 进程（AnythingLLM）
taskkill /F /FI "WINDOWTITLE eq AnythingLLM*" >nul 2>nul

:: 停止 Python 进程（StudyAssistant Backend）
taskkill /F /FI "WINDOWTITLE eq StudyAssistant Backend*" >nul 2>nul

:: 停止前端开发服务器
taskkill /F /FI "WINDOWTITLE eq StudyAssistant Frontend*" >nul 2>nul

echo.
echo ✓ 所有服务已停止
echo.
pause
