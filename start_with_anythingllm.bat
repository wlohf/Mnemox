@echo off
chcp 65001 >nul
echo ====================================
echo   启动 StudyAssistant + AnythingLLM
echo ====================================
echo.

echo [1/4] 检查 Node.js 和 Python...
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 Node.js，请先安装 Node.js
    pause
    exit /b 1
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

echo ✓ Node.js 和 Python 已安装
echo.

echo [2/4] 启动 AnythingLLM 服务...
echo 正在启动 AnythingLLM Server (端口 3001)...
start "AnythingLLM Server" cmd /k "cd ..\tools\anything-llm\server && yarn dev"
timeout /t 3 >nul

echo 正在启动 AnythingLLM Collector (端口 8888)...
start "AnythingLLM Collector" cmd /k "cd ..\tools\anything-llm\collector && yarn dev"
timeout /t 3 >nul

echo ✓ AnythingLLM 服务已启动
echo.

echo [3/4] 启动 StudyAssistant 后端...
start "StudyAssistant Backend" cmd /k "cd backend && python -m uvicorn app.main:app --reload --port 8000"
timeout /t 3 >nul

echo ✓ StudyAssistant 后端已启动
echo.

echo [4/4] 启动 StudyAssistant 前端...
start "StudyAssistant Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ====================================
echo   所有服务已启动！
echo ====================================
echo.
echo 🌐 服务地址：
echo   - AnythingLLM Web:        http://localhost:3001
echo   - StudyAssistant API:     http://localhost:8000
echo   - StudyAssistant API文档:  http://localhost:8000/docs
echo   - StudyAssistant Web:     http://localhost:5173
echo.
echo 💡 提示：
echo   - 关闭此窗口不会停止服务
echo   - 要停止所有服务，请关闭对应的命令窗口
echo   - 或运行 stop_all.bat 停止所有服务
echo.
pause
