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

Say "Hollow Hull scripts version: 2026-10-12c (realistic ship: fal textures, furniture and props; sound import crash fixed)" "Magenta"

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

# --- 2. kit -----------------------------------------------------------------
Say "`n=== 2/5  Exporting the ship and cave kit from Blender ==="
$kitDir = Join-Path $HH "export\ship_kit"
$code = Invoke-Native $BlenderExe @("--background", "--factory-startup", "--python-exit-code", "1",
    "--python", (Join-Path $HH "blender\build_ship_kit.py"), "--", "--out", $kitDir)
$kitPieces = @()
try { $kitPieces = @((Get-Content (Join-Path $kitDir "manifest.json") -Raw | ConvertFrom-Json).pieces) } catch { }
$missing = @($kitPieces | Where-Object { -not (Test-Path (Join-Path $kitDir $_.file)) }).Count
if ($code -ne 0 -or $kitPieces.Count -lt 30 -or $missing -gt 0) {
    Fail "Blender kit export (exit code $code, $($kitPieces.Count) pieces, $missing FBX files missing)"
}
Say "OK: $($kitPieces.Count) FBX files" "Green"

# --- 3. layout ------------------------------------------------------------
Say "`n=== 3/5  Building level placements ==="
foreach ($pair in @(@("flooded_deck.json", "placements.json"), @("the_hollow.json", "placements_the_hollow.json"))) {
    $code = Invoke-Native $Py @((Join-Path $HH "level\layout.py"),
        (Join-Path $HH "level\$($pair[0])"), (Join-Path $HH "level\$($pair[1])"))
    if ($code -ne 0) { Fail "layout.py $($pair[0]) (exit code $code)" }
}
Say "OK: the ship and The Hollow" "Green"

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
  3. Choose Blueprint. Project Location: C:\Projects   Project Name: HollowHull  (exactly this name)
  4. Click Create. When the editor has opened, close it.
  5. Run RUN_PHASE1.bat again.
"@
if (-not $found.Uproject) {
    if ($found.Others.Count -gt 0) {
        Say "Found other Unreal projects, which are left alone: $(($found.Others | Select-Object -First 4 | ForEach-Object { $_.FullName }) -join ', ')" "DarkGray"
    }
    Say "No project named HollowHull was found." "Yellow"
    Say $launcherSteps "Yellow"
    Fail "No HollowHull project found in C:\Projects or Documents\Unreal Projects."
}
$uproject = $found.Uproject
$Project = $found.Dir
$ProjectName = $found.Name
Say "Using project: $uproject" "White"
if ($Project -match "OneDrive") {
    # OneDrive breaks Unreal projects (locked and half-synced files), so move it out automatically.
    $target = Join-Path "C:\Projects" $ProjectName
    Say "The project is inside OneDrive. Moving it to $target ..." "Yellow"
    if (Get-Process -Name "UnrealEditor*" -ErrorAction SilentlyContinue) {
        Fail "Unreal is open. Close Unreal completely, then double-click RUN_PHASE1 again."
    }
    if (Test-Path $target) {
        Fail "$target already exists. Delete or rename that folder, then run RUN_PHASE1 again."
    }
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    try {
        Move-Item -Path $Project -Destination $target -ErrorAction Stop
    } catch {
        Say "Automatic move failed: $_" "Red"
        Say "Move it by hand: close Unreal, cut the folder $Project and paste it into C:\Projects." "Yellow"
        Fail "Could not move the project out of OneDrive."
    }
    $Project = $target
    $uproject = Join-Path $target "$ProjectName.uproject"
    Say "Moved. Using project: $uproject" "Green"
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
# Fab packs (Paragon characters) that the launcher put into another project are
# self-contained Content folders. Move (not copy) any that HollowHull is missing:
# on the same drive a move is an instant rename and needs no free space.
$myContent = Join-Path $Project "Content"
function Get-FreeGB([string]$Path) {
    try { return [math]::Round(([IO.DriveInfo]::new([IO.Path]::GetPathRoot($Path))).AvailableFreeSpace / 1GB, 1) }
    catch { return -1 }
}
function Test-HasAllFiles([string]$Dest, [string]$Src) {
    # True when every file under $Src is also under $Dest with the same size.
    $root = (Get-Item -LiteralPath $Src -Force).FullName.TrimEnd('\', '/')
    foreach ($f in Get-ChildItem -LiteralPath $Src -Recurse -File -Force -ErrorAction SilentlyContinue) {
        $d = Join-Path $Dest $f.FullName.Substring($root.Length)
        if (-not (Test-Path -LiteralPath $d)) { return $false }
        if ((Get-Item -LiteralPath $d -Force).Length -ne $f.Length) { return $false }
    }
    return $true
}
Say "Free space on $([IO.Path]::GetPathRoot($Project)) $(Get-FreeGB $Project) GB" "Gray"
foreach ($dir in (Find-OtherProjectDirs $Project $Project)) {
    $packs = Get-ChildItem (Join-Path $dir "Content") -Directory -Filter "Paragon*" -ErrorAction SilentlyContinue
    foreach ($pack in $packs) {
        $dest = Join-Path $myContent $pack.Name
        if (-not (Test-Path $dest)) {
            Say "Moving $($pack.Name) from $dir into HollowHull..." "Yellow"
            try {
                Move-Item -LiteralPath $pack.FullName -Destination $dest -ErrorAction Stop
                continue
            } catch {
                Say "  quick move not possible ($($_.Exception.Message)); moving file by file instead" "Gray"
            }
        } elseif (Test-HasAllFiles $dest $pack.FullName) {
            # HollowHull already has a complete copy, so the other one is a duplicate.
            Say "$($pack.Name) is already complete in HollowHull; removing the duplicate from $dir to free space" "Yellow"
            Remove-Item -LiteralPath $pack.FullName -Recurse -Force -ErrorAction SilentlyContinue
            continue
        } else {
            Say "$($pack.Name) in HollowHull is incomplete (an earlier copy stopped); finishing it from $dir..." "Yellow"
        }
        # Resumes an unfinished copy: files already there are skipped, the rest are moved.
        $code = Invoke-Native "robocopy" @($pack.FullName, $dest, "/E", "/MOVE", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
        if ($code -ge 8) {
            Say "Free space now: $(Get-FreeGB $Project) GB" "Yellow"
            Fail "Moving $($pack.Name) failed (robocopy exit code $code). If it says 'not enough space', free some disk space and run RUN_PHASE1 again - it carries on where it stopped."
        }
        if ((Test-Path $pack.FullName) -and (Test-HasAllFiles $dest $pack.FullName)) {
            Remove-Item -LiteralPath $pack.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
# Epic's Combat variant comes from a separate project made with Third Person + Variants: Combat.
# Copy its Variant_Combat folder, plus any template files it uses that HollowHull lacks
# (/XC /XN /XO = only files missing here; nothing in HollowHull is overwritten).
$combatDir = Find-OtherProjectDirs $Project $Project | Where-Object { Test-Path (Join-Path $_ "Content\Variant_Combat") } | Select-Object -First 1
if ($combatDir) {
    Say "Copying missing Combat variant files from $combatDir..." "Yellow"
    foreach ($folder in @("Variant_Combat", "Characters", "Input", "LevelPrototyping")) {
        $src = Join-Path $combatDir "Content\$folder"
        if (-not (Test-Path $src)) { continue }
        $code = Invoke-Native "robocopy" @($src, (Join-Path $myContent $folder), "/E", "/XC", "/XN", "/XO", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
        if ($code -ge 8) { Fail "Copying $folder from the Combat project failed (robocopy exit code $code)" }
    }
    # its project settings, so Claude can see if the variant needs any (collision channels, tags)
    $cfgOut = Join-Path $LogDir "combat_config"
    New-Item -ItemType Directory -Force $cfgOut | Out-Null
    Copy-Item (Join-Path $combatDir "Config\*.ini") $cfgOut -Force -ErrorAction SilentlyContinue
}
if (Test-Path (Join-Path $myContent "Variant_Combat")) { Say "Combat variant: in the project" "Green" }
else { Say "Combat variant: not found yet (make a Third Person project with Variants: Combat in C:\Projects)" "Yellow" }
$myPacks = @(Get-ChildItem $myContent -Directory -Filter "Paragon*" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
if ($myPacks.Count -gt 0) { Say "Fab characters in the project: $($myPacks -join ', ')" "Green" }
else { Say "No Paragon characters found in HollowHull or your other projects yet." "Yellow" }
$free = Get-FreeGB $Project
if ($free -ge 0 -and $free -lt 15) {
    Say "Only $free GB free on the project drive. Unreal needs roughly 10-15 GB for the characters' shaders and cache." "Yellow"
    Say "If Unreal fails or closes, free some space (Recycle Bin, Downloads, Disk Cleanup) and run again." "Yellow"
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
Say "Do NOT press Play in Unreal until this window says 'Everything checks out'." "Yellow"

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
$inventory = Join-Path $Project "Saved\HollowHull\inventory.json"
if (Test-Path $inventory) { Copy-Item $inventory (Join-Path $LogDir "inventory.json") -Force }
$probe = Join-Path $Project "Saved\HollowHull\combat_probe.json"
if (Test-Path $probe) { Copy-Item $probe (Join-Path $LogDir "combat_probe.json") -Force }
$ueLog = Join-Path $Project "Saved\Logs\$ProjectName.log"
if (Test-Path $ueLog) { Copy-Item $ueLog (Join-Path $LogDir "unreal_log.txt") -Force }
# the enemies' AI and the Combat Blueprints as text plus the raw asset files, for Claude to read
$logicText = Join-Path $Project "Saved\HollowHull\combat_logic.txt"
if (Test-Path $logicText) { Copy-Item $logicText (Join-Path $LogDir "combat_logic.txt") -Force }
try {
    $stage = Join-Path $env:TEMP "hh_combat_logic"
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force (Join-Path $stage "text") | Out-Null
    $logicDir = Join-Path $Project "Saved\HollowHull\logic"
    if (Test-Path $logicDir) { Copy-Item (Join-Path $logicDir "*") (Join-Path $stage "text") -Force }
    $bpDir = Join-Path $Project "Content\Variant_Combat\Blueprints"
    if (Test-Path $bpDir) { Copy-Item $bpDir (Join-Path $stage "assets") -Recurse -Force }
    $zip = Join-Path $LogDir "combat_logic.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    Say "  (could not pack combat_logic.zip: $_)" "Yellow"
}

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
    if ($m.Value.PSObject.Properties["size_cm_imported"] -and [double]$m.Value.size_cm_imported -le 0.01) {
        $problems += "$($m.Name): imported mesh is empty"
    }
    if ($m.Value.collision_hulls_imported -lt $m.Value.collision_hulls_expected) {
        $problems += "$($m.Name): collision $($m.Value.collision_hulls_imported)/$($m.Value.collision_hulls_expected)"
    }
}
$ueLogCopy = Join-Path $LogDir "unreal_log.txt"
if ((Test-Path $ueLogCopy) -and (Select-String -Path $ueLogCopy -Pattern "EnhancedInputActionEvent references invalid" -Quiet)) {
    $problems += "the template character's input actions are broken, so the player cannot move: recreate the project in the launcher (see README)"
}
foreach ($w in $r.warnings) { Say "warning: $w" "Yellow" }
$hollow = $null
if ($r.PSObject.Properties["levels"] -and $r.levels.PSObject.Properties["L_TheHollow"]) { $hollow = $r.levels.L_TheHollow }
if (-not $hollow -or -not $hollow.saved) { $problems += "The Hollow (L_TheHollow) was not built" }
if ($problems.Count -gt 0) {
    Say "Build stopped at stage: $($r.stage)" "Red"
    if ($r.error) { Say "Error:`n$($r.error)" "Red" }
    if (Test-Path $ueLogCopy) {
        Say "--- [HH] lines from the Unreal log ---" "Yellow"
        Select-String -Path $ueLogCopy -Pattern '\[HH\]|LogPython: Error|Traceback' |
            Select-Object -Last 30 | ForEach-Object { Write-Host $_.Line }
    }
    foreach ($p in $problems) { Say "problem: $p" "Red" }
    Say "`nThe level may still be playable. Send Claude reports\phase1\run_log.txt and setup_report.json." "Yellow"
} else {
    Say "Everything checks out." "Green"
}
if ($r.PSObject.Properties["combat"]) {
    Say "`n=== Combat (Phase 2) ==="
    foreach ($c in $r.combat.characters.PSObject.Properties) {
        if ($c.Name -eq "GameMode") { continue }
        if ($c.Value.ok) {
            $moves = if ($c.Value.anim_source -eq "Paragon") { "its own animations" } else { "Epic's combat animations" }
            $pace = if ($c.Value.walk_speed.now) { ", moves at $($c.Value.walk_speed.now) cm/s" } else { "" }
            Say "  $($c.Name): Paragon body, $moves$pace" "Green"
            if (-not $c.Value.foot_ik.off) { Say "    (foot adjuster could not be switched off for $($c.Name); legs may still bend)" "Yellow" }
            if ($c.Value.additive_fixed) {
                $fx = @($c.Value.additive_fixed.PSObject.Properties | Where-Object { $_.Value -notmatch 'no full-pose|Error' })
                if ($fx.Count -gt 0) { Say "    standing pose fixed ($($fx.Count) places used a partial 'Idle' that shrank the body)" "Green" }
            }
            $rd = $c.Value.ragdoll
            if ($rd -and $rd.simulated.Count -gt 0 -and $rd.joints_set -gt 0) {
                Say "    ragdoll: $($rd.simulated.Count) body parts swing, $($rd.kinematic.Count) loose parts ride along, $($rd.joints_set) of $($rd.found.joints) joints set" "Green"
            } elseif ($rd -and $rd.simulated.Count -gt 0) {
                Say "    ragdoll: body parts set, but the joints could not be changed; hits may still make loose parts flap" "Yellow"
            } else { Say "    (ragdoll for $($c.Name) could not be adjusted; hits may still make it wobble)" "Yellow" }
        }
        else { Say "  $($c.Name): mannequin body for now (details in setup_report.json)" "Yellow" }
    }
    $gm = $r.combat.characters.GameMode
    if ($r.combat.epic_character.ok) { Say "  after dying you come back as Revenant" "Green" }
    elseif ($gm) { Say "  respawn: could not dress Epic's character as Revenant (you may come back as the mannequin)" "Yellow" }
    $enemies = 0
    foreach ($k in $r.spawned.PSObject.Properties) { if ($k.Name -like "Enemy_*") { $enemies += [int]$k.Value } }
    $hollowEnemies = 0
    if ($hollow -and $hollow.spawned) {
        foreach ($k in $hollow.spawned.PSObject.Properties) { if ($k.Name -like "Enemy_*") { $hollowEnemies += [int]$k.Value } }
    }
    Say "  enemies placed: $enemies on the ship, $hollowEnemies in The Hollow" "White"
    $enemies += $hollowEnemies
    if ($r.combat.waking) {
        $asleep = @($r.combat.waking.PSObject.Properties | Where-Object { $_.Value.placed -like "asleep*" }).Count
        if ($asleep -eq $enemies) { Say "  each enemy waits in its room until you walk in" "Green" }
        else { Say "  $asleep of $enemies enemies wait in their rooms; the rest chase you from the start (see combat.waking in setup_report.json)" "Yellow" }
    }
    $reach = $r.combat.melee_reach_cm
    if ($reach -is [double] -or $reach -is [int] -or $reach -is [decimal]) { Say "  enemies swing from up to $reach cm away" "Green" }
    elseif ($reach) { Say "  could not widen the enemies' reach: $reach" "Yellow" }
    $st = $r.combat.state_tree
    if ($st -and $st.labels_off -gt 0) { Say "  AI state labels over enemies switched off ($($st.labels_off))" "Green" }
    elseif ($st -and $st.states -gt 0) { Say "  AI state labels over enemies are off (switched off by an earlier build)" "Green" }
    elseif ($st) { Say "  AI state labels over enemies still on (see combat.state_tree in setup_report.json)" "Yellow" }
    if ($r.combat.life_bars) {
        $bars = $r.combat.life_bars
        if ($bars.player -like "lower left*") { Say "  your health bar is in the lower left of the screen" "Green" }
        else { Say "  your health bar stays over the hero: $($bars.player)" "Yellow" }
        if ($bars.enemy -ne "hidden") { Say "  enemy health bars still over their heads: $($bars.enemy)" "Yellow" }
    }
    $keys = @($r.combat.controls | Where-Object { $_.PSObject.Properties["action"] } |
        ForEach-Object { "$($_.key) = $($_.action -replace '^IA_', '')" } | Select-Object -Unique)
    if ($keys.Count -gt 0) { Say "  attack keys: $($keys -join ', ')" "White" }
}
if ($r.audio) {
    $a = $r.audio
    if ($a.imported -gt 0) {
        Say "Sound: $($a.imported) sounds imported (footsteps, hits, gunshots, swings, music)" "Green"
        if ($a.falloff) { Say "  sounds fade with distance: $($a.falloff)" "White" }
        foreach ($l in $a.level_music.PSObject.Properties) { Say "  music for $($l.Name): $($l.Value)" "White" }
    } else { Say "Sound: nothing imported (see audio in setup_report.json)" "Yellow" }
    if ($a.problems) { Say "  some sounds had problems (see audio.problems in setup_report.json)" "Yellow" }
}
if ($hollow -and $hollow.spawned) {
    $hs = $hollow.spawned
    $meshes = 0
    foreach ($k in $hs.PSObject.Properties) { if ($k.Name -like "SM_*") { $meshes += [int]$k.Value } }
    Say "`n=== The Hollow (L_TheHollow) ==="
    Say "  $meshes pieces of flesh and bone, $([int]$hs.PointLight) glowing lights" "Green"
}
if ($r.textures) {
    $ok = @($r.textures.PSObject.Properties | Where-Object { $_.Value -eq "textured" }).Count
    $all = @($r.textures.PSObject.Properties).Count
    Say "Realistic surfaces: $ok of $all materials got their fal textures" $(if ($ok -eq $all) { "Green" } else { "Yellow" })
    foreach ($t in $r.textures.PSObject.Properties) { if ($t.Value -ne "textured") { Say "  $($t.Name): $($t.Value)" "Yellow" } }
}
Say "`nNow in Unreal: press Play (Alt+P). WASD to move, Space to jump."  "Cyan"
Say "Route: cabin -> corridor -> crew quarters -> corridor -> flooded engine room (stairs to the mezzanine)" "Cyan"
Say "       -> south exit under the mezzanine -> green corridor -> cargo hold." "Cyan"
Say "Monsters: Khaimera in the crew quarters and the green corridor, Grux in the engine room, Sevarog in the cargo hold." "Cyan"
Say "Kill Sevarog and the floor gives way: you fall into The Hollow." "Magenta"
Say "  The Hollow: the drop -> rib tunnel -> ossuary -> drowned gallery (deep water) -> throat -> heart chamber." "Cyan"
Say "  To go straight there: Content Browser > HollowHull > Maps > double-click L_TheHollow, then Play." "Cyan"
Say "Then tell Claude what broke, felt wrong, or looked too dark/bright." "Cyan"
Say "While you play, recorders write reports\phase1\play_trace.json, audio_trace.json and world_trace.json - send them and reports\phase1\combat_logic.txt to Claude with the other reports." "Cyan"
Stop-Transcript | Out-Null
