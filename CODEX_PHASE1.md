# Codex task: Hollow Hull, Phase 1 (greybox level in Unreal)

You are running on the user's own computer, where Blender and Unreal Engine 5.7
are installed. Claude (in the cloud) wrote every script in this folder. Your
job is to **run them in order, check each result, and report back**. You are
not asked to design or improve anything.

## Rules

1. Run the steps in order. After each step, check the "Expect" line.
2. If a step fails, **stop**, copy the exact error and the last 40 lines of
   output into the report (step 8), and tell the user. Do not work around it.
3. Do not edit anything in this repo except `reports/`. If you think a script is wrong, say so in the
   report. Claude fixes scripts; you run them.
4. Do not hand-edit assets under `/Game/HollowHull/` in Unreal. Re-running
   `hh_setup.py` overwrites the meshes and respawns the level.
5. Ask the user before you install anything or touch files outside the repo
   and the Unreal project folder.

Commands below are for Windows PowerShell. On macOS or Linux use the same
arguments with that OS's paths.

---

## Step 0: Get the code

The user made `C:\Users\gasan\OneDrive\Desktop\hollow-hull` for this
project. Clone the repo into it. Use the trailing `.` so the files go into that
folder rather than a new subfolder.

```powershell
$HH = "C:\Users\gasan\OneDrive\Desktop\hollow-hull"
Set-Location $HH
if (Test-Path "$HH\.git") { git pull origin main }
elseif (-not (Get-ChildItem $HH -Force)) { git clone https://github.com/Project888-maker/hollow-hull.git . }
else { Write-Host "Folder is not empty and is not a git clone: ask the user before touching it" }
```

**Expect:** `$HH\CODEX_PHASE1.md` exists. If the folder already held files,
stop and ask the user. Do not delete or move them.

## Step 1: Find the tools

```powershell
$BLENDER = (Get-ChildItem "C:\Program Files\Blender Foundation" -Recurse -Filter blender.exe | Select-Object -First 1).FullName
$UE = "C:\Program Files\Epic Games\UE_5.7"
$UEEDITOR = "$UE\Engine\Binaries\Win64\UnrealEditor.exe"
& $BLENDER --version
Test-Path $UEEDITOR
python --version
```
If Blender or Unreal is installed somewhere else, ask the user for the path.

**Expect:** Blender prints `Blender 5.x`, `Test-Path` prints `True`, Python is 3.9 or newer.

## Step 2: Generate the ship kit in Blender

```powershell
& $BLENDER --background --factory-startup --python "$HH\blender\build_ship_kit.py" -- --out "$HH\export\ship_kit"
```

**Expect:** the last line is `[HH] kit done: 21 pieces -> ...`, and
`$HH\export\ship_kit` holds 21 `.fbx` files plus `manifest.json`.

If this fails on the user's Blender version, record the error, run
`git checkout -- export/ship_kit` to restore the committed
FBX files Claude generated, and continue.

## Step 3: Generate the level placements

```powershell
python "$HH\level\layout.py" "$HH\level\flooded_deck.json" "$HH\level\placements.json"
```

**Expect:** `[HH] 383 meshes, 24 lights -> ...`

## Step 4: Create the Unreal project

**The Unreal project must not live in a OneDrive-synced folder** (Desktop
and usually Documents are synced). OneDrive locks Unreal's cache files and
uploads gigabytes. Use `C:\Projects\HollowHull` unless the user picks another
non-synced path.

```powershell
New-Item -ItemType Directory -Force "C:\Projects" | Out-Null
$PROJ = "C:\Projects\HollowHull"
python "$HH\tools\prepare_project.py" --engine "$UE" --dest "$PROJ"
```
If the user already created a Third Person project, run this instead:
`python "$HH\tools\prepare_project.py" --existing "<path>\<Name>.uproject"`

**Expect:** `[HH] project ready: ...\HollowHull.uproject`

## Step 5: Build the level inside Unreal

```powershell
& $UEEDITOR "$PROJ\HollowHull.uproject" -ExecutePythonScript="$HH\unreal\hh_setup.py"
```

The editor opens. **The first launch compiles shaders and can take 10 to 40
minutes.** Leave it open. When the script finishes, the log
`$PROJ\Saved\Logs\HollowHull.log` contains `[HH] report -> ...`.

```powershell
Select-String -Path "$PROJ\Saved\Logs\HollowHull.log" -Pattern "\[HH\]"
Get-Content "$PROJ\Saved\HollowHull\setup_report.json"
```

**Expect** in `setup_report.json`:
- `"ok": true`
- 21 entries under `"meshes"`, each with `collision_hulls_imported` equal to
  `collision_hulls_expected`
- under `"spawned"`, these counts: SM_Wall 75, SM_Pillar 88, SM_Ceiling 46,
  SM_Floor_Steel 39, SM_Water_Tile 20, SM_Lamp_Cage 24, SM_Wall_Porthole 11,
  SM_Floor_Grate 9, SM_Wall_Door 8, SM_Railing 8, PointLight 24, PlayerStart 1
- `"warnings"` copied into the report as they are, even when the list is empty

**If you control Unreal through an MCP connection** instead of the command
line, run this in the editor's Python:
```python
import os; os.environ["HH_REPO"] = r"<full path to the hollow-hull repo>"
exec(open(os.path.join(os.environ["HH_REPO"], "unreal/hh_setup.py")).read())
```

## Step 6: Screenshots (optional but very useful)

With the editor still open on `L_FloodedDeck`, go to Tools > Execute Python
Script and choose `$HH\unreal\hh_screenshots.py` (or `exec` it over MCP). Wait
about 30 seconds.

**Expect:** `HH_cabin.png`, `HH_engine_room.png`, `HH_engine_mezzanine.png`
and `HH_hold.png` in `$PROJ\Saved\Screenshots\Windows*\`. Copy them to
`$HH\reports\phase1\`.

## Step 7: Hand over to the user for a play test

Tell the user:
> The level is built. In Unreal, press **Play** (Alt+P). Walk with WASD, jump
> with Space. Route: start cabin → east corridor → crew quarters → corridor
> south → flooded engine room (wade through the water, climb the stairs to the
> mezzanine) → exit under the mezzanine on the south side → green-lit corridor
> → cargo hold. Note anything you can walk through, get stuck on, or that looks
> too dark or too bright.

## Step 8: Report

Write `$HH\reports\phase1\codex_report.md` containing:
1. Blender version, Unreal version, operating system
2. Pass or fail for steps 2 to 6, with the error text for any failure
3. The full contents of `setup_report.json`
4. Any `[HH] WARNING` lines from the Unreal log
5. The user's play-test notes, if they give any

Then try:
```powershell
git add reports
git commit -m "Hollow Hull phase 1: Codex run report"
git push origin main
```
If the push is rejected, run `git pull --rebase origin main`
and push again. If you have no push access, show the user the report so they
can paste it to Claude.
