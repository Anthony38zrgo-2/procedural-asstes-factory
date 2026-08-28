param(
    [ValidateSet("Base", "Environment")]
    [string]$Mode = "Base",
    [string]$BlenderExe = ""
)

$ErrorActionPreference = "Stop"
$factory = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$studio = Join-Path $factory "track-studio"
$pipeline = Join-Path $studio "blender\track_pipeline"
$config = Join-Path $pipeline "configs\la_chutana_factory.json"
$python = (Get-Command python -ErrorAction Stop).Source

& $python (Join-Path $PSScriptRoot "prepare_la_chutana_inputs.py")
if ($LASTEXITCODE -ne 0) { throw "Unable to stage La Chutana inputs." }

if ($Mode -eq "Environment") {
    & $python (Join-Path $pipeline "generate_environment.py") `
        --config $config `
        --trees-density low `
        --bushes-density low `
        --grass-density medium `
        --buildings-density very_low `
        --seed 1995
    if ($LASTEXITCODE -ne 0) { throw "Unable to regenerate La Chutana environment placements." }
}

& $python (Join-Path $PSScriptRoot "preflight_la_chutana.py") --mode $Mode
if ($LASTEXITCODE -ne 0) {
    throw "Factory dependencies are incomplete for mode $Mode. Generate the listed assets locally; do not copy them from Formula90s."
}

if ([string]::IsNullOrWhiteSpace($BlenderExe)) {
    $candidates = @(
        "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        "blender"
    )
    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate) -or (Get-Command $candidate -ErrorAction SilentlyContinue)) {
            $BlenderExe = $candidate
            break
        }
    }
}
if ([string]::IsNullOrWhiteSpace($BlenderExe)) {
    throw "Blender was not found. Pass -BlenderExe explicitly."
}

if ($Mode -eq "Base") {
    & $BlenderExe --background --python (Join-Path $pipeline "build_track_blender.py") -- --config $config
    if ($LASTEXITCODE -ne 0) { throw "La Chutana base GLB build failed." }
    & $BlenderExe --background --python (Join-Path $pipeline "validate_curbs_blender.py") -- --config $config
    if ($LASTEXITCODE -ne 0) { throw "La Chutana curb validation failed." }
} else {
    $baseBlend = Join-Path $studio "blender\generated\la_chutana\track_base.blend"
    if (-not (Test-Path -LiteralPath $baseBlend)) {
        throw "Base blend missing. Run this script with -Mode Base first."
    }
    & $BlenderExe --background --python (Join-Path $pipeline "build_environment_blender.py") -- --config $config
    if ($LASTEXITCODE -ne 0) { throw "La Chutana environment GLB build failed." }
}

$output = Join-Path $studio "output\la_chutana\la_chutana.glb"
if (-not (Test-Path -LiteralPath $output)) { throw "Expected runtime GLB was not published: $output" }
Write-Host "Factory quick-test output: $output" -ForegroundColor Green
