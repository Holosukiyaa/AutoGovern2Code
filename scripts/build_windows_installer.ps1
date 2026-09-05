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
$uiSource = Join-Path $repoRoot 'src\ag2c\ui'
$uiData = "${uiSource}:ag2c\ui"
$desktopSource = Join-Path $repoRoot 'packaging\windows\desktop\AG2CDesktop.cs'
$desktopManifest = Join-Path $repoRoot 'packaging\windows\desktop\app.manifest'
$desktopConfig = Join-Path $repoRoot 'packaging\windows\desktop\AutoGovern2Code.exe.config'
$webExtensions = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll'

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
    --add-data $uiData `
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

$cscCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
) | Where-Object { Test-Path -LiteralPath $_ }
if (-not $cscCandidates) {
    throw '.NET Framework csc.exe was not found; the desktop tray host cannot be built.'
}
$csc = $cscCandidates | Select-Object -First 1
if (-not (Test-Path -LiteralPath $desktopConfig)) {
    throw "Desktop host config is missing: $desktopConfig"
}
if (-not (Test-Path -LiteralPath $webExtensions)) {
    throw "System.Web.Extensions.dll was not found at $webExtensions"
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
$desktop = Join-Path $runtimeRoot 'AutoGovern2Code.exe'
& $csc `
    /nologo `
    /platform:x64 `
    /target:winexe `
    "/out:$desktop" `
    /reference:System.dll `
    /reference:System.Drawing.dll `
    /reference:System.Net.Http.dll `
    /reference:System.Windows.Forms.dll `
    "/reference:$webExtensions" `
    "/win32manifest:$desktopManifest" `
    $desktopSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $desktop)) {
    throw "Desktop tray host build failed with exit code $LASTEXITCODE."
}
Copy-Item -LiteralPath $desktopConfig -Destination (Join-Path $runtimeRoot 'AutoGovern2Code.exe.config') -Force

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
