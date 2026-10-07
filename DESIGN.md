# Hollow Hull: vertical slice design

## Pitch
Winter, 1907. The steamship *Saint Ormund* sits frozen in pack ice. You are a
smuggler who boarded for one last job. Something below deck has been waiting,
and it is already inside you.

## Pillars
- **Every bullet is a decision.** Ammo, health and power are scarce. Melee is
  free but risky.
- **The ship is the enemy.** Cramped corridors, multi-level rooms, flooded
  decks, and a corridor that is no longer the same when you come back.
- **Power that costs you.** Using the infection makes you stronger and makes
  it harder to stay yourself.

## Core loop
Explore → find scarce supplies → fight (dodge, combo, shoot to punish) →
choose whether to spend infection power → push deeper.

## The slice: L_FloodedDeck (10 to 15 minutes)
| # | Space | Beat |
|---|---|---|
| 1 | Cabin (start) | Wake up, lantern light, first note. Controls tutorial |
| 2 | Upper corridor | Portholes show the ice outside. Sealed door. Ship creaks |
| 3 | Crew quarters | Empty bunks, first growth. **First enemy**: teaches dodge + combo |
| 4 | Lower corridor | Lights fail. Something moves behind you |
| 5 | Engine room | Flooded floor, boilers, mezzanine. **Arena**: 2 to 3 enemies, use height |
| 6 | Shifting corridor | Sickly green light, growths everywhere. Coming back, the layout has changed |
| 7 | Cargo hold | The source of the growth. Ending sting, then cut to black |

## Controls (gamepad / keyboard)
Move WASD · Camera mouse · Dodge Space/B · Light attack LMB/X · Heavy attack
hold LMB/Y · Aim RMB/LT · Shoot LMB while aiming/RT · Infection power Q/LB ·
Interact E/A

## Systems, by phase
- **Phase 2, combat:** character with a 3-hit light combo and a heavy finisher
  (montages, with combo windows from anim notifies). Dodge with i-frames. A
  harpoon pistol with 6 shots total in the slice. A Health/Ammo/Power
  component. A hit-stop and camera-shake pass.
- **Phase 3, enemies and infection:** a "Drowned" crew creature (StateTree or
  Behavior Tree: patrol → hear → stalk → telegraphed lunge → recover window).
  Infection 0 to 100 rises when you use power. It drives post-process
  intensity, whispers, and at high values the camera sometimes resists you.
- **Phase 5, ship shifting:** corridor sections swap while you aren't looking
  (level streaming or hidden actor sets).

## Look
Cold blue light from the portholes against warm sodium lamps. Wet, rusted
steel. Volumetric fog. Flesh growths with bioluminescent pustules. Inspired by
Edwardian ship interiors, *Still Wakes the Deep*, *Dead Space* and Lovecraft.
