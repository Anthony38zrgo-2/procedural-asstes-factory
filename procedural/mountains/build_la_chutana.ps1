param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$mountainRoot = $PSScriptRoot
$inputSvg = Join-Path $mountainRoot "inputs\la_chutana\la_chutana_topo.svg"
$outputDir = Join-Path $mountainRoot "assets\la_chutana"

& $Python (Join-Path $mountainRoot "tools\generate_topo_terrain.py") $inputSvg $outputDir
if ($LASTEXITCODE -ne 0) {
    throw "La generacion de montanas termino con codigo $LASTEXITCODE"
}

Write-Host "Montanas generadas en $outputDir"
