param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildRoot = Join-Path $repoRoot 'build\windows'
$runtimeRoot = Join-Path $buildRoot 'runtime'
$installerRoot = Join-Path $buildRoot 'installer'
$launcher = Join-Path $repoRoot 'packaging\windows\launcher.py'
$installerScript = Join-Path $repoRoot 'packaging\windows\AutoGovern2Code.iss'
$skillSource = Join-Path $repoRoot 'src\ag2c\skills'
$skillData = "${skillSource}:ag2c\skills"
$desktopEntry = Join-Path $repoRoot 'packaging\windows\tray.py'
$desktopNotice = Join-Path $repoRoot 'packaging\windows\NOTICE-imgui.txt'

if (-not (Test-Path -LiteralPath (Join-Path $skillSource 'ag2c-governed-development\SKILL.md'))) {
    throw "Packaged AG2C Skill source is missing from $skillSource."
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $packageVersion = (& python -c "import ag2c; print(ag2c.__version__)" 2>&1 | Out-String).Trim()
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
if ($LASTEXITCODE -ne 0 -or $packageVersion -ne $Version) {
    throw "Requested installer version $Version does not match package version $packageVersion."
}

if (Test-Path -LiteralPath $buildRoot) {
    $resolvedBuild = (Resolve-Path -LiteralPath $buildRoot).Path
    if (-not $resolvedBuild.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean build directory outside the repository: $resolvedBuild"
    }
    Remove-Item -LiteralPath $resolvedBuild -Recurse -Force
}
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $installerRoot -Force | Out-Null

& python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name ag2c `
    --paths (Join-Path $repoRoot 'src') `
    --add-data $skillData `
    --distpath $runtimeRoot `
    --workpath (Join-Path $buildRoot 'pyinstaller') `
    --specpath (Join-Path $buildRoot 'spec') `
    $launcher
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$runtime = Join-Path $runtimeRoot 'ag2c\ag2c.exe'
$runtimeVersion = (& $runtime --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $runtimeVersion -ne "AutoGovern2Code $Version") {
    throw "Frozen runtime smoke test failed: $runtimeVersion"
}

$skillProbeRoot = Join-Path $buildRoot 'skill-probe'
& $runtime skill install --destination $skillProbeRoot | Out-Null
$skillProbeExitCode = $LASTEXITCODE
$skillProbe = Join-Path $skillProbeRoot 'ag2c-governed-development\SKILL.md'
if ($skillProbeExitCode -ne 0 -or -not (Test-Path -LiteralPath $skillProbe)) {
    throw "Frozen runtime could not install its packaged Skill (exit code $skillProbeExitCode)."
}
Remove-Item -LiteralPath $skillProbeRoot -Recurse -Force

if (-not (Test-Path -LiteralPath $desktopEntry)) {
    throw "Desktop tray host entry is missing: $desktopEntry"
}
$gitRoot = Join-Path $runtimeRoot 'git'
$env:PYTHONPATH = Join-Path $repoRoot 'src'
try {
    & python -c "from pathlib import Path; from ag2c.gitops import install_git_runtime; print(install_git_runtime(Path(r'$gitRoot')))"
    if ($LASTEXITCODE -ne 0) {
        throw "Bundled MinGit materialize failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
if (-not (Test-Path -LiteralPath (Join-Path $gitRoot 'cmd\git.exe'))) {
    throw "Bundled MinGit was not placed at $gitRoot"
}
$ag2cGit = Join-Path $runtimeRoot 'ag2c\git'
if (Test-Path -LiteralPath $ag2cGit) {
    Remove-Item -LiteralPath $ag2cGit -Recurse -Force
}
Copy-Item -LiteralPath $gitRoot -Destination $ag2cGit -Recurse -Force
& python -m pip install --disable-pip-version-check "imgui-bundle>=1.5"
if ($LASTEXITCODE -ne 0) {
    throw "imgui-bundle install failed with exit code $LASTEXITCODE."
}
$trayDist = Join-Path $buildRoot 'tray'
& python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name AutoGovern2Code `
    --paths (Join-Path $repoRoot 'src') `
    --hidden-import ag2c.imgui_tray `
    --hidden-import ag2c.tray_host `
    --exclude-module imgui_bundle.imguizmo `
    --exclude-module imgui_bundle.immvision `
    --exclude-module imgui_bundle.implot3d `
    --exclude-module PySide6 `
    --distpath $trayDist `
    --workpath (Join-Path $buildRoot 'pyinstaller-tray') `
    --specpath (Join-Path $buildRoot 'spec-tray') `
    $desktopEntry
if ($LASTEXITCODE -ne 0) {
    throw "Desktop tray host build failed with exit code $LASTEXITCODE."
}
$trayOut = Join-Path $trayDist 'AutoGovern2Code'
if (-not (Test-Path -LiteralPath (Join-Path $trayOut 'AutoGovern2Code.exe'))) {
    throw "Desktop tray host exe was not created."
}
$trayHost = Join-Path $runtimeRoot 'tray-host'
if (Test-Path -LiteralPath $trayHost) {
    Remove-Item -LiteralPath $trayHost -Recurse -Force
}
Copy-Item -LiteralPath $trayOut -Destination $trayHost -Recurse -Force
Copy-Item -LiteralPath $desktopNotice -Destination (Join-Path $trayHost 'NOTICE-imgui.txt') -Force

$isccCandidates = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
if (-not $isccCandidates) {
    throw 'Inno Setup 6 was not found. Install it before building the Windows installer.'
}
$iscc = $isccCandidates | Select-Object -First 1

& $iscc "/DMyAppVersion=$Version" "/DSourceRoot=$repoRoot" "/DBuildRoot=$buildRoot" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$installer = Join-Path $installerRoot 'AutoGovern2Code-Setup-Windows-x64.exe'
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer was not created at $installer."
}
Write-Output $installer
