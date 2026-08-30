$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$testerDirectory = Join-Path $projectRoot "Testers"
$testerExecutable = Join-Path $testerDirectory "Tama.exe"
$testerNotes = Join-Path $testerDirectory "Testers Read This.txt"
$releaseDirectory = Join-Path $projectRoot "release"
$stagingDirectory = Join-Path $projectRoot "release_staging"
$packageRoot = Join-Path $stagingDirectory "Tama"
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

try {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }

    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null

    Copy-Item -LiteralPath $testerExecutable -Destination $packageRoot
    Copy-Item -LiteralPath $testerNotes -Destination $packageRoot

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
    Write-Host "+-- Testers Read This.txt"
}
finally {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}
