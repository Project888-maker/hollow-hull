"""Hollow Hull sound: footsteps, swings, gunshots, hits, deaths and music per level.

Two halves:

import_audio()  build time (an hh_setup stage). Imports audio/wav/*.wav (made by
                audio/make_audio.py) into /Game/HollowHull/Audio, makes the music loop
                and gives every sound one shared distance falloff (ATT_HH_World).

start(out)      play time (init_unreal.py starts it on every editor launch, like the
                play recorder). Nothing happens until Play is pressed; then every frame
                it looks at the characters and plays:
                  - footsteps for the floor under each one (steel, wood, grate, water,
                    and in The Hollow flesh and bone),
                    a heavier thud on landing
                  - the hero's own voice from the Paragon packs on each swing, when hurt
                    and when dying, plus a whoosh for monster swings and a gunshot for
                    each of Revenant's shots
                  - a hit sound whenever someone loses health
                  - the level's music (level/<level>.json "music"), with a drum and
                    string layer faded in while a monster is close
                It also settles Epic's half-limp hit reaction, which otherwise lasts
                until the character lands (see _recover_from_hit).
                A summary goes to reports/phase1/audio_trace.json. Every Unreal call is
                guarded: sound can never stop the game, it only goes quiet.
"""

import glob
import hashlib
import json
import math
import os
import random
import re
import time

import unreal

try:
    import hh_moves
except Exception:  # the moves are extra; sound works without them
    hh_moves = None

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.path.join(os.environ["HH_REPO"], "unreal")
ROOT = os.path.dirname(HERE)
WAV_DIR = os.path.join(ROOT, "audio", "wav")
AUDIO = "/Game/HollowHull/Audio"
ATTENUATION = AUDIO + "/ATT_HH_World"
FAR_ATTENUATION = AUDIO + "/ATT_HH_Far"  # The Hollow's heartbeat and groans carry much further

# --- mix (safe to edit; takes effect next Play after an editor restart) -----

MUSIC_VOLUME = 0.55
COMBAT_VOLUME = 0.6
MUSIC_FADE_IN = 4.0
COMBAT_FADE_IN, COMBAT_FADE_OUT = 2.5, 5.0
THREAT_CM = 1500          # a living monster this close (and on this deck) starts the fight layer
CALM_AFTER = 8.0          # seconds without a monster close before the fight layer fades
STEP_VOLUME = {"player": 0.55, "monster": 0.8}
SURFACE_VOLUME = {"water": 0.7}  # wading is softer than a boot on steel
VOICE_VOLUME = 0.9
PAIN_GAP = 0.7            # seconds between pain cries from one character
FALLOFF_INNER_CM, FALLOFF_CM = 400.0, 3200.0
HIT_HOLD, HIT_GIVE_UP = 0.6, 3.0  # a hit's limpness shows this long; settle it then if on the floor

# Paragon voice cues per hero; {h} is the hero name
CUE_DIRS = {"Revenant": "/Game/ParagonRevenant/Audio/Cues"}
CUE_DIR = "/Game/Paragon{h}/Characters/Heroes/{h}/Sounds/SoundCues"
HERO_HEAD_CM = {"Revenant": 165, "Khaimera": 165, "Grux": 205, "Sevarog": 240}
FLOORS = {"SM_Floor_Steel": "steel", "SM_Floor_Wood": "wood", "SM_Floor_Grate": "grate",
          "SM_Floor_Flesh": "flesh", "SM_Floor_Bone": "bone"}
HASH_TAG = "HHWavHash"
VARIANTS = {"step_steel": 4, "step_wood": 4, "step_grate": 4, "step_water": 4, "step_flesh": 4, "step_bone": 4,
            "hit": 3, "gunshot": 3, "whoosh": 2}


def _level_music():
    """level name -> music asset name, from level/*.json ("music")."""
    out = {}
    for path in glob.glob(os.path.join(ROOT, "level", "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("level") and data.get("music"):
                out[data["level"]] = data["music"]
        except Exception:
            continue
    return out


# --- build time -------------------------------------------------------------

def _make_attenuation(asset_tools, eal, path=ATTENUATION, inner=None, falloff=None):
    att = unreal.load_asset(path) if eal.does_asset_exist(path) else None
    if att is None:
        factory = None
        try:
            factory = unreal.SoundAttenuationFactory()
        except Exception:
            pass
        att = asset_tools.create_asset(path.rsplit("/", 1)[1], AUDIO, unreal.SoundAttenuation, factory)
    _set_falloff(att, inner, falloff)
    eal.save_asset(path, only_if_is_dirty=False)
    return att


def _set_falloff(att, inner=None, falloff=None):
    s = att.get_editor_property("attenuation")
    for name, value in (("attenuate", True), ("spatialize", True),
                        ("attenuation_shape", unreal.AttenuationShape.SPHERE),
                        ("attenuation_shape_extents", unreal.Vector(inner or FALLOFF_INNER_CM, 0, 0)),
                        ("falloff_distance", falloff or FALLOFF_CM),
                        ("distance_algorithm", unreal.AttenuationDistanceModel.NATURAL_SOUND),
                        ("attenuate_with_lpf", True), ("lpf_radius_min", 1500.0), ("lpf_radius_max", 4000.0)):
        try:
            s.set_editor_property(name, value)
        except Exception:
            pass
    att.set_editor_property("attenuation", s)


def import_audio(report, warn, log):
    """Import the generated sounds. Problems are warnings: the game runs without sound."""
    info = report.setdefault("audio", {})
    files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")))
    if not files:
        warn("no sounds in audio/wav; run python audio/make_audio.py")
        info["imported"] = 0
        return
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    eal = unreal.EditorAssetLibrary
    # Re-importing over an existing SoundWave crashed Unreal (access violation inside
    # the sound factory, 2026-10-12). So a sound is imported only when its WAV is new or
    # changed (hash kept as a metadata tag), and a changed one is deleted first and
    # imported fresh, never replaced in place. One file per import, logged first, so a
    # crash names the file.
    skipped, fresh = 0, 0
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        asset_path = f"{AUDIO}/{name}"
        with open(path, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()
        if eal.does_asset_exist(asset_path):
            old = unreal.load_asset(asset_path)
            if old is not None and eal.get_metadata_tag(old, HASH_TAG) == digest:
                skipped += 1
                continue
            old = None
            if not eal.delete_asset(asset_path):
                warn(f"{name}: old sound could not be removed, kept as it is")
                continue
        log(f"audio: importing {name}")
        t = unreal.AssetImportTask()
        t.set_editor_property("filename", path)
        t.set_editor_property("destination_path", AUDIO)
        t.set_editor_property("destination_name", name)
        t.set_editor_property("replace_existing", False)
        t.set_editor_property("automated", True)
        t.set_editor_property("save", False)
        asset_tools.import_asset_tasks([t])
        wave = unreal.load_asset(asset_path)
        if wave is not None:
            eal.set_metadata_tag(wave, HASH_TAG, digest)
            fresh += 1
    info["unchanged"], info["newly_imported"] = skipped, fresh
    att = None
    try:
        att = _make_attenuation(asset_tools, eal)
        info["falloff"] = f"full volume to {FALLOFF_INNER_CM / 100:g} m, silent by {(FALLOFF_INNER_CM + FALLOFF_CM) / 100:g} m"
        _make_attenuation(asset_tools, eal, FAR_ATTENUATION, 800.0, 6000.0)
    except Exception as exc:
        warn(f"sound falloff not made: {exc}")
    done, problems = [], {}
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        asset_path = f"{AUDIO}/{name}"
        wave = unreal.load_asset(asset_path)
        if wave is None:
            problems[name] = "not imported"
            continue
        try:
            music = name.startswith("music_") or name == "combat_layer"
            wave.set_editor_property("looping", music)
            # stings play flat over everything (2D); everything else fades with distance
            if att is not None and not music and not name.startswith("sting_"):
                wave.set_editor_property("attenuation_settings", att)
            eal.save_asset(asset_path, only_if_is_dirty=False)
            done.append(name)
        except Exception as exc:
            problems[name] = str(exc)[:200]
    info["imported"] = len(done)
    info["music"] = sorted(n for n in done if n.startswith("music_") or n == "combat_layer")
    info["level_music"] = _level_music()
    if problems:
        info["problems"] = problems
        warn(f"{len(problems)} sounds had problems: {sorted(problems)}")
    log(f"audio: {len(done)} sounds imported to {AUDIO}")


# --- play time --------------------------------------------------------------

S = {"handle": None, "out": None, "world": None, "chars": {}, "sounds": {}, "music": None, "combat": None,
     "threat_t": -99.0, "t0": 0.0, "floors": None, "att": None, "level_music": None,
     "played": {}, "sections": {}, "errors": {}, "sessions": []}


def _err(where, exc):
    S["errors"].setdefault(where, f"{type(exc).__name__}: {exc}"[:200])


def _game_world():
    try:
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    except Exception:
        return None


def _sound(path):
    # not EditorAssetLibrary.does_asset_exist: the editor's asset functions refuse to run
    # during Play and answer "no", which silenced every sound in the 2026-10-11s run
    if path not in S["sounds"]:
        snd = None
        try:
            snd = unreal.load_asset(path)
        except Exception as exc:
            _err("load " + path, exc)
        S["sounds"][path] = snd
    return S["sounds"][path]


def _ours(name):
    n = VARIANTS.get(name)
    return _sound(f"{AUDIO}/{name}_{random.randint(1, n)}" if n else f"{AUDIO}/{name}")


def _voice(hero, what):
    folder = CUE_DIRS.get(hero, CUE_DIR.format(h=hero))
    return _sound(f"{folder}/{hero}_{what}")


def _attenuation():
    if S["att"] is None:
        att = None
        try:
            att = unreal.load_asset(ATTENUATION)
        except Exception:
            pass
        if att is None:
            try:  # build has not run yet: make one that lives only for this session
                att = unreal.new_object(unreal.SoundAttenuation)
                _set_falloff(att)
            except Exception as exc:
                _err("attenuation", exc)
        S["att"] = att or False
    return S["att"] or None


def _play(label, sound, loc, volume=1.0, pitch=1.0):
    if sound is None:
        S["played"][label + " (missing)"] = S["played"].get(label + " (missing)", 0) + 1
        return
    try:
        unreal.GameplayStatics.play_sound_at_location(
            S["world"], sound, loc, unreal.Rotator(), volume, pitch * random.uniform(0.95, 1.05), 0.0, _attenuation())
        S["played"][label] = S["played"].get(label, 0) + 1
    except Exception as exc:
        _err("play " + label, exc)


def _load_floors(level):
    """(column, row) -> [(floor z, surface)] from the level's placements (level/placements*.json)."""
    floors = {}
    try:
        data = {}
        for path in sorted(glob.glob(os.path.join(ROOT, "level", "placements*.json"))):
            with open(path, encoding="utf-8") as f:
                candidate = json.load(f)
            if candidate.get("level") == level:
                data = candidate
                break
        for m in data.get("meshes", []):
            kind = "water" if m["mesh"] == "SM_Water_Tile" else FLOORS.get(m["mesh"])
            if kind:
                floors.setdefault((round(m["x"] / 400), round(m["y"] / 400)), []).append((m["z"], kind))
    except Exception as exc:
        _err("placements", exc)
    return floors


def _surface(loc, half_h):
    feet = loc.z - half_h
    here = S["floors"].get((round(loc.x / 400), round(loc.y / 400)), [])
    if any(kind == "water" and feet < z + 40 for z, kind in here):
        return "water"
    solid = [(abs(feet - z), kind) for z, kind in here if kind != "water"]
    return min(solid)[1] if solid else "steel"


def _hero(actor):
    """Which Paragon hero this character wears."""
    try:
        mesh = actor.get_editor_property("mesh")
        path = mesh.get_skeletal_mesh_asset().get_path_name()
        m = re.search(r"/Paragon(\w+?)/", path)
        if m:
            return m.group(1)
    except Exception:
        pass
    name = actor.get_class().get_name()
    return next((h for h in HERO_HEAD_CM if h in name), None)


def _prop(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _new_char(actor, player):
    hero = _hero(actor)
    head = HERO_HEAD_CM.get(hero, 170)
    half_h = 90.0
    try:
        half_h = actor.get_editor_property("capsule_component").get_scaled_capsule_half_height()
    except Exception:
        pass
    return {"hero": hero, "player": player, "stride": 0.9 * head, "pitch": math.sqrt(165.0 / head),
            "half_h": half_h, "walked": 0.0, "last": None, "hp": None, "dead": False, "pain_t": -9.0,
            "montage": None, "section": None, "air": False, "hit_t": None}


def _attack_sounds(c, actor, montage, section, loc):
    """A new attack (montage start or next combo section)."""
    name = montage.get_name() if montage else ""
    S["sections"].setdefault(name, [])
    if section and section not in S["sections"][name] and len(S["sections"][name]) < 12:
        S["sections"][name].append(section)
    if "Attack" not in name:
        return
    # a charged attack runs Default -> Charge -> Attack; only the last one is the blow
    if re.search(r"charge|loop|windup", section or "", re.I) or ("Charged" in name and section == "Default"):
        return
    hero = c["hero"]
    if hero == "Revenant":
        _play("gunshot", _ours("gunshot"), loc, 0.9)
        if random.random() < 0.35:
            _play("voice swing", _voice(hero, "Effort_Attack"), loc, VOICE_VOLUME * 0.7)
        return
    _play("whoosh", _ours("whoosh"), loc, 0.8, c["pitch"])
    _play("voice swing", _voice(hero, "Effort_Swing" if random.random() < 0.6 else "Effort_Attack"), loc, VOICE_VOLUME)


def _recover_from_hit(c, actor, t):
    """Epic's hit reaction makes the body half limp (physics blend 0.5, the hips kept
    animated) and only its landing event makes it solid again. A blow that does not lift the
    character off the floor never lands, so arms dangled and stretched until a later hit
    (50 s in the 2026-10-11t run). HIT_HOLD seconds after a hit, if the character is on the
    floor, do what Epic's landing does: blend weight 0, once.
    Never ease through in-between weights: any weight above 0 makes Unreal simulate every
    body again, hips included, and in the 2026-10-11u run that let bodies slide up to 3 m
    away from their capsules (one fell through the floor when it died)."""
    if c["hit_t"] is None or c["dead"]:
        return
    if t - c["hit_t"] < HIT_HOLD:
        return
    try:
        on_ground = actor.get_editor_property("character_movement").is_moving_on_ground()
    except Exception:
        on_ground = True
    if not on_ground and t - c["hit_t"] < HIT_GIVE_UP:
        return  # still in the air: Epic's own landing will settle it
    try:
        actor.get_editor_property("mesh").set_physics_blend_weight(0.0)
        S["session"]["hit_recoveries"] = S["session"].get("hit_recoveries", 0) + 1
    except Exception as exc:
        _err("hit recovery", exc)
    c["hit_t"] = None


def _nearest_foe(loc):
    """Where the closest living monster is (last frame), or None."""
    best, where = None, None
    for c in S["chars"].values():
        if c["player"] or c["dead"] or c.get("loc") is None:
            continue
        d = math.hypot(c["loc"].x - loc.x, c["loc"].y - loc.y)
        if best is None or d < best:
            best, where = d, c["loc"]
    return where


def _look(actor, t, player_pawn):
    key = actor.get_path_name()
    c = S["chars"].get(key)
    if c is None:
        c = S["chars"][key] = _new_char(actor, actor == player_pawn)
    loc = actor.get_actor_location()
    c["loc"] = loc
    hero = c["hero"]

    # health: hits, pain, death
    hp = _prop(actor, "Current HP")
    if hp is not None:
        hp = float(hp)
        if c["hp"] is not None and hp < c["hp"] - 1e-3 and not c["dead"]:
            _play("hit", _ours("hit"), loc, 1.0, c["pitch"])
            if hp <= 0:
                c["dead"] = True
                _play("voice death", _voice(hero, "Effort_Death"), loc, VOICE_VOLUME)
            elif t - c["pain_t"] > PAIN_GAP:
                c["pain_t"] = t
                heavy = c["hp"] - hp > 0.25 * max(c["hp"], 1e-3)
                _play("voice pain", _voice(hero, "Effort_PainHeavy" if heavy else "Effort_Pain"), loc, VOICE_VOLUME)
            if hp > 0:
                c["hit_t"] = t
                if hh_moves and hh_moves.handles(c):
                    foe = _nearest_foe(loc)
                    if hh_moves.hit(c, actor, t, foe, c["hp"] - hp, c.get("max_hp")):
                        c["hit_t"] = None  # a flinch instead of Epic's limp wobble
        c["hp"] = hp
        c["max_hp"] = max(c.get("max_hp") or 0.0, hp)
    _recover_from_hit(c, actor, t)
    if c["dead"]:
        return c, loc

    # attacks: each new montage, and each new section of a combo
    attacking = False
    try:
        anim = actor.get_editor_property("mesh").get_anim_instance()
        montage = anim.get_current_active_montage() if anim else None
        section = str(anim.montage_get_current_section(montage)) if montage else None
        if montage is not None and (montage != c["montage"] or section != c["section"]):
            _attack_sounds(c, actor, montage, section, loc)
        c["montage"], c["section"] = montage, section
        attacking = montage is not None and "Attack" in montage.get_name()
    except Exception as exc:
        _err("montage", exc)
    if hh_moves and hh_moves.handles(c):
        foe = _nearest_foe(loc)
        near = foe is not None and math.hypot(foe.x - loc.x, foe.y - loc.y) < hh_moves.CALM_RADIUS_CM
        hh_moves.tick(c, actor, t, attacking, near)

    # footsteps by distance walked; a heavier step on landing
    try:
        move = actor.get_editor_property("character_movement")
        on_ground = move.is_moving_on_ground()
    except Exception as exc:
        _err("movement", exc)
        on_ground = True
    if c["last"] is not None:
        d = math.hypot(loc.x - c["last"].x, loc.y - c["last"].y)
        if on_ground and d < 300:  # ignore teleports
            c["walked"] += d
    who = "player" if c["player"] else "monster"
    feet = unreal.Vector(loc.x, loc.y, loc.z - c["half_h"])
    if on_ground and c["air"]:
        _play("land", _ours("step_" + _surface(loc, c["half_h"])), feet, STEP_VOLUME[who] * 1.4, c["pitch"] * 0.85)
        _play("voice land", _voice(hero, "Effort_Land"), loc, VOICE_VOLUME * 0.6)
        c["walked"] = 0.0
    elif c["walked"] >= c["stride"]:
        c["walked"] -= c["stride"] * math.floor(c["walked"] / c["stride"])
        floor = _surface(loc, c["half_h"])
        _play("step " + floor, _ours("step_" + floor), feet,
              STEP_VOLUME[who] * SURFACE_VOLUME.get(floor, 1.0), c["pitch"])
    c["air"] = not on_ground
    c["last"] = loc
    return c, loc


def _sound_2d(world, snd, volume):
    """An unplayed 2D sound for music. Unreal's Python names CreateSound2D differently from
    what the 2026-10-11t run tried (create_sound_2d did not exist), so look it up."""
    gs = unreal.GameplayStatics
    for name in ("create_sound2d", "create_sound_2d"):
        fn = getattr(gs, name, None)
        if fn is not None:
            return fn(world, snd, volume)
    for name in ("spawn_sound2d", "spawn_sound_2d"):  # these start playing; fade_in restarts it
        fn = getattr(gs, name, None)
        if fn is not None:
            return fn(world, snd, volume)
    S["errors"].setdefault("2d sound names", [n for n in dir(gs) if "sound" in n.lower()])
    raise RuntimeError("no 2D sound function on GameplayStatics")


def _music(world, t, threat):
    """Level music once per session; the fight layer while a monster is close."""
    if S["music"] is None:
        level = re.sub(r"^UEDPIE_\d+_", "", world.get_name())
        name = S["level_music"].get(level, "music_ship")
        snd = _sound(f"{AUDIO}/{name}")
        S["session"]["music"] = name if snd else name + " (missing)"
        S["music"] = False
        if snd is not None:
            try:
                comp = _sound_2d(world, snd, MUSIC_VOLUME)
                comp.fade_in(MUSIC_FADE_IN, 1.0, random.uniform(0, 30))
                S["music"] = comp
            except Exception as exc:
                _err("music", exc)
    if threat:
        S["threat_t"] = t
    calm = t - S["threat_t"] > CALM_AFTER
    if S["combat"] is None and not calm:
        snd = _sound(f"{AUDIO}/combat_layer")
        if snd is not None:
            try:
                comp = _sound_2d(world, snd, COMBAT_VOLUME)
                comp.fade_in(COMBAT_FADE_IN, 1.0, 0.0)
                S["combat"] = comp
                S["session"]["fights"] += 1
            except Exception as exc:
                _err("combat music", exc)
                S["combat"] = False
    elif S["combat"] and calm:
        try:
            S["combat"].fade_out(COMBAT_FADE_OUT, 0.0)
        except Exception as exc:
            _err("combat fade", exc)
        S["combat"] = None


def _write():
    if not S["out"]:
        return
    try:
        os.makedirs(os.path.dirname(S["out"]), exist_ok=True)
        data = {"what": "Hollow Hull sound: what played in each Play session (newest last)",
                "errors": S["errors"], "attack_sections_seen": S["sections"], "sessions": S["sessions"][-3:],
                "moves": hh_moves.summary() if hh_moves else "hh_moves not loaded"}
        with open(S["out"], "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except Exception as exc:
        _err("write", exc)


def _end_session():
    if S.get("session") is not None:
        S["session"]["played"] = dict(sorted(S["played"].items()))
        S["session"]["seconds"] = round(time.time() - S["t0"], 1)
        _write()
    S.update({"world": None, "chars": {}, "music": None, "combat": None, "threat_t": -99.0, "session": None,
              "played": {}})


def _tick(_dt):
    # paused while hh_setup builds: no Unreal calls from inside the build's asset work
    # (the 2026-10-11s build crashed in Python during a Slate tick while compiling Sevarog)
    if S.get("paused") or S.get("busy"):
        return
    S["busy"] = True
    try:
        _tick_inner()
    finally:
        S["busy"] = False


def _tick_inner():
    try:
        world = _game_world()
        if world is None:
            if S["world"] is not None:
                _end_session()
            return
        if S["world"] is not None and S["world"] != world:
            _end_session()
        if S["world"] is None:
            S["world"], S["t0"] = world, time.time()
            S["session"] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "map": world.get_name(), "fights": 0}
            S["sessions"].append(S["session"])
            level = re.sub(r"^UEDPIE_\d+_", "", world.get_name())
            if S["floors"] is None or S.get("floors_for") != level:
                S["floors"], S["floors_for"] = _load_floors(level), level
            if S["level_music"] is None:
                S["level_music"] = _level_music()
        t = time.time() - S["t0"]
        player = unreal.GameplayStatics.get_player_pawn(world, 0)
        ploc = player.get_actor_location() if player else None
        threat = False
        for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character):
            try:
                c, loc = _look(actor, t, player)
            except Exception as exc:
                _err("look", exc)
                continue
            if (ploc is not None and not c["player"] and not c["dead"]
                    and math.hypot(loc.x - ploc.x, loc.y - ploc.y) < THREAT_CM and abs(loc.z - ploc.z) < 400):
                threat = True
        _music(world, t, threat)
    except Exception as exc:
        _err("tick", exc)


def start(out_path):
    """Play sounds during every Play session from now on; a summary goes to out_path."""
    S["out"] = out_path
    if S["handle"] is None:
        S["handle"] = unreal.register_slate_post_tick_callback(_tick)
    unreal.log(f"[HH] sound on -> {out_path}")
