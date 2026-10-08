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
  -SkipTemplateCheck                        don't check that the project came from the launcher
#>
param(
    [string]$Blender = "",
    [string]$UnrealRoot = "",
    [string]$Project = "C:\Projects\HollowHull",
    [switch]$SkipUnreal,
    [switch]$SkipTemplateCheck,
    [int]$UnrealTimeoutMinutes = 90
)

$ErrorActionPreference = "Stop"
$HH = $PSScriptRoot
. (Join-Path $HH "tools\find_project.ps1")
$ProjectName = "HollowHull"
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

function Show-UnrealLog {
    # Copy Unreal's log (and newest crash report) into reports\phase1 and print the lines that matter.
    $log = Join-Path $Project "Saved\Logs\$ProjectName.log"
    if (Test-Path $log) {
        Copy-Item $log (Join-Path $LogDir "unreal_log.txt") -Force
        $lines = Get-Content (Join-Path $LogDir "unreal_log.txt")
        Say "`n--- Unreal log: [HH], fatal and error lines ---" "Yellow"
        $lines | Select-String -Pattern '\[HH\]|Fatal|Assertion failed|Unhandled Exception|Error:' |
            Select-Object -Last 50 | ForEach-Object { Write-Host $_.Line }
        Say "--- Unreal log: last 20 lines ---" "Yellow"
        $lines | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
    } else {
        Say "No Unreal log found at $log" "Yellow"
    }
    $crash = Get-ChildItem (Join-Path $Project "Saved\Crashes") -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($crash) {
        $ctxFile = Join-Path $crash.FullName "CrashContext.runtime-xml"
        if (Test-Path $ctxFile) {
            Copy-Item $ctxFile (Join-Path $LogDir "crash_context.xml") -Force
            $m = Select-String -Path $ctxFile -Pattern '<ErrorMessage>(.*?)</ErrorMessage>' | Select-Object -First 1
            if ($m) { Say "Crash message: $($m.Matches[0].Groups[1].Value)" "Red" }
        }
    }
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

# --- 4. Unreal project ---------------------------------------------------
Say "`n=== 4/5  Preparing the Unreal project at $Project ==="
$found = Find-UnrealProject $Project
$launcherSteps = @"
Create the project with Epic's launcher (only needed once):
  1. Close Unreal. If the folder $Project exists, delete it.
  2. Open Unreal Engine 5.7 > New Project > Games > Third Person.
  3. Choose Blueprint. Project Location: $(Split-Path $Project)   Project Name: $(Split-Path $Project -Leaf)
  4. Click Create. When the editor has opened, close it.
  5. Run RUN_PHASE1.bat again.
"@
if (-not $found.Uproject) {
    Say $launcherSteps "Yellow"
    Fail "No Unreal project found in $Project or the usual project folders."
}
$uproject = $found.Uproject
$Project = $found.Dir
$ProjectName = $found.Name
Say "Using project: $uproject" "White"
if ($found.Candidates.Count -gt 1) {
    Say "(newest of $($found.Candidates.Count) projects found; others: $(($found.Candidates | Select-Object -Skip 1 -First 3 | ForEach-Object { $_.FullName }) -join ', '))" "DarkGray"
}
if ($Project -match "OneDrive") {
    Say "That project is inside OneDrive, which breaks Unreal projects. Move it out:" "Yellow"
    Say "  1. Close Unreal." "Yellow"
    Say "  2. In File Explorer, cut the folder $Project" "Yellow"
    Say "  3. Paste it into C:\Projects (create that folder if needed)." "Yellow"
    Say "  4. Run RUN_PHASE1.bat again." "Yellow"
    Fail "Project is inside OneDrive."
}
# A launcher-made Third Person project contains Enhanced Input actions (IA_*.uasset)
# somewhere under Content; the old copied-template project had none.
$inputActions = @(Get-ChildItem (Join-Path $Project "Content") -Recurse -Filter "IA_*.uasset" -ErrorAction SilentlyContinue)
Say "Template input actions found: $($inputActions.Count)" "Gray"
if ($inputActions.Count -eq 0 -and -not $SkipTemplateCheck) {
    Say "This project has no input action assets (IA_*), so the player cannot move." "Yellow"
    Say "It was probably made by an older version of this script. Recreate it in the launcher:" "Yellow"
    Say $launcherSteps "Yellow"
    Fail "Incomplete project at $Project (use -SkipTemplateCheck to ignore)."
}
$code = Invoke-Native $Py @((Join-Path $HH "tools\prepare_project.py"), "--existing", $uproject, "--repo", $HH)
if ($code -ne 0) { Fail "prepare_project.py (exit code $code)" }
Say "OK" "Green"

# --- 5. Unreal build ------------------------------------------------------
Say "`n=== 5/5  Opening Unreal and building the level ==="
$report = Join-Path $Project "Saved\HollowHull\setup_report.json"
Remove-Item $report -ErrorAction SilentlyContinue
# The project's Content/Python/init_unreal.py sees this file on startup and builds the level.
$requestDir = Join-Path $Project "Saved\HollowHull"
New-Item -ItemType Directory -Force $requestDir | Out-Null
Set-Content -Path (Join-Path $requestDir "build_request") -Value (Get-Date -Format o)
$proc = Start-Process -FilePath $UEEditor -ArgumentList "`"$uproject`"" -PassThru
Say "Unreal is starting. The FIRST launch compiles shaders and can take 10-40 minutes." "Yellow"
Say "Leave this window and the editor open. Waiting for the build to finish..." "Yellow"

$deadline = (Get-Date).AddMinutes($UnrealTimeoutMinutes)
$started = Get-Date
$lastStage = ""
$r = $null
$ticks = 0
while ($true) {
    if (Test-Path $report) {
        try { $r = Get-Content $report -Raw | ConvertFrom-Json } catch { $r = $null }
        if ($r) {
            if ($r.stage -ne $lastStage) { Say "  build stage: $($r.stage)" "Gray"; $lastStage = $r.stage }
            if ($r.finished) { break }
        }
    }
    if ($proc.HasExited) {
        Say "`nUnreal closed before the build finished (last stage: '$lastStage', exit code $($proc.ExitCode))." "Red"
        Show-UnrealLog
        if ($r) { Copy-Item $report (Join-Path $LogDir "setup_report.json") -Force }
        Fail "Unreal closed during the build. Send Claude the lines above, or the files in reports\phase1."
    }
    if ((Get-Date) -gt $deadline) {
        Show-UnrealLog
        Fail "Build not finished after $UnrealTimeoutMinutes minutes (last stage: '$lastStage'). Is a dialog open in Unreal?"
    }
    Start-Sleep -Seconds 10
    $ticks++
    if ($ticks % 12 -eq 0) { Write-Host "  still working... $([int]((Get-Date) - $started).TotalMinutes) min" -ForegroundColor DarkGray }
}
Copy-Item $report (Join-Path $LogDir "setup_report.json") -Force
$ueLog = Join-Path $Project "Saved\Logs\$ProjectName.log"
if (Test-Path $ueLog) { Copy-Item $ueLog (Join-Path $LogDir "unreal_log.txt") -Force }

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
$ueLogCopy = Join-Path $LogDir "unreal_log.txt"
if ((Test-Path $ueLogCopy) -and (Select-String -Path $ueLogCopy -Pattern "EnhancedInputActionEvent references invalid" -Quiet)) {
    $problems += "the template character's input actions are broken, so the player cannot move: recreate the project in the launcher (see README)"
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
