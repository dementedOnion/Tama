$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$git = (Get-Command git -ErrorAction Stop).Source
$testerDirectory = Join-Path $projectRoot "Testers"
$testerExecutable = Join-Path $testerDirectory "Tama.exe"
$testerNotes = Join-Path $testerDirectory "Testers Read This.txt"
$releaseDirectory = Join-Path $projectRoot "release"
$stagingDirectory = Join-Path $projectRoot "release_staging"
$packageRoot = Join-Path $stagingDirectory "Tama"
$sourceRoot = Join-Path $packageRoot "Tama-main"
$releaseArchive = Join-Path $releaseDirectory "Tama.zip"

function Format-Size([long]$bytes) {
    if ($bytes -ge 1MB) {
        return "{0:N2} MB" -f ($bytes / 1MB)
    }

    return "{0:N0} bytes" -f $bytes
}

foreach ($requiredFile in @($testerExecutable, $testerNotes)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required tester file was not found: $requiredFile"
    }
}

Push-Location $projectRoot
try {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }

    New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null

    Copy-Item -LiteralPath $testerExecutable -Destination $packageRoot
    Copy-Item -LiteralPath $testerNotes -Destination $packageRoot

    # Git supplies the allowlist, so ignored and untracked local files cannot
    # enter the source snapshot. Missing paths are tracked deletions.
    $trackedFiles = & $git -C $projectRoot ls-files
    if ($LASTEXITCODE -ne 0) {
        throw "Git could not list the tracked project files."
    }

    foreach ($relativePath in $trackedFiles) {
        if ($relativePath -like "Testers/*") {
            continue
        }

        $sourcePath = Join-Path $projectRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            continue
        }

        $destinationPath = Join-Path $sourceRoot $relativePath
        $destinationDirectory = Split-Path -Parent $destinationPath
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    }

    if (Test-Path -LiteralPath $releaseArchive) {
        Remove-Item -LiteralPath $releaseArchive -Force
    }

    Compress-Archive -LiteralPath $packageRoot -DestinationPath $releaseArchive

    $zipInfo = Get-Item -LiteralPath $releaseArchive
    $exeInfo = Get-Item -LiteralPath $testerExecutable
    $notesInfo = Get-Item -LiteralPath $testerNotes
    $exeHash = (Get-FileHash -LiteralPath $testerExecutable -Algorithm SHA256).Hash
    $notesHash = (Get-FileHash -LiteralPath $testerNotes -Algorithm SHA256).Hash

    Write-Host ""
    Write-Host "Release package created successfully."
    Write-Host "ZIP: $($zipInfo.FullName)"
    Write-Host "ZIP size: $(Format-Size $zipInfo.Length)"
    Write-Host "Tama.exe: $(Format-Size $exeInfo.Length), SHA256 $exeHash"
    Write-Host "Tester note: $(Format-Size $notesInfo.Length), SHA256 $notesHash"
    Write-Host "Package tree:"
    Write-Host "Tama/"
    Write-Host "|-- Tama.exe"
    Write-Host "|-- Testers Read This.txt"
    Write-Host "+-- Tama-main/"

    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File |
        ForEach-Object { $_.FullName.Substring($sourceRoot.Length + 1).Replace("\", "/") } |
        Sort-Object |
        ForEach-Object { Write-Host "    |-- $_" }
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}
