# Hollow Hull

A small third-person survival-horror concept: one flooded deck of a cursed
1900s steamship. It's inspired by the genre of *Black Tides: Draga's Wake*,
with its own names, story and art. See [DESIGN.md](DESIGN.md).

## Quick start (Windows)

1. Get the files into `C:\Users\gasan\OneDrive\Desktop\hollow-hull`: either
   `git clone https://github.com/Project888-maker/hollow-hull.git .` inside
   that folder, or on GitHub click **Code > Download ZIP** and extract the
   contents there.
2. Create the Unreal project once, with Epic's launcher: **Unreal Engine 5.7 >
   New Project > Games > Third Person > Blueprint**, Project Location
   `C:\Projects`, Project Name `HollowHull`, **Create**. Close the editor when it
   has opened. (The launcher installs the template's input and character
   content; a copied template folder does not.)
3. Double-click **`RUN_PHASE1.bat`**. If Windows shows "Windows protected your
   PC", click **More info > Run anyway**. Unreal opens, builds the level and
   stays open. The first launch compiles shaders (10 to 40 minutes).

Everything is logged to `reports\phase1\run_log.txt`. If Unreal closes by
itself at any point, double-click **`COLLECT_LOGS.bat`** and send Claude what it
shows (graphics card, crash message, the important log lines).

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
| `blender/hh_kit.py` | Every kit piece, built procedurally with `UCX_` collision: the ship (walls, floors, stairs, boiler, props) and The Hollow (rib walls, mouth doorways, spines, bone piles, glowing growths, the heart) |
| `blender/build_ship_kit.py` | Exports one FBX per piece and `manifest.json` (runs headless) |
| `blender/build_level_preview.py` | Builds the level in Blender from the placements and renders previews |
| `level/flooded_deck.json` | **Level 1, the ship**: text grid map, zones, doors, stairs, props |
| `level/the_hollow.json` | **Level 2, The Hollow**: the living cave under the ice, its glow lights, fog and look |
| `level/layout.py` | Turns a grid map into exact placements (`placements.json`, `placements_the_hollow.json`) |
| `unreal/hh_setup.py` | Imports the kit, creates materials, builds `L_TheHollow` and `L_FloodedDeck` |
| `unreal/hh_audio.py` | Sound while you play: footsteps per floor, swings, hits, voices, each level's music |
| `unreal/hh_moves.py` | Extra moves for Revenant from his own Paragon animations: flinch from the side he is hit, stagger on big hits, gun-spin reload after shooting, idle fidgets |
| `unreal/hh_world.py` | World events while you play: the fall into The Hollow when Sevarog dies, the beating heart, breathing in the walls |
| `audio/make_audio.py` | Synthesises all music and sound effects into `audio/wav` |
| `textures/materials.json` | Realistic surface pictures per material: the fal.ai prompt, how many metres one copy covers, wet-to-dry shine |
| `tools/fal_textures.py` | Asks fal.ai for each picture (`FAL_KEY` from the environment) into `textures/<material>/source.png` |
| `tools/make_pbr.py` | Makes each picture tile seamlessly and adds bump (normal) and shine (AO/roughness) maps; `hh_setup.py` plugs them into the game's materials, Blender previews use them too |
| `meshes/models.json` | Kit pieces replaced by fal.ai 3D models (the heart, skull piles, crates, barrels, bunks, table, chairs, sea chests, rope, sacks, valve wheel): prompt, size or fit, triangle budget |
| `tools/fal_models.py` | Makes those models: fal concept picture, then Hunyuan3D, then fitted in Blender into `meshes/<piece>.glb` plus its colour map; `hh_kit.py` uses them instead of the hand-built piece |
| `unreal/hh_combat.py` | Phase 2: retargets Epic's Combat variant onto the Paragon heroes, places the enemies and a nav mesh |
| `unreal/hh_screenshots.py` | Captures four review shots inside Unreal |
| `tools/prepare_project.py` | Prepares the launcher-made project: plugins, startup map, `init_unreal.py` build hook |
| `export/ship_kit/` | Generated FBX files (committed, so Unreal works even without Blender) |
| `preview/` | Blender renders of the kit and the ship (`preview/hollow/` for The Hollow) |
| `reports/` | Codex run reports and Unreal screenshots |

## Phases

1. **Greybox level** (done): kit, layout, lighting and atmosphere, walkable with the template character → `CODEX_PHASE1.md`
2. **Combat core** (now): Epic's Third Person Combat variant (combo and charged attacks, AI enemies, health
   bars) with Paragon heroes retargeted onto it: Revenant as the player, Khaimera, Grux and Sevarog as enemies
   (`level/flooded_deck.json` → `enemies`). Needs the Fab Paragon packs and a helper project made with
   Third Person + Variants: Combat; `RUN_PHASE1.bat` copies both into HollowHull. Next: realistic kills
   (hit-stop, directional hit reactions, ragdoll impulse), harpoon pistol
3. **Enemies and infection**: one creature type with AI, plus the infection meter and its screen effects
4. **Art pass**: Megascans/Fab materials, fal-generated textures and concept art, hero meshes, decals
5. **Shifting corridor, audio, polish**
