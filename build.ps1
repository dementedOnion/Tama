param(
    [switch]$Promote
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$buildDirectory = Join-Path $projectRoot "testing_build"
$distDirectory = Join-Path $projectRoot "testing_dist"
$executable = Join-Path $distDirectory "Tama.exe"
$testerDirectory = Join-Path $projectRoot "Testers"
$testerExecutable = Join-Path $testerDirectory "Tama.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at $python. Create the .venv and install the project dependencies first."
}

Push-Location $projectRoot
$originalPath = $env:PATH

try {
    # Keep unrelated development-tool DLLs out of PyInstaller's dependency scan.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"

    if (Test-Path -LiteralPath $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }

    if (Test-Path -LiteralPath $distDirectory) {
        Remove-Item -LiteralPath $distDirectory -Recurse -Force
    }

    & $python -m PyInstaller --noconfirm --clean --workpath $buildDirectory --distpath $distDirectory "Tama.spec"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Build completed without creating testing_dist\Tama.exe."
    }

    $sizeMb = [math]::Round((Get-Item -LiteralPath $executable).Length / 1MB, 2)
    Write-Host "Built testing_dist\Tama.exe ($sizeMb MB)"

    if ($Promote) {
        New-Item -ItemType Directory -Path $testerDirectory -Force | Out-Null
        Copy-Item -LiteralPath $executable -Destination $testerExecutable -Force
        Write-Host "Promoted the successful build to Testers\Tama.exe"
    }
}
finally {
    $env:PATH = $originalPath
    Pop-Location
}
