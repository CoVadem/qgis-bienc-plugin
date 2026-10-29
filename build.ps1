param(
    [string]$Output = "build\covadem_enc.zip"
)
# Packages the covadem_enc plugin folder into a zip installable via
# QGIS > Plugins > Manage and Install Plugins > Install from ZIP.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("covadem_enc_build_" + [guid]::NewGuid())
try {
    $target = Join-Path $staging "covadem_enc"
    Copy-Item -Recurse (Join-Path $root "covadem_enc") $target
    Get-ChildItem -Recurse -Directory $target -Filter "__pycache__" | Remove-Item -Recurse -Force
    $out = Join-Path $root $Output
    New-Item -ItemType Directory -Force (Split-Path -Parent $out) | Out-Null
    if (Test-Path $out) { Remove-Item $out }
    Compress-Archive -Path $target -DestinationPath $out
    Write-Host "Created $out"
}
finally {
    Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
}
