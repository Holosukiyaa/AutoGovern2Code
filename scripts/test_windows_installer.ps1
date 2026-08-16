param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ag2c-installer-smoke-" + [guid]::NewGuid().ToString('N'))
$installRoot = Join-Path $testRoot 'program'
$profileRoot = Join-Path $testRoot 'profile'
$projectRoot = Join-Path $testRoot 'project'
$installLog = Join-Path $testRoot 'install.log'
$oldHome = $env:HOME
$oldUserProfile = $env:USERPROFILE
$oldCodexHome = $env:CODEX_HOME
$uninstalled = $false

function Get-UserPathState {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    if ($null -eq $key) {
        return @{ Exists = $false; Value = $null; Kind = $null }
    }
    try {
        $pathName = $key.GetValueNames() | Where-Object { $_ -ieq 'Path' } | Select-Object -First 1
        if ($null -eq $pathName) {
            return @{ Exists = $false; Value = $null; Kind = $null }
        }
        return @{
            Exists = $true
            Value = [string]$key.GetValue(
                $pathName,
                $null,
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
            )
            Kind = $key.GetValueKind($pathName)
        }
    }
    finally {
        $key.Dispose()
    }
}

function Restore-UserPathState([hashtable]$State) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        if ($State.Exists) {
            $key.SetValue('Path', $State.Value, $State.Kind)
        }
        else {
            $key.DeleteValue('Path', $false)
        }
    }
    finally {
        $key.Dispose()
    }
}

$userPathBefore = Get-UserPathState

try {
    New-Item -ItemType Directory -Path $profileRoot -Force | Out-Null
    $env:HOME = $profileRoot
    $env:USERPROFILE = $profileRoot
    $env:CODEX_HOME = Join-Path $profileRoot '.codex'
    $install = Start-Process -FilePath $installer -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        "/DIR=`"$installRoot`"",
        "/LOG=`"$installLog`""
    ) -Wait -PassThru
    if ($install.ExitCode -ne 0) {
        throw "Installer exited with code $($install.ExitCode)."
    }
    $installLogText = Get-Content -Raw -LiteralPath $installLog
    if ($installLogText -match '(?m)CurStepChanged raised an exception|Runtime error \(at ') {
        throw 'Installer reported an internal setup error despite returning exit code 0.'
    }
    $expectedPath = (Join-Path $installRoot 'ag2c').TrimEnd('\').ToLowerInvariant()
    $installedPathEntries = (Get-UserPathState).Value -split ';'
    if (-not ($installedPathEntries | Where-Object { $_.Trim().TrimEnd('\').ToLowerInvariant() -eq $expectedPath })) {
        throw 'Installer did not add the AG2C runtime to the user PATH.'
    }

    $runtime = Join-Path $installRoot 'ag2c\ag2c.exe'
    $runtimeVersion = (& $runtime --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeVersion -ne "AutoGovern2Code $Version") {
        throw "Installed runtime smoke test failed: $runtimeVersion"
    }
    foreach ($skill in @(
        (Join-Path $profileRoot '.codex\skills\ag2c-governed-development\SKILL.md'),
        (Join-Path $profileRoot '.claude\skills\ag2c-governed-development\SKILL.md'),
        (Join-Path $profileRoot '.agents\skills\ag2c-governed-development\SKILL.md')
    )) {
        if (-not (Test-Path -LiteralPath $skill)) {
            throw "Installer did not install the expected Skill: $skill"
        }
    }

    New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
    & git -C $projectRoot init | Out-Null
    & git -C $projectRoot config user.name 'AG2C Installer Smoke Test'
    & git -C $projectRoot config user.email 'installer-smoke@example.invalid'
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'src') | Out-Null
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'src\value.txt'), "installed runtime`n", $utf8NoBom)
    & git -C $projectRoot add .
    & git -C $projectRoot commit -m 'test: initialize installer project' | Out-Null
    & $runtime setup --project $projectRoot --project-id installer-smoke | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'The installed runtime could not enroll a Git project.'
    }
    Push-Location $projectRoot
    try {
        & $runtime guard status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'The installed runtime did not activate the enrolled project.'
        }
    }
    finally {
        Pop-Location
    }
    $hook = Get-Content -Raw (Join-Path $projectRoot '.ag2c\state\hooks\pre-commit')
    if ($hook -notmatch [regex]::Escape($runtime.Replace('\', '/')) -or $hook -match ' -m ag2c') {
        throw 'The installed runtime did not write a self-contained Git guard command.'
    }

    $uninstaller = Join-Path $installRoot 'unins000.exe'
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART'
    ) -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) {
        throw "Uninstaller exited with code $($uninstall.ExitCode)."
    }
    $uninstalled = $true
    foreach ($skillRoot in @('.codex', '.claude', '.agents')) {
        if (Test-Path -LiteralPath (Join-Path $profileRoot "$skillRoot\skills\ag2c-governed-development")) {
            throw "Uninstaller left the unchanged $skillRoot Skill behind."
        }
    }
    $userPathAfter = Get-UserPathState
    if (
        $userPathAfter.Exists -ne $userPathBefore.Exists -or
        $userPathAfter.Value -ne $userPathBefore.Value -or
        ($userPathBefore.Exists -and $userPathAfter.Kind -ne $userPathBefore.Kind)
    ) {
        throw 'Uninstaller did not restore the original user PATH exactly.'
    }
}
catch {
    if (Test-Path -LiteralPath $installLog) {
        Write-Host '--- Inno Setup install log (last 120 lines) ---'
        Get-Content -LiteralPath $installLog -Tail 120 | Write-Host
    }
    throw
}
finally {
    $uninstaller = Join-Path $installRoot 'unins000.exe'
    if (-not $uninstalled -and (Test-Path -LiteralPath $uninstaller)) {
        $cleanup = Start-Process -FilePath $uninstaller -ArgumentList @(
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART'
        ) -Wait -PassThru
        if ($cleanup.ExitCode -ne 0) {
            Write-Warning "Cleanup uninstaller exited with code $($cleanup.ExitCode)."
        }
    }
    Restore-UserPathState $userPathBefore
    $env:HOME = $oldHome
    $env:USERPROFILE = $oldUserProfile
    $env:CODEX_HOME = $oldCodexHome
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
