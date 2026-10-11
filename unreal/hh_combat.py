"""Hollow Hull Phase 2: Paragon characters on Epic's Combat variant.

Loaded by hh_setup.py, which adds these as build stages:

  char:<Name>  for each hero: IK rigs + retargeter (Manny -> Paragon), the Combat
               variant's anim blueprint and attack montages retargeted to that
               skeleton, and a child Blueprint of the Combat player/enemy that
               wears the Paragon mesh. A character that fails falls back to the
               plain Combat mannequin; the build never stops because of it.
  gameplay     game mode (Combat, with Revenant as the pawn), a nav mesh volume
               over the ship so enemies can walk, and the enemies from
               placements.json.

Everything learned on the way (what worked, property names found on the Combat
Blueprints, API names) goes into report["combat"] and
Saved/HollowHull/combat_probe.json, so the next round can be precise.
"""

import json
import os
import re
import traceback

import unreal

COMBAT = "/Game/Variant_Combat"
CHAR_DIR = "/Game/HollowHull/Characters"
RTG_DIR = CHAR_DIR + "/Retarget"
MANNY = "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple"
PLAYER_BP = COMBAT + "/Blueprints/BP_CombatCharacter"
ENEMY_BP = COMBAT + "/Blueprints/AI/BP_CombatEnemy"
GAME_MODE_BP = COMBAT + "/Blueprints/BP_CombatGameMode"
# Combat variant assets the characters play; retargeted per hero
ANIM_BP = COMBAT + "/Anims/ABP_Manny_Combat"
MONTAGES = [COMBAT + "/Anims/AM_ComboAttack", COMBAT + "/Anims/AM_ChargedAttack"]

PARAGON = "/Game/Paragon{0}/Characters/Heroes/{0}/Meshes/{0}"
# role, health multiplier (applied if the Combat Blueprint exposes a health value)
# head_cm: height of the head bone after scaling (a 1.8 m man is about 165 cm);
# Paragon heroes are authored oversized, so each is scaled to this height
# anim: "native" = the hero's own Paragon anim blueprint (its own walk/run/idle), with the
# Combat attack montages retargeted onto it; "combat" = Epic's Combat anim blueprint retargeted
HEROES = {
    "Revenant": {"parent": PLAYER_BP, "hp": 1.0, "head_cm": 165, "anim": "native"},
    "Khaimera": {"parent": ENEMY_BP, "hp": 1.0, "head_cm": 165, "anim": "native"},
    "Grux": {"parent": ENEMY_BP, "hp": 2.0, "head_cm": 205, "anim": "native"},
    "Sevarog": {"parent": ENEMY_BP, "hp": 4.0, "head_cm": 240, "anim": "native"},
}
PARAGON_ABP = "/Game/Paragon{0}/Characters/Heroes/{0}/{0}_AnimBlueprint"
PLAYER_HERO = "Revenant"

# Likely variable names on the Combat Blueprints (they mirror Epic's C++ version).
# Whatever exists is recorded in the probe; montage names are matched by asset name.
MONTAGE_PROPS = {
    "AM_ComboAttack": ["Combo Attack Montage", "ComboAttackMontage", "ComboMontage", "AttackMontage"],
    "AM_ChargedAttack": ["Charged Attack Montage", "ChargedAttackMontage", "ChargedMontage"],
}
HP_PROPS = ["MaxHP", "Max HP", "MaxHealth", "Max Health", "HP", "Health", "CurrentHP", "Current HP"]
PROBE_PROPS = (sum(MONTAGE_PROPS.values(), []) + HP_PROPS +
               ["MeleeDamage", "Melee Damage", "Damage", "MeleeTraceDistance", "MeleeTraceRadius",
                "MeleeKnockbackImpulse", "KnockbackImpulse", "MeleeLaunchImpulse", "ChargedAttackDamage",
                "ComboSectionNames", "DeathCameraShake", "RespawnTime", "DeferredDestructionTime",
                "LifeBarWidget", "ComboInputCacheTimeTolerance", "AttackRange", "HitReactMontage"])

H = None  # helpers from hh_setup (log, warn, report, ctx, asset_exists, load_or_create, eal, asset_tools, _tag, _count)
built = {}  # hero name -> generated class of its Blueprint
probe = {}


def init(helpers):
    global H
    H = type("Helpers", (), helpers)
    H.report["combat"] = {"characters": {}}


def _info(name):
    return H.report["combat"]["characters"].setdefault(name, {})


def _write_probe():
    path = os.path.join(os.path.dirname(H._report_path()), "combat_probe.json")
    with open(path, "w") as f:
        json.dump(probe, f, indent=1, default=str)


def _api(obj):
    return sorted(m for m in dir(obj) if not m.startswith("_"))


def _try(info, key, fn, *args):
    """Call fn(*args); record the error under info[key] instead of raising. Returns (ok, result)."""
    try:
        return True, fn(*args)
    except Exception as exc:
        info[key] = f"{type(exc).__name__}: {exc}"
        return False, None


def _call_first(obj, names, *args):
    """Call the first method in names that exists on obj (APIs get renamed between versions)."""
    for n in names:
        if hasattr(obj, n):
            return n, getattr(obj, n)(*args)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")


# --- probe: what the Combat Blueprints contain ---------------------------------

def probe_combat_blueprints():
    """Record which candidate variables exist on the Combat Blueprints, plus their
    Find-in-Blueprints text (lists every variable and function name)."""
    for path in (PLAYER_BP, ENEMY_BP, GAME_MODE_BP):
        entry = probe.setdefault(path.split("/")[-1], {})
        try:
            cls = H.eal.load_blueprint_class(path)
            cdo = unreal.get_default_object(cls)
            found = {}
            for n in PROBE_PROPS:
                try:
                    found[n] = str(cdo.get_editor_property(n))
                except Exception:
                    pass
            entry["properties"] = found
            data = H.eal.find_asset_data(path)
            fib = data.get_tag_value("FiBData") if data else None
            entry["fib_text"] = str(fib)[:60000] if fib else None
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
    record_controls()
    _write_probe()


def _imc_mappings(imc):
    getters = [lambda: imc.get_editor_property("mappings"),
               lambda: imc.get_editor_property("default_key_mappings").get_editor_property("mappings"),
               lambda: imc.get_mappings()]
    for get in getters:
        try:
            found = list(get())
            if found:
                return found
        except Exception:
            pass
    return []


def record_controls():
    """Which keys the Combat input mapping uses, so the runner can print the controls."""
    controls = []
    try:
        imc = unreal.load_asset(COMBAT + "/Input/IMC_Combat")
        for m in _imc_mappings(imc):
            action = m.get_editor_property("action")
            key = m.get_editor_property("key")
            controls.append({"action": action.get_name() if action else "?",
                             "key": str(key.get_editor_property("key_name"))})
    except Exception as exc:
        controls.append({"error": f"{type(exc).__name__}: {exc}"})
    H.report["combat"]["controls"] = controls


# --- retargeting ----------------------------------------------------------------

def _ik_rig(asset_name, mesh, info):
    rig, created = H.load_or_create(asset_name, RTG_DIR, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    ctrl = unreal.IKRigController.get_controller(rig)
    chains = []
    ok, chains = _try(info, f"{asset_name}.chains", ctrl.get_retarget_chains)
    if created or not chains:
        ctrl.set_skeletal_mesh(mesh)
        ctrl.apply_auto_generated_retarget_definition()
        _try(info, f"{asset_name}.fbik", ctrl.apply_auto_fbik)
        H.eal.save_loaded_asset(rig)
        ok, chains = _try(info, f"{asset_name}.chains", ctrl.get_retarget_chains)
    info[f"{asset_name}_chains"] = len(chains or [])
    probe.setdefault("api", {}).setdefault("IKRigController", _api(ctrl))
    return rig


def _retargeter(name, src_rig, tgt_rig, info):
    rtg, created = H.load_or_create(f"RTG_Manny_to_{name}", RTG_DIR, unreal.IKRetargeter, unreal.IKRetargetFactory())
    rc = unreal.IKRetargeterController.get_controller(rtg)
    probe.setdefault("api", {}).setdefault("IKRetargeterController", _api(rc))
    if created:
        src, tgt = unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetSourceOrTarget.TARGET
        if hasattr(rc, "add_default_ops"):  # newer retargeters keep their solvers in an op stack
            _try(info, "add_default_ops", rc.add_default_ops)
        rc.set_ik_rig(src, src_rig)
        rc.set_ik_rig(tgt, tgt_rig)
        if hasattr(rc, "assign_ik_rig_to_all_ops"):
            _try(info, "assign_src_ops", rc.assign_ik_rig_to_all_ops, src, src_rig)
            _try(info, "assign_tgt_ops", rc.assign_ik_rig_to_all_ops, tgt, tgt_rig)
        _try(info, "auto_map_chains", rc.auto_map_chains, unreal.AutoMapChainType.FUZZY, True)
        # Paragon heroes stand in a different reference pose than Manny: line their bones up
        _try(info, "auto_align", rc.auto_align_all_bones, tgt)
        H.eal.save_loaded_asset(rtg)
    return rtg


RETARGET_CLASSES = {"AnimSequence", "AnimMontage", "BlendSpace", "BlendSpace1D", "AnimBlueprint"}


def _retargeted_candidates(path, name):
    """Where Unreal may have put the copy of path for this hero: the batch retarget
    writes to the top Content folder, older engines next to the original."""
    base = path.split("/")[-1]
    return [f"/Game/{base}_{name}", f"{path.rsplit('/', 1)[0]}/{base}_{name}"]


def _find_retargeted(name):
    found = {}
    for p in [ANIM_BP] + MONTAGES:
        for cand in _retargeted_candidates(p, name):
            if H.asset_exists(cand):
                asset = unreal.load_asset(cand)
                if asset:
                    found[p.split("/")[-1]] = asset
                    break
    return found


def _hero_copies_in_root(name):
    """Retargeted animation assets for this hero in the top Content folder (ours to replace)."""
    pattern = re.compile(rf"_{name}(_\d+)?$")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    return [str(a.package_name) for a in registry.get_assets_by_path("/Game", recursive=False)
            if str(a.asset_class_path.asset_name) in RETARGET_CLASSES and pattern.search(str(a.asset_name))]


def _save_everything(info):
    """The batch retarget leaves new assets (the anim blueprint among them) unsaved."""
    try:
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(False, True)
    except Exception as exc:
        info["save_dirty"] = f"{type(exc).__name__}: {exc}"


def retarget_anims(name, manny, mesh, rtg, info):
    """Duplicate the Combat anim blueprint and montages onto this hero's skeleton.
    Returns {original asset name: retargeted asset}."""
    wanted = [ANIM_BP] + MONTAGES
    found = _find_retargeted(name)
    if len(found) < len(wanted):
        # an earlier run left an incomplete set: start this hero over
        stale = _hero_copies_in_root(name)
        for path in stale:
            _try(info, "delete_stale", H.eal.delete_asset, path)
        info["stale_removed"] = len(stale)
        assets = [H.eal.find_asset_data(p) for p in wanted]
        batch = unreal.IKRetargetBatchOperation
        out = batch.duplicate_and_retarget(assets, manny, mesh, rtg, "", "", "", f"_{name}", True)
        info["retargeted_assets"] = len(out or [])
        info["retarget_output"] = sorted(str(a.package_name) for a in out or [])[:40]
        _save_everything(info)
        found = _find_retargeted(name)
    info["retargeted"] = sorted(found)
    missing = [p.split("/")[-1] for p in wanted if p.split("/")[-1] not in found]
    if missing:
        raise RuntimeError(f"retargeted copies not found for {missing}")
    for asset in found.values():  # make sure they are on disk
        H.eal.save_loaded_asset(asset, only_if_is_dirty=True)
    return found


def _discard_retarget(name, info):
    """Delete this hero's half-made retarget assets so the next run starts clean."""
    removed = []
    for path in [f"{RTG_DIR}/IK_{name}", f"{RTG_DIR}/RTG_Manny_to_{name}"] + _hero_copies_in_root(name):
        try:
            if H.asset_exists(path) and H.eal.delete_asset(path):
                removed.append(path.split("/")[-1])
        except Exception:
            pass
    info["discarded"] = removed


# --- character Blueprints -------------------------------------------------------

def _child_blueprint(asset_name, parent_path):
    path = f"{CHAR_DIR}/{asset_name}"
    if H.asset_exists(path):
        bp = unreal.load_asset(path)
        if bp:
            return bp
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", H.eal.load_blueprint_class(parent_path))
    bp = H.asset_tools.create_asset(asset_name, CHAR_DIR, unreal.Blueprint, factory)
    if bp is None:
        raise RuntimeError(f"Unreal refused to create {path}")
    return bp


def _head_height(mesh, info):
    """Height of the head bone in the reference pose (feet at 0), or None.
    The mesh bounds are useless for this: Paragon bounds are padded far beyond the body."""
    try:
        skeleton = mesh.get_editor_property("skeleton")
        pose = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
        for bone in ("head", "Head", "neck_01", "neck_02"):
            try:
                t = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD)
            except Exception:
                continue
            if t.translation.z > 20:
                info["head_bone"] = {"name": bone, "z": round(t.translation.z, 1)}
                return float(t.translation.z) * (1.08 if bone.startswith("neck") else 1.0)
    except Exception as exc:
        info["head_error"] = f"{type(exc).__name__}: {exc}"
    return None


def _fit_body(name, mesh, info):
    """(scale, capsule radius, capsule half height, mesh Z offset) for this hero."""
    b = mesh.get_bounds()
    ext = b.box_extent
    info["bounds_extent"] = [round(ext.x), round(ext.y), round(ext.z)]
    head = _head_height(mesh, info)
    if head:
        scale = max(0.3, min(2.0, HEROES[name]["head_cm"] / head))
        top = HEROES[name]["head_cm"] + 15  # top of the skull
    else:  # fall back to the padded bounds, roughly: they run ~25% past the body
        scale = 1.0
        top = ext.z * 2 * 0.75
    half = max(88.0, top / 2)
    radius = max(34.0, min(half * 0.45, 80.0))
    return scale, radius, half, -half


def _montage_slots(montage):
    try:
        return [str(t.get_editor_property("slot_name")) for t in montage.get_editor_property("slot_anim_tracks")]
    except Exception:
        return []


def _set_montage_slot(montage, slot):
    tracks = montage.get_editor_property("slot_anim_tracks")
    for t in tracks:
        t.set_editor_property("slot_name", unreal.Name(slot))
    montage.set_editor_property("slot_anim_tracks", tracks)
    H.eal.save_loaded_asset(montage, only_if_is_dirty=False)


def _hero_montage_slot(name):
    """Slot the hero's own attack montages play in (its anim blueprint has a node for it)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for a in registry.get_assets_by_path(f"/Game/Paragon{name}", recursive=True):
        if str(a.asset_class_path.asset_name) == "AnimMontage" and "LevelStart" not in str(a.asset_name):
            slots = _montage_slots(unreal.load_asset(str(a.package_name)))
            if slots:
                return slots[0], str(a.asset_name)
    return None, None


def _native_anim_class(name, anims, info):
    """The hero's own Paragon anim blueprint, made to play the Combat montages; None if unusable."""
    path = PARAGON_ABP.format(name)
    if not H.asset_exists(path):
        info["native_anim"] = f"missing {path}"
        return None
    # an anim blueprint that casts to the hero's sample character would never see our character move
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False,
                                                     include_hard_package_references=True)
        deps = [str(d) for d in registry.get_dependencies(unreal.Name(path), opts) or []]
    except Exception as exc:
        deps = []
        info["native_deps_error"] = f"{type(exc).__name__}: {exc}"
    tied = [d for d in deps if "PlayerCharacter" in d]
    if tied:
        info["native_anim"] = f"tied to {tied[0]}"
        return None
    abp = unreal.load_asset(path)
    if not abp:
        info["native_anim"] = f"could not load {path}"
        return None
    slot, source = _hero_montage_slot(name)
    info["native_slot"] = {"slot": slot, "from": source}
    if slot:
        for key in ("AM_ComboAttack", "AM_ChargedAttack"):
            m = anims.get(key)
            if m and slot not in _montage_slots(m):
                _set_montage_slot(m, slot)
                info.setdefault("montage_slot_changed", []).append(m.get_name())
    return abp.generated_class()


def configure_blueprint(name, bp, mesh, anims, info):
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    cdo = unreal.get_default_object(bp.generated_class())
    if mesh is not None and ANIM_BP.split("/")[-1] in anims:
        comp = cdo.get_editor_property("mesh")
        _call_first(comp, ["set_skeletal_mesh_asset", "set_skeletal_mesh"], mesh)
        comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_BLUEPRINT)
        anim_class = None
        if HEROES[name].get("anim") == "native":
            try:
                anim_class = _native_anim_class(name, anims, info)
            except Exception as exc:
                info["native_anim"] = f"{type(exc).__name__}: {exc}"
        info["anim_source"] = "Paragon" if anim_class else "Combat (retargeted)"
        comp.set_editor_property("anim_class", anim_class or anims[ANIM_BP.split("/")[-1]].generated_class())
        scale, radius, half, z = _fit_body(name, mesh, info)
        comp.set_editor_property("relative_location", unreal.Vector(0, 0, z))
        comp.set_editor_property("relative_rotation", unreal.Rotator(roll=0.0, pitch=0.0, yaw=-90.0))
        comp.set_editor_property("relative_scale3d", unreal.Vector(scale, scale, scale))
        cap = cdo.get_editor_property("capsule_component")
        cap.set_editor_property("capsule_radius", radius)
        cap.set_editor_property("capsule_half_height", half)
        info["body"] = {"scale": round(scale, 3), "radius": round(radius), "half_height": round(half),
                        "mesh_z": round(z)}
        # point the attack variables at this hero's retargeted montages
        set_props = {}
        for montage_name, props in MONTAGE_PROPS.items():
            m = anims.get(montage_name)
            for p in props if m else []:
                try:
                    cdo.set_editor_property(p, m)
                    set_props[p] = m.get_name()
                    break
                except Exception:
                    pass
        info["montage_props_set"] = set_props
    hp_scale = HEROES[name]["hp"]
    if hp_scale != 1.0:
        # scale the parent's value (not this Blueprint's, which a previous run already scaled)
        parent = unreal.get_default_object(H.eal.load_blueprint_class(HEROES[name]["parent"]))
        for p in HP_PROPS:
            try:
                v = parent.get_editor_property(p)
                cdo.set_editor_property(p, type(v)(v * hp_scale))
                info.setdefault("hp_set", {})[p] = v * hp_scale
            except Exception:
                pass
    H.eal.save_loaded_asset(bp, only_if_is_dirty=False)


def build_character(name):
    """One hero, never raising: on any failure the plain Combat mannequin is used instead."""
    info = _info(name)
    try:
        if name == PLAYER_HERO:
            probe_combat_blueprints()
        mesh = unreal.load_asset(PARAGON.format(name))
        manny = unreal.load_asset(MANNY)
        if mesh is None or manny is None:
            raise RuntimeError(f"missing mesh: {PARAGON.format(name) if mesh is None else MANNY}")
        anims = {}
        try:
            src_rig = _ik_rig("IK_Manny", manny, info)
            tgt_rig = _ik_rig(f"IK_{name}", mesh, info)
            rtg = _retargeter(name, src_rig, tgt_rig, info)
            anims = retarget_anims(name, manny, mesh, rtg, info)
        except Exception:
            info["retarget_error"] = traceback.format_exc()
            H.warn(f"{name}: retargeting failed, using the mannequin body (details in setup_report combat)")
            anims = {}
            _discard_retarget(name, info)
        bp = _child_blueprint(f"BP_HH_{name}", HEROES[name]["parent"])
        configure_blueprint(name, bp, mesh if anims else None, anims, info)
        built[name] = bp.generated_class()
        info["blueprint"] = f"{CHAR_DIR}/BP_HH_{name}"
        info["ok"] = bool(anims)
        H.log(f"{name}: {'Paragon body' if anims else 'mannequin body'} -> {info['blueprint']}")
    except Exception:
        info["error"] = traceback.format_exc()
        info["ok"] = False
        H.warn(f"{name}: character setup failed, the Combat variant's own character is used")
    _write_probe()


def build_game_mode():
    info = _info("GameMode")
    try:
        bp = _child_blueprint("BP_HH_CombatGameMode", GAME_MODE_BP)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        if PLAYER_HERO in built:
            cdo = unreal.get_default_object(bp.generated_class())
            cdo.set_editor_property("default_pawn_class", built[PLAYER_HERO])
            info["default_pawn"] = PLAYER_HERO
        H.eal.save_loaded_asset(bp, only_if_is_dirty=False)
        return f"{CHAR_DIR}/BP_HH_CombatGameMode"
    except Exception:
        info["error"] = traceback.format_exc()
        H.warn("could not make the combat game mode; using the Combat variant's own")
        return GAME_MODE_BP


# --- level ----------------------------------------------------------------------

def spawn_gameplay(data):
    """Nav mesh volume over the ship, then the enemies. Returns the game mode path to use."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    bmin, bmax = data["bounds"]["min"], data["bounds"]["max"]
    centre = unreal.Vector((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, (bmin[2] + bmax[2]) / 2)
    nav = eas.spawn_actor_from_class(unreal.NavMeshBoundsVolume, centre)
    if nav is None:
        H.warn("could not place the nav mesh volume; enemies will stand still")
    else:
        H._tag(nav, "gameplay")
        # the default volume brush is a 200 cm cube
        nav.set_actor_scale3d(unreal.Vector((bmax[0] - bmin[0]) / 200, (bmax[1] - bmin[1]) / 200,
                                            (bmax[2] - bmin[2] + 200) / 200))
        origin, extent = nav.get_actor_bounds(False)
        H.report["combat"]["nav_extent"] = [round(extent.x), round(extent.y), round(extent.z)]
        if extent.x < 1000:
            H.warn("nav mesh volume came out too small; enemies may not move")
        H._count("NavMeshBoundsVolume")
    enemy_fallback = None
    for e in data.get("enemies", []):
        cls = built.get(e["type"])
        if cls is None:
            enemy_fallback = enemy_fallback or H.eal.load_blueprint_class(ENEMY_BP)
            cls = enemy_fallback
        actor = eas.spawn_actor_from_class(cls, unreal.Vector(e["x"], e["y"], e["z"]),
                                           unreal.Rotator(roll=0.0, pitch=0.0, yaw=float(e["yaw"])))
        if actor is None:
            H.warn(f"could not place enemy {e['type']} in {e['zone']}")
            continue
        H._tag(actor, "enemies")
        actor.set_actor_label(f"Enemy_{e['type']}_{e['zone']}")
        H._count(f"Enemy_{e['type']}")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    try:
        unreal.SystemLibrary.execute_console_command(world, "RebuildNavigation")
    except Exception as exc:
        H.warn(f"could not start the nav mesh build: {exc}")
    return build_game_mode()
