# Hollow Hull

A small third-person survival-horror concept: one flooded deck of a cursed
1900s steamship. It's inspired by the genre of *Black Tides: Draga's Wake*,
with its own names, story and art. See [DESIGN.md](DESIGN.md).

## How we work

```
Claude (cloud)                    Codex (your PC)                  You
──────────────                    ───────────────                  ───
writes scripts, generates   ──►   pulls this repo, runs     ──►   press Play,
assets, renders previews,         Blender + Unreal steps from      say what feels
pushes to this repo               CODEX_PHASE<N>.md, reports       wrong
        ▲                                   │                         │
        └───────── report + screenshots ────┴──────── feedback ───────┘
```

- **Scripts are the source of truth.** The kit, the layout and the Unreal
  level are all generated, so a change is made in a script and re-run, never
  by hand in Unreal.
- Actors the setup script spawns carry the tag `HH_Generated` and are
  replaced on every re-run. Put anything you place by hand in your own
  sublevel, or leave it untagged.
- Material instances (`/Game/HollowHull/Materials/MI_*`) are created once and
  never overwritten. Tune them or plug textures into them freely.

## Where things live on the PC

| What | Path |
|---|---|
| This repo (Codex's working copy) | `C:\Users\gasan\OneDrive\Desktop\hollow-hull` |
| Unreal project (keep it out of OneDrive) | `C:\Projects\HollowHull` |

## Folders

| Path | What it is |
|---|---|
| `blender/hh_kit.py` | Every kit piece, built procedurally (walls, floors, stairs, boiler, props) with `UCX_` collision |
| `blender/build_ship_kit.py` | Exports one FBX per piece and `manifest.json` (runs headless) |
| `blender/build_level_preview.py` | Builds the level in Blender from the placements and renders previews |
| `level/flooded_deck.json` | **The level**: text grid map, zones, doors, stairs, props |
| `level/layout.py` | Turns the grid map into exact placements (`placements.json`) |
| `unreal/hh_setup.py` | Imports the kit, creates materials, builds `L_FloodedDeck` |
| `unreal/hh_screenshots.py` | Captures four review shots inside Unreal |
| `tools/prepare_project.py` | Creates the Unreal project from the Third Person template |
| `export/ship_kit/` | Generated FBX files (committed, so Unreal works even without Blender) |
| `preview/` | Blender renders of the kit and the level |
| `reports/` | Codex run reports and Unreal screenshots |

## Phases

1. **Greybox level** (now): kit, layout, lighting and atmosphere, walkable with the template character → `CODEX_PHASE1.md`
2. **Combat core**: dodge with i-frames, 3-hit melee combo, harpoon pistol, scarce health/ammo/power
3. **Enemies and infection**: one creature type with AI, plus the infection meter and its screen effects
4. **Art pass**: Megascans/Fab materials, fal-generated textures and concept art, hero meshes, decals
5. **Shifting corridor, audio, polish**
