"""Play recorder: while you play in the editor, notes what every character does.

init_unreal.py starts it on every editor launch. It does nothing until Play is pressed;
then, four times a second, it looks at the player and the monsters (position, speed,
health, which attack is playing, whether the body has gone ragdoll and which body parts
are simulating, how far the body has drifted from its capsule, who is standing inside
whom) and writes reports/phase1/play_trace.json in the hollow-hull folder, so Claude can
see what happened without a video. Every Unreal call is guarded: the recorder can never
stop the game, it only goes quiet.
"""

import json
import math
import os
import time

import unreal

PERIOD = 0.25        # seconds between looks
SAMPLE_EVERY = 2     # positions are logged every 2nd look (twice a second)
FLUSH_EVERY = 5.0    # seconds between file writes while playing
MAX_EVENTS = 4000
MAX_SAMPLES = 12000
KEEP_SESSIONS = 3

S = {"out": None, "handle": None, "world": None, "session": None, "sessions": [], "next": 0.0,
     "flush": 0.0, "looks": 0, "last": {}, "overlaps": set(), "max_dt": 0.0, "errors": {}}


def _err(where, exc):
    n = S["errors"].get(where)
    if n is None:
        S["errors"][where] = f"{type(exc).__name__}: {exc}"[:200]


def _game_world():
    try:
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    except Exception:
        try:
            return unreal.EditorLevelLibrary.get_game_world()
        except Exception:
            return None


def _short(actor):
    name = actor.get_name()
    for cut in ("BP_HH_", "BP_"):
        if name.startswith(cut):
            name = name[len(cut):]
    return name.replace("_C_", "#")


def _prop(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _bodies_simulating(mesh):
    out = []
    try:
        for i in range(mesh.get_num_bones()):
            bone = mesh.get_bone_name(i)
            if mesh.is_simulating_physics(bone):
                out.append(str(bone))
    except Exception as exc:
        _err("bodies", exc)
    return out


def _look(actor, t):
    """One character's state as a dict."""
    st = {}
    loc = actor.get_actor_location()
    st["pos"] = [round(loc.x), round(loc.y), round(loc.z)]
    try:
        v = actor.get_velocity()
        st["speed"] = round(math.hypot(v.x, v.y))
        st["vz"] = round(v.z)
    except Exception as exc:
        _err("velocity", exc)
    try:
        st["yaw"] = round(actor.get_actor_rotation().yaw)
    except Exception:
        pass
    hp = _prop(actor, "Current HP")
    if hp is not None:
        st["hp"] = round(float(hp), 2)
    att = _prop(actor, "Is Attacking")
    if att is not None:
        st["attacking"] = bool(att)
    danger = _prop(actor, "Last Danger Time")
    if danger is not None:
        st["danger_t"] = round(float(danger), 2)
    try:
        ctrl = actor.get_controller()
        if ctrl is not None and hasattr(ctrl, "get_move_status"):
            st["ai_move"] = str(ctrl.get_move_status()).split(".")[-1].split(":")[0].lower()
    except Exception as exc:
        _err("controller", exc)
    move = _prop(actor, "character_movement")
    if move is not None:
        mode = _prop(move, "movement_mode")
        if mode is not None:
            st["move"] = str(mode).split(".")[-1].replace("MOVE_", "").lower()
    capsule = _prop(actor, "capsule_component")
    if capsule is not None:
        try:
            st["radius"] = round(capsule.get_scaled_capsule_radius())
            st["half_h"] = round(capsule.get_scaled_capsule_half_height())
        except Exception as exc:
            _err("capsule", exc)
    mesh = _prop(actor, "mesh")
    if mesh is not None:
        sim = None
        for fn in ("is_any_simulating_physics", "is_simulating_physics"):
            try:
                sim = bool(getattr(mesh, fn)())
                break
            except Exception:
                continue
        st["ragdoll"] = sim
        try:
            p = mesh.get_socket_location("pelvis")
            # where the hips are compared with where the capsule says the body is
            st["hips_off"] = [round(p.x - loc.x), round(p.y - loc.y), round(p.z - loc.z)]
        except Exception as exc:
            _err("pelvis", exc)
        try:
            anim = mesh.get_anim_instance()
            m = anim.get_current_active_montage() if anim else None
            st["montage"] = m.get_name() if m else None
        except Exception as exc:
            _err("montage", exc)
        st["_mesh"] = mesh
    return st


def _event(t, who, what, **data):
    ev = S["session"]["events"]
    if len(ev) < MAX_EVENTS:
        ev.append(dict({"t": round(t, 2), "who": who, "what": what}, **data))


def _compare(t, who, st):
    """Events for what changed since this character's last look."""
    old = S["last"].get(who)
    if old is None:
        _event(t, who, "appears", pos=st.get("pos"), hp=st.get("hp"), radius=st.get("radius"))
        return
    if st.get("hp") != old.get("hp"):
        _event(t, who, "hp", was=old.get("hp"), now=st.get("hp"))
    if st.get("montage") != old.get("montage"):
        _event(t, who, "action", now=st.get("montage"))
    if st.get("attacking") != old.get("attacking"):
        _event(t, who, "attacking", now=st.get("attacking"))
    if st.get("danger_t") != old.get("danger_t") and st.get("danger_t", -1) > 0:
        _event(t, who, "senses_danger")
    if st.get("ai_move") != old.get("ai_move"):
        _event(t, who, "ai_move", now=st.get("ai_move"))
    if st.get("move") != old.get("move"):
        _event(t, who, "movement", was=old.get("move"), now=st.get("move"))
    if st.get("ragdoll") != old.get("ragdoll"):
        data = {"now": st.get("ragdoll"), "hips_off": st.get("hips_off")}
        if st.get("ragdoll") and "_mesh" in st:
            data["simulating"] = _bodies_simulating(st["_mesh"])
        _event(t, who, "ragdoll", **data)
    off, was = st.get("hips_off"), old.get("hips_off")
    if off and was and math.dist(off, was) > 60:
        _event(t, who, "hips_jump", was=was, now=off)


def _overlaps(t, looks):
    names = list(looks)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = looks[a].get("pos"), looks[b].get("pos")
            if not pa or not pb:
                continue
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            reach = (looks[a].get("radius") or 40) + (looks[b].get("radius") or 40)
            key = (a, b)
            inside = d < 0.8 * reach and abs(pa[2] - pb[2]) < 150
            if inside and key not in S["overlaps"]:
                S["overlaps"].add(key)
                _event(t, a, "inside_other", other=b, dist=round(d), radii=reach)
            elif not inside and key in S["overlaps"] and d > reach:
                S["overlaps"].discard(key)


def _sample(world, t):
    try:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character)
    except Exception as exc:
        _err("actors", exc)
        return
    looks = {}
    for a in actors:
        try:
            who = _short(a)
            st = _look(a, t)
            looks[who] = st
            _compare(t, who, st)
        except Exception as exc:
            _err("look", exc)
    for who in set(S["last"]) - set(looks):
        _event(t, who, "gone")
    _overlaps(t, looks)
    S["looks"] += 1
    if S["looks"] % SAMPLE_EVERY == 0:
        rows = S["session"]["samples"]
        for who, st in looks.items():
            if len(rows) < MAX_SAMPLES:
                rows.append([round(t, 2), who, *st.get("pos", [0, 0, 0]), st.get("speed"),
                             st.get("yaw"), st.get("hp"), int(bool(st.get("ragdoll"))), st.get("hips_off")])
        S["session"]["frame_ms_max"].append(round(S["max_dt"] * 1000))
        S["max_dt"] = 0.0
    for st in looks.values():
        st.pop("_mesh", None)
    S["last"] = looks


def _write():
    if not S["out"]:
        return
    try:
        os.makedirs(os.path.dirname(S["out"]), exist_ok=True)
        data = {
            "what": "Hollow Hull play recorder: one entry per Play session (newest last)",
            "samples_columns": ["t", "who", "x", "y", "z", "speed", "yaw", "hp", "ragdoll", "hips_off"],
            "recorder_errors": S["errors"],
            "sessions": S["sessions"][-KEEP_SESSIONS:],
        }
        tmp = S["out"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, S["out"])
    except Exception as exc:
        _err("write", exc)


def _tick(dt):
    try:
        S["max_dt"] = max(S["max_dt"], dt)
        now = time.time()
        if now < S["next"]:
            return
        S["next"] = now + PERIOD
        world = _game_world()
        if world is None:
            if S["session"] is not None:
                S["session"]["duration"] = round(now - S["session"]["_t0"], 1)
                S["session"].pop("_t0", None)
                S["session"] = None
                S["last"], S["overlaps"] = {}, set()
                _write()
            return
        if S["session"] is None:
            S["session"] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "_t0": now,
                            "map": world.get_name(), "events": [], "samples": [], "frame_ms_max": []}
            S["sessions"].append(S["session"])
            S["looks"], S["flush"] = 0, now + FLUSH_EVERY
        _sample(world, now - S["session"]["_t0"])
        if now >= S["flush"]:
            S["flush"] = now + FLUSH_EVERY
            _write()
    except Exception as exc:
        _err("tick", exc)


def start(out_path):
    """Begin watching for Play sessions; results go to out_path."""
    S["out"] = out_path
    if S["handle"] is None:
        S["handle"] = unreal.register_slate_post_tick_callback(_tick)
    unreal.log(f"[HH] play recorder on -> {out_path}")
