"""Hollow Hull: import the kit and build the levels inside Unreal 5.7:
L_TheHollow (the cave under the ice) first, then L_FloodedDeck (the ship), which is
left open at the end.

Normally started by RUN_PHASE1.bat: it leaves a build request in the project's
Saved/HollowHull folder, and the project's Content/Python/init_unreal.py
(written by tools/prepare_project.py) runs this file when the editor starts.
To run it by hand: Tools > Execute Python Script... and pick this file.

Safe to re-run: meshes are re-imported in place, material instances keep their
values (textures you assigned are not touched), and every actor this script
spawned (tag HH_Generated) is deleted and spawned again.

Work runs in stages on editor ticks once the editor has settled; the report at
<Project>/Saved/HollowHull/setup_report.json is rewritten after every stage
("stage" says how far it got, "finished" turns true at the end).
"""

import importlib
import json
import os
import sys
import traceback

import unreal

# --- paths -----------------------------------------------------------------

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:  # some launch modes do not define __file__
    HERE = os.path.join(os.environ["HH_REPO"], "unreal")
ROOT = os.path.dirname(HERE)
KIT_DIR = os.path.join(ROOT, "export", "ship_kit")
# (map name, placements file from level/layout.py); the last one is left open in the editor
LEVELS = [("L_TheHollow", "placements_the_hollow.json"), ("L_FloodedDeck", "placements.json")]

PKG = "/Game/HollowHull"
MESH_DIR = PKG + "/Meshes"
MAT_DIR = PKG + "/Materials"
TEX_DIR = PKG + "/Textures"
TEXTURES = os.path.join(ROOT, "textures")  # textures/<material>/{basecolor,normal,orm}.png (tools/make_pbr.py)
UV_METRES = 2.0  # one UV unit on the kit pieces (blender/hh_kit.py UV_METRES_PER_TILE)
MAP_DIR = PKG + "/Maps"
MAP_PATH = MAP_DIR + "/L_FloodedDeck"
TAG = "HH_Generated"
# meshes and lights with an "fx" in the placements get this tag (plus the fx name, e.g.
# HH_FX_pulse) and can move, so unreal/hh_world.py can animate them while you play
FX_TAG = "HH_FX_"

# --- look tuning (safe to edit and re-run) --------------------------------

FOG_DENSITY = 0.035
FOG_COLOR = (0.02, 0.025, 0.03)
VIGNETTE = 0.6
FILM_GRAIN = 0.2
CHROMATIC_ABERRATION = 0.4
EXPOSURE_MIN_EV, EXPOSURE_MAX_EV = -1.0, 4.0

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import hh_combat  # noqa: E402  (Phase 2: Paragon characters on the Combat variant)
importlib.reload(hh_combat)  # pick up edits when re-run in the same editor session
import hh_audio  # noqa: E402  (not reloaded: init_unreal.py runs its in-game half)

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


# --- asset helpers ---------------------------------------------------------
# Unreal's asset registry fills in the background after startup; with big
# content packs it can still be incomplete when the build runs. So existence is
# also checked on disk, and a failed create says why instead of returning None.

def _asset_file(path):
    """/Game/A/B -> <Project>/Content/A/B (without extension)."""
    content = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    return os.path.join(content, *path[len("/Game/"):].split("/"))


def asset_exists(path):
    if eal.does_asset_exist(path):
        return True
    base = _asset_file(path)
    return os.path.exists(base + ".uasset") or os.path.exists(base + ".umap")


def load_or_create(name, folder, cls, factory):
    """Returns (asset, created)."""
    path = f"{folder}/{name}"
    if asset_exists(path):
        asset = unreal.load_asset(path)
        if asset:
            return asset, False
        raise RuntimeError(f"{path} exists on disk but could not be loaded")
    asset = asset_tools.create_asset(name, folder, cls, factory)
    if asset is None:
        raise RuntimeError(f"Unreal refused to create {path}")
    return asset, True


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
    mat, created = load_or_create("M_HH_Master", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if not created:
        return mat

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
    mat, created = load_or_create("M_HH_Water", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if not created:
        return mat
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
        mi, created = load_or_create(mi_name, MAT_DIR, unreal.MaterialInstanceConstant,
                                     unreal.MaterialInstanceConstantFactoryNew())
        if not created:
            instances[src_name] = mi
            if src_name != "M_Water":
                apply_textures(src_name, mi)
            continue
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
        if parent is master:
            apply_textures(src_name, mi)
        mel.update_material_instance(mi)
        eal.save_loaded_asset(mi)
        instances[src_name] = mi
        report["materials"].append(mi_name)
    log(f"material instances ready: {len(instances)}")
    return instances


def _texture_specs():
    path = os.path.join(TEXTURES, "materials.json")
    if "texture_specs" not in ctx:
        try:
            with open(path, encoding="utf-8") as f:
                ctx["texture_specs"] = json.load(f)["materials"]
        except Exception:
            ctx["texture_specs"] = {}
    return ctx["texture_specs"]


def _import_texture(path, name, kind):
    t = unreal.AssetImportTask()
    for prop, value in (("filename", path), ("destination_path", TEX_DIR), ("destination_name", name),
                        ("automated", True), ("replace_existing", True), ("save", False)):
        t.set_editor_property(prop, value)
    asset_tools.import_asset_tasks([t])
    tex = unreal.load_asset(f"{TEX_DIR}/{name}")
    if tex is None:
        raise RuntimeError(f"{os.path.basename(path)} did not import")
    if kind == "normal":
        set_prop(tex, "compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
        set_prop(tex, "srgb", False)
    elif kind == "orm":
        set_prop(tex, "compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
        set_prop(tex, "srgb", False)
    eal.save_loaded_asset(tex)
    return tex


def apply_textures(src_name, mi):
    """Plug textures/<material>/ into its material instance: colour, ORM (AO, roughness,
    metallic) and normal map, tiled so one copy covers tile_m metres. Runs on every build,
    so new or regenerated pictures always reach the game. No pictures: left as it is."""
    spec = _texture_specs().get(src_name)
    folder = os.path.join(TEXTURES, src_name)
    files = {k: os.path.join(folder, f"{k}.png") for k in ("basecolor", "orm", "normal")}
    if not spec or not all(os.path.exists(f) for f in files.values()):
        return False
    info = report.setdefault("textures", {})
    try:
        for kind, param in (("basecolor", "BaseColorTex"), ("orm", "ORMTex"), ("normal", "NormalTex")):
            tex = _import_texture(files[kind], f"T_{src_name[2:]}_{kind}", kind)
            mel.set_material_instance_texture_parameter_value(mi, param, tex)
        tint = spec.get("tint", [1.0, 1.0, 1.0])
        mel.set_material_instance_vector_parameter_value(mi, "BaseColor", unreal.LinearColor(*tint, 1))
        mel.set_material_instance_scalar_parameter_value(mi, "Tiling", UV_METRES / spec.get("tile_m", 2.0))
        mel.set_material_instance_scalar_parameter_value(mi, "Roughness", 1.0)
        mel.set_material_instance_scalar_parameter_value(mi, "Metallic", 0.0)
        mel.set_material_instance_scalar_parameter_value(mi, "AO", 1.0)
        mel.update_material_instance(mi)
        eal.save_loaded_asset(mi)
        info[src_name] = "textured"
        return True
    except Exception as exc:
        info[src_name] = f"failed: {exc}"[:200]
        warn(f"{src_name}: textures not applied ({exc})")
        return False


# --- meshes --------------------------------------------------------------

def _fbx_options(scale=1.0):
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
                        ("one_convex_hull_per_ucx", True), ("generate_lightmap_u_vs", True),
                        ("import_uniform_scale", float(scale))]:
        set_prop(sm, prop, value)
    return ui


def _import_piece(piece, scale=1.0):
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", os.path.join(KIT_DIR, piece["file"]))
    t.set_editor_property("destination_path", MESH_DIR)
    t.set_editor_property("destination_name", piece["name"])
    t.set_editor_property("automated", True)
    t.set_editor_property("replace_existing", True)
    t.set_editor_property("save", False)
    t.set_editor_property("options", _fbx_options(scale))
    asset_tools.import_asset_tasks([t])
    return unreal.load_asset(f"{MESH_DIR}/{piece['name']}")


def _expected_size_cm(piece):
    """Largest dimension of the piece as exported from Blender, in centimetres."""
    return max(hi - lo for lo, hi in zip(piece["bounds_min_m"], piece["bounds_max_m"])) * 100.0


def _mesh_size_cm(mesh):
    box = mesh.get_bounding_box()
    lo, hi = box.min, box.max
    return max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)


def _off(ratio):
    return abs(ratio - 1.0) > 0.05


def import_kit(manifest, instances):
    # The newer Interchange importer works asynchronously; touching a mesh it is
    # still building can crash the editor. The classic importer finishes first.
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
    sme = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    meshes = {}
    for piece in manifest["pieces"]:
        name = piece["name"]
        mesh = _import_piece(piece)
        if not isinstance(mesh, unreal.StaticMesh):
            warn(f"{name} did not import as a StaticMesh")
            continue

        # Size check: importers disagree about Blender's FBX units and can bring
        # a mesh in 100x too small. Re-importing in place leaves stale mesh
        # objects behind, so the mesh is imported once and the placed actors are
        # scaled to the size Blender exported instead.
        expected = _expected_size_cm(piece)
        actual = _mesh_size_cm(mesh)
        import_scale, spawn_scale = 1.0, 1.0
        if actual <= 0.001:
            warn(f"{name}: imported mesh is empty")
        elif _off(expected / actual):
            spawn_scale = expected / actual
            log(f"{name}: imported at {actual:.2f} cm, expected {expected:.0f} cm; placed actors scaled by {spawn_scale:.4g}")
        meshes[name] = mesh
        ctx.setdefault("spawn_scale", {})[name] = spawn_scale

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
                                  "collision_hulls_imported": hulls, "material_slots": len(slots),
                                  "size_cm_expected": round(expected, 1), "size_cm_imported": round(actual, 1),
                                  "import_scale": round(import_scale, 4), "spawn_scale": round(spawn_scale, 4)}
        log(f"imported {name}: {actual:.0f} cm, {len(slots)} slots, {hulls} hulls")
    log(f"imported {len(meshes)}/{len(manifest['pieces'])} meshes")
    return meshes


# --- level ---------------------------------------------------------------

def open_or_create_level(map_path):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if asset_exists(map_path):
        les.load_level(map_path)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        old = [a for a in eas.get_all_level_actors() if TAG in [str(t) for t in a.tags]]
        for a in old:
            eas.destroy_actor(a)
        log(f"reopened level, removed {len(old)} generated actors")
    else:
        les.new_level(map_path)
        log(f"created new level {map_path}")
    return les


def _tag(actor, folder):
    actor.set_editor_property("tags", [unreal.Name(TAG)])
    actor.set_folder_path(f"HollowHull/{folder}")


def _count(kind):
    spawned = ctx.get("spawned", report["spawned"])
    spawned[kind] = spawned.get(kind, 0) + 1


def _fx(actor, fx):
    """Let hh_world find and move this actor while you play."""
    actor.set_editor_property("tags", [unreal.Name(TAG), unreal.Name(FX_TAG + fx)])
    root = actor.get_editor_property("root_component")
    if root is not None:
        root.set_mobility(unreal.ComponentMobility.MOVABLE)


def spawn_meshes(data, meshes):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for m in data["meshes"]:
        mesh = meshes.get(m["mesh"])
        if not mesh:
            continue
        loc = unreal.Vector(m["x"], m["y"], m["z"])
        rot = unreal.Rotator(roll=float(m.get("roll", 0)), pitch=float(m.get("pitch", 0)), yaw=float(m["yaw"]))
        actor = eas.spawn_actor_from_object(mesh, loc, rot)
        if actor is None:
            if m["mesh"] not in ctx.setdefault("spawn_failed", set()):
                warn(f"could not place {m['mesh']} (Unreal returned no actor)")
                ctx["spawn_failed"].add(m["mesh"])
            continue
        scale = ctx.get("spawn_scale", {}).get(m["mesh"], 1.0)
        if scale != 1.0:
            actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
        _tag(actor, m["tag"] or "misc")
        if m.get("fx"):
            try:
                _fx(actor, m["fx"])
            except Exception as exc:
                warn(f"{m['mesh']}: could not make it move ({exc})")
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
        if li.get("shadows") is False:
            comp.set_cast_shadows(False)
        if li.get("fx"):
            _fx(actor, li["fx"])
        actor.set_actor_label(f"Lamp_{li['zone']}")
        _count("PointLight")


def spawn_atmosphere(data):
    """Fog and the camera's look; a level's "look" (level/<level>.json) overrides the
    ship's values, e.g. The Hollow's thick green-black fog and heavy vignette."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    bmin, bmax = data["bounds"]["min"], data["bounds"]["max"]
    centre = unreal.Vector((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, 0)
    look = data.get("look", {})

    fog = eas.spawn_actor_from_class(unreal.ExponentialHeightFog, centre)
    _tag(fog, "atmosphere")
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    set_prop(fc, "fog_density", look.get("fog_density", FOG_DENSITY))
    set_prop(fc, "fog_height_falloff", 0.001)
    set_prop(fc, "enable_volumetric_fog", True)
    set_prop(fc, "volumetric_fog_scattering_distribution", look.get("fog_scattering", 0.4))
    set_prop(fc, "fog_inscattering_luminance", unreal.LinearColor(*look.get("fog_color", FOG_COLOR), 1))
    _count("ExponentialHeightFog")

    ppv = eas.spawn_actor_from_class(unreal.PostProcessVolume, centre)
    _tag(ppv, "atmosphere")
    set_prop(ppv, "unbound", True)
    s = ppv.get_editor_property("settings")
    looks = [
        ("vignette_intensity", look.get("vignette", VIGNETTE)),
        ("film_grain_intensity", look.get("film_grain", FILM_GRAIN)),
        ("scene_fringe_intensity", look.get("chromatic_aberration", CHROMATIC_ABERRATION)),
        ("auto_exposure_min_brightness", look.get("exposure_min_ev", EXPOSURE_MIN_EV)),
        ("auto_exposure_max_brightness", look.get("exposure_max_ev", EXPOSURE_MAX_EV)),
        ("motion_blur_amount", 0.0),  # the combat camera shakes; blur smeared the whole screen
    ]
    if look.get("tint"):
        looks.append(("scene_color_tint", unreal.LinearColor(*look["tint"], 1)))
    for prop, value in looks:
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
    """Use the combat game mode (Phase 2) if it was made, else the Third Person template's."""
    if ctx.get("game_mode"):
        cls = eal.load_blueprint_class(ctx["game_mode"])
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if cls and set_prop(world.get_world_settings(), "default_game_mode", cls):
            report["game_mode"] = ctx["game_mode"]
            log(f"game mode override -> {ctx['game_mode']}")
            return
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
MAX_SCAN_WAIT_TICKS = 4000
STAGE_GAP_TICKS = 20
ctx = {}


def _report_path():
    saved = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    out = os.path.join(saved, "HollowHull")
    os.makedirs(out, exist_ok=True)
    return os.path.join(out, "setup_report.json")


def write_report():
    with open(_report_path(), "w") as f:
        json.dump(report, f, indent=2, default=str)  # engine values (names, enums) as text


def stage_load():
    with open(os.path.join(KIT_DIR, "manifest.json")) as f:
        ctx["manifest"] = json.load(f)
    ctx["levels"] = {}
    for name, file in LEVELS:
        path = os.path.join(ROOT, "level", file)
        if not os.path.exists(path):
            warn(f"{file} is missing, so {name} is not built (run level/layout.py)")
            continue
        with open(path) as f:
            ctx["levels"][name] = json.load(f)


def stage_materials():
    ctx["instances"] = build_material_instances(ctx["manifest"])


def stage_import():
    ctx["meshes"] = import_kit(ctx["manifest"], ctx["instances"])


def stage_audio():
    try:
        hh_audio.import_audio(report, warn, log)
    except Exception as exc:
        warn(f"sounds not imported: {exc}")


def _level_stage(name, fn):
    """A stage for one level: skipped when its placements are missing."""
    def stage():
        data = ctx["levels"].get(name)
        if data is None:
            return
        ctx["data"] = data
        # the ship's counts stay in report["spawned"] (run_phase1.ps1 checks them)
        ctx["spawned"] = (report["spawned"] if name == "L_FloodedDeck"
                          else report.setdefault("levels", {}).setdefault(name, {}).setdefault("spawned", {}))
        fn(name)
    return stage


def stage_level(name):
    ctx["les"] = open_or_create_level(f"{MAP_DIR}/{name}")


def stage_meshes(name):
    spawn_meshes(ctx["data"], ctx["meshes"])


def stage_lights(name):
    spawn_lights(ctx["data"])


def stage_atmosphere(name):
    spawn_atmosphere(ctx["data"])


def stage_gameplay(name):
    if ctx.get("combat"):
        ctx["game_mode"] = hh_combat.spawn_gameplay(ctx["data"])
    else:
        log("Combat variant not in the project; skipping enemies")


def stage_save(name):
    set_game_mode()
    ctx["les"].save_current_level()
    report.setdefault("levels", {}).setdefault(name, {})["saved"] = f"{MAP_DIR}/{name}"
    if name == "L_FloodedDeck":
        report["level"] = MAP_PATH
    # start the editor camera at the player start, looking the way the player will
    ps = ctx["data"]["player_start"]
    try:
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
            unreal.Vector(ps["x"], ps["y"], 170.0), unreal.Rotator(roll=0.0, pitch=-5.0, yaw=float(ps["yaw"])))
    except Exception as exc:
        warn(f"could not move the editor camera: {exc}")


INVENTORY_CLASSES = {"Blueprint", "World", "SkeletalMesh", "Skeleton", "AnimBlueprint", "StateTree", "BehaviorTree",
                     "BlackboardData", "InputAction", "InputMappingContext", "AnimMontage", "AnimSequence",
                     "BlendSpace", "BlendSpace1D", "PhysicsAsset", "IKRigDefinition", "IKRetargeter",
                     "WidgetBlueprint", "NiagaraSystem", "ParticleSystem", "SoundCue", "UserDefinedEnum",
                     "UserDefinedStruct", "DataTable", "CurveFloat"}


def stage_inventory():
    """List what the project contains (template variants, Fab characters) for Claude to script against.
    Informational only: a failure here is a warning, never a failed build."""
    try:
        _write_inventory()
    except Exception as exc:
        warn(f"inventory not written: {exc}")


def _write_inventory():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    items = []
    for a in registry.get_assets_by_path("/Game", recursive=True):
        cls = str(a.asset_class_path.asset_name)
        pkg = str(a.package_name)
        if cls not in INVENTORY_CLASSES or pkg.startswith(PKG):
            continue
        entry = {"path": pkg, "class": cls}
        if cls in ("Blueprint", "AnimBlueprint", "WidgetBlueprint"):
            parent = a.get_tag_value("ParentClass")
            if parent:
                entry["parent"] = str(parent).split(".")[-1].rstrip("'")
        if cls in ("SkeletalMesh", "AnimSequence", "AnimMontage", "BlendSpace", "BlendSpace1D", "AnimBlueprint"):
            # which skeleton an animation plays on (Paragon heroes each have their own)
            skel = a.get_tag_value("Skeleton") or a.get_tag_value("TargetSkeleton")
            if skel:
                entry["skeleton"] = str(skel).split(".")[-1].rstrip("'")
        items.append(entry)
    items.sort(key=lambda e: (e["class"], e["path"]))
    with open(os.path.join(os.path.dirname(_report_path()), "inventory.json"), "w") as f:
        json.dump({"assets": items}, f, indent=1)
    counts = {}
    for e in items:
        counts[e["class"]] = counts.get(e["class"], 0) + 1
    report["inventory"] = counts
    # top-level Content folders straight from disk (Fab packs land here), in MB
    content = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    folders = {}
    for entry in sorted(os.listdir(content)):
        full = os.path.join(content, entry)
        if os.path.isdir(full):
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(full) for f in fs)
            folders[entry] = round(size / 1e6, 1)
    report["content_folders_mb"] = folders
    log(f"inventory: {counts}; content folders: {folders}")


def _character_stage(name):
    def stage():
        if ctx.get("combat"):
            hh_combat.build_character(name)
    return stage


def stage_combat_check():
    ctx["combat"] = asset_exists(hh_combat.ENEMY_BP)
    if ctx["combat"]:
        hh_combat.init({k: globals()[k] for k in ("log", "warn", "report", "asset_exists", "load_or_create", "eal",
                                                   "asset_tools", "_tag", "_count", "_report_path")})
    else:
        warn("Combat variant not found in the project (Content/Variant_Combat); no enemies this time")


STAGES = ([("load", stage_load), ("inventory", stage_inventory), ("materials", stage_materials),
           ("import", stage_import), ("audio", stage_audio), ("combat check", stage_combat_check)] +
          [(f"character {n}", _character_stage(n)) for n in hh_combat.HEROES] +
          [(f"{step} {lvl}", _level_stage(lvl, fn)) for lvl, _ in LEVELS
           for step, fn in (("level", stage_level), ("meshes", stage_meshes), ("lights", stage_lights),
                            ("atmosphere", stage_atmosphere), ("gameplay", stage_gameplay), ("save", stage_save))])
state = {"i": 0, "wait": WARMUP_TICKS, "handle": None, "busy": False}


def _pause_play_helpers(paused):
    """The play recorder and sound player (started by init_unreal.py) tick every frame;
    keep them out of the way while the build compiles and saves assets."""
    for name in ("hh_trace", "hh_audio", "hh_world"):
        mod = sys.modules.get(name)
        if mod is not None and isinstance(getattr(mod, "S", None), dict):
            mod.S["paused"] = paused


def finish(ok):
    _pause_play_helpers(False)
    unreal.unregister_slate_post_tick_callback(state["handle"])
    report["finished"] = True
    expected = len(ctx.get("manifest", {}).get("pieces", [])) or -1
    report["ok"] = ok and len(ctx.get("meshes", {})) == expected
    write_report()
    log(f"done: ok={report['ok']}, {sum(report['spawned'].values())} actors, "
        f"{len(report['warnings'])} warnings")
    unreal.log(f"[HH] report -> {_report_path()}")


def _tick(_dt):
    # Creating and compiling assets pumps the editor's UI, which can call this
    # callback again while a stage is still running; ignore those nested calls.
    if state["busy"]:
        return
    state["busy"] = True
    try:
        _advance()
    finally:
        state["busy"] = False


def _in_play_mode():
    try:
        return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor()
    except Exception:
        return False


def _advance():
    if state["wait"] > 0:
        state["wait"] -= 1
        return
    # Unreal refuses editor building while a game is running in the editor
    # (Play pressed too early): pause until Play is stopped.
    if _in_play_mode():
        if not state.get("pie_logged"):
            warn("Play was pressed during the build; paused until Play is stopped")
            report["stage"] = "paused: stop Play in Unreal"
            write_report()
            state["pie_logged"] = True
        return
    state["pie_logged"] = False
    # wait for the startup asset scan, but not forever: existence checks also
    # look on disk, so after ~2 minutes it is safe to go ahead anyway
    scan_ticks = state.get("scan_ticks", 0)
    if (state["i"] == 0 and scan_ticks < MAX_SCAN_WAIT_TICKS
            and unreal.AssetRegistryHelpers.get_asset_registry().is_loading_assets()):
        state["scan_ticks"] = scan_ticks + 1
        if not state.get("registry_logged"):
            log("waiting for Unreal to finish scanning project assets")
            report["stage"] = "waiting for asset scan"
            write_report()
            state["registry_logged"] = True
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


_pause_play_helpers(True)
report.update({"ok": False, "finished": False, "stage": "waiting for editor"})
write_report()
log(f"queued {len(STAGES)} stages; starting after the editor settles")
state["handle"] = unreal.register_slate_post_tick_callback(_tick)
