param(
    [string]$Version = "1.0.3",
    [string]$Repo = "wlohf/Mnemox",
    [string]$ReleaseNotesPath = "",
    [switch]$Draft
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$DesktopReleaseDir = Join-Path $Root "release\desktop"

if (-not $ReleaseNotesPath) {
    $ReleaseNotesPath = Join-Path $Root "release-notes-v$Version.md"
}

$InstallerName = "Mnemox-Setup-$Version.exe"
$InstallerPath = Join-Path $DesktopReleaseDir $InstallerName
$LatestYmlPath = Join-Path $DesktopReleaseDir "latest.yml"
$BlockmapPath = Join-Path $DesktopReleaseDir "$InstallerName.blockmap"

if (-not (Test-Path $InstallerPath)) {
    throw "未找到安装包：$InstallerPath"
}
if (-not (Test-Path $LatestYmlPath)) {
    throw "未找到 latest.yml：$LatestYmlPath"
}
if (-not (Test-Path $ReleaseNotesPath)) {
    throw "未找到发布说明：$ReleaseNotesPath"
}

$token = $env:GITHUB_TOKEN
if (-not $token) {
    $token = $env:GH_TOKEN
}
if (-not $token) {
    throw "缺少 GITHUB_TOKEN 或 GH_TOKEN，无法创建 GitHub Release"
}

$headers = @{
    Authorization = "Bearer $token"
    Accept = "application/vnd.github+json"
    "User-Agent" = "Mnemox-Release-Script"
}

$tag = "v$Version"
$releaseName = "Mnemox $tag"
$body = Get-Content -Raw $ReleaseNotesPath
$releaseApi = "https://api.github.com/repos/$Repo/releases"

try {
    $existing = Invoke-RestMethod -Method Get -Uri "$releaseApi/tags/$tag" -Headers $headers
    $releaseId = $existing.id
} catch {
    $payload = @{
        tag_name = $tag
        name = $releaseName
        body = $body
        draft = [bool]$Draft
        prerelease = $false
        generate_release_notes = $false
    } | ConvertTo-Json -Depth 4
    $created = Invoke-RestMethod -Method Post -Uri $releaseApi -Headers $headers -Body $payload
    $releaseId = $created.id
}

$release = Invoke-RestMethod -Method Get -Uri "$releaseApi/$releaseId" -Headers $headers
$uploadUrl = ($release.upload_url -replace "\{\?name,label\}", "")

$assets = @($InstallerPath, $LatestYmlPath)
if (Test-Path $BlockmapPath) {
    $assets += $BlockmapPath
}

foreach ($assetPath in $assets) {
    $fileName = [System.IO.Path]::GetFileName($assetPath)
    $assetBytes = [System.IO.File]::ReadAllBytes($assetPath)
    $assetHeaders = @{
        Authorization = "Bearer $token"
        Accept = "application/vnd.github+json"
        "User-Agent" = "Mnemox-Release-Script"
        "Content-Type" = "application/octet-stream"
    }

    $existingAssets = Invoke-RestMethod -Method Get -Uri "$releaseApi/$releaseId/assets" -Headers $headers
    $sameName = @($existingAssets) | Where-Object { $_.name -eq $fileName } | Select-Object -First 1
    if ($sameName) {
        Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$Repo/releases/assets/$($sameName.id)" -Headers $headers | Out-Null
    }

    Invoke-RestMethod -Method Post -Uri "$uploadUrl?name=$([uri]::EscapeDataString($fileName))" -Headers $assetHeaders -Body $assetBytes | Out-Null
}

Write-Host "[OK] GitHub Release ready: https://github.com/$Repo/releases/tag/$tag"
