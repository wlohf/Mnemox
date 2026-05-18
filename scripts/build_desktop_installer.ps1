param(
    [string]$Python = "py -3.12",
    [string]$ElectronMirror = "https://npmmirror.com/mirrors/electron/",
    [string]$ElectronBuilderBinariesMirror = "https://npmmirror.com/mirrors/electron-builder-binaries/",
    [switch]$SkipBackendExe
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$DesktopDir = Join-Path $Root "desktop"
$BuildDir = Join-Path $Root "desktop-build"
$BackendBuildDir = Join-Path $BuildDir "backend"
$PyVenv = Join-Path $BuildDir ".py312"
$ReleaseDesktopDir = Join-Path $Root "release\desktop"

function Run-Cmd {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    Push-Location $WorkingDirectory
    try {
        cmd /d /c $Command
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed ($LASTEXITCODE): $Command"
        }
    }
    finally {
        Pop-Location
    }
}

function Run-CmdWithEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [hashtable]$Environment = @{}
    )

    $oldValues = @{}
    foreach ($key in $Environment.Keys) {
        $oldValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    try {
        Run-Cmd $Command $WorkingDirectory
    }
    finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $oldValues[$key], "Process")
        }
    }
}

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReleaseDesktopDir | Out-Null

Write-Host "[1/5] Building frontend..."
Run-Cmd "npm run build" $FrontendDir

if (-not $SkipBackendExe) {
    Write-Host "[2/5] Building backend executable with PyInstaller..."
    if (-not (Test-Path (Join-Path $PyVenv "Scripts\python.exe"))) {
        Run-Cmd "$Python -m venv `"$PyVenv`"" $Root
    }
    $PyExe = Join-Path $PyVenv "Scripts\python.exe"
    Run-Cmd "`"$PyExe`" -m pip install --upgrade pip" $Root
    Run-Cmd "`"$PyExe`" -m pip install -r `"$BackendDir\requirements.txt`" pyinstaller" $Root

    if (Test-Path $BackendBuildDir) {
        Remove-Item -Recurse -Force $BackendBuildDir
    }
    New-Item -ItemType Directory -Force -Path $BackendBuildDir | Out-Null

    $DistPath = Join-Path $BackendBuildDir "dist"
    $WorkPath = Join-Path $BackendBuildDir "work"
    $SpecPath = Join-Path $BackendBuildDir "spec"
    New-Item -ItemType Directory -Force -Path $SpecPath | Out-Null

    $Pyinstaller = @(
        "`"$PyExe`" -m PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name mnemox-backend",
        "--distpath `"$DistPath`"",
        "--workpath `"$WorkPath`"",
        "--specpath `"$SpecPath`"",
        "--collect-all app",
        "--collect-submodules app",
        "--collect-submodules uvicorn",
        "--collect-submodules fastapi",
        "--collect-submodules sqlalchemy",
        "--collect-submodules jose",
        "--collect-submodules multipart",
        "--hidden-import aiosqlite",
        "--hidden-import bcrypt",
        "--hidden-import cryptography",
        "`"$BackendDir\desktop_main.py`""
    ) -join " "

    Run-Cmd $Pyinstaller $BackendDir

    $BuiltBackend = Join-Path $DistPath "mnemox-backend"
    if (-not (Test-Path (Join-Path $BuiltBackend "mnemox-backend.exe"))) {
        throw "PyInstaller did not create mnemox-backend.exe"
    }

    Copy-Item -Recurse -Force $BuiltBackend (Join-Path $BackendBuildDir "mnemox-backend")
}

Write-Host "[3/5] Installing desktop dependencies..."
if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    $npmEnv = @{}
    if ($ElectronMirror) {
        $npmEnv["ELECTRON_MIRROR"] = $ElectronMirror
        $npmEnv["npm_config_electron_mirror"] = $ElectronMirror
    }
    if ($ElectronBuilderBinariesMirror) {
        $npmEnv["ELECTRON_BUILDER_BINARIES_MIRROR"] = $ElectronBuilderBinariesMirror
    }
    Run-CmdWithEnv "npm install" $DesktopDir $npmEnv
}

Write-Host "[4/5] Running desktop tests..."
Run-Cmd "npm test" $DesktopDir

Write-Host "[5/5] Building Windows installer..."
$stalePatterns = @(
    "Mnemox Setup *.exe",
    "Mnemox Setup *.exe.blockmap",
    "Mnemox-Setup-*.exe",
    "Mnemox-Setup-*.exe.blockmap"
)
foreach ($pattern in $stalePatterns) {
    Get-ChildItem -Path $ReleaseDesktopDir -Filter $pattern -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}
$builderEnv = @{}
if ($ElectronMirror) {
    $builderEnv["ELECTRON_MIRROR"] = $ElectronMirror
    $builderEnv["npm_config_electron_mirror"] = $ElectronMirror
}
if ($ElectronBuilderBinariesMirror) {
    $builderEnv["ELECTRON_BUILDER_BINARIES_MIRROR"] = $ElectronBuilderBinariesMirror
}
Run-CmdWithEnv "npm run dist" $DesktopDir $builderEnv

Write-Host "[OK] Desktop installer output: $(Join-Path $Root 'release\desktop')"
