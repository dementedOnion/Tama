$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$buildDirectory = Join-Path $projectRoot "build"
$distDirectory = Join-Path $projectRoot "dist"
$executable = Join-Path $distDirectory "Tama.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at $python. Create the .venv and install the project dependencies first."
}

Push-Location $projectRoot

try {
    if (Test-Path -LiteralPath $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }

    if (Test-Path -LiteralPath $distDirectory) {
        Remove-Item -LiteralPath $distDirectory -Recurse -Force
    }

    & $python -m PyInstaller --noconfirm --clean "Tama.spec"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Build completed without creating dist\Tama.exe."
    }

    $sizeMb = [math]::Round((Get-Item -LiteralPath $executable).Length / 1MB, 2)
    Write-Host "Built dist\Tama.exe ($sizeMb MB)"
}
finally {
    Pop-Location
}
