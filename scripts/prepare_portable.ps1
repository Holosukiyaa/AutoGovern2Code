param(
    [string]$OutputRoot = "",
    [switch]$SkipGit
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot 'build\portable\AutoGovern2Code'
}

$runtimeRoot = Join-Path $repoRoot 'build\windows\runtime'
$devTray = Join-Path $repoRoot 'build\dev-tray'
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$exeSource = $null
foreach ($candidate in @(
        (Join-Path $runtimeRoot 'AutoGovern2Code.exe'),
        (Join-Path $devTray 'AutoGovern2Code.exe')
    )) {
    if (Test-Path -LiteralPath $candidate) {
        $exeSource = $candidate
        break
    }
}
if (-not $exeSource) {
    throw "Native AutoGovern2Code.exe was not found. Build the tray host first."
}

Copy-Item -LiteralPath $exeSource -Destination (Join-Path $OutputRoot 'AutoGovern2Code.exe') -Force
$config = Join-Path $repoRoot 'packaging\windows\desktop\AutoGovern2Code.exe.config'
if (Test-Path -LiteralPath $config) {
    Copy-Item -LiteralPath $config -Destination (Join-Path $OutputRoot 'AutoGovern2Code.exe.config') -Force
}

$ag2cSource = $null
foreach ($candidate in @(
        (Join-Path $runtimeRoot 'ag2c'),
        (Join-Path $devTray 'ag2c')
    )) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'ag2c.exe')) {
        $ag2cSource = $candidate
        break
    }
}
if (-not $ag2cSource) {
    throw "ag2c.exe runtime was not found under build\windows\runtime or build\dev-tray."
}
$ag2cDest = Join-Path $OutputRoot 'ag2c'
if (Test-Path -LiteralPath $ag2cDest) {
    Remove-Item -LiteralPath $ag2cDest -Recurse -Force
}
Copy-Item -LiteralPath $ag2cSource -Destination $ag2cDest -Recurse -Force

Set-Content -LiteralPath (Join-Path $OutputRoot 'portable.ini') -Value "home=." -Encoding ascii
New-Item -ItemType Directory -Path (Join-Path $OutputRoot 'data') -Force | Out-Null

if (-not $SkipGit) {
    $gitRoot = Join-Path $OutputRoot 'git'
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    & python -c "from pathlib import Path; from ag2c.gitops import install_git_runtime; print(install_git_runtime(Path(r'$gitRoot')))"
    if ($LASTEXITCODE -ne 0) {
        throw "MinGit could not be placed at $gitRoot"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $gitRoot 'cmd\git.exe'))) {
        throw "MinGit git.exe is missing from $gitRoot"
    }
}

Write-Output $OutputRoot
