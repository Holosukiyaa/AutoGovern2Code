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
