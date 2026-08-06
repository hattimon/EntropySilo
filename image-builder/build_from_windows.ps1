param([string]$Distribution = "Ubuntu")
$ErrorActionPreference = "Stop"
$project = (Get-Location).Path
$wslPath = (wsl.exe -d $Distribution -- wslpath -a $project).Trim()
wsl.exe -d $Distribution -- bash -lc "cd '$wslPath' && bash image-builder/prepare_assets.sh"
wsl.exe -d $Distribution -u root -- bash -lc "cd '$wslPath' && bash image-builder/build_image.sh"
if ($LASTEXITCODE -ne 0) { throw "Budowanie obrazu nie powiodło się." }
Write-Host "Obraz EntropySilo, raport zgodności i plik .sha256 znajdują się w $project\output"
