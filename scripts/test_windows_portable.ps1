param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP "ag2c-portable-smoke-$PID"
$profileRoot = Join-Path $work 'profile'
$extract = Join-Path $work 'extract'
New-Item -ItemType Directory -Path $extract -Force | Out-Null
New-Item -ItemType Directory -Path $profileRoot -Force | Out-Null

$saved = @{}
foreach ($name in @('HOME', 'USERPROFILE', 'CODEX_HOME', 'LOCALAPPDATA', 'AG2C_DATA_ROOT', 'AG2C_PORTABLE', 'AG2C_GIT', 'AG2C_GIT_ROOT')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$pathWithGit = $env:PATH

try {
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $extract
    $root = Join-Path $extract 'AutoGovern2Code'
    foreach ($expected in @('portable.ini', 'AutoGovern2Code.exe', 'NOTICE-imgui.txt', 'ag2c\ag2c.exe', 'git\cmd\git.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $expected))) {
            throw "Portable package is missing: $expected"
        }
    }

    # Isolate the user profile so nothing escapes the portable folder.
    $env:HOME = $profileRoot
    $env:USERPROFILE = $profileRoot
    $env:CODEX_HOME = Join-Path $profileRoot '.codex'
    $env:LOCALAPPDATA = Join-Path $profileRoot 'AppData\Local'
    foreach ($name in @('AG2C_DATA_ROOT', 'AG2C_PORTABLE', 'AG2C_GIT', 'AG2C_GIT_ROOT')) {
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }

    $runtime = Join-Path $root 'ag2c\ag2c.exe'
    $runtimeVersion = (& $runtime --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $runtimeVersion -ne "AutoGovern2Code $Version") {
        throw "Portable runtime smoke test failed: $runtimeVersion"
    }

    $projectRoot = Join-Path $work 'project'
    New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
    & git -C $projectRoot init | Out-Null
    & git -C $projectRoot config user.name 'AG2C Portable Smoke Test'
    & git -C $projectRoot config user.email 'portable-smoke@example.invalid'
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'src') | Out-Null
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'src\value.txt'), "portable runtime`n", $utf8NoBom)
    & git -C $projectRoot add .
    & git -C $projectRoot commit -m 'test: initialize portable project' | Out-Null
    $headBeforeSetup = (& git -C $projectRoot rev-parse HEAD | Out-String).Trim()

    # Enroll with system Git removed from PATH: the bundled git\ must serve.
    $env:PATH = (
        ($env:PATH -split ';' | Where-Object {
            $entry = $_.Trim()
            $entry -and -not (Test-Path -LiteralPath (Join-Path $entry 'git.exe'))
        }) -join ';'
    )
    & $runtime setup --project $projectRoot --project-id portable-smoke | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Portable runtime could not enroll a Git project without system Git on PATH.'
    }
    Push-Location $projectRoot
    try {
        & $runtime guard status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Portable runtime did not activate the enrolled project.'
        }
    }
    finally {
        Pop-Location
    }

    # Evidence must stay inside the portable folder; the user profile stays clean.
    if (-not (Test-Path -LiteralPath (Join-Path $root 'data\projects'))) {
        throw 'Portable runtime did not keep its project store inside the portable data folder.'
    }
    if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'AutoGovern2Code')) {
        throw 'Portable runtime wrote to the per-user store instead of its own data folder.'
    }

    # Move the whole folder: registry, guard, and Git hooks must re-heal.
    $movedParent = Join-Path $work 'moved'
    New-Item -ItemType Directory -Path $movedParent -Force | Out-Null
    Move-Item -LiteralPath $root -Destination (Join-Path $movedParent 'AutoGovern2Code')
    $movedRoot = Join-Path $movedParent 'AutoGovern2Code'
    $movedRuntime = Join-Path $movedRoot 'ag2c\ag2c.exe'
    Push-Location $projectRoot
    try {
        & $movedRuntime guard status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Portable runtime broke after the folder was moved.'
        }
    }
    finally {
        Pop-Location
    }

    # The Git guard hook must still fire from the moved location: a direct commit
    # on the canonical checkout has to be blocked by AG2C.
    $portableGit = Join-Path $movedRoot 'git\cmd\git.exe'
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'src\value.txt'), "changed after move`n", $utf8NoBom)
    & $portableGit -C $projectRoot add . 2>&1 | Out-Null
    $commitOutput = (& $portableGit -C $projectRoot commit -m 'should be blocked' 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -or $commitOutput -notmatch 'AG2C') {
        throw "AG2C guard hook did not fire after the portable folder was moved: $commitOutput"
    }

    # The blocked commit leaves the change staged; reset both index and tree.
    & $portableGit -C $projectRoot reset --hard HEAD 2>&1 | Out-Null
    if ((& $portableGit -C $projectRoot status --porcelain | Out-String).Trim()) {
        throw 'Enrollment changed files in the user project.'
    }
    if ((& $portableGit -C $projectRoot rev-parse HEAD | Out-String).Trim() -ne $headBeforeSetup) {
        throw 'Enrollment moved the project HEAD.'
    }

    Write-Output 'Portable smoke test passed.'
}
finally {
    $env:PATH = $pathWithGit
    foreach ($name in $saved.Keys) {
        if ($null -eq $saved[$name]) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
        }
    }
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
