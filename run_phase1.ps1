<#
Hollow Hull - Phase 1 in one go, no Codex needed.

Easiest: double-click RUN_PHASE1.bat in this folder.
Or in PowerShell:  powershell -ExecutionPolicy Bypass -File run_phase1.ps1

Steps: export the Blender kit -> build level placements -> create the Unreal
project -> open Unreal and build the level -> check the result.
Everything is logged to reports\phase1\run_log.txt.

Options (all optional):
  -Blender    "C:\...\blender.exe"          if Blender is not found automatically
  -UnrealRoot "C:\Program Files\Epic Games\UE_5.7"
  -Project    "C:\Projects\HollowHull"      must NOT be inside OneDrive
  -SkipUnreal                               only run the Blender + layout steps
#>
param(
    [string]$Blender = "",
    [string]$UnrealRoot = "",
    [string]$Project = "C:\Projects\HollowHull",
    [switch]$SkipUnreal,
    [int]$UnrealTimeoutMinutes = 90
)

$ErrorActionPreference = "Stop"
$HH = $PSScriptRoot
$LogDir = Join-Path $HH "reports\phase1"
New-Item -ItemType Directory -Force $LogDir | Out-Null
Start-Transcript -Path (Join-Path $LogDir "run_log.txt") -Force | Out-Null

$Expected = @{
    "SM_Wall" = 75; "SM_Pillar" = 88; "SM_Ceiling" = 46; "SM_Floor_Steel" = 39
    "SM_Water_Tile" = 20; "SM_Lamp_Cage" = 24; "SM_Wall_Porthole" = 11
    "SM_Floor_Grate" = 9; "SM_Wall_Door" = 8; "SM_Railing" = 8
    "PointLight" = 24; "PlayerStart" = 1
}

function Say([string]$Text, [string]$Color = "Cyan") { Write-Host $Text -ForegroundColor $Color }

function Fail([string]$Text) {
    Say "`nFAILED: $Text" "Red"
    Say "Send Claude the file reports\phase1\run_log.txt (or paste the red lines above)." "Yellow"
    Stop-Transcript | Out-Null
    exit 1
}

function Invoke-Native([string]$Exe, [string[]]$ArgList) {
    # Native tools write progress to stderr; keep it as plain log text, not errors.
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Exe @ArgList 2>&1 | ForEach-Object { Write-Host "$_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    return $code
}

function Find-Blender {
    if ($Blender) {
        if (Test-Path $Blender) { return (Resolve-Path $Blender).Path }
        Fail "Blender not found at $Blender"
    }
    $roots = @(
        (Join-Path $env:ProgramFiles "Blender Foundation"),
        (Join-Path $env:LOCALAPPDATA "Programs\Blender Foundation"),
        "C:\Program Files (x86)\Steam\steamapps\common\Blender"
    )
    foreach ($r in $roots) {
        if ($r -and (Test-Path $r)) {
            $f = Get-ChildItem $r -Recurse -Filter "blender.exe" -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1
            if ($f) { return $f.FullName }
        }
    }
    Fail "Could not find blender.exe. Run again with -Blender `"C:\path\to\blender.exe`""
}

function Find-BlenderPython([string]$BlenderExe) {
    # Blender ships its own Python, so no separate Python install is needed.
    $py = Get-ChildItem (Split-Path $BlenderExe) -Recurse -Filter "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '[\\/]python[\\/]bin[\\/]python(\.exe)?$' } |
        Select-Object -First 1
    if (-not $py) { Fail "Could not find Blender's bundled python next to $BlenderExe" }
    return $py.FullName
}

function Find-Unreal {
    if ($UnrealRoot) {
        if (Test-Path $UnrealRoot) { return (Resolve-Path $UnrealRoot).Path }
        Fail "Unreal not found at $UnrealRoot"
    }
    $default = Join-Path $env:ProgramFiles "Epic Games\UE_5.7"
    if (Test-Path $default) { return $default }
    $dat = "C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat"
    if (Test-Path $dat) {
        $hit = (Get-Content $dat -Raw | ConvertFrom-Json).InstallationList |
            Where-Object { $_.AppName -eq "UE_5.7" } | Select-Object -First 1
        if ($hit -and (Test-Path $hit.InstallLocation)) { return $hit.InstallLocation }
    }
    Fail "Could not find Unreal Engine 5.7. Run again with -UnrealRoot `"C:\path\to\UE_5.7`""
}

# --- 1. tools -------------------------------------------------------------
Say "`n=== 1/5  Finding Blender and Unreal ==="
$BlenderExe = Find-Blender
$Py = Find-BlenderPython $BlenderExe
Say "Blender: $BlenderExe" "Gray"
Say "Python:  $Py" "Gray"
if (-not $SkipUnreal) {
    $UE = Find-Unreal
    $UEEditor = Join-Path $UE "Engine\Binaries\Win64\UnrealEditor.exe"
    if (-not (Test-Path $UEEditor)) { Fail "UnrealEditor.exe missing at $UEEditor" }
    Say "Unreal:  $UE" "Gray"
    if ($Project -match "OneDrive") { Fail "Project path '$Project' is inside OneDrive. Use a path like C:\Projects\HollowHull" }
}

# --- 2. ship kit ----------------------------------------------------------
Say "`n=== 2/5  Exporting the ship kit from Blender ==="
$kitDir = Join-Path $HH "export\ship_kit"
$code = Invoke-Native $BlenderExe @("--background", "--factory-startup", "--python-exit-code", "1",
    "--python", (Join-Path $HH "blender\build_ship_kit.py"), "--", "--out", $kitDir)
$fbx = @(Get-ChildItem $kitDir -Filter "*.fbx" -ErrorAction SilentlyContinue).Count
if ($code -ne 0 -or $fbx -ne 21) { Fail "Blender kit export (exit code $code, $fbx of 21 FBX files)" }
Say "OK: 21 FBX files" "Green"

# --- 3. layout ------------------------------------------------------------
Say "`n=== 3/5  Building level placements ==="
$code = Invoke-Native $Py @((Join-Path $HH "level\layout.py"),
    (Join-Path $HH "level\flooded_deck.json"), (Join-Path $HH "level\placements.json"))
if ($code -ne 0) { Fail "layout.py (exit code $code)" }
Say "OK" "Green"

if ($SkipUnreal) {
    Say "`nDone (Unreal skipped)." "Green"
    Stop-Transcript | Out-Null
    exit 0
}

# --- 4. Unreal project ----------------------------------------------------
Say "`n=== 4/5  Preparing the Unreal project at $Project ==="
$uproject = Join-Path $Project "HollowHull.uproject"
$prep = Join-Path $HH "tools\prepare_project.py"
if (Test-Path $uproject) {
    $code = Invoke-Native $Py @($prep, "--existing", $uproject)
} elseif ((Test-Path $Project) -and @(Get-ChildItem $Project -Force).Count -gt 0) {
    Fail "$Project exists, is not empty and has no HollowHull.uproject. Empty it or pass -Project with another folder."
} else {
    $code = Invoke-Native $Py @($prep, "--engine", $UE, "--dest", $Project)
}
if ($code -ne 0 -or -not (Test-Path $uproject)) { Fail "prepare_project.py (exit code $code)" }
Say "OK" "Green"

# --- 5. Unreal build ------------------------------------------------------
Say "`n=== 5/5  Opening Unreal and building the level ==="
$report = Join-Path $Project "Saved\HollowHull\setup_report.json"
Remove-Item $report -ErrorAction SilentlyContinue
$setup = Join-Path $HH "unreal\hh_setup.py"
Start-Process -FilePath $UEEditor -ArgumentList "`"$uproject`" -ExecutePythonScript=`"$setup`""
Say "Unreal is starting. The FIRST launch compiles shaders and can take 10-40 minutes." "Yellow"
Say "Leave this window and the editor open. Waiting for the build report..." "Yellow"

$deadline = (Get-Date).AddMinutes($UnrealTimeoutMinutes)
$started = Get-Date
while (-not (Test-Path $report)) {
    if ((Get-Date) -gt $deadline) { Fail "No report after $UnrealTimeoutMinutes minutes. Is the Unreal editor still loading or showing a dialog?" }
    Start-Sleep -Seconds 15
    $mins = [int]((Get-Date) - $started).TotalMinutes
    Write-Host "  still waiting... $mins min" -ForegroundColor DarkGray
}
Start-Sleep -Seconds 2
Copy-Item $report (Join-Path $LogDir "setup_report.json") -Force
$r = Get-Content $report -Raw | ConvertFrom-Json

# --- check ----------------------------------------------------------------
Say "`n=== Result ==="
$problems = @()
if (-not $r.ok) { $problems += "setup reported ok=false" }
if ($r.error) { $problems += "error: $($r.error)" }
foreach ($k in $Expected.Keys) {
    $got = 0
    if ($r.spawned.PSObject.Properties[$k]) { $got = [int]$r.spawned.$k }
    if ($got -ne $Expected[$k]) { $problems += "$k spawned $got, expected $($Expected[$k])" }
}
foreach ($m in $r.meshes.PSObject.Properties) {
    if ($m.Value.collision_hulls_imported -lt $m.Value.collision_hulls_expected) {
        $problems += "$($m.Name): collision $($m.Value.collision_hulls_imported)/$($m.Value.collision_hulls_expected)"
    }
}
foreach ($w in $r.warnings) { Say "warning: $w" "Yellow" }
if ($problems.Count -gt 0) {
    foreach ($p in $problems) { Say "problem: $p" "Red" }
    Say "`nThe level may still be playable. Send Claude reports\phase1\run_log.txt and setup_report.json." "Yellow"
} else {
    Say "Everything checks out." "Green"
}
Say "`nNow in Unreal: press Play (Alt+P). WASD to move, Space to jump." "Cyan"
Say "Route: cabin -> corridor -> crew quarters -> corridor -> flooded engine room (stairs to the mezzanine)" "Cyan"
Say "       -> south exit under the mezzanine -> green corridor -> cargo hold." "Cyan"
Say "Then tell Claude what broke, felt wrong, or looked too dark/bright." "Cyan"
Stop-Transcript | Out-Null
