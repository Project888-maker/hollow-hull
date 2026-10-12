"""Extra moves for the player's hero from his own Paragon animations, played at run time.

Epic's Combat variant gives every character the same kit: a three-hit combo, a charged
attack, and a half-limp physics wobble when hit. Revenant's Paragon pack has much more,
so while you play this adds (called every frame from hh_audio, which already watches
each character):

  - a flinch when he is hit, from the side the blow came from (HitReact_Front/Back/Left/
    Right) instead of Epic's limp wobble
  - a heavy stagger (Knockback_Bwd) on a big hit
  - the gun-spin reload when he stops shooting and stands still for a moment
  - now and then, standing idle with no monster near, a fidget (hat tip, hat spin)
  - three attacks on keys, from his Paragon abilities (see ABILITIES):
      Q  Obliterate: a piercing shot along where you look that hits every monster in line
      E  Mark Blast: a blast all around him that throws close monsters back
      R  Reckoning: his ultimate, a heavy volley into every monster in a wide arc ahead
    Each turns him to the nearest monster near where the camera looks, plays his own
    ability animation, effects and voice, then damages monsters through Epic's own
    "Apply Damage" (the same call his gun uses, so health bars, knockback, death and
    respawn all work as usual). Each has a cooldown.

Each plays as a one-off on the anim blueprint's DefaultSlot (the slot the attack montages
use), so it overlays the body and ends by itself. Moving or attacking cancels the calm
ones. Everything is guarded and counted in audio_trace.json under "moves".
"""

import math
import random

import unreal

ANIMS = "/Game/Paragon{h}/Characters/Heroes/{h}/Animations/{a}"
SLOT = "DefaultSlot"
HEROES = {
    "Revenant": {
        "hit": {"front": "HitReact_Front", "back": "HitReact_Back", "left": "HitReact_Left", "right": "HitReact_Right"},
        "heavy": "Knockback_Bwd",
        "reload": ["Reload_Spin", "RMB_Reload_Med", "Emote_Reload"],
        "fidget": ["Emote_Hat_Lift", "Emote_HatSpin", "Idle_Alternate"],
    },
}
RELOAD_AFTER = 1.2      # seconds after the last shot, standing still
FIDGET_AFTER = 9.0      # seconds standing idle with no monster near
CALM_RADIUS_CM = 1500.0
HEAVY_HIT = 0.12        # share of max health lost in one blow that counts as heavy

FX = "/Game/ParagonRevenant/FX/Particles/Revenant/Abilities/{}"
# damage: monsters have 5 (Khaimera), 10 (Grux) and 20 (Sevarog) health; a gun shot does 1.
# knock/lift: cm/s pushed away and up (lift above ~150 so Epic's hit physics ends on landing).
# hit_at: the share of the animation when the blow lands. reach in cm, arc in degrees each side.
ABILITIES = {
    "Revenant": {
        "Q": {"name": "obliterate", "anim": ["Q_Ability"], "cooldown": 4.0, "hit_at": 0.35, "rate": 1.15,
              "damage": 3.0, "shape": "line", "reach": 2500.0, "width": 110.0, "knock": 450.0, "lift": 220.0,
              "voice": "Effort_Ability_Q", "sound": [("gunshot", 1.4, 0.7), ("whoosh", 0.8, 0.6)],
              "fx_cast": "Obliterate/FX/P_Revenant_Obliterate_Firing", "fx_hit": "Obliterate/FX/P_Revenant_Obliterate_Hit"},
        "E": {"name": "mark blast", "anim": ["E_Ability", "E_Ability_V2"], "cooldown": 7.0, "hit_at": 0.4, "rate": 1.2,
              "damage": 2.0, "shape": "circle", "reach": 550.0, "knock": 750.0, "lift": 320.0,
              "voice": "Effort_Ability_E", "sound": [("whoosh", 1.3, 0.5), ("gunshot", 1.0, 0.55)],
              "fx_cast": "Mark/FX/P_Revenant_Mark_Cast", "fx_hit": "Mark/FX/P_Revenant_Mark_Hit"},
        "R": {"name": "reckoning", "anim": ["R_Ability"], "cooldown": 18.0, "hit_at": 0.5, "rate": 1.0,
              "damage": 6.0, "shape": "arc", "reach": 1600.0, "arc": 60.0, "knock": 650.0, "lift": 380.0,
              "voice": "Effort_Ability_Ultimate", "sound": [("gunshot", 1.6, 0.5), ("gunshot", 1.2, 0.65)],
              "fx_cast": "Ultimate/FX/P_Revenant_Ultimate_Muzzleflash", "fx_hit": "Ultimate/FX/P_Revenant_Ultimate_Hit",
              "ready_voice": "Ability_Ultimate_Ready"},
    },
}
AIM_ASSIST_DEG = 30.0   # snap to a monster this close to where the camera looks
MONSTER_RADIUS = 55.0
MUZZLES = ["Muzzle_01", "Muzzle", "muzzle_01", "weapon_r", "hand_r"]

M = {"seqs": {}, "counts": {}, "errors": {}, "fx": {}, "keys": None, "muzzle": None,
     "abilities": {}}


def _count(what):
    M["counts"][what] = M["counts"].get(what, 0) + 1


def _err(where, exc):
    M["errors"].setdefault(where, f"{type(exc).__name__}: {exc}"[:200])


def summary():
    return {"played": dict(M["counts"]), "abilities": M["abilities"], "errors": dict(M["errors"])}


def _seq(hero, name):
    key = (hero, name)
    if key not in M["seqs"]:
        M["seqs"][key] = unreal.load_asset(ANIMS.format(h=hero, a=name))
    return M["seqs"][key]


def _first(hero, names):
    for n in names if isinstance(names, list) else [names]:
        s = _seq(hero, n)
        if s is not None:
            return n, s
    return None, None


def _play(c, anim, hero, names, what, rate=1.0):
    name, seq = _first(hero, names)
    if seq is None:
        M["errors"].setdefault(what, f"no animation {names}")
        return False
    try:
        anim.play_slot_animation_as_dynamic_montage(seq, SLOT, 0.1, 0.2, rate, 1, -1.0, 0.0)
        c["move"] = what
        _count(f"{what}: {name}")
        return True
    except Exception as exc:
        _err(what, exc)
        return False


def _stop_calm(c, anim):
    if c.get("move") in ("reload", "fidget"):
        try:
            anim.stop_slot_animation(0.2, SLOT)
        except Exception as exc:
            _err("stop", exc)
        c["move"] = None


def handles(c):
    return c.get("player") and c.get("hero") in HEROES


def hit(c, actor, t, attacker_loc, lost, max_hp):
    """The hero just lost health: flinch away from the blow. Returns True when a flinch
    played (the caller then skips Epic's limp wobble)."""
    hero = c["hero"]
    try:
        anim = actor.get_editor_property("mesh").get_anim_instance()
        if anim is None:
            return False
        current = anim.get_current_active_montage()
        if current is not None and "Attack" in current.get_name():
            return False  # never cut his own attack short: Epic's combo state must see it end
        if c.get("ability"):
            return False  # nor one of his abilities before its blow lands
        if max_hp and lost >= HEAVY_HIT * max_hp and _play(c, anim, hero, HEROES[hero]["heavy"], "stagger"):
            pass
        else:
            side = "front"
            if attacker_loc is not None:
                loc = actor.get_actor_location()
                to = unreal.Vector(attacker_loc.x - loc.x, attacker_loc.y - loc.y, 0.0)
                fwd, right = actor.get_actor_forward_vector(), actor.get_actor_right_vector()
                f = to.x * fwd.x + to.y * fwd.y
                r = to.x * right.x + to.y * right.y
                side = ("front" if f >= 0 else "back") if abs(f) >= abs(r) else ("right" if r > 0 else "left")
            if not _play(c, anim, hero, HEROES[hero]["hit"][side], "flinch"):
                return False
        # a clean flinch instead of Epic's half-limp physics wobble
        actor.get_editor_property("mesh").set_physics_blend_weight(0.0)
        c["move_t"] = t
        return True
    except Exception as exc:
        _err("hit", exc)
        return False


def _stat(key, what, n=1):
    a = M["abilities"].setdefault(key, {})
    a[what] = round(a.get(what, 0) + n, 2)


def _keys():
    """unreal.Key for Q, E and R (built once; False when this engine will not make them)."""
    if M["keys"] is None:
        keys = {}
        for name in ("Q", "E", "R"):
            for make in (lambda n: unreal.Key(key_name=n), _key_by_property):
                try:
                    keys[name] = make(name)
                    break
                except Exception as exc:
                    _err("key " + name, exc)
        M["keys"] = keys or False
    return M["keys"] or {}


def _key_by_property(name):
    k = unreal.Key()
    k.set_editor_property("key_name", name)
    return k


def _fx(path):
    if path not in M["fx"]:
        ps = None
        try:
            ps = unreal.load_asset(FX.format(path))
        except Exception as exc:
            _err("fx " + path, exc)
        M["fx"][path] = ps
    return M["fx"][path]


def _spawn_fx(world, path, loc, yaw=0.0, scale=1.0):
    ps = _fx(path)
    if ps is None:
        return
    try:
        unreal.GameplayStatics.spawn_emitter_at_location(
            world, ps, loc, unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), unreal.Vector(scale, scale, scale), True)
    except Exception as exc:
        _err("spawn fx", exc)


def _muzzle(actor):
    """Where his gun is: the first socket the mesh has, else in front of his chest."""
    try:
        mesh = actor.get_editor_property("mesh")
        if M["muzzle"] is None:
            M["muzzle"] = next((n for n in MUZZLES if mesh.does_socket_exist(n)), "")
        if M["muzzle"]:
            return mesh.get_socket_location(M["muzzle"])
    except Exception as exc:
        _err("muzzle", exc)
    loc, fwd = actor.get_actor_location(), actor.get_actor_forward_vector()
    return unreal.Vector(loc.x + fwd.x * 70.0, loc.y + fwd.y * 70.0, loc.z + 40.0)


def _monsters(world, me):
    """[(actor, location, health)] for every living monster."""
    out = []
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character):
        try:
            if a == me:
                continue
            hp = a.get_editor_property("Current HP")
            if hp is None or float(hp) <= 0:
                continue
            out.append((a, a.get_actor_location(), float(hp)))
        except Exception:
            continue  # not one of Epic's combat characters, or being destroyed
    return out


def _blocked(world, me, foe, a, b):
    """A wall between the two? (A trace that fails to run counts as clear.)"""
    try:
        r = unreal.SystemLibrary.line_trace_single(
            world, a, b, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [me, foe],
            unreal.DrawDebugTrace.NONE, True)
        if isinstance(r, tuple):
            r = r[0] if r and isinstance(r[0], bool) else (r[-1] if r else None)
        return bool(r) if isinstance(r, bool) else r is not None
    except Exception as exc:
        _err("line of sight", exc)
        return False


def _aim_yaw(world, actor, spec, foes, loc):
    """Where the camera looks, snapped onto the closest monster near that line."""
    yaw = actor.get_actor_rotation().yaw
    try:
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        yaw = pc.get_control_rotation().yaw
    except Exception as exc:
        _err("aim", exc)
    if spec["shape"] == "circle":
        return yaw
    best = None
    for foe, floc, _ in foes:
        dx, dy = floc.x - loc.x, floc.y - loc.y
        dist = math.hypot(dx, dy)
        if dist > spec["reach"] + MONSTER_RADIUS or abs(floc.z - loc.z) > 300:
            continue
        off = abs((math.degrees(math.atan2(dy, dx)) - yaw + 180.0) % 360.0 - 180.0)
        if off <= AIM_ASSIST_DEG and (best is None or (off, dist) < best[:2]):
            best = (off, dist, math.degrees(math.atan2(dy, dx)))
    return best[2] if best else yaw


def _in_shape(spec, loc, yaw, floc):
    dx, dy = floc.x - loc.x, floc.y - loc.y
    if abs(floc.z - loc.z) > 300:
        return False
    dist = math.hypot(dx, dy)
    if spec["shape"] == "circle":
        return dist <= spec["reach"] + MONSTER_RADIUS
    fx, fy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    along = dx * fx + dy * fy
    if along <= 0 or along > spec["reach"] + MONSTER_RADIUS:
        return False
    if spec["shape"] == "line":
        return abs(dx * fy - dy * fx) <= spec["width"] + MONSTER_RADIUS
    off = abs((math.degrees(math.atan2(dy, dx)) - yaw + 180.0) % 360.0 - 180.0)
    return off <= spec["arc"] or dist < 2 * MONSTER_RADIUS


def _damage(world, actor, foe, floc, hp, spec, loc):
    """Hurt one monster the way Epic's own attacks do; True when its health went down."""
    dx, dy = floc.x - loc.x, floc.y - loc.y
    d = math.hypot(dx, dy) or 1.0
    impulse = unreal.Vector(dx / d * spec["knock"], dy / d * spec["knock"], spec["lift"])
    try:
        foe.call_method("Apply Damage", (spec["damage"], actor, floc, impulse))
    except Exception as exc:
        _err("apply damage", exc)
    try:
        after = float(foe.get_editor_property("Current HP"))
    except Exception:
        after = hp - spec["damage"]  # destroyed already: it died
    if after < hp - 1e-3:
        return True
    try:  # the interface call did nothing: plain engine damage, which the enemy also handles
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        unreal.GameplayStatics.apply_damage(foe, spec["damage"], pc, actor, unreal.DamageType)
        foe.launch_character(impulse, True, True)
        _stat("fallback", "engine damage")
        return float(foe.get_editor_property("Current HP")) < hp - 1e-3
    except Exception as exc:
        _err("engine damage", exc)
        return False


def _cast(c, actor, anim, t, key, spec, world, sound):
    hero = c["hero"]
    loc = actor.get_actor_location()
    foes = _monsters(world, actor)
    yaw = _aim_yaw(world, actor, spec, foes, loc)
    try:
        actor.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), False)
    except Exception as exc:
        _err("turn", exc)
    name, seq = _first(hero, spec["anim"])
    length = 1.0
    if seq is not None:
        try:
            length = float(seq.get_play_length())
        except Exception as exc:
            _err("anim length", exc)
        M["abilities"].setdefault(key, {})["anim seconds"] = round(length, 2)
    if not _play(c, anim, hero, spec["anim"], spec["name"], spec["rate"]):
        _stat(key, "no animation")  # the blow still lands, a moment later
    c["ability"] = {"key": key, "spec": spec, "yaw": yaw,
                    "fire_t": t + min(1.0, max(0.15, spec["hit_at"] * length / spec["rate"]))}
    c.setdefault("ready_t", {})[key] = t + spec["cooldown"]
    c["last_shot"] = t  # a gun-spin reload once things calm down
    if sound and spec.get("voice"):
        sound("voice:" + spec["voice"], loc)
    _stat(key, "cast")


def _fire(c, actor, t, world, sound):
    ab, c["ability"] = c["ability"], None
    spec, key, yaw = ab["spec"], ab["key"], ab["yaw"]
    loc = actor.get_actor_location()
    muzzle = _muzzle(actor)
    chest = unreal.Vector(loc.x, loc.y, loc.z + 40.0)
    if sound:
        for what, volume, pitch in spec["sound"]:
            sound(what, muzzle, volume, pitch)
    _spawn_fx(world, spec["fx_cast"], muzzle if spec["shape"] != "circle" else loc, yaw)
    hits = 0
    for foe, floc, hp in _monsters(world, actor):
        if not _in_shape(spec, loc, yaw, floc):
            continue
        if _blocked(world, actor, foe, chest, unreal.Vector(floc.x, floc.y, floc.z + 40.0)):
            _stat(key, "behind a wall")
            continue
        if _damage(world, actor, foe, floc, hp, spec, loc):
            hits += 1
            _stat(key, "damage dealt", spec["damage"])
            _spawn_fx(world, spec["fx_hit"], floc, yaw)
    _stat(key, "monsters hit", hits)
    if hits == 0:
        _stat(key, "missed")


def _abilities(c, actor, anim, t, attacking, world, sound):
    """Q, E and R. True while an ability is under way (the calm moves then wait)."""
    hero = c["hero"]
    specs = ABILITIES.get(hero)
    if not specs or world is None:
        return False
    if c.get("ability"):
        if attacking:  # an Epic attack took the slot before the blow: called off
            _stat(c["ability"]["key"], "cut short")
            c["ability"] = None
        elif t >= c["ability"]["fire_t"]:
            _fire(c, actor, t, world, sound)
            return True
        else:
            return True
    ready = c.setdefault("ready_t", {})
    for key, spec in specs.items():
        if spec.get("ready_voice") and ready.get(key) and t >= ready[key] and sound:
            ready[key] = None  # say once that the ultimate is back
            sound("voice:" + spec["ready_voice"], actor.get_actor_location(), 0.7)
    keys = _keys()
    if not keys:
        return False
    try:
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        down = {k for k, key in keys.items() if pc.is_input_key_down(key)}
    except Exception as exc:
        _err("keys", exc)
        return False
    pressed = down - c.get("keys_down", set())
    c["keys_down"] = down
    for key in ("Q", "E", "R"):
        if key not in pressed or key not in specs:
            continue
        if attacking:
            _stat(key, "pressed mid-attack")
            continue
        if t < (ready.get(key) or 0.0):
            _stat(key, "on cooldown")
            if sound and t - c.get("cooldown_voice_t", -99.0) > 4.0:
                c["cooldown_voice_t"] = t
                sound("voice:Ability_OnCooldown", actor.get_actor_location(), 0.6)
            continue
        _cast(c, actor, anim, t, key, specs[key], world, sound)
        return True
    return False


def tick(c, actor, t, attacking, monster_near, world=None, sound=None):
    """Every frame for the player's hero: abilities on Q/E/R, reload after shooting,
    fidget when calm. sound(name, location, volume=1, pitch=1) plays one of our sounds,
    or the hero's voice cue for a name starting "voice:"."""
    hero = c["hero"]
    try:
        anim = actor.get_editor_property("mesh").get_anim_instance()
        if anim is None:
            return
        try:
            if _abilities(c, actor, anim, t, attacking, world, sound):
                c["still_since"] = None
                return
        except Exception as exc:
            _err("abilities", exc)
            c["ability"] = None
        v = actor.get_velocity()
        moving = math.hypot(v.x, v.y) > 40.0
        if attacking:
            c["last_shot"] = t
            if c.get("move") in ("reload", "fidget"):
                c["move"] = None  # the attack montage has taken the slot
            c["still_since"] = None
            return
        if moving:
            _stop_calm(c, anim)
            c["still_since"] = None
            return
        if c.get("still_since") is None:
            c["still_since"] = t
        busy = anim.is_any_montage_playing()
        if not busy and c.get("move") in ("reload", "fidget", "flinch", "stagger"):
            c["move"] = None
        if busy:
            return
        shot = c.get("last_shot")
        if shot is not None and t - shot > RELOAD_AFTER and t - c["still_since"] > 0.3:
            c["last_shot"] = None
            _play(c, anim, hero, HEROES[hero]["reload"], "reload")
            c["fidget_t"] = t
            return
        if not monster_near and t - c["still_since"] > FIDGET_AFTER and t - c.get("fidget_t", -99.0) > FIDGET_AFTER * 2:
            c["fidget_t"] = t
            _play(c, anim, hero, random.choice(HEROES[hero]["fidget"]), "fidget")
    except Exception as exc:
        _err("tick", exc)
