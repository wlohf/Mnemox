# 学习助手启动脚本 (PowerShell)
# 使用方法：右键点击 -> 使用 PowerShell 运行

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "🚀 启动学习助手系统" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# 检查目录
if (-not (Test-Path "backend")) {
    Write-Host "❌ 错误：未找到 backend 目录" -ForegroundColor Red
    Write-Host "请确保在项目根目录运行此脚本" -ForegroundColor Yellow
    Read-Host "按任意键退出"
    exit 1
}

if (-not (Test-Path "frontend")) {
    Write-Host "❌ 错误：未找到 frontend 目录" -ForegroundColor Red
    Write-Host "请确保在项目根目录运行此脚本" -ForegroundColor Yellow
    Read-Host "按任意键退出"
    exit 1
}

# 启动后端
Write-Host "✅ 正在启动后端服务..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; Write-Host '🔧 后端服务运行中...' -ForegroundColor Green; python -m app.main" -WindowStyle Normal

Start-Sleep -Seconds 2

# 启动前端
Write-Host "✅ 正在启动前端服务..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; Write-Host '🎨 前端服务运行中...' -ForegroundColor Cyan; npm run dev" -WindowStyle Normal

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "✅ 启动完成！" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📌 后端地址: http://localhost:8000" -ForegroundColor Yellow
Write-Host "📌 前端地址: http://localhost:5173" -ForegroundColor Yellow
Write-Host "📌 API文档:  http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "💡 提示：" -ForegroundColor Cyan
Write-Host "   - 两个新窗口将自动打开"
Write-Host "   - 后端窗口显示API日志"
Write-Host "   - 前端窗口显示访问地址"
Write-Host "   - 关闭窗口即可停止服务"
Write-Host ""
Write-Host "🌐 正在打开浏览器..." -ForegroundColor Green
Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "✨ 祝学习愉快！" -ForegroundColor Magenta
Write-Host ""
Read-Host "按 Enter 键关闭此窗口"
