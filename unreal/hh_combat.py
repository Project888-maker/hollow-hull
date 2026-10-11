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
import math
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
CONTROLLER_BP = COMBAT + "/Blueprints/BP_CombatPlayerController"
# the Combat player controller respawns a fixed character class after death
RESPAWN_PROPS = ["Character Class", "CharacterClass", "Pawn Class", "PawnClass", "Respawn Class",
                 "Player Character Class", "Character To Spawn"]
# Combat variant assets the characters play; retargeted per hero
ANIM_BP = COMBAT + "/Anims/ABP_Manny_Combat"
MONTAGES = [COMBAT + "/Anims/AM_ComboAttack", COMBAT + "/Anims/AM_ChargedAttack"]

PARAGON = "/Game/Paragon{0}/Characters/Heroes/{0}/Meshes/{0}"
# role, health multiplier (applied if the Combat Blueprint exposes a health value)
# head_cm: height of the head bone after scaling (a 1.8 m man is about 165 cm);
# Paragon heroes are authored oversized, so each is scaled to this height
# Each hero keeps the Combat anim blueprint and attack montages (retargeted to its
# skeleton: they carry the AI, combo and damage logic), but the mannequin animations
# inside them are swapped for the hero's own Paragon ones (see NATIVE_ANIMS).
HEROES = {
    "Revenant": {"parent": PLAYER_BP, "hp": 3.0, "head_cm": 165, "speed": 360, "min_radius": 48,
                 # his own gun shots (the mannequin's punches left the gun hanging in the air)
                 "attacks": ["Primary_Fire_Fast", "Primary_Fire_Med", "Primary_Fire_Slow", "RMB"],
                 # shots reach further than fists; camera far enough back to see him walk
                 "props": {"Melee Trace Distance": 250.0, "Default Camera Distance": 220.0}},
    # min_radius: wider bodies so monsters stop at arm's length instead of standing inside
    # you (doors are 140 cm wide, so no wider than 132)
    "Khaimera": {"parent": ENEMY_BP, "hp": 1.0, "head_cm": 165, "speed": 380, "min_radius": 46,
                 "attacks": ["Melee_A", "Melee_B", "Melee_C", "Melee_A_Slow"]},
    "Grux": {"parent": ENEMY_BP, "hp": 2.0, "head_cm": 205, "speed": 300, "min_radius": 60,
             "attacks": ["PrimaryAttack_LA", "PrimaryAttack_RA", "PrimaryAttack_LB", "PrimaryAttack_RB"]},
    "Sevarog": {"parent": ENEMY_BP, "hp": 4.0, "head_cm": 240, "walk": True, "speed": 260, "min_radius": 66,
                "attacks": ["Swing1_Medium", "Swing2_Medium", "Swing3_Medium", "Swing3_Slow"]},
}
# retargeted mannequin animation (name without the hero suffix) -> the hero's own, first that exists
NATIVE_ANIMS = {
    "MM_Idle": ["Idle_NonAdditive", "Idle", "Idle_Relaxed_A", "Idle_Alternate"],
    "MF_Unarmed_Jog_Fwd": ["Jog_Fwd"], "MF_Unarmed_Jog_Fwd_Left": ["Jog_Fwd"], "MF_Unarmed_Jog_Fwd_Right": ["Jog_Fwd"],
    "MF_Unarmed_Jog_Bwd": ["Jog_Bwd"], "MF_Unarmed_Jog_Bwd_Left": ["Jog_Bwd"], "MF_Unarmed_Jog_Bwd_Right": ["Jog_Bwd"],
    "MF_Unarmed_Jog_Left": ["Jog_Left", "Jog_Lft"], "MF_Unarmed_Jog_Right": ["Jog_Right", "Jog_Rgt"],
    "MF_Unarmed_Walk_Fwd": ["Walk_Fwd", "Jog_Fwd"], "MF_Unarmed_Walk_Fwd_Left": ["Walk_Fwd", "Jog_Fwd"],
    "MF_Unarmed_Walk_Fwd_Right": ["Walk_Fwd", "Jog_Fwd"], "MF_Unarmed_Walk_Bwd": ["Walk_Bwd", "Jog_Bwd"],
    "MF_Unarmed_Walk_Bwd_Left": ["Walk_Bwd", "Jog_Bwd"], "MF_Unarmed_Walk_Bwd_Right": ["Walk_Bwd", "Jog_Bwd"],
    "MF_Unarmed_Walk_Left": ["Walk_Left", "Jog_Left", "Jog_Lft"],
    "MF_Unarmed_Walk_Right": ["Walk_Right", "Jog_Right", "Jog_Rgt"],
    "MM_Jump": ["Jump_Start"],
    "MM_Fall_Loop": ["Jump_Fall_Loop", "Jump_Loop", "Jump_Apex", "JumpApex"],
    "MM_Land": ["Jump_Land", "Jump_Recovery"],
}
ATTACK_SLOTS = ["MM_Attack_01", "MM_Attack_02", "MM_Attack_03", "MM_ChargedAttack"]
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

PROBE_TARGETS = {  # Combat Blueprint -> the engine class it builds on
    PLAYER_BP: "Character", ENEMY_BP: "Character", GAME_MODE_BP: "GameModeBase",
    CONTROLLER_BP: "PlayerController", COMBAT + "/Blueprints/AI/BP_CombatAIController": "AIController",
    COMBAT + "/Blueprints/AI/BP_Combat_EnemySpawner": "Actor",
    COMBAT + "/Blueprints/Interactables/BP_Combat_ActivationVolume": "Actor",
}


# a name as the .uasset name table stores it: int32 length (with the null), chars, null
_NAME_RE = re.compile(rb"([\x02-\x7f])\x00\x00\x00([ -~]{1,126})\x00")
_variables_cache = {}


def asset_names(path):
    """Every name in the asset's name table (variables, functions, pins...). Python's view
    of a Blueprint default object does not list Blueprint variables (their names have
    spaces), but get_editor_property finds them once the name is known."""
    content = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    with open(os.path.join(content, path[len("/Game/"):] + ".uasset"), "rb") as f:
        data = f.read()
    return {m.group(2).decode() for m in _NAME_RE.finditer(data) if m.group(1)[0] == len(m.group(2)) + 1}


def blueprint_variables(path, engine_class):
    """{name: value} of the variables the Blueprint adds on top of its engine class."""
    if path in _variables_cache:
        return _variables_cache[path]
    cdo = unreal.get_default_object(H.eal.load_blueprint_class(path))
    base = unreal.get_default_object(getattr(unreal, engine_class).static_class())
    names = set()
    try:
        names |= asset_names(path)
    except Exception as exc:
        probe.setdefault("name_table_errors", {})[path] = f"{type(exc).__name__}: {exc}"
    names |= set(dir(cdo)) - set(dir(base))
    out = {}
    for n in sorted(names):
        if n.startswith(("_", "/")) or "." in n:
            continue
        try:
            v = cdo.get_editor_property(n)
        except Exception:
            continue
        try:
            base.get_editor_property(n)
            continue  # the engine class has it too
        except Exception:
            pass
        out[n] = str(v)[:160]
    _variables_cache[path] = out
    return out


def probe_combat_blueprints():
    """Record the Combat Blueprints' own variables (so settings are found by their real
    names, not guessed) and which of the guessed names exist."""
    for path, engine_class in PROBE_TARGETS.items():
        if H.asset_exists(path):
            try:
                probe.setdefault(path.split("/")[-1], {})["variables"] = blueprint_variables(path, engine_class)
            except Exception as exc:
                probe.setdefault(path.split("/")[-1], {})["variables_error"] = f"{type(exc).__name__}: {exc}"
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
    try:
        dump_logic()
    except Exception as exc:
        probe["logic_export_error"] = f"{type(exc).__name__}: {exc}"
    _write_probe()


LOGIC_DIRS = (COMBAT + "/Blueprints",)


def dump_logic():
    """Write the Combat Blueprints and the enemy's StateTree out as text (Unreal's copy-paste
    format: every node, pin and setting), so Claude can read how the enemies decide to
    attack, flank and evade. Goes to Saved/HollowHull/logic; the runner zips it into
    reports/phase1/combat_logic.zip together with the raw asset files."""
    out_dir = os.path.join(os.path.dirname(H._report_path()), "logic")
    os.makedirs(out_dir, exist_ok=True)
    result = probe.setdefault("logic_export", {})
    exporter_cls = getattr(unreal, "ObjectExporterT3D", None)
    if exporter_cls is None:
        result["error"] = "no ObjectExporterT3D in this Unreal"
        return
    paths = []
    for d in LOGIC_DIRS:
        try:
            paths += [str(p).split(".")[0] for p in H.eal.list_assets(d, recursive=True, include_folder=False)]
        except Exception as exc:
            result[d] = f"list: {type(exc).__name__}: {exc}"
    for path in sorted(set(paths)):
        name = path.split("/")[-1]
        try:
            asset = unreal.load_asset(path)
            if asset is None:
                continue
            kind = asset.get_class().get_name()
            if kind not in ("Blueprint", "StateTree", "EnvQuery", "BlackboardData", "BehaviorTree",
                            "WidgetBlueprint", "AnimBlueprint", "UserDefinedStruct", "UserDefinedEnum"):
                continue
            target = os.path.join(out_dir, f"{name}.t3d")
            task = unreal.AssetExportTask()
            task.set_editor_property("object", asset)
            task.set_editor_property("filename", target)
            task.set_editor_property("exporter", exporter_cls())
            for prop, value in (("automated", True), ("prompt", False), ("replace_identical", True),
                                ("selected", False)):
                try:
                    task.set_editor_property(prop, value)
                except Exception:
                    pass
            ok = unreal.Exporter.run_asset_export_task(task)
            size = os.path.getsize(target) if os.path.exists(target) else 0
            result[name] = f"{kind}: {'ok' if ok else 'failed'} {size} bytes"
        except Exception as exc:
            result[name] = f"{type(exc).__name__}: {exc}"[:200]
    try:
        text = write_logic_text(out_dir)
        result["_text"] = f"{os.path.getsize(text)} bytes"
    except Exception as exc:
        result["_text"] = f"{type(exc).__name__}: {exc}"[:200]


# the files that decide how enemies fight, in reading order
LOGIC_TEXT = ("ST_CombatEnemy", "StateTreeTask_", "StateTreeCondition_", "EnvQuery", "BP_CombatAIController",
              "BP_CombatEnemy", "BP_CombatCharacter")
_NOISE = [re.compile(p) for p in (
    r"PinId=[0-9A-F]{32},", r"PersistentGuid=[0-9A-F]{32},", r"NodeGuid=[0-9A-F]{32}",
    r"bHidden=False,", r"bNotConnectable=False,", r"bDefaultValueIsReadOnly=False,",
    r"bDefaultValueIsIgnored=False,", r"bAdvancedView=False,", r"bOrphanedPin=False,",
    r"PinType\.PinSubCategory=\"\",", r"PinType\.PinSubCategoryMemberReference=\(\),",
    r"PinType\.PinValueType=\(\),", r"PinType\.ContainerType=None,", r"PinType\.bIsReference=False,",
    r"PinType\.bIsConst=False,", r"PinType\.bIsWeakPointer=False,", r"PinType\.bIsUObjectWrapper=False,",
    r"PinType\.bSerializeAsSinglePrecisionFloat=False,", r"PinFriendlyName=NSLOCTEXT\([^)]*\),",
    r"PinToolTip=\"[^\"]*\",")]
_DROP = re.compile(r"^\s*(NodePosX|NodePosY|NodeWidth|NodeHeight|ErrorType|bCommentBubble|"
                   r"EnabledState|bIsNodeEnabled|bHasCompilerMessage|AdvancedPinDisplay)=")


def write_logic_text(out_dir):
    """One trimmed text file of the enemy logic (combat_logic.txt next to the reports):
    the copy-paste text with ids, positions and default flags removed."""
    names = sorted(f for f in os.listdir(out_dir) if f.endswith(".t3d"))
    ordered = [f for key in LOGIC_TEXT for f in names if f.startswith(key)]
    seen, chunks = set(), []
    for f in ordered:
        if f in seen:
            continue
        seen.add(f)
        with open(os.path.join(out_dir, f), encoding="utf-8", errors="replace") as fh:
            lines = []
            for line in fh:
                if _DROP.match(line):
                    continue
                for rx in _NOISE:
                    line = rx.sub("", line)
                lines.append(line.rstrip() + "\n")
        chunks.append(f"\n######## {f} ########\n" + "".join(lines))
    path = os.path.join(os.path.dirname(out_dir), "combat_logic.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(chunks))
    probe["logic_digest"] = logic_digest(chunks)
    return path


# the big character Blueprints: only the lines that say what a node does
_KEY_LINE = re.compile(r"Begin Object Class=|FunctionReference=|VariableReference=|EventReference=|"
                       r"CustomFunctionName=|MemberName=|DefaultValue=\"[^\"]+\"|NodeComment=|"
                       r"LinkedTo=|StateName|Name=\"")


def logic_digest(chunks, limit=1_500_000):
    """The enemy logic as a list of lines inside combat_probe.json (the text file did not
    make it to Claude): the AI files whole, the large character Blueprints filtered."""
    out, total = [], 0
    for chunk in chunks:
        lines = chunk.splitlines()
        title = next((x for x in lines if x.startswith("########")), "")
        big = "BP_CombatEnemy" in title or "BP_CombatCharacter" in title
        for line in lines:
            line = line.strip()
            if not line or (big and line != title and not _KEY_LINE.search(line)):
                continue
            if big and "CustomProperties Pin" in line:
                # keep the pin's name, value and links only
                keep = re.findall(r'PinName="[^"]*"|DefaultValue="[^"]+"|DefaultObject="[^"]+"|LinkedTo=\([^)]*\)', line)
                line = "Pin " + " ".join(keep)
            total += len(line) + 1
            if total > limit:
                out.append("... (cut: size limit)")
                return out
            out.append(line)
    return out


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
    pattern = re.compile(rf"_{name}_?\d*$")
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


def _native_assets(name):
    """{asset name: package path} of the hero's own animation sequences."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    out = {}
    for a in registry.get_assets_by_path(f"/Game/Paragon{name}", recursive=True):
        if str(a.asset_class_path.asset_name) == "AnimSequence":
            out.setdefault(str(a.asset_name), str(a.package_name))
    return out


def use_native_animations(name, info):
    """Swap the retargeted mannequin animations for the hero's own: every reference to,
    say, MM_Idle_Grux (in the anim blueprint, blend space and montages) is pointed at
    Grux's Idle and the copy is deleted. Both are on the hero's skeleton."""
    native = _native_assets(name)
    plan = dict((k, v) for k, v in NATIVE_ANIMS.items())
    if not HEROES[name].get("walk"):  # walk = jog for heroes without walk cycles
        plan = {k: [c for c in v if not c.startswith("Walk_")] or v for k, v in plan.items()}
    for slot, anim in zip(ATTACK_SLOTS, HEROES[name].get("attacks", [])):
        plan[slot] = [anim]
    swapped, missing = {}, []
    groups = {}
    # a re-run of the retarget can add a numbered set (MF_Unarmed_Jog_Fwd_Revenant1, ...)
    # next to the first; the anim blueprint may use either, so all are swapped
    root = {}
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for a in registry.get_assets_by_path("/Game", recursive=False):
        m = re.match(rf"^(.*)_{name}_?\d*$", str(a.asset_name))
        if m:
            root.setdefault(m.group(1), []).append(str(a.package_name))
    for base, candidates in plan.items():
        for copy in root.get(base, []):
            current = unreal.load_asset(copy)
            if current is None or current.get_path_name().startswith(f"/Game/Paragon{name}/"):
                continue  # already swapped by an earlier run (the copy is now a redirector)
            target = next((native[c] for c in candidates if c in native and not _is_additive(native[c])), None)
            if not target:
                missing.append(base)
                continue
            groups.setdefault(target, []).append(copy)
    for target, copies in groups.items():
        to = unreal.load_asset(target)
        olds = [a for a in (unreal.load_asset(c) for c in copies) if a]
        if to and olds and H.eal.consolidate_assets(to, olds):
            for c in copies:
                swapped[c.split("/")[-1]] = target.split("/")[-1]
    _save_everything(info)
    info["native_swapped"] = swapped
    if missing:
        info["native_missing"] = missing
    return len(swapped)


def _is_additive(anim_or_path):
    """True for an animation that only stores changes on top of another pose (Paragon's
    Khaimera 'Idle'): played on its own every bone shrinks to nothing."""
    try:
        anim = unreal.load_asset(anim_or_path) if isinstance(anim_or_path, str) else anim_or_path
        return "NONE" not in str(anim.get_editor_property("additive_anim_type")).upper()
    except Exception:
        return False


def _full_pose_for(name, anim, native):
    """A full-pose stand-in for an additive animation of the hero, or None."""
    base = anim.get_name()
    tries = [f"{base}_NonAdditive", base.replace("_additive", "").replace("_Additive", "")]
    if "idle" in base.lower():
        tries += NATIVE_ANIMS["MM_Idle"]
    for t in tries:
        if t in native and t != base and not _is_additive(native[t]):
            return unreal.load_asset(native[t])
    return None


def replace_additive_anims(name, info):
    """Earlier runs put Khaimera's additive 'Idle' into her blend space and anim blueprint,
    so whenever she stood still she collapsed into a tiny heap (and the log filled with
    zero-scale body warnings). Every additive animation the hero's anim blueprint plays
    directly or through a blend space is replaced by a full-pose one."""
    native = _native_assets(name)
    report = info.setdefault("additive_fixed", {})
    abp_path = f"/Game/{ANIM_BP.split('/')[-1]}_{name}"
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False,
                                                 include_hard_package_references=True)
    for dep in registry.get_dependencies(unreal.Name(abp_path), opts) or []:
        try:
            asset = unreal.load_asset(str(dep))
            if not isinstance(asset, unreal.BlendSpace):
                continue
            samples = list(asset.get_editor_property("sample_data"))
            changed = False
            for smp in samples:
                anim = smp.get_editor_property("animation")
                if anim and _is_additive(anim):
                    full = _full_pose_for(name, anim, native)
                    if full:
                        smp.set_editor_property("animation", full)
                        report[f"{asset.get_name()}:{anim.get_name()}"] = full.get_name()
                        changed = True
                    else:
                        report[f"{asset.get_name()}:{anim.get_name()}"] = "no full-pose version"
            if changed:
                asset.set_editor_property("sample_data", samples)
                H.eal.save_loaded_asset(asset, only_if_is_dirty=False)
        except Exception as exc:
            report[str(dep)] = f"{type(exc).__name__}: {exc}"[:200]
    # sequence players inside the anim blueprint (the idle state of its state machine)
    abp = unreal.load_asset(abp_path)
    node_cls = getattr(unreal, "AnimGraphNode_SequencePlayer", None)
    if abp is None or node_cls is None or not hasattr(unreal, "ObjectIterator"):
        return
    touched = False
    for gnode in unreal.ObjectIterator(node_cls):
        try:
            if not gnode.get_path_name().startswith(abp_path + "."):
                continue
            node = gnode.get_editor_property("node")
            seq = node.get_editor_property("sequence")
            if seq and _is_additive(seq):
                full = _full_pose_for(name, seq, native)
                if full:
                    node.set_editor_property("sequence", full)
                    gnode.set_editor_property("node", node)
                    report[f"{gnode.get_name()}:{seq.get_name()}"] = full.get_name()
                    touched = True
        except Exception as exc:
            report[gnode.get_name()] = f"{type(exc).__name__}: {exc}"[:200]
    if touched:
        unreal.BlueprintEditorLibrary.compile_blueprint(abp)
        H.eal.save_loaded_asset(abp, only_if_is_dirty=False)


def native_jog_speed(name, info):
    """The speed (cm/s, unscaled) the hero's own Jog_Fwd was authored for, read from the
    Paragon blend spaces that place it. None if no blend space says."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    speeds = []
    for a in registry.get_assets_by_path(f"/Game/Paragon{name}", recursive=True):
        if str(a.asset_class_path.asset_name) not in ("BlendSpace", "BlendSpace1D"):
            continue
        try:
            bs = unreal.load_asset(str(a.package_name))
            for sample in bs.get_editor_property("sample_data"):
                anim = sample.get_editor_property("animation")
                if anim and anim.get_name() == "Jog_Fwd":
                    v = sample.get_editor_property("sample_value")
                    sp = max(abs(v.x), abs(v.y))
                    if 150 <= sp <= 1200:
                        speeds.append(sp)
        except Exception:
            continue
    info["jog_speed_samples"] = sorted(set(round(x) for x in speeds))
    return max(speeds) if speeds else None


def _anim_length(anim):
    for get in (lambda: anim.get_play_length(), lambda: unreal.AnimationLibrary.get_sequence_length(anim),
                lambda: anim.get_editor_property("sequence_length")):
        try:
            v = float(get())
            if v > 0:
                return v
        except Exception:
            pass
    raise RuntimeError("no length")


def measured_ground_speed(anim, samples=40):
    """Speed (cm/s, unscaled) a locomotion cycle is meant to travel at, measured from its
    feet: while a foot is planted it moves back, relative to the root, at exactly the speed
    the body should move forward. Works for in-place and root-motion cycles alike."""
    lib, world = unreal.AnimPoseExtensions, unreal.AnimPoseSpaces.WORLD
    opts = unreal.AnimPoseEvaluationOptions()
    length = _anim_length(anim)
    dt = length / samples
    tracks = {"foot_l": [], "foot_r": []}
    for i in range(samples):
        pose = lib.get_anim_pose_at_time(anim, i * dt, opts)
        try:
            root = lib.get_bone_pose(pose, "root", world).translation
        except Exception:
            root = unreal.Vector(0, 0, 0)
        for bone, pts in tracks.items():
            p = lib.get_bone_pose(pose, bone, world).translation
            pts.append((p.x - root.x, p.y - root.y, p.z))
    speeds = []
    for pts in tracks.values():
        zs = [p[2] for p in pts]
        if max(zs) - min(zs) < 2:
            continue  # the foot never lifts: not a walk or run
        planted = min(zs) + 0.25 * (max(zs) - min(zs))
        for a, b in zip(pts, pts[1:]):
            if a[2] <= planted and b[2] <= planted:
                speeds.append(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / dt)
    speeds.sort()
    return speeds[len(speeds) // 2] if speeds else None


def hero_jog_speed(name, info):
    """Authored (unscaled) speed of the hero's Jog_Fwd: measured from its feet, else read
    from the Paragon blend spaces that place it. None if neither works."""
    native = _native_assets(name)
    if "Jog_Fwd" in native:
        try:
            v = measured_ground_speed(unreal.load_asset(native["Jog_Fwd"]))
            info["jog_speed_measured"] = round(v) if v else None
            if v and 150 <= v <= 900:
                return v
        except Exception as exc:
            info["jog_speed_measure_error"] = f"{type(exc).__name__}: {exc}"
    return native_jog_speed(name, info)


def _speed_axis(bs):
    params = list(bs.get_editor_property("blend_parameters"))
    if isinstance(bs, getattr(unreal, "BlendSpace1D", ())):
        return 0, params
    for i, p in enumerate(params[:2]):
        if "speed" in str(p.get_editor_property("display_name")).lower():
            return i, params
    return (1 if abs(params[1].get_editor_property("max")) > abs(params[0].get_editor_property("max")) else 0), params


_AXES = ("x", "y", "z")
MIN_RATE = 0.75  # slowest a locomotion cycle may play before it reads as slow motion
PLAYER_PACE = 1.15  # Revenant moves (and his jog plays) this much faster than authored


def fit_locomotion_blendspace(name, jog_speed, scale, info):
    """The Combat anim blueprint picks idle/walk/jog from a blend space laid out for the
    mannequin (its run sits at the mannequin's run speed). With the hero's own animations
    in those slots, the body moved at one speed while the legs ran at another: sliding.
    The fastest sample (the jog) is moved to the hero's real scaled jog speed, the rest
    in proportion, and each animation's play rate is set so its feet match the speed it
    now stands for (a jog standing in for a walk plays slower)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False,
                                                 include_hard_package_references=True)
    abp = f"/Game/{ANIM_BP.split('/')[-1]}_{name}"
    report = info.setdefault("blendspace", {})
    natural = {}  # anim name -> its own scaled ground speed

    def natural_speed(anim):
        key = anim.get_name()
        if key not in natural:
            try:
                v = measured_ground_speed(anim)
                natural[key] = v * scale if v and v >= 50 else None
            except Exception:
                natural[key] = None
        return natural[key]

    for dep in registry.get_dependencies(unreal.Name(abp), opts) or []:
        bs = unreal.load_asset(str(dep))
        if not isinstance(bs, unreal.BlendSpace):
            continue
        entry = report.setdefault(bs.get_name(), {})
        try:
            axis, params = _speed_axis(bs)
            ax = _AXES[axis]
            samples = list(bs.get_editor_property("sample_data"))

            def speed_of(smp):
                return abs(getattr(smp.get_editor_property("sample_value"), ax))

            def anim_of(smp):
                return smp.get_editor_property("animation")

            entry["before"] = [[anim_of(x).get_name() if anim_of(x) else "", round(speed_of(x))] for x in samples]
            top = max(samples, key=speed_of) if samples else None
            if top is None or speed_of(top) <= 0:
                entry["skipped"] = "no moving sample"
                continue
            k = jog_speed / speed_of(top)
            if k > 1.0:  # the samples must stay inside the axis range
                p = params[axis]
                p.set_editor_property("max", float(p.get_editor_property("max")) * k)
                params[axis] = p
                bs.set_editor_property("blend_parameters", params)
            for smp in samples:
                v = smp.get_editor_property("sample_value")
                setattr(v, ax, getattr(v, ax) * k)
                smp.set_editor_property("sample_value", v)
                anim = anim_of(smp)
                own = natural_speed(anim) if anim and speed_of(smp) > 0 else None
                if own and speed_of(smp) < own * MIN_RATE:
                    # no walk of their own: a jog played at half speed looks like slow
                    # motion, so the slot moves up to where the jog still looks like a jog
                    setattr(v, ax, math.copysign(own * MIN_RATE, getattr(v, ax)))
                    smp.set_editor_property("sample_value", v)
                if own:
                    smp.set_editor_property("rate_scale", min(1.6, max(MIN_RATE, speed_of(smp) / own)))
            bs.set_editor_property("sample_data", samples)
            H.eal.save_loaded_asset(bs, only_if_is_dirty=False)
            entry["after"] = [[anim_of(x).get_name() if anim_of(x) else "", round(speed_of(x)),
                               round(x.get_editor_property("rate_scale"), 2)] for x in samples]
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"


# Epic's hits throw bodies across an open arena; this ship has 4 m corridors. The upward
# launch sent people tumbling through the air, so it is cut, but not below a small hop:
# a hit sets the body half limp (physics blend 0.5) and only landing sets it back to 0.
# At 10% (30-35 cm/s) the character never left the ground at ~14 fps (one frame of gravity
# outweighs it), never landed, and stayed half limp for the rest of the game.
# Half (150-175 cm/s) still lifts off at 6 fps and rises only ~15 cm.
IMPACT_SCALE = {"launch": 0.5, "impulse": 0.4, "knockback": 0.4}


def tune_impacts(name, cdo, info):
    """Softer knockback and launch on hits (they flung bodies through walls and onto
    their heads), and Epic's on-screen debug text off. Values come from the parent so
    re-runs do not compound."""
    parent_path = HEROES[name]["parent"]
    own = blueprint_variables(parent_path, "Character")
    parent = unreal.get_default_object(H.eal.load_blueprint_class(parent_path))
    changed = {}
    for n in own:
        low = n.lower().replace(" ", "")
        try:
            v = parent.get_editor_property(n)
            factor = next((f for k, f in IMPACT_SCALE.items() if k in low), None)
            if factor is not None and type(v) in (int, float):
                cdo.set_editor_property(n, type(v)(v * factor))
                changed[n] = [v, round(v * factor, 2)]
            elif "debug" in low and v is True:
                cdo.set_editor_property(n, False)
                changed[n] = [True, False]
        except Exception:
            pass
    info["impacts"] = changed


def _control_rig_nodes(abp_path):
    """The Control Rig nodes in a hero's anim blueprint graph."""
    asset = abp_path.split("/")[-1]
    found = {}
    node_cls = getattr(unreal, "AnimGraphNode_ControlRig", None)
    if node_cls is not None and hasattr(unreal, "ObjectIterator"):
        for obj in unreal.ObjectIterator(node_cls):
            if obj.get_path_name().startswith(abp_path + "."):
                found[obj.get_path_name()] = obj
    if not found:
        for i in range(8):
            obj = unreal.find_object(None, f"{abp_path}.{asset}:AnimGraph.AnimGraphNode_ControlRig_{i}")
            if obj is not None:
                found[obj.get_path_name()] = obj
    return list(found.values())


def disable_foot_ik(name, info):
    """Epic's combat anim blueprint ends with CR_Mannequin_FootIK, a foot-placement rig
    made for the mannequin skeleton; on the Paragon heroes it bent knees and ankles.
    Its node is set to zero strength in the hero's copy, so the animation passes
    through it unchanged, and the blueprint is recompiled."""
    abp_path = f"/Game/{ANIM_BP.split('/')[-1]}_{name}"
    report = info.setdefault("foot_ik", {})
    abp = unreal.load_asset(abp_path)
    if abp is None:
        report["error"] = "no anim blueprint copy"
        return
    nodes = _control_rig_nodes(abp_path)
    report["nodes"] = len(nodes)
    done = []
    for graph_node in nodes:
        try:
            node = graph_node.get_editor_property("node")
            for prop, value in (("alpha", 0.0), ("alpha_bool_enabled", False)):
                try:
                    node.set_editor_property(prop, value)
                except Exception:
                    pass
            graph_node.set_editor_property("node", node)
            done.append(graph_node.get_name())
        except Exception as exc:
            report.setdefault("errors", []).append(f"{graph_node.get_name()}: {type(exc).__name__}: {exc}")
    if done:
        unreal.BlueprintEditorLibrary.compile_blueprint(abp)
        H.eal.save_loaded_asset(abp, only_if_is_dirty=False)
    report["off"] = done


def animation_blueprint_rigs(info):
    """Control Rigs the Combat anim blueprint runs (one bends Paragon legs wrongly)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    out = {}
    # the Combat one, and the template's plain one (a possible rig-free replacement)
    for path in (ANIM_BP, "/Game/Characters/Mannequins/Anims/Unarmed/ABP_Unarmed"):
        try:
            opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False,
                                                         include_hard_package_references=True)
            out[path.split("/")[-1]] = [str(d) for d in registry.get_dependencies(unreal.Name(path), opts) or []]
        except Exception as exc:
            out[path.split("/")[-1]] = [f"error: {exc}"]
    info["anim_blueprint_dependencies"] = out
    return out


# Bones that carry the ragdoll, with masses in kg for a ~80 kg body. Every other body
# (cloth strips, tails, twist bones, guns, Khaimera's hidden ghost-beast skeleton) gets
# its joint freed and stops simulating, without collision: its bone then simply rides
# the bone it hangs from instead of flapping about. Bodies between two ragdoll bones
# (Khaimera's twist-bone upper arm) keep carrying the limb.
RAGDOLL_BONES = {
    "pelvis": 12.0, "spine_01": 8.0, "spine_02": 8.0, "spine_03": 10.0, "neck_01": 2.0, "head": 5.0,
    "clavicle_l": 1.5, "clavicle_r": 1.5, "upperarm_l": 2.5, "upperarm_r": 2.5,
    "lowerarm_l": 1.5, "lowerarm_r": 1.5, "hand_l": 0.6, "hand_r": 0.6,
    "thigh_l": 9.0, "thigh_r": 9.0, "calf_l": 4.0, "calf_r": 4.0, "foot_l": 1.2, "foot_r": 1.2,
}
PASSENGER_MASS = 0.3
# joint limits in degrees (swing1, swing2, twist); spine, neck and head bend less
JOINT_LIMITS = {"spine": (20, 20, 10), "neck": (25, 25, 15), "head": (25, 25, 15), "pelvis": (20, 20, 10)}
JOINT_LIMIT_DEFAULT = (35, 35, 20)
# slows limbs down: a hit makes the body sway instead of flail
BODY_DAMPING = {"linear_damping": 0.5, "angular_damping": 8.0}


ENUMS = {}  # enum values resolved by tame_ragdoll
SUBOBJECT_SCAN = 20000  # highest object number tried when looking bodies up by name


def _subobjects(pa, cls_name, prop, diag=None):
    """The physics asset's bodies or joints. Its list properties are not readable from
    Python in 5.7, so they are found as objects living inside the asset: first among all
    loaded objects, then by name (bodies are called SkeletalBodySetup_<n>)."""
    diag = diag if diag is not None else {}
    try:
        return list(pa.get_editor_property(prop))
    except Exception as exc:
        diag[f"{prop}_list"] = str(exc)[:120]
    path = pa.get_path_name()
    cls = getattr(unreal, cls_name, None)
    found = {}
    if cls is not None and hasattr(unreal, "ObjectIterator"):
        try:
            seen, samples = 0, []
            for o in unreal.ObjectIterator(cls):
                seen += 1
                p = o.get_path_name()
                outer = None
                try:
                    outer = o.get_outer().get_path_name()
                except Exception:
                    pass
                if outer == path or p.startswith(path + ":") or p.startswith(path + "."):
                    found[p] = o
                elif len(samples) < 3:
                    samples.append(p)
            diag[f"{cls_name}_loaded"] = seen
            diag[f"{cls_name}_samples"] = samples
        except Exception as exc:
            diag[f"{cls_name}_iterator"] = f"{type(exc).__name__}: {exc}"
    if not found and hasattr(unreal, "find_object"):
        for i in range(SUBOBJECT_SCAN):
            try:
                o = unreal.find_object(pa, f"{cls_name}_{i}")
            except Exception:
                o = None
            if o is not None:
                found[o.get_path_name()] = o
        diag[f"{cls_name}_by_name"] = len(found)
    return list(found.values())


def _joint_limits(bone):
    b = bone.lower()
    for word, lim in JOINT_LIMITS.items():
        if word in b:
            return lim
    return JOINT_LIMIT_DEFAULT


def _bone_paths(name):
    """bone -> its chain up to the root, read from the hero's idle; {} if unavailable."""
    native = _native_assets(name)
    anim = unreal.load_asset(native["Idle"]) if "Idle" in native else None

    def path(bone):
        if anim is None:
            return None
        try:
            return [str(b) for b in unreal.AnimationLibrary.find_bone_path_to_root(anim, bone)]
        except Exception:
            return None
    return path


def _enum(cls_name, *words, diag=None):
    """An Unreal enum value by any of its likely Python names (5.7 calls EPhysicsType's
    PhysType_Default 'PHYS_TYPE_DEFAULT', not 'DEFAULT'). None if the enum has none of them."""
    cls = getattr(unreal, cls_name, None)
    if cls is None:
        return None
    names = [n for n in dir(cls) if n.isupper()]
    if diag is not None:
        diag.setdefault("enums", {})[cls_name] = names[:12]
    for w in words:
        if w in names:
            return getattr(cls, w)
    for w in words:
        for n in names:
            if n.endswith(w):
                return getattr(cls, n)
    return None


def _set_body(body, physics_type, mass, damping, collide, errors, bone):
    if physics_type is not None:
        try:
            body.set_editor_property("physics_type", physics_type)
        except Exception as exc:
            errors.append(f"{bone} physics_type: {exc}")
    if not collide and ENUMS.get("no_collision") is not None:
        # the engine spells this property 'CollisionReponse'
        for prop in ("collision_reponse", "collision_response"):
            try:
                body.set_editor_property(prop, ENUMS["no_collision"])
                break
            except Exception as exc:
                last = exc
        else:
            errors.append(f"{bone} collision: {last}")
    try:
        inst = body.get_editor_property("default_instance")
    except Exception as exc:
        errors.append(f"{bone} instance: {exc}")
        return
    for prop, value in damping.items():
        try:
            inst.set_editor_property(prop, value)
        except Exception as exc:
            errors.append(f"{bone} {prop}: {exc}")
    if mass:
        # a fixed mass: Khaimera's bodies came out weightless (zero-scale warnings), which
        # made her ragdoll explode and her death trip an engine check (zero total mass)
        try:
            inst.set_editor_property("override_mass", True)
            inst.set_editor_property("mass_in_kg_override", float(mass))
        except Exception as exc:
            errors.append(f"{bone} mass: {exc}")
    try:
        body.set_editor_property("default_instance", inst)
    except Exception as exc:
        errors.append(f"{bone} set instance: {exc}")


def _outputs(result):
    """A Blueprint function's outputs as a list, without the joint handle it was given
    (Python hands back by-reference arguments along with the real outputs)."""
    items = list(result) if isinstance(result, (tuple, list)) else [result]
    return [v for v in items if "Accessor" not in type(v).__name__]


class _AccessorJoint:
    """A joint edited through Unreal's Blueprint joint functions (PhysicsAsset.get_constraints
    + ConstraintInstanceBlueprintLibrary). The joint's own settings struct cannot be read from
    Python in 5.7, so editing it directly failed on every joint."""

    def __init__(self, lib, acc):
        self.lib, self.acc = lib, acc
        names = [str(v) for v in _outputs(lib.get_attached_body_names(acc))]
        if len(names) < 2:
            raise RuntimeError(f"body names came back as {names}")
        self.parent, self.child = names[-2], names[-1]

    def angular(self):
        return _outputs(self.lib.get_angular_limits(self.acc))[-6:]

    def limit(self, limits):
        cur = self.angular()  # swing1 motion, swing1 angle, swing2 motion, swing2 angle, twist motion, twist angle
        lim = [float(min(c, l)) if c > 0 else float(l) for c, l in zip((cur[1], cur[3], cur[5]), limits)]
        m = ENUMS["limited"]
        self.lib.set_angular_limits(self.acc, m, lim[0], m, lim[1], m, lim[2])

    def free(self):
        """No pull either way: the loose part's body stays put, its bone rides its parent."""
        f = ENUMS["free"]
        self.lib.set_angular_limits(self.acc, f, 0.0, f, 0.0, f, 0.0)
        self.lib.set_linear_limits(self.acc, ENUMS["linear_free"], ENUMS["linear_free"], ENUMS["linear_free"], 0.0)
        self.lib.set_disable_collision(self.acc, True)


class _TemplateJoint:
    """Fallback: edit the joint's settings struct directly (fails in 5.7, kept for others)."""

    def __init__(self, tpl):
        self.tpl = tpl
        inst = tpl.get_editor_property("default_instance")
        self.child = str(inst.get_editor_property("constraint_bone1"))
        try:
            self.parent = str(inst.get_editor_property("constraint_bone2"))
        except Exception:
            self.parent = None

    def angular(self):
        cone = self.tpl.get_editor_property("default_instance").get_editor_property(
            "profile_instance").get_editor_property("cone_limit")
        return [cone.get_editor_property("swing1_limit_degrees"), cone.get_editor_property("swing2_limit_degrees")]

    def _edit(self, motion, limits):
        inst = self.tpl.get_editor_property("default_instance")
        prof = inst.get_editor_property("profile_instance")
        cone = prof.get_editor_property("cone_limit")
        twist = prof.get_editor_property("twist_limit")
        for axis, lim in (("swing1", limits[0]), ("swing2", limits[1])):
            cone.set_editor_property(f"{axis}_motion", motion)
            if lim:
                cur = cone.get_editor_property(f"{axis}_limit_degrees")
                cone.set_editor_property(f"{axis}_limit_degrees", float(min(cur, lim) if cur > 0 else lim))
        twist.set_editor_property("twist_motion", motion)
        if limits[2]:
            cur = twist.get_editor_property("twist_limit_degrees")
            twist.set_editor_property("twist_limit_degrees", float(min(cur, limits[2]) if cur > 0 else limits[2]))
        prof.set_editor_property("cone_limit", cone)
        prof.set_editor_property("twist_limit", twist)
        inst.set_editor_property("profile_instance", prof)
        self.tpl.set_editor_property("default_instance", inst)

    def limit(self, limits):
        self._edit(ENUMS["limited"], limits)

    def free(self):
        raise RuntimeError("cannot free a joint through its template")


def _joints(pa, diag, errors):
    """The asset's joints as editable handles, each knowing its parent and child body."""
    lib = getattr(unreal, "ConstraintInstanceBlueprintLibrary", None)
    get = getattr(pa, "get_constraints", None)
    diag["joint_api"] = {"library": lib is not None, "get_constraints": get is not None}
    if lib is not None and get is not None:
        try:
            try:
                accessors = get(False)
            except TypeError:
                accessors = get()
            if isinstance(accessors, tuple):  # (return value, out list) in some bindings
                accessors = next((a for a in accessors if isinstance(a, (list, unreal.Array))), [])
            handles = []
            for acc in accessors or []:
                try:
                    handles.append(_AccessorJoint(lib, acc))
                except Exception as exc:
                    errors.append(f"joint names: {type(exc).__name__}: {exc}")
            diag["joint_route"] = "blueprint library"
            if handles:
                return handles
        except Exception as exc:
            diag["joint_api"]["error"] = f"{type(exc).__name__}: {exc}"[:200]
    diag["joint_route"] = "templates"
    handles = []
    for tpl in _subobjects(pa, "PhysicsConstraintTemplate", "constraint_setup", diag):
        try:
            handles.append(_TemplateJoint(tpl))
        except Exception as exc:
            errors.append(f"joint template: {type(exc).__name__}: {exc}")
    return handles


def _error_summary(errors):
    """'12x bone collision: msg' lines: one per kind of failure, so none hides another."""
    kinds = {}
    for e in errors:
        bone, _, rest = e.partition(" ")
        key = rest if rest else e
        k = kinds.setdefault(key, [0, bone])
        k[0] += 1
    return [f"{n}x {key} (e.g. {bone})"[:300] for key, (n, bone) in list(kinds.items())[:15]]


def tame_ragdoll(name, pa, info):
    """When hit, the Combat characters go half-limp for a moment (Epic's hit reaction blends
    in ragdoll); when killed, fully limp. The generated physics assets had a body on every
    cloth strip, tail and gun bone with loose joints, so a hit set everything wobbling like
    jelly. Now only the main skeleton swings, with real masses, joint limits and damping;
    the loose parts' bodies stand still (unjointed, no collision) while their bones ride along."""
    out = info.setdefault("ragdoll", {})
    out.update({"simulated": [], "bridging": [], "riding": [], "kinematic": []})
    errors = []
    diag = out.setdefault("lookup", {})
    bodies = _subobjects(pa, "SkeletalBodySetup", "skeletal_body_setups", diag)
    ENUMS.update({
        "default": _enum("PhysicsType", "PHYS_TYPE_DEFAULT", "DEFAULT", diag=diag),
        "kinematic": _enum("PhysicsType", "PHYS_TYPE_KINEMATIC", "KINEMATIC"),
        "limited": _enum("AngularConstraintMotion", "ACM_LIMITED", "LIMITED", diag=diag),
        "free": _enum("AngularConstraintMotion", "ACM_FREE", "FREE"),
        "linear_free": _enum("LinearConstraintMotion", "LCM_FREE", "FREE", diag=diag),
        "no_collision": _enum("BodyCollisionResponse", "BODY_COLLISION_DISABLED", "DISABLED", diag=diag),
    })
    missing = [k for k, v in ENUMS.items() if v is None]
    if missing:
        errors.append(f"enums: not found {missing}")
    joints = _joints(pa, diag, errors)
    out["found"] = {"bodies": len(bodies), "joints": len(joints)}

    by_bone = {}
    for body in bodies:
        try:
            by_bone[str(body.get_editor_property("bone_name"))] = body
        except Exception as exc:
            errors.append(f"body bone_name: {exc}")
    named = [j for j in joints if j.child in by_bone]
    if joints and len(named) < 0.8 * len(joints):
        # names that do not match the bodies would free the main skeleton's joints too
        errors.append(f"joints: only {len(named)} of {len(joints)} name a body, e.g. "
                      f"{joints[0].child}/{joints[0].parent}; joints left alone")
        joints = []
    # the joint tree: a body between two ragdoll bones (Khaimera's upper arm is only a
    # twist bone) carries the ragdoll too, or the forearm would come off when she dies
    parent_of = {j.child: j.parent for j in joints}
    core = {b for b in by_bone if b in RAGDOLL_BONES}
    bridge = set()
    for b in core:
        p, seen = parent_of.get(b), set()
        chain = []
        while p and p not in core and p not in seen:
            seen.add(p)
            chain.append(p)
            p = parent_of.get(p)
        if p in core:
            bridge.update(chain)

    # joints first: a loose part may only stop simulating once its joint is free,
    # otherwise its still body would hold the limb it hangs from in the air
    freed, done = set(), 0
    for j in joints:
        try:
            if j.child in core or j.child in bridge:
                j.limit(_joint_limits(j.child) if j.child in core else JOINT_LIMIT_DEFAULT)
            else:
                j.free()
                freed.add(j.child)
            done += 1
        except Exception as exc:
            errors.append(f"{j.child} joint: {type(exc).__name__}: {exc}")
    out["joints_set"] = done

    path_of = _bone_paths(name)
    loose_damping = {"linear_damping": 2.0, "angular_damping": 10.0}
    for bone, body in by_bone.items():
        if bone in core:
            role = "simulated"
            _set_body(body, ENUMS["default"], RAGDOLL_BONES[bone], BODY_DAMPING, True, errors, bone)
        elif bone in bridge:
            role = "bridging"
            _set_body(body, ENUMS["default"], 1.0, BODY_DAMPING, False, errors, bone)
        elif bone in freed or (joints and bone not in parent_of):
            role = "kinematic"
            _set_body(body, ENUMS["kinematic"], PASSENGER_MASS, loose_damping, False, errors, bone)
        else:
            # joint could not be freed: keep it simulating, light and without collision
            path = path_of(bone)
            hangs = any(b in RAGDOLL_BONES for b in path[1:]) if path else True
            role = "riding" if hangs else "kinematic"
            _set_body(body, ENUMS["default"] if hangs else ENUMS["kinematic"],
                      PASSENGER_MASS, loose_damping, False, errors, bone)
        out[role].append(bone)

    # read a few settings back, so the report shows what actually stuck
    check = {}
    for j in joints:
        kind = "core" if j.child in core else "freed" if j.child in freed else None
        if kind and kind not in check:
            try:
                check[kind] = [j.child] + [str(v) for v in j.angular()]
            except Exception as exc:
                check[kind] = f"{j.child}: {type(exc).__name__}: {exc}"[:200]
    for role in ("simulated", "kinematic"):
        if out[role]:
            b = by_bone[out[role][0]]
            try:
                check[role] = [out[role][0], str(b.get_editor_property("physics_type"))]
            except Exception as exc:
                check[role] = f"{type(exc).__name__}: {exc}"[:200]
    out["check"] = check
    out["errors"] = _error_summary(errors)
    if bodies or joints:
        H.eal.save_loaded_asset(pa, only_if_is_dirty=False)
    return out


def ragdoll_physics(name, mesh, info):
    """A per-bone physics asset for the hero. The Combat characters go limp when hit and
    when they die; the Paragon meshes only carry coarse shape helpers (e.g. Grux_Extents),
    so the whole body flipped over as one block and poked through walls."""
    try:
        before = mesh.get_editor_property("physics_asset")
        info["physics_before"] = before.get_name() if before else None
    except Exception:
        info["physics_before"] = "?"
    path = f"{CHAR_DIR}/PA_HH_{name}"
    if H.asset_exists(path):
        pa = unreal.load_asset(path)
        try:
            tame_ragdoll(name, pa, info)
            info["physics"] = "per-bone ragdoll, loose parts ride along"
        except Exception as exc:
            info["physics"] = f"tuning failed: {type(exc).__name__}: {exc}"
        return pa
    makers = []
    try:
        makers.append(unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem))
    except Exception:
        pass
    if hasattr(unreal, "EditorSkeletalMeshLibrary"):
        makers.append(unreal.EditorSkeletalMeshLibrary)
    for lib in makers:
        info.setdefault("physics_api", sorted(m for m in dir(lib) if "physic" in m.lower()))
        fn = getattr(lib, "create_physics_asset", None)
        if fn is None:
            continue
        try:
            pa = fn(mesh)
        except TypeError:
            pa = fn(mesh, False)  # (mesh, set_to_mesh) in some versions
        if pa:
            # keep it with our characters, under a fixed name
            if pa.get_path_name().split(".")[0] != path:
                H.eal.rename_asset(pa.get_path_name().split(".")[0], path)
                pa = unreal.load_asset(path)
            try:
                tame_ragdoll(name, pa, info)
            except Exception as exc:
                info["physics_tuning_error"] = f"{type(exc).__name__}: {exc}"
            H.eal.save_loaded_asset(pa, only_if_is_dirty=False)
            info["physics"] = "made per-bone ragdoll"
            return pa
    info["physics"] = "could not make a ragdoll; physics left as it was"
    return None


def configure_blueprint(name, bp, mesh, anims, info, stats=True):
    """Dress bp as the hero. stats=False (used on Epic's own character, which is its own
    parent) leaves health and hit strength alone so re-runs cannot compound them."""
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    cdo = unreal.get_default_object(bp.generated_class())
    if mesh is not None and ANIM_BP.split("/")[-1] in anims:
        comp = cdo.get_editor_property("mesh")
        _call_first(comp, ["set_skeletal_mesh_asset", "set_skeletal_mesh"], mesh)
        comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_BLUEPRINT)
        comp.set_editor_property("anim_class", anims[ANIM_BP.split("/")[-1]].generated_class())
        pa = None
        try:
            pa = ragdoll_physics(name, mesh, info)
        except Exception as exc:
            info["physics"] = f"{type(exc).__name__}: {exc}"
        if pa:
            comp.set_editor_property("physics_asset_override", pa)
        scale, radius, half, z = _fit_body(name, mesh, info)
        radius = max(radius, HEROES[name].get("min_radius", 0))
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
    speed = HEROES[name].get("speed")
    jog = None
    try:
        jog = hero_jog_speed(name, info)
    except Exception as exc:
        info["jog_speed_error"] = f"{type(exc).__name__}: {exc}"
    scale = (info.get("body") or {}).get("scale", 1.0)
    if jog:
        # feet stay planted when the body moves at the speed the jog was made for
        # (shrunk with the mesh); enemies keep their slower cap for the narrow ship
        matched = round(jog * scale * (PLAYER_PACE if name == PLAYER_HERO else 1.0))
        speed = matched if name == PLAYER_HERO else min(speed, matched)
        info["jog_speed"] = {"authored": round(jog), "scaled": matched}
        if mesh is not None:
            fit_locomotion_blendspace(name, matched, scale, info)
    if stats:
        try:
            tune_impacts(name, cdo, info)
        except Exception as exc:
            info["impacts_error"] = f"{type(exc).__name__}: {exc}"
    for prop, value in HEROES[name].get("props", {}).items():
        try:
            cdo.set_editor_property(prop, value)
            info.setdefault("props_set", {})[prop] = value
        except Exception as exc:
            info.setdefault("props_failed", {})[prop] = f"{type(exc).__name__}: {exc}"
    if speed:  # Epic's enemies are tuned for an open arena; the ship's corridors are 4 m wide
        try:
            cmc = cdo.get_editor_property("character_movement")
            info["walk_speed"] = {"was": round(cmc.get_editor_property("max_walk_speed")), "now": speed}
            cmc.set_editor_property("max_walk_speed", float(speed))
            if HEROES[name]["parent"] == ENEMY_BP:
                # Path following snapped the speed between 0 and full every time the AI
                # stopped to dodge or re-chased, so the legs flicked between idle and jog;
                # with acceleration the speed ramps. Avoidance kept nudging the velocity of
                # monsters standing still; the capsules already keep them apart.
                for prop, value in (("use_acceleration_for_paths", True), ("max_acceleration", 1000.0),
                                    ("braking_deceleration_walking", 1200.0), ("use_rvo_avoidance", False)):
                    cmc.set_editor_property(prop, value)
                info["path_movement"] = "accelerates, no avoidance"
        except Exception as exc:
            info["walk_speed"] = f"{type(exc).__name__}: {exc}"
    hp_scale = HEROES[name]["hp"]
    if stats and hp_scale != 1.0:
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


def add_lantern(bp, info):
    """A dim warm light that follows the player, so the hero is not a black silhouette
    against the corridor lamps (and it suits a dark flooded ship)."""
    try:
        sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        lib = unreal.SubobjectDataBlueprintFunctionLibrary
        handles = sds.k2_gather_subobject_data_for_blueprint(bp)
        light = None
        for h in handles:
            obj = lib.get_object(sds.k2_find_subobject_data_from_handle(h))
            if isinstance(obj, unreal.PointLightComponent):
                light = obj
        if light is None:
            params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=unreal.PointLightComponent,
                                                  blueprint_context=bp)
            result = sds.add_new_subobject(params)
            handle = result[0] if isinstance(result, tuple) else result
            light = lib.get_object(sds.k2_find_subobject_data_from_handle(handle))
        light.set_editor_property("relative_location", unreal.Vector(40, 0, 60))
        light.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
        light.set_editor_property("intensity", 6.0)
        light.set_editor_property("attenuation_radius", 600.0)
        light.set_editor_property("light_color", unreal.Color(r=255, g=190, b=130, a=255))
        light.set_editor_property("cast_shadows", False)  # cheap on integrated graphics
        info["lantern"] = "ok"
    except Exception as exc:
        info["lantern"] = f"{type(exc).__name__}: {exc}"


def dress_epic_character(name, mesh, anims):
    """Epic's player controller respawns its own BP_CombatCharacter after death (the class
    is fixed inside its graph, there is no setting for it), so that character is dressed
    as the hero too: mesh, animations, size, speed and attacks; health stays Epic's."""
    info = H.report["combat"].setdefault("epic_character", {})
    try:
        bp = unreal.load_asset(PLAYER_BP)
        configure_blueprint(name, bp, mesh, anims, info, stats=False)
        info["ok"] = True
    except Exception as exc:
        info["ok"] = False
        info["error"] = f"{type(exc).__name__}: {exc}"


def build_character(name):
    """One hero, never raising: on any failure the plain Combat mannequin is used instead."""
    info = _info(name)
    try:
        if name == PLAYER_HERO:
            probe_combat_blueprints()
            animation_blueprint_rigs(H.report["combat"])
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
        parent = HEROES[name]["parent"]
        if anims:
            try:
                use_native_animations(name, info)
            except Exception as exc:
                info["native_error"] = f"{type(exc).__name__}: {exc}"
            try:
                disable_foot_ik(name, info)
            except Exception as exc:
                info.setdefault("foot_ik", {})["error"] = f"{type(exc).__name__}: {exc}"
            try:
                replace_additive_anims(name, info)
            except Exception as exc:
                info["additive_error"] = f"{type(exc).__name__}: {exc}"
            # the idle copy is gone once the hero's own animations are wired in
            idle = unreal.load_asset(f"/Game/MM_Idle_{name}")  # a redirector to the hero's Idle once swapped
            native = idle is None or idle.get_path_name().startswith(f"/Game/Paragon{name}/")
            info["anim_source"] = "Paragon" if native else "Combat (retargeted)"
        bp = _child_blueprint(f"BP_HH_{name}", parent)
        info["parent"] = parent
        if name == PLAYER_HERO:
            add_lantern(bp, info)  # before configure_blueprint, which compiles and saves
        configure_blueprint(name, bp, mesh if anims else None, anims, info)
        built[name] = bp.generated_class()
        if name == PLAYER_HERO and anims:
            dress_epic_character(name, mesh, anims)
        info["blueprint"] = f"{CHAR_DIR}/BP_HH_{name}"
        info["ok"] = bool(anims)
        H.log(f"{name}: {'Paragon body' if anims else 'mannequin body'} -> {info['blueprint']}")
    except Exception:
        info["error"] = traceback.format_exc()
        info["ok"] = False
        H.warn(f"{name}: character setup failed, the Combat variant's own character is used")
    _write_probe()


def build_player_controller(info):
    """Child of the Combat player controller whose respawn class is our hero (without it
    the player came back as the grey mannequin after dying). Returns its class or None."""
    try:
        bp = _child_blueprint("BP_HH_CombatPlayerController", CONTROLLER_BP)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        cdo = unreal.get_default_object(bp.generated_class())
        found = {}
        try:  # its own variables that hold a class, e.g. the character to respawn
            own = blueprint_variables(CONTROLLER_BP, "PlayerController")
            # only a variable that currently points at the Combat mannequin character
            candidates = [n for n, v in own.items() if "BP_CombatCharacter" in v]
        except Exception:
            candidates = []
        info["controller_candidates"] = candidates
        for p in candidates + RESPAWN_PROPS:
            try:
                found[p] = str(cdo.get_editor_property(p))
                cdo.set_editor_property(p, built[PLAYER_HERO])
                info["respawn_class_property"] = p
                break
            except Exception:
                pass
        info["controller_props"] = found
        H.eal.save_loaded_asset(bp, only_if_is_dirty=False)
        return bp.generated_class()
    except Exception as exc:
        info["controller_error"] = f"{type(exc).__name__}: {exc}"
        return None


def build_game_mode():
    info = _info("GameMode")
    try:
        bp = _child_blueprint("BP_HH_CombatGameMode", GAME_MODE_BP)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        if PLAYER_HERO in built:
            cdo = unreal.get_default_object(bp.generated_class())
            cdo.set_editor_property("default_pawn_class", built[PLAYER_HERO])
            info["default_pawn"] = PLAYER_HERO
            pc = build_player_controller(info) if H.asset_exists(CONTROLLER_BP) else None
            if pc:
                cdo.set_editor_property("player_controller_class", pc)
                info["player_controller"] = "BP_HH_CombatPlayerController"
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
    build_navigation(nav)
    return build_game_mode()


def build_navigation(nav):
    """Scaling the volume from Python does not tell the navigation system its bounds
    changed (the old build covered a 2 m cube, and in Play the enemies had no nav mesh),
    so register the new bounds explicitly, rebuild, and record what came out."""
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    info = H.report["combat"].setdefault("navigation", {})
    try:
        nav_sys = unreal.NavigationSystemV1.get_navigation_system(world)
        if nav is not None:
            nav_sys.on_navigation_bounds_updated(nav)
        info["bounds_registered"] = nav is not None
    except Exception as exc:
        info["bounds_error"] = f"{type(exc).__name__}: {exc}"
    try:
        unreal.SystemLibrary.execute_console_command(world, "RebuildNavigation")
    except Exception as exc:
        H.warn(f"could not start the nav mesh build: {exc}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    navmeshes = [a for a in eas.get_all_level_actors() if "RecastNavMesh" in a.get_class().get_name()]
    info["navmesh_actors"] = len(navmeshes)
    if not navmeshes:
        H.warn("no nav mesh in the level after the build; one will be built when Play starts")
