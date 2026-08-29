<##
.SYNOPSIS
    Publishes already-authored Formula90s runtime assets as immutable packages.

.DESCRIPTION
    This is the transition bridge while the canonical vehicle authoring bundles
    are being consolidated in this repository. It accepts only final GLB files
    and runtime metadata from Formula90s; it never invokes Blender or generates
    geometry. Each package receives a content manifest with SHA-256 hashes.
.EXAMPLE
    .\publishing\publish_formula90_runtime_assets.ps1 -FormulaRepo D:\Formula90s
##>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string]$FormulaRepo,
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'published\formula90s')
)

$ErrorActionPreference = 'Stop'
$formula = (Resolve-Path -LiteralPath $FormulaRepo).Path
$output = [IO.Path]::GetFullPath($OutputRoot)

$vehicles = @(
    @{ Id = 'f1_94'; Source = 'game\assets\models\vehicles\f1_94\decoupled'; Physics = 'game\data\vehicles\f1_94\f1_94_physics.json'; Files = @('geometry\F1_94_chassis_geometry.glb','geometry\F1_94_wheel_front_geometry.glb','geometry\F1_94_wheel_rear_geometry.glb','manifest.json') },
    @{ Id = 'f1_2009_fw31'; Source = 'game\assets\models\vehicles\f1_94\variants\f1_2009_fw31'; Physics = 'game\data\vehicles\f1_94\variants\f1_2009_fw31_physics.json'; Files = @('geometry\F1_2009_fw31_chassis.glb','geometry\F1_2009_fw31_wheel_front.glb','geometry\F1_2009_fw31_wheel_rear.glb','manifest.json') },
    @{ Id = 'f1_2026_2008'; Source = 'game\assets\models\vehicles\f1-2026-2008'; Physics = 'game\data\vehicles\f1_2026_2008\f1_2026_2008_physics.json'; Files = @('f1_2026_2008_chassis.glb','f1_2026_2008_wheel_front.glb','f1_2026_2008_wheel_rear.glb','manifest.json') }
)

New-Item -ItemType Directory -Force -Path $output | Out-Null
foreach ($vehicle in $vehicles) {
    $sourceRoot = Join-Path $formula $vehicle.Source
    $targetRoot = Join-Path $output ('vehicles\' + $vehicle.Id)
    New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
    $entries = @()
    foreach ($relative in $vehicle.Files) {
        $source = [IO.Path]::GetFullPath((Join-Path $sourceRoot $relative))
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing final runtime input: $source" }
        $name = Split-Path -Leaf $source
        Copy-Item -LiteralPath $source -Destination (Join-Path $targetRoot $name) -Force
        $hash = (Get-FileHash -LiteralPath (Join-Path $targetRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant()
        $entries += [ordered]@{ file = $name; sha256 = $hash }
    }
    $physics = Join-Path $formula $vehicle.Physics
    if (-not (Test-Path -LiteralPath $physics -PathType Leaf)) { throw "Missing physics profile: $physics" }
    Copy-Item -LiteralPath $physics -Destination (Join-Path $targetRoot 'physics.json') -Force
    $entries += [ordered]@{ file = 'physics.json'; sha256 = (Get-FileHash -LiteralPath (Join-Path $targetRoot 'physics.json') -Algorithm SHA256).Hash.ToLowerInvariant() }
    [ordered]@{ schema_version = 1; package_type = 'formula90s-runtime-vehicle'; vehicle_id = $vehicle.Id; files = $entries } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $targetRoot 'package_manifest.json') -Encoding UTF8
}
Write-Host "Published Formula90s runtime packages to $output"
