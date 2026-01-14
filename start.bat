@echo off
chcp 65001 >nul
echo ====================================
echo 🚀 启动学习助手系统
echo ====================================
echo.

REM 检查是否在正确的目录
if not exist "backend" (
    echo ❌ 错误：未找到 backend 目录
    echo 请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

if not exist "frontend" (
    echo ❌ 错误：未找到 frontend 目录
    echo 请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

echo ✅ 正在启动后端服务...
start "学习助手-后端" cmd /k "cd backend && python -m app.main"
timeout /t 2 /nobreak >nul

echo ✅ 正在启动前端服务...
start "学习助手-前端" cmd /k "cd frontend && npm run dev"

echo.
echo ====================================
echo ✅ 启动完成！
echo ====================================
echo.
echo 📌 后端地址: http://localhost:8000
echo 📌 前端地址: http://localhost:5173
echo 📌 API文档:  http://localhost:8000/docs
echo.
echo 💡 提示：
echo    - 两个新窗口将自动打开
echo    - 后端窗口显示API日志
echo    - 前端窗口显示访问地址
echo    - 关闭窗口即可停止服务
echo.
echo 🌐 稍后浏览器将自动打开...
timeout /t 3 /nobreak >nul
start http://localhost:5173
echo.
echo ✨ 祝学习愉快！
echo.
pause
