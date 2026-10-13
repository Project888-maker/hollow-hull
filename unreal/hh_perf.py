"""Graphics presets and a frame-rate recorder for Play sessions.

The game ran at about 14 fps on the ship and 11 in The Hollow on integrated graphics
(run of 2026-10-13). What costs the most there:

  - every lamp cast a shadow: each point light renders the level six times (a cube of
    shadow maps) every frame, 24 lamps on the ship and 21 in The Hollow
  - volumetric fog: a 3D grid lit by every lamp, every frame
  - full resolution, screen-space ambient occlusion and reflections

So during Play this keeps shadows only on the few lamps nearest the hero and applies a
preset of engine settings. F9 cycles the presets so you can feel the difference:

  Fast      70% resolution, no volumetric fog, no AO or screen reflections, 2 shadow lamps
  Balanced  85% resolution, coarser volumetric fog, 4 shadow lamps        (the default)
  Full      what the build set up: every lamp casts shadows, nothing reduced

Settings are console variables changed at run time only, put back when Play stops, so
nothing in the project is altered. reports/phase1/perf_trace.json gets the average and
worst frame times per level and preset, the screen size, and how long our own Python
helpers (sound, recorder, world events) take each frame.
"""

import json
import os
import statistics
import time

import unreal

PRESETS = {
    "Fast": {"shadow_lamps": 2, "cvars": {
        "r.ScreenPercentage": 70, "r.VolumetricFog": 0, "r.AmbientOcclusionLevels": 0,
        "r.SSR.Quality": 0, "r.Shadow.MaxResolution": 512, "r.BloomQuality": 2}},
    "Balanced": {"shadow_lamps": 4, "cvars": {
        "r.ScreenPercentage": 85, "r.VolumetricFog.GridPixelSize": 16, "r.VolumetricFog.GridSizeZ": 64,
        "r.Shadow.MaxResolution": 512}},
    "Full": {"shadow_lamps": None, "cvars": {}},
}
ORDER = ["Balanced", "Fast", "Full"]
DEFAULT = "Balanced"
SWITCH_KEY = "F9"
LAMP_EVERY = 0.5        # seconds between choosing which lamps cast shadows
LAMP_MARGIN_CM = 300.0  # a lamp counts as near while the hero is inside its light radius plus this
REPORT_AFTER = 8.0      # seconds after a switch, show the fps the new preset gets

S = {"handle": None, "out": None, "paused": False, "busy": False, "world": None, "session": None,
     "sessions": [], "errors": {}, "preset": DEFAULT, "original": {}, "lamps": None, "lamp_t": -99.0,
     "key": None, "key_down": False, "frames": [], "switch_t": None}


def _err(where, exc):
    S["errors"].setdefault(where, f"{type(exc).__name__}: {exc}"[:200])


def add_python(name, seconds):
    """Called by the other helpers with the time their tick took."""
    if S["session"] is None:
        return
    acc = S["session"]["_python"].setdefault(name, [0.0, 0])
    acc[0] += seconds * 1000.0
    acc[1] += 1


def _game_world():
    try:
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    except Exception:
        return None


def _cvar_get(name):
    try:
        return unreal.SystemLibrary.get_console_variable_float_value(name)
    except Exception as exc:
        _err("read " + name, exc)
        return None


def _cvar_set(world, name, value):
    try:
        unreal.SystemLibrary.execute_console_command(world, f"{name} {value:g}")
    except Exception as exc:
        _err("set " + name, exc)


def _apply(world, name):
    """Switch to a preset: put every changed setting back, then apply this preset's."""
    S["preset"] = name
    wanted = PRESETS[name]["cvars"]
    for cvar in {c for p in PRESETS.values() for c in p["cvars"]}:
        if cvar not in S["original"]:
            S["original"][cvar] = _cvar_get(cvar)
        value = wanted.get(cvar, S["original"][cvar])
        if value is not None:
            _cvar_set(world, cvar, value)
    S["lamp_t"] = -99.0  # choose shadow lamps again now
    S["switch_t"] = time.time()
    S["frames"] = []
    seen = {c: _cvar_get(c) for c in wanted}
    S["session"].setdefault("applied", {})[name] = {c: v for c, v in seen.items() if v is not None}


def _restore(world):
    for cvar, value in S["original"].items():
        if value is not None:
            _cvar_set(world, cvar, value)
    for comp, shadows in (S["lamps"] or []):
        try:
            comp.set_cast_shadows(shadows)
        except Exception:
            pass


def _find_lamps(world):
    lamps = []
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PointLight):
        try:
            comp = actor.get_component_by_class(unreal.PointLightComponent)
            if comp.get_editor_property("mobility") != unreal.ComponentMobility.MOVABLE:
                comp.set_mobility(unreal.ComponentMobility.MOVABLE)  # only movable lamps may change shadows
            lamps.append((comp, bool(comp.get_editor_property("cast_shadows"))))
        except Exception as exc:
            _err("lamp", exc)
    S["session"]["lamps"] = {"found": len(lamps), "casting_shadows": sum(1 for _, s in lamps if s)}
    return lamps


def _shadow_budget(world, now):
    """Shadows only on the lamps nearest the hero (among those built to cast them)."""
    if now - S["lamp_t"] < LAMP_EVERY:
        return
    S["lamp_t"] = now
    if S["lamps"] is None:
        S["lamps"] = _find_lamps(world)
    budget = PRESETS[S["preset"]]["shadow_lamps"]
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    if pawn is None:
        return
    p = pawn.get_actor_location()
    near = []
    for comp, shadows in S["lamps"]:
        if not shadows:
            continue
        try:
            loc = comp.get_world_location()
            d = ((loc.x - p.x) ** 2 + (loc.y - p.y) ** 2 + (loc.z - p.z) ** 2) ** 0.5
            reach = comp.get_editor_property("attenuation_radius") + LAMP_MARGIN_CM
            near.append((d, d <= reach, comp))
        except Exception as exc:
            _err("lamp distance", exc)
    near.sort(key=lambda n: n[0])
    on = 0
    for d, inside, comp in near:
        want = budget is None or (inside and on < budget)
        on += want
        try:
            if bool(comp.get_editor_property("cast_shadows")) != want:
                comp.set_cast_shadows(want)
        except Exception as exc:
            _err("set shadows", exc)
    S["session"]["shadow_lamps_max"] = max(S["session"].get("shadow_lamps_max", 0), on)


def _switch_key(world):
    try:
        if S["key"] is None:
            k = unreal.Key()
            k.set_editor_property("key_name", SWITCH_KEY)
            S["key"] = k
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        down = bool(pc and pc.is_input_key_down(S["key"]))
    except Exception as exc:
        _err("key", exc)
        S["key"] = False
        return
    if down and not S["key_down"]:
        name = ORDER[(ORDER.index(S["preset"]) + 1) % len(ORDER)]
        _apply(world, name)
        _say(world, f"Graphics: {name}  (F9 to change)")
        S["session"].setdefault("switches", []).append(name)
    S["key_down"] = down


def _say(world, text, seconds=4.0):
    try:
        unreal.SystemLibrary.print_string(world, text, print_to_screen=True, print_to_log=True,
                                          text_color=unreal.LinearColor(1.0, 0.85, 0.3, 1.0), duration=seconds)
    except Exception as exc:
        _err("say", exc)


def _record(world, dt):
    """Frame times per level and preset; after a switch, show what the preset gets."""
    if dt <= 0 or dt > 2.0:
        return  # a loading hitch, not a frame
    level = S["session"]["level"]
    stats = S["session"]["frames"].setdefault(f"{level} / {S['preset']}", {"frames": 0, "seconds": 0.0, "ms": []})
    stats["frames"] += 1
    stats["seconds"] += dt
    if len(stats["ms"]) < 20000:
        stats["ms"].append(round(dt * 1000.0, 1))
    S["frames"].append(dt)
    if S["switch_t"] and time.time() - S["switch_t"] > REPORT_AFTER and S["frames"]:
        fps = len(S["frames"]) / sum(S["frames"])
        _say(world, f"Graphics: {S['preset']}, about {fps:.0f} fps", 3.0)
        S["switch_t"] = None


def _level(world):
    name = world.get_name()
    return name.split("_", 2)[-1] if name.startswith("UEDPIE_") else name


def _summary(sess):
    out = {k: v for k, v in sess.items() if k not in ("frames", "_t0", "_written", "_python")}
    out["fps"] = {}
    for key, st in sess["frames"].items():
        ms = sorted(st["ms"])
        if not ms:
            continue
        out["fps"][key] = {"average_fps": round(st["frames"] / st["seconds"], 1), "seconds": round(st["seconds"], 1),
                           "median_ms": round(statistics.median(ms), 1),
                           "worst_5pct_ms": ms[int(len(ms) * 0.95)], "worst_ms": ms[-1]}
    out["python_ms_per_frame"] = {n: round(t / max(c, 1), 2) for n, (t, c) in sess["_python"].items()}
    return out


def _write():
    if not S["out"]:
        return
    try:
        os.makedirs(os.path.dirname(S["out"]), exist_ok=True)
        data = {"what": "Hollow Hull frame rate per Play session (newest last); F9 cycles graphics presets",
                "presets": PRESETS, "errors": S["errors"], "sessions": [_summary(s) for s in S["sessions"][-4:]]}
        with open(S["out"], "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except Exception as exc:
        _err("write", exc)


def _end_session():
    _restore(S["world"])
    _write()
    S.update({"world": None, "session": None, "lamps": None, "key_down": False, "frames": [], "switch_t": None})


def _tick(dt):
    if S["paused"] or S["busy"]:
        return
    S["busy"] = True
    t0 = time.perf_counter()
    try:
        world = _game_world()
        if world is None:
            if S["world"] is not None:
                _end_session()
            return
        if S["world"] is not None and S["world"] != world:  # travelled to the next level
            _end_session()
        if S["world"] is None:
            S["world"] = world
            S["session"] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "level": _level(world),
                            "frames": {}, "_python": {}, "_t0": time.time()}
            S["sessions"].append(S["session"])
            try:
                size = unreal.WidgetLayoutLibrary.get_viewport_size(world)
                S["session"]["screen"] = [int(size.x), int(size.y)]
            except Exception as exc:
                _err("screen size", exc)
            _apply(world, S["preset"])
            _say(world, f"Graphics: {S['preset']}  (F9 to change)", 5.0)
        now = time.time()
        _record(world, dt)
        _shadow_budget(world, now)
        if S["key"] is not False:
            _switch_key(world)
        sess = S["session"]
        if now - sess.get("_written", 0.0) > 10.0:
            sess["_written"] = now
            _write()
    except Exception as exc:
        _err("tick", exc)
    finally:
        add_python("graphics", time.perf_counter() - t0)
        S["busy"] = False


def start(out_path):
    """Apply the graphics preset and record frame rates in every Play session from now on."""
    S["out"] = out_path
    if S["handle"] is None:
        S["handle"] = unreal.register_slate_post_tick_callback(_tick)
    unreal.log(f"[HH] graphics presets and frame-rate recorder on -> {out_path}")
