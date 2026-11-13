param(
    [switch]$SkipInstall,
    [string]$PythonExecutable = "python"
)
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $SkipInstall) {
    & $PythonExecutable -m pip install -r (Join-Path $repoRoot "packaging/requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "Unable to install pinned companion build dependencies." }
}
& $PythonExecutable (Join-Path $repoRoot "scripts/build_companion.py") --target windows-x64
if ($LASTEXITCODE -ne 0) { throw "Companion build or verification failed." }
