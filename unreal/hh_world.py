"""Hollow Hull world events while you play: the fall into The Hollow, and the cave being alive.

init_unreal.py starts it on every editor launch (like the sound player). Nothing happens
until Play is pressed; then every frame:

On the ship (L_FloodedDeck)
    When Sevarog dies in the cargo hold, the screen fades to black with a deep crack
    and rumble, and the game travels down into L_TheHollow.

In The Hollow (L_TheHollow)
    - You wake in the dark: the screen fades in from black.
    - The ship lamp hanging at the edge of the hole above flickers, then dies.
    - The heart beats. You hear it from everywhere, louder as you get closer, and it
      beats faster the closer you are (fastest while Sevarog is fighting you). On every
      beat the heart swells, the red glows in the throat and the heart chamber flare,
      and the throat's membranes bulge in.
    - Something breathes behind the walls, close to you, and groans far away.
    - When Sevarog dies under the heart, the heart stops, its light drains away, and
      the screen fades to black.

What it finds and does goes to reports/phase1/world_trace.json. Every Unreal call is
guarded: if anything here fails, the game simply goes on without it.
"""

import json
import math
import os
import random
import re
import time

import unreal

AUDIO = "/Game/HollowHull/Audio"
FAR_ATTENUATION = AUDIO + "/ATT_HH_Far"
NEAR_ATTENUATION = AUDIO + "/ATT_HH_World"
SHIP, HOLLOW = "L_FloodedDeck", "L_TheHollow"
HOLLOW_PATH = "/Game/HollowHull/Maps/" + HOLLOW
FX_TAG = "HH_FX_"  # hh_setup tags animated actors HH_FX_pulse, HH_FX_heart, HH_FX_flicker

# --- feel (safe to edit; takes effect after an editor restart) -------------

DEATH_HOLD = 4.0             # seconds Sevarog's body lies there before the fall starts
FALL_FADE = 2.5              # fade to black on the ship
FALL_BLACK = 1.5             # black before the level changes
WAKE_BLACK, WAKE_FADE = 1.5, 5.0   # in The Hollow: black, then a slow fade in
FLICKER_FOR = 9.0            # the ship lamp above the hole flickers this long, then dies
BEAT_SLOW, BEAT_FAST, BEAT_RAGE = 1.4, 0.72, 0.55   # seconds per heartbeat: far, close, fighting
HEART_FAR_CM, HEART_NEAR_CM = 4500.0, 900.0
HEART_SWELL = 0.06           # the heart grows this much on a beat
WALL_SWELL = 0.9             # the throat's membranes thicken this much on a beat
GLOW_LOW, GLOW_HIGH = 0.35, 1.6    # pulsing lights between beats and at the peak
HEARTBEAT_VOLUME = 0.9
BREATH_EVERY = (9.0, 20.0)   # seconds between breaths behind the walls
GROAN_EVERY = (22.0, 45.0)
BREATH_CM, GROAN_CM = 550.0, 1600.0
HEART_STOP_DIM, END_FADE_AFTER, END_FADE = 5.0, 7.0, 4.0

S = {"handle": None, "out": None, "world": None, "session": None, "sessions": [], "errors": {},
     "sounds": {}, "att": {}}


def _err(where, exc):
    S["errors"].setdefault(where, f"{type(exc).__name__}: {exc}"[:200])


def _event(what, **data):
    sess = S["session"]
    if sess is not None and len(sess["events"]) < 60:
        sess["events"].append({"t": round(time.time() - sess["_t0"], 1), "what": what, **data})


def _game_world():
    try:
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    except Exception:
        return None


def _map_name(world):
    return re.sub(r"^UEDPIE_\d+_", "", world.get_name())


# --- sound -------------------------------------------------------------------

def _sound(name):
    if name not in S["sounds"]:
        snd = None
        try:  # unreal.load_asset works during Play; the editor's asset library does not
            snd = unreal.load_asset(f"{AUDIO}/{name}")
        except Exception as exc:
            _err("load " + name, exc)
        S["sounds"][name] = snd
    return S["sounds"][name]


def _attenuation(path, inner, falloff):
    if path not in S["att"]:
        att = None
        try:
            att = unreal.load_asset(path)
        except Exception:
            pass
        if att is None:  # the build has not made it yet: one that lives for this session
            try:
                att = unreal.new_object(unreal.SoundAttenuation)
                st = att.get_editor_property("attenuation")
                for k, v in (("attenuate", True), ("spatialize", True),
                             ("attenuation_shape_extents", unreal.Vector(inner, 0, 0)),
                             ("falloff_distance", falloff)):
                    st.set_editor_property(k, v)
                att.set_editor_property("attenuation", st)
            except Exception as exc:
                _err("attenuation", exc)
        S["att"][path] = att
    return S["att"][path]


def _play_at(name, loc, volume=1.0, pitch=1.0, far=False):
    snd = _sound(name)
    sess = S["session"]
    if snd is None:
        sess["played"][name + " (missing)"] = sess["played"].get(name + " (missing)", 0) + 1
        return
    att = (_attenuation(FAR_ATTENUATION, 800.0, 6000.0) if far
           else _attenuation(NEAR_ATTENUATION, 400.0, 3200.0))
    try:
        unreal.GameplayStatics.play_sound_at_location(S["world"], snd, loc, unreal.Rotator(), volume, pitch,
                                                      0.0, att)
        sess["played"][name] = sess["played"].get(name, 0) + 1
    except Exception as exc:
        _err("play " + name, exc)


def _play_2d(name, volume=1.0):
    snd = _sound(name)
    if snd is None:
        return
    try:
        unreal.GameplayStatics.play_sound2d(S["world"], snd, volume)
        S["session"]["played"][name] = S["session"]["played"].get(name, 0) + 1
    except Exception:
        try:  # older/newer Python names for PlaySound2D
            unreal.GameplayStatics.play_sound_2d(S["world"], snd, volume)
            S["session"]["played"][name] = S["session"]["played"].get(name, 0) + 1
        except Exception as exc:
            _err("play2d " + name, exc)


# --- camera fades --------------------------------------------------------------

def _camera(world):
    try:
        return unreal.GameplayStatics.get_player_camera_manager(world, 0)
    except Exception as exc:
        _err("camera", exc)
        return None


def _fade(world, frm, to, seconds, hold=True, audio=False):
    cam = _camera(world)
    if cam is None:
        return
    try:
        cam.start_camera_fade(frm, to, seconds, unreal.LinearColor(0, 0, 0, 1), audio, hold)
    except Exception as exc:
        _err("fade", exc)


# --- characters ------------------------------------------------------------------

def _hero(actor):
    try:
        path = actor.get_editor_property("mesh").get_skeletal_mesh_asset().get_path_name()
        m = re.search(r"/Paragon(\w+?)/", path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _sevarog(world):
    """(location, hp) of Sevarog if he is in the level, else None."""
    sess = S["session"]
    actor = sess.get("sev_actor")
    if actor is None:
        try:
            for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character):
                if _hero(a) == "Sevarog":
                    actor = sess["sev_actor"] = a
                    _event("Sevarog found")
                    break
        except Exception as exc:
            _err("find Sevarog", exc)
    if actor is None:
        return None
    try:
        hp = actor.get_editor_property("Current HP")
        return actor.get_actor_location(), (float(hp) if hp is not None else None)
    except Exception:
        # destroyed after death: count that as dead
        return None if not sess.get("sev_alive") else (sess.get("sev_loc"), 0.0)


def _watch_sevarog(world, t):
    """Sets sess['sev_dead_t'] once Sevarog has been seen alive and then dies."""
    sess = S["session"]
    if sess.get("sev_dead_t") is not None:
        return
    found = _sevarog(world)
    if found is None:
        return
    loc, hp = found
    if hp is None:
        return
    if hp > 0:
        sess["sev_alive"], sess["sev_loc"] = True, loc
    elif sess.get("sev_alive"):
        sess["sev_dead_t"] = t
        _event("Sevarog died")


# --- the ship: the fall ------------------------------------------------------------

def _ship(world, t):
    sess = S["session"]
    _watch_sevarog(world, t)
    dead = sess.get("sev_dead_t")
    if dead is None:
        return
    if not sess.get("falling") and t - dead > DEATH_HOLD:
        sess["falling"] = t
        _fade(world, 0.0, 1.0, FALL_FADE, hold=True, audio=True)
        _play_2d("sting_fall", 1.0)
        _event("the floor gives way")
    if sess.get("falling") and not sess.get("travelled") and t - sess["falling"] > FALL_FADE + FALL_BLACK:
        sess["travelled"] = True
        try:
            unreal.GameplayStatics.open_level(world, HOLLOW_PATH, True, "")
            _event("travelling to The Hollow")
        except Exception as exc:
            _err("open level", exc)


# --- The Hollow: the living cave ------------------------------------------------------

def _gather(world):
    """Find the animated actors and remember how they started."""
    sess = S["session"]
    found = {"pulse_lights": [], "pulse_meshes": [], "heart": [], "flicker": []}
    for fx in ("pulse", "heart", "flicker"):
        try:
            actors = unreal.GameplayStatics.get_all_actors_with_tag(world, FX_TAG + fx)
        except Exception as exc:
            _err("find " + fx, exc)
            continue
        for a in actors:
            try:
                light = a.get_component_by_class(unreal.PointLightComponent)
                if light is not None:
                    entry = (light, float(light.get_editor_property("intensity")))
                    found["flicker" if fx == "flicker" else "pulse_lights"].append(entry)
                    continue
                entry = (a, a.get_actor_scale3d())
                found["heart" if fx == "heart" else "pulse_meshes"].append(entry)
            except Exception as exc:
                _err("read " + fx, exc)
    sess["fx"] = found
    sess["found"] = {k: len(v) for k, v in found.items()}
    if found["heart"]:
        sess["heart_loc"] = found["heart"][0][0].get_actor_location()
        # the mesh hangs from its pivot; the beating body is ~2.3 m below it
        sess["heart_loc"] = unreal.Vector(sess["heart_loc"].x, sess["heart_loc"].y, sess["heart_loc"].z - 230)


def _beat_shape(since):
    """Lub-dub: a strong swell and a softer one 0.28 s later (0..1)."""
    return max(math.exp(-((since - 0.06) / 0.09) ** 2), 0.7 * math.exp(-((since - 0.34) / 0.09) ** 2))


def _hollow(world, t):
    sess = S["session"]
    if "fx" not in sess:
        _gather(world)
        _fade(world, 1.0, 1.0, 0.01, hold=True)  # black first: you have just fallen
        sess["wake_at"] = t + WAKE_BLACK
        sess["next_beat"] = t + 0.8
        sess["next_breath"] = t + random.uniform(*BREATH_EVERY)
        sess["next_groan"] = t + random.uniform(*GROAN_EVERY) * 0.5
        _event("woke in The Hollow", found=sess["found"])
    if sess.get("wake_at") is not None and t >= sess["wake_at"]:
        sess["wake_at"] = None
        _fade(world, 1.0, 0.0, WAKE_FADE, hold=False)
        _play_2d("sting_wake", 0.9)

    fx = sess["fx"]
    player = unreal.GameplayStatics.get_player_pawn(world, 0)
    ploc = player.get_actor_location() if player else None

    # the ship lamp above the hole: sputters, then goes out for good
    for light, base in fx["flicker"]:
        try:
            if t < FLICKER_FOR:
                on = random.random() < (0.75 if t < FLICKER_FOR * 0.6 else 0.35)
                light.set_intensity(base * (random.uniform(0.6, 1.1) if on else random.uniform(0.0, 0.1)))
            elif not sess.get("lamp_out"):
                light.set_intensity(0.0)
        except Exception as exc:
            _err("flicker", exc)
    if t >= FLICKER_FOR and not sess.get("lamp_out") and fx["flicker"]:
        sess["lamp_out"] = True
        _event("the lamp above went out")

    _watch_sevarog(world, t)
    stopped = sess.get("sev_dead_t")

    # the heartbeat
    heart = sess.get("heart_loc")
    if heart is not None and stopped is None and t >= sess["next_beat"]:
        period = BEAT_SLOW
        if ploc is not None:
            d = math.dist((ploc.x, ploc.y, ploc.z), (heart.x, heart.y, heart.z))
            u = min(max((HEART_FAR_CM - d) / (HEART_FAR_CM - HEART_NEAR_CM), 0.0), 1.0)
            period = BEAT_SLOW + (BEAT_FAST - BEAT_SLOW) * u
            sev = sess.get("sev_loc")
            if sess.get("sev_alive") and sev is not None and math.dist((ploc.x, ploc.y), (sev.x, sev.y)) < 1500:
                period = BEAT_RAGE
        sess["last_beat"] = t
        sess["next_beat"] = t + period
        sess["beats"] = sess.get("beats", 0) + 1
        _play_at("heartbeat", heart, HEARTBEAT_VOLUME, 1.0, far=True)
    since = t - sess.get("last_beat", -99.0)
    pulse = _beat_shape(since) if stopped is None else 0.0
    dim = 1.0
    if stopped is not None:
        dim = max(0.0, 1.0 - (t - stopped) / HEART_STOP_DIM)
        if not sess.get("last_beat_played") and t - stopped > 1.5 and heart is not None:
            sess["last_beat_played"] = True
            _play_at("heartbeat", heart, HEARTBEAT_VOLUME, 0.8, far=True)
            _event("the heart stopped")
        if not sess.get("end_fade") and t - stopped > END_FADE_AFTER:
            sess["end_fade"] = True
            _fade(world, 0.0, 1.0, END_FADE, hold=True, audio=True)
            _event("fade to black: end of The Hollow")

    for actor, base in fx["heart"]:
        try:
            k = 1.0 + HEART_SWELL * pulse
            actor.set_actor_scale3d(unreal.Vector(base.x * k, base.y * k, base.z * (1.0 + HEART_SWELL * 0.6 * pulse)))
        except Exception as exc:
            _err("heart", exc)
    for actor, base in fx["pulse_meshes"]:
        try:
            actor.set_actor_scale3d(unreal.Vector(base.x, base.y * (1.0 + WALL_SWELL * pulse), base.z))
        except Exception as exc:
            _err("walls", exc)
    for light, base in fx["pulse_lights"]:
        try:
            if stopped is None:
                light.set_intensity(base * (GLOW_LOW + (GLOW_HIGH - GLOW_LOW) * pulse))
            else:
                light.set_intensity(base * GLOW_LOW * dim)
        except Exception as exc:
            _err("glow", exc)

    # breathing behind the walls, groans in the distance
    if ploc is not None and stopped is None:
        if t >= sess["next_breath"]:
            sess["next_breath"] = t + random.uniform(*BREATH_EVERY)
            a = random.uniform(0, math.tau)
            _play_at(f"breath_{random.randint(1, 3)}",
                     unreal.Vector(ploc.x + BREATH_CM * math.cos(a), ploc.y + BREATH_CM * math.sin(a), ploc.z),
                     0.8, random.uniform(0.9, 1.05))
        if t >= sess["next_groan"]:
            sess["next_groan"] = t + random.uniform(*GROAN_EVERY)
            a = random.uniform(0, math.tau)
            _play_at(f"groan_{random.randint(1, 2)}",
                     unreal.Vector(ploc.x + GROAN_CM * math.cos(a), ploc.y + GROAN_CM * math.sin(a), ploc.z),
                     1.0, random.uniform(0.85, 1.0), far=True)


# --- session bookkeeping ------------------------------------------------------------

def _write():
    if not S["out"]:
        return
    try:
        os.makedirs(os.path.dirname(S["out"]), exist_ok=True)
        sessions = [{k: v for k, v in s.items() if not k.startswith("_") and k not in
                     ("fx", "sev_actor", "sev_loc", "heart_loc")} for s in S["sessions"][-4:]]
        with open(S["out"], "w", encoding="utf-8") as f:
            json.dump({"what": "Hollow Hull world events per Play session (newest last)",
                       "errors": S["errors"], "sessions": sessions}, f, indent=1, default=str)
    except Exception as exc:
        _err("write", exc)


def _end_session():
    if S["session"] is not None:
        S["session"]["seconds"] = round(time.time() - S["session"]["_t0"], 1)
        _write()
    S["world"], S["session"] = None, None


def _tick(_dt):
    # paused while hh_setup builds (no Unreal calls during the build's asset work)
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
            S["world"] = world
            S["session"] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "map": _map_name(world),
                            "events": [], "played": {}, "_t0": time.time()}
            S["sessions"].append(S["session"])
        sess = S["session"]
        t = time.time() - sess["_t0"]
        if sess["map"] == SHIP:
            _ship(world, t)
        elif sess["map"] == HOLLOW:
            _hollow(world, t)
        if t - sess.get("_written", 0.0) > 5.0:
            sess["_written"] = t
            _write()
    except Exception as exc:
        _err("tick", exc)


def start(out_path):
    """Run the world events in every Play session from now on; a summary goes to out_path."""
    S["out"] = out_path
    if S["handle"] is None:
        S["handle"] = unreal.register_slate_post_tick_callback(_tick)
    unreal.log(f"[HH] world events on -> {out_path}")
