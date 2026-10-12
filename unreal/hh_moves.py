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

M = {"seqs": {}, "counts": {}, "errors": {}}


def _count(what):
    M["counts"][what] = M["counts"].get(what, 0) + 1


def _err(where, exc):
    M["errors"].setdefault(where, f"{type(exc).__name__}: {exc}"[:200])


def summary():
    return {"played": dict(M["counts"]), "errors": dict(M["errors"])}


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


def tick(c, actor, t, attacking, monster_near):
    """Every frame for the player's hero: reload after shooting, fidget when calm."""
    hero = c["hero"]
    try:
        anim = actor.get_editor_property("mesh").get_anim_instance()
        if anim is None:
            return
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
