# Mnemox 一键本地体验启动脚本
# 如果 PowerShell 执行策略阻止运行，请直接双击 start.bat。
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bat = Join-Path $Root 'start.bat'
if (-not (Test-Path $Bat)) {
  Write-Host '未找到 start.bat，请确认在项目根目录运行。' -ForegroundColor Red
  Read-Host '按 Enter 退出'
  exit 1
}
& $Bat
