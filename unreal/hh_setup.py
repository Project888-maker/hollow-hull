"""Hollow Hull: import the ship kit and build L_FloodedDeck inside Unreal 5.7.

Run from the command line (opens the editor, runs this, leaves the editor open):
    UnrealEditor.exe "<path>/HollowHull.uproject" -ExecutePythonScript="<repo>/unreal/hh_setup.py"
or inside the editor: Tools > Execute Python Script... and pick this file.

Safe to re-run: meshes are re-imported in place, material instances keep their
values (textures you assigned are not touched), and every actor this script
spawned (tag HH_Generated) is deleted and spawned again.

Work runs in stages on editor ticks once the editor has settled; the report at
<Project>/Saved/HollowHull/setup_report.json is rewritten after every stage
("stage" says how far it got, "finished" turns true at the end).
"""

import json
import os
import traceback

import unreal

# --- paths -----------------------------------------------------------------

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:  # some launch modes do not define __file__
    HERE = os.path.join(os.environ["HH_REPO"], "unreal")
ROOT = os.path.dirname(HERE)
KIT_DIR = os.path.join(ROOT, "export", "ship_kit")
PLACEMENTS = os.path.join(ROOT, "level", "placements.json")

PKG = "/Game/HollowHull"
MESH_DIR = PKG + "/Meshes"
MAT_DIR = PKG + "/Materials"
MAP_PATH = PKG + "/Maps/L_FloodedDeck"
TAG = "HH_Generated"

# --- look tuning (safe to edit and re-run) --------------------------------

FOG_DENSITY = 0.035
FOG_COLOR = (0.02, 0.025, 0.03)
VIGNETTE = 0.6
FILM_GRAIN = 0.2
CHROMATIC_ABERRATION = 0.4
EXPOSURE_MIN_EV, EXPOSURE_MAX_EV = -1.0, 4.0

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
report = {"warnings": [], "meshes": {}, "spawned": {}, "materials": []}


def log(msg):
    unreal.log(f"[HH] {msg}")


def warn(msg):
    unreal.log_warning(f"[HH] WARNING {msg}")
    report["warnings"].append(msg)


def set_prop(obj, name, value):
    """set_editor_property that records a warning instead of aborting the run."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:  # property names drift between engine versions
        warn(f"could not set {type(obj).__name__}.{name}: {exc}")
        return False


# --- materials -----------------------------------------------------------

def _expr(mat, cls, x, y, param=None):
    e = mel.create_material_expression(mat, cls, x, y)
    if param:
        e.set_editor_property("parameter_name", param)
    return e


def _texture_param(mat, name, default_path, x, y, uv, normal=False):
    t = _expr(mat, unreal.MaterialExpressionTextureSampleParameter2D, x, y, name)
    t.set_editor_property("texture", unreal.load_asset(default_path))
    if normal:
        t.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    mel.connect_material_expressions(uv, "", t, "UVs")
    return t


def build_master_material():
    """M_HH_Master: tint x texture for colour, ORM-packed texture x scalars, normal map.

    Defaults are white/flat textures, so it renders as plain colour until real
    textures (Megascans, fal) are assigned on the material instances.
    """
    path = f"{MAT_DIR}/M_HH_Master"
    if eal.does_asset_exist(path):
        return unreal.load_asset(path)
    mat = asset_tools.create_asset("M_HH_Master", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())

    coords = _expr(mat, unreal.MaterialExpressionTextureCoordinate, -1400, 0)
    tiling = _expr(mat, unreal.MaterialExpressionScalarParameter, -1400, 150, "Tiling")
    tiling.set_editor_property("default_value", 1.0)
    uv = _expr(mat, unreal.MaterialExpressionMultiply, -1200, 50)
    mel.connect_material_expressions(coords, "", uv, "A")
    mel.connect_material_expressions(tiling, "", uv, "B")

    white = "/Engine/EngineResources/WhiteSquareTexture"
    base_tex = _texture_param(mat, "BaseColorTex", white, -900, -300, uv)
    orm_tex = _texture_param(mat, "ORMTex", white, -900, 100, uv)
    nrm_tex = _texture_param(mat, "NormalTex", "/Engine/EngineMaterials/DefaultNormal", -900, 500, uv, normal=True)

    tint = _expr(mat, unreal.MaterialExpressionVectorParameter, -900, -500, "BaseColor")
    tint.set_editor_property("default_value", unreal.LinearColor(0.5, 0.5, 0.5, 1))
    base = _expr(mat, unreal.MaterialExpressionMultiply, -500, -400)
    mel.connect_material_expressions(base_tex, "RGB", base, "A")
    mel.connect_material_expressions(tint, "", base, "B")
    mel.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)

    for i, (pin, param, default, prop) in enumerate([
        ("R", "AO", 1.0, unreal.MaterialProperty.MP_AMBIENT_OCCLUSION),
        ("G", "Roughness", 0.6, unreal.MaterialProperty.MP_ROUGHNESS),
        ("B", "Metallic", 0.0, unreal.MaterialProperty.MP_METALLIC),
    ]):
        scalar = _expr(mat, unreal.MaterialExpressionScalarParameter, -700, 0 + i * 120, param)
        scalar.set_editor_property("default_value", default)
        mul = _expr(mat, unreal.MaterialExpressionMultiply, -400, 0 + i * 120)
        mel.connect_material_expressions(orm_tex, pin, mul, "A")
        mel.connect_material_expressions(scalar, "", mul, "B")
        mel.connect_material_property(mul, "", prop)

    mel.connect_material_property(nrm_tex, "RGB", unreal.MaterialProperty.MP_NORMAL)

    ecol = _expr(mat, unreal.MaterialExpressionVectorParameter, -700, 800, "EmissiveColor")
    ecol.set_editor_property("default_value", unreal.LinearColor(0, 0, 0, 1))
    estr = _expr(mat, unreal.MaterialExpressionScalarParameter, -700, 950, "EmissiveStrength")
    estr.set_editor_property("default_value", 0.0)
    emul = _expr(mat, unreal.MaterialExpressionMultiply, -400, 850)
    mel.connect_material_expressions(ecol, "", emul, "A")
    mel.connect_material_expressions(estr, "", emul, "B")
    mel.connect_material_property(emul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    log("created M_HH_Master")
    return mat


def build_water_material():
    path = f"{MAT_DIR}/M_HH_Water"
    if eal.does_asset_exist(path):
        return unreal.load_asset(path)
    mat = asset_tools.create_asset("M_HH_Water", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    set_prop(mat, "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    set_prop(mat, "translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
    for name, value, prop, x, y in [
        ("Opacity", 0.8, unreal.MaterialProperty.MP_OPACITY, -400, 200),
        ("Roughness", 0.04, unreal.MaterialProperty.MP_ROUGHNESS, -400, 100),
        ("Specular", 1.0, unreal.MaterialProperty.MP_SPECULAR, -400, 300),
    ]:
        s = _expr(mat, unreal.MaterialExpressionScalarParameter, x, y, name)
        s.set_editor_property("default_value", value)
        mel.connect_material_property(s, "", prop)
    col = _expr(mat, unreal.MaterialExpressionVectorParameter, -400, -100, "BaseColor")
    col.set_editor_property("default_value", unreal.LinearColor(0.01, 0.03, 0.03, 1))
    mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    log("created M_HH_Water")
    return mat


def build_material_instances(manifest):
    """One MI per Blender material. Existing MIs are left alone so hand-tuned
    values and assigned textures survive a re-run."""
    master = build_master_material()
    water = build_water_material()
    instances = {}
    for src_name, spec in manifest["materials"].items():
        mi_name = "MI_" + src_name[2:]
        path = f"{MAT_DIR}/{mi_name}"
        if eal.does_asset_exist(path):
            instances[src_name] = unreal.load_asset(path)
            continue
        mi = asset_tools.create_asset(mi_name, MAT_DIR, unreal.MaterialInstanceConstant,
                                      unreal.MaterialInstanceConstantFactoryNew())
        parent = water if src_name == "M_Water" else master
        mel.set_material_instance_parent(mi, parent)
        r, g, b = spec["base_color"]
        mel.set_material_instance_vector_parameter_value(mi, "BaseColor", unreal.LinearColor(r, g, b, 1))
        if parent is master:
            mel.set_material_instance_scalar_parameter_value(mi, "Roughness", spec["roughness"])
            mel.set_material_instance_scalar_parameter_value(mi, "Metallic", spec["metallic"])
            if spec["emissive"]:
                mel.set_material_instance_vector_parameter_value(mi, "EmissiveColor", unreal.LinearColor(r, g, b, 1))
                mel.set_material_instance_scalar_parameter_value(mi, "EmissiveStrength", spec["emissive"] * 4)
        mel.update_material_instance(mi)
        eal.save_loaded_asset(mi)
        instances[src_name] = mi
        report["materials"].append(mi_name)
    log(f"material instances ready: {len(instances)}")
    return instances


# --- meshes --------------------------------------------------------------

def _fbx_options():
    """Classic FBX importer settings: mesh only, keep UCX_ hulls, no materials
    (slots are pointed at our material instances afterwards)."""
    ui = unreal.FbxImportUI()
    for prop, value in [("import_mesh", True), ("import_textures", False), ("import_materials", False),
                        ("import_as_skeletal", False), ("import_animations", False),
                        ("automated_import_should_detect_type", False)]:
        set_prop(ui, prop, value)
    set_prop(ui, "mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    sm = ui.get_editor_property("static_mesh_import_data")
    for prop, value in [("combine_meshes", True), ("auto_generate_collision", False),
                        ("one_convex_hull_per_ucx", True), ("generate_lightmap_u_vs", True)]:
        set_prop(sm, prop, value)
    return ui


def import_kit(manifest, instances):
    # The newer Interchange importer works asynchronously; touching a mesh it is
    # still building can crash the editor. The classic importer finishes first.
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
    sme = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    meshes = {}
    for piece in manifest["pieces"]:
        name = piece["name"]
        t = unreal.AssetImportTask()
        t.set_editor_property("filename", os.path.join(KIT_DIR, piece["file"]))
        t.set_editor_property("destination_path", MESH_DIR)
        t.set_editor_property("destination_name", name)
        t.set_editor_property("automated", True)
        t.set_editor_property("replace_existing", True)
        t.set_editor_property("save", False)
        t.set_editor_property("options", _fbx_options())
        asset_tools.import_asset_tasks([t])

        mesh = unreal.load_asset(f"{MESH_DIR}/{name}")
        if not isinstance(mesh, unreal.StaticMesh):
            warn(f"{name} did not import as a StaticMesh")
            continue
        meshes[name] = mesh

        # point every slot at our material instance: by slot name, else by FBX slot order
        slots = mesh.get_editor_property("static_materials")
        for i, slot in enumerate(slots):
            slot_name = str(slot.get_editor_property("material_slot_name")).split(".")[0]
            if slot_name not in instances and i < len(piece["materials"]):
                slot_name = piece["materials"][i]
            if slot_name in instances:
                mesh.set_material(i, instances[slot_name])
            else:
                warn(f"{name}: no material instance for slot {i} '{slot_name}'")

        # collision: the FBX carries UCX_ hulls; fall back to per-poly if they were dropped
        hulls = sme.get_convex_collision_count(mesh)
        if piece["collision_hulls"] and hulls == 0:
            body = mesh.get_editor_property("body_setup")
            if body:
                set_prop(body, "collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
            warn(f"{name}: UCX collision missing after import, using complex-as-simple")
        eal.save_loaded_asset(mesh)
        report["meshes"][name] = {"collision_hulls_expected": piece["collision_hulls"],
                                  "collision_hulls_imported": hulls, "material_slots": len(slots)}
        log(f"imported {name}: {len(slots)} slots, {hulls} hulls")
    log(f"imported {len(meshes)}/{len(manifest['pieces'])} meshes")
    return meshes


# --- level ---------------------------------------------------------------

def open_or_create_level():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if eal.does_asset_exist(MAP_PATH):
        les.load_level(MAP_PATH)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        old = [a for a in eas.get_all_level_actors() if TAG in [str(t) for t in a.tags]]
        for a in old:
            eas.destroy_actor(a)
        log(f"reopened level, removed {len(old)} generated actors")
    else:
        les.new_level(MAP_PATH)
        log("created new level")
    return les


def _tag(actor, folder):
    actor.set_editor_property("tags", [unreal.Name(TAG)])
    actor.set_folder_path(f"HollowHull/{folder}")


def _count(kind):
    report["spawned"][kind] = report["spawned"].get(kind, 0) + 1


def spawn_meshes(data, meshes):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for m in data["meshes"]:
        mesh = meshes.get(m["mesh"])
        if not mesh:
            continue
        loc = unreal.Vector(m["x"], m["y"], m["z"])
        rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=float(m["yaw"]))
        actor = eas.spawn_actor_from_object(mesh, loc, rot)
        _tag(actor, m["tag"] or "misc")
        if not m["collision"]:
            actor.static_mesh_component.set_collision_profile_name("NoCollision")
        _count(m["mesh"])


def spawn_lights(data):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for li in data["lights"]:
        actor = eas.spawn_actor_from_class(unreal.PointLight, unreal.Vector(li["x"], li["y"], li["z"]))
        _tag(actor, "lights")
        comp = actor.get_component_by_class(unreal.PointLightComponent)
        set_prop(comp, "intensity_units", unreal.LightUnits.CANDELAS)
        comp.set_intensity(li["intensity_cd"])
        r, g, b = li["color"]
        comp.set_light_color(unreal.LinearColor(r, g, b, 1))
        comp.set_attenuation_radius(li["radius_cm"])
        set_prop(comp, "source_radius", 6.0)
        actor.set_actor_label(f"Lamp_{li['zone']}")
        _count("PointLight")


def spawn_atmosphere(data):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    bmin, bmax = data["bounds"]["min"], data["bounds"]["max"]
    centre = unreal.Vector((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, 0)

    fog = eas.spawn_actor_from_class(unreal.ExponentialHeightFog, centre)
    _tag(fog, "atmosphere")
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    set_prop(fc, "fog_density", FOG_DENSITY)
    set_prop(fc, "fog_height_falloff", 0.001)
    set_prop(fc, "enable_volumetric_fog", True)
    set_prop(fc, "volumetric_fog_scattering_distribution", 0.4)
    set_prop(fc, "fog_inscattering_luminance", unreal.LinearColor(*FOG_COLOR, 1))
    _count("ExponentialHeightFog")

    ppv = eas.spawn_actor_from_class(unreal.PostProcessVolume, centre)
    _tag(ppv, "atmosphere")
    set_prop(ppv, "unbound", True)
    s = ppv.get_editor_property("settings")
    for prop, value in [
        ("vignette_intensity", VIGNETTE),
        ("film_grain_intensity", FILM_GRAIN),
        ("scene_fringe_intensity", CHROMATIC_ABERRATION),
        ("auto_exposure_min_brightness", EXPOSURE_MIN_EV),
        ("auto_exposure_max_brightness", EXPOSURE_MAX_EV),
    ]:
        if set_prop(s, "override_" + prop, True):
            set_prop(s, prop, value)
    set_prop(ppv, "settings", s)
    _count("PostProcessVolume")

    ps = data["player_start"]
    start = eas.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(ps["x"], ps["y"], ps["z"]),
                                       unreal.Rotator(roll=0.0, pitch=0.0, yaw=float(ps["yaw"])))
    _tag(start, "gameplay")
    _count("PlayerStart")


def set_game_mode():
    """Use the Third Person template's game mode so Play spawns the template character."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    candidates = [a for a in registry.get_assets_by_path("/Game", recursive=True)
                  if "GameMode" in str(a.asset_name) and str(a.asset_class_path.asset_name) == "Blueprint"]
    candidates.sort(key=lambda a: ("ThirdPerson" not in str(a.asset_name), str(a.package_name)))
    if not candidates:
        warn("no GameMode blueprint found; Play will use the project default game mode")
        return
    path = str(candidates[0].package_name)
    cls = eal.load_blueprint_class(path)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if set_prop(world.get_world_settings(), "default_game_mode", cls):
        report["game_mode"] = path
        log(f"game mode override -> {path}")


# --- staged runner ---------------------------------------------------------
# The work runs in stages on editor ticks, after the editor has settled, and the
# report is written after every stage. If the editor dies, the report's "stage"
# says exactly where.

WARMUP_TICKS = 240
STAGE_GAP_TICKS = 20
ctx = {}


def _report_path():
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    out = os.path.join(saved, "HollowHull")
    os.makedirs(out, exist_ok=True)
    return os.path.join(out, "setup_report.json")


def write_report():
    with open(_report_path(), "w") as f:
        json.dump(report, f, indent=2)


def stage_load():
    with open(os.path.join(KIT_DIR, "manifest.json")) as f:
        ctx["manifest"] = json.load(f)
    with open(PLACEMENTS) as f:
        ctx["data"] = json.load(f)


def stage_materials():
    ctx["instances"] = build_material_instances(ctx["manifest"])


def stage_import():
    ctx["meshes"] = import_kit(ctx["manifest"], ctx["instances"])


def stage_level():
    ctx["les"] = open_or_create_level()


def stage_meshes():
    spawn_meshes(ctx["data"], ctx["meshes"])


def stage_lights():
    spawn_lights(ctx["data"])


def stage_atmosphere():
    spawn_atmosphere(ctx["data"])


def stage_save():
    set_game_mode()
    ctx["les"].save_current_level()
    report["level"] = MAP_PATH


STAGES = [("load", stage_load), ("materials", stage_materials), ("import", stage_import),
          ("level", stage_level), ("meshes", stage_meshes), ("lights", stage_lights),
          ("atmosphere", stage_atmosphere), ("save", stage_save)]
state = {"i": 0, "wait": WARMUP_TICKS, "handle": None}


def finish(ok):
    unreal.unregister_slate_post_tick_callback(state["handle"])
    report["finished"] = True
    expected = len(ctx.get("manifest", {}).get("pieces", [])) or -1
    report["ok"] = ok and len(ctx.get("meshes", {})) == expected
    write_report()
    log(f"done: ok={report['ok']}, {sum(report['spawned'].values())} actors, "
        f"{len(report['warnings'])} warnings")
    unreal.log(f"[HH] report -> {_report_path()}")


def _tick(_dt):
    if state["wait"] > 0:
        state["wait"] -= 1
        return
    name, fn = STAGES[state["i"]]
    report["stage"] = name
    write_report()
    log(f"stage {state['i'] + 1}/{len(STAGES)}: {name}")
    try:
        fn()
    except Exception:
        report["error"] = f"stage {name}: " + traceback.format_exc()
        unreal.log_error("[HH] FAILED " + report["error"])
        finish(False)
        return
    state["i"] += 1
    state["wait"] = STAGE_GAP_TICKS
    if state["i"] >= len(STAGES):
        finish(True)


report.update({"ok": False, "finished": False, "stage": "waiting for editor"})
write_report()
log(f"queued {len(STAGES)} stages; starting after the editor settles")
state["handle"] = unreal.register_slate_post_tick_callback(_tick)
