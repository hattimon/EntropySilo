param(
    [string]$Distribution = "Ubuntu",
    [string]$Version = "0.3.0"
)
$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$wslProject = (wsl.exe -d $Distribution wslpath -a ($project -replace '\\','/')).Trim()
if (-not $wslProject) { throw "Nie udało się przeliczyć ścieżki projektu dla WSL." }
wsl.exe -d $Distribution -u root -- bash -lc "cd '$wslProject' && ./live-builder/setup_build_host.sh && ENTROPYSILO_LIVE_VERSION='$Version' ./live-builder/build_live.sh"
if ($LASTEXITCODE -ne 0) { throw "Budowa EntropySilo Live USB nie powiodła się." }
