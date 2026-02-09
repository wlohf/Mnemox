@echo off
chcp 65001 >nul
echo ====================================
echo     学习助手 - 一键启动
echo ====================================
echo.

REM 检查Python虚拟环境
if not exist "backend\venv" (
    echo [1/4] 正在创建Python虚拟环境...
    cd backend
    python -m venv venv
    cd ..
)

REM 激活虚拟环境并安装依赖
echo [2/4] 正在安装后端依赖...
cd backend
call venv\Scripts\activate
pip install -r requirements.txt -q

REM 创建.env文件（如果不存在）
if not exist ".env" (
    echo [INFO] 创建默认配置文件...
    copy env.example .env
    echo.
    echo ⚠️  请编辑 backend\.env 文件，配置你的API密钥
    echo.
)

REM 启动后端（后台运行）
echo [3/4] 正在启动后端服务...
start "StudyAssistant-Backend" cmd /k "call venv\Scripts\activate && python -m app.main"
cd ..

REM 检查并启动前端
echo [4/4] 正在启动前端服务...
cd frontend
if not exist "node_modules" (
    echo 安装前端依赖（首次启动需要等待）...
    call npm install
)
start "StudyAssistant-Frontend" cmd /k "npm run dev"
cd ..

echo.
echo ====================================
echo ✅ 启动完成！
echo.
echo 📍 前端地址: http://localhost:5173
echo 📍 后端API:  http://localhost:8000
echo 📍 API文档:  http://localhost:8000/docs
echo.
echo 💡 提示：关闭两个黑色窗口即可停止服务
echo ====================================

REM 等待5秒后自动打开浏览器
timeout /t 5 /nobreak >nul
start http://localhost:5173
