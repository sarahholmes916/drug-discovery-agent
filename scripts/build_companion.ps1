param(
    [switch]$SkipInstall,
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$entryPoint = Join-Path $repoRoot "apps\companion_main.py"
$pocketMinerVendor = Join-Path $repoRoot "src\drug_discovery_agent\_vendor\pocketminer"
$distribution = Join-Path $repoRoot "dist"
$buildRoot = Join-Path $repoRoot "build\companion"
$stageRoot = Join-Path $repoRoot "build\companion-release"
$archive = Join-Path $distribution "DrugDiscoveryAgent-Companion-windows-x64.zip"
$webArchive = Join-Path $repoRoot "apps\web\downloads\DrugDiscoveryAgent-Companion-windows-x64.zip"
$pythonPrefix = (& $PythonExecutable -c "import sys; print(sys.prefix)").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect the selected Python environment."
}
$pythonRuntimeBin = Join-Path $pythonPrefix "Library\bin"
if (Test-Path -LiteralPath $pythonRuntimeBin) {
    # PyInstaller must be able to resolve Conda's OpenSSL, SQLite, compression,
    # and FFI runtimes while analyzing extension modules.
    $env:PATH = "$pythonRuntimeBin;$env:PATH"
}

if (-not $SkipInstall) {
    # Install build/runtime libraries without reinstalling the active project's
    # console launcher, which may be in use by a running companion process.
    & $PythonExecutable -m pip install `
        "pydantic>=2.7,<3" `
        "PyYAML>=6,<7" `
        "numpy>=1.26" `
        "scipy>=1.13" `
        "rdkit>=2024.3" `
        "gemmi>=0.7" `
        "meeko>=0.7.1,<0.9" `
        "openpyxl>=3.1,<4" `
        "fastapi>=0.110" `
        "uvicorn>=0.29" `
        "python-multipart>=0.0.9" `
        "pyinstaller>=6.10,<7"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install companion build dependencies."
    }
}

& $PythonExecutable -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name "DrugDiscoveryAgent-Companion" `
    --distpath $distribution `
    --workpath $buildRoot `
    --specpath $buildRoot `
    --paths (Join-Path $repoRoot "src") `
    --paths $repoRoot `
    --collect-submodules drug_discovery_agent `
    --collect-all meeko `
    --add-data "$(Join-Path $pocketMinerVendor 'LICENSE');drug_discovery_agent/_vendor/pocketminer" `
    --add-data "$(Join-Path $pocketMinerVendor 'manifest.json');drug_discovery_agent/_vendor/pocketminer" `
    --add-data "$(Join-Path $pocketMinerVendor 'models\pocketminer.data-00000-of-00001');drug_discovery_agent/_vendor/pocketminer/models" `
    --add-data "$(Join-Path $pocketMinerVendor 'models\pocketminer.index');drug_discovery_agent/_vendor/pocketminer/models" `
    --add-data "$(Join-Path $pocketMinerVendor 'src\gvp.py');drug_discovery_agent/_vendor/pocketminer/src" `
    --add-data "$(Join-Path $pocketMinerVendor 'src\models.py');drug_discovery_agent/_vendor/pocketminer/src" `
    --add-data "$(Join-Path $pocketMinerVendor 'src\util.py');drug_discovery_agent/_vendor/pocketminer/src" `
    --add-data "$(Join-Path $pocketMinerVendor 'src\validate_performance_on_xtals.py');drug_discovery_agent/_vendor/pocketminer/src" `
    --add-data "$(Join-Path $pocketMinerVendor 'src\xtal_predict.py');drug_discovery_agent/_vendor/pocketminer/src" `
    $entryPoint
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed to build the companion."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $distribution "DrugDiscoveryAgent-Companion.exe") -Destination $stageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot "packaging\COMPANION_README.txt") -Destination $stageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot "THIRD_PARTY_NOTICES.md") -Destination $stageRoot
Copy-Item -LiteralPath (Join-Path $pocketMinerVendor "LICENSE") -Destination (Join-Path $stageRoot "POCKETMINER_LICENSE.txt")
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $archive
Copy-Item -LiteralPath $archive -Destination $webArchive -Force
Write-Host "Built $archive"
Write-Host "Copied the website download to $webArchive"
