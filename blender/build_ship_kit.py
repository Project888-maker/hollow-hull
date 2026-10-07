"""Generate the Hollow Hull ship kit and export one FBX per piece for Unreal.

Run headless (no Blender UI needed):
    blender --background --factory-startup --python build_ship_kit.py -- --out ../export/ship_kit [--preview ../preview/kit_lineup.jpg]

Writes <out>/<SM_Name>.fbx for every piece plus <out>/manifest.json, which the
Unreal import script and the Codex checklist both read.
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hh_kit  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--preview", help="optional JPEG path for a rendered lineup of all pieces")
    return ap.parse_args(argv)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def build_kit(scene):
    col = bpy.data.collections.new("ShipKit")
    scene.collection.children.link(col)
    built = []
    for make in hh_kit.KIT:
        piece = make()
        mats = list(piece.mats)
        obj, ucx = piece.build(col)
        built.append((obj, ucx, mats))
    return built


def export_piece(obj, ucx, out_dir):
    bpy.ops.object.select_all(action="DESELECT")
    for o in [obj, *ucx]:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obj
    path = os.path.join(out_dir, obj.name + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
    )
    return path


def mesh_stats(obj):
    me = obj.data
    me.calc_loop_triangles()
    xs = [v.co for v in me.vertices]
    mn = [round(min(c[i] for c in xs), 3) for i in range(3)]
    mx = [round(max(c[i] for c in xs), 3) for i in range(3)]
    return len(me.loop_triangles), mn, mx


def render_lineup(built, path):
    scene = bpy.context.scene
    cols = 7
    for i, (obj, ucx, _) in enumerate(built):
        obj.location = ((i % cols) * 5.5, -(i // cols) * 5.5, 0)
        for u in ucx:
            u.hide_render = True
            u.hide_set(True)
    rows = math.ceil(len(built) / cols)
    centre = ((cols - 1) * 5.5 / 2, -(rows - 1) * 5.5 / 2, 0)

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = cols * 5.5 + 2
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (centre[0] + 22, centre[1] - 22, 26)
    direction = cam.location - Vector(centre)
    cam.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("World")
    world.color = (0.05, 0.06, 0.07)
    scene.world = world

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 88
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    scene = reset_scene()
    built = build_kit(scene)

    manifest = {"cell_m": hh_kit.CELL, "storey_m": hh_kit.STOREY, "materials": {}, "pieces": []}
    for name, (color, rough, metal, emit) in hh_kit.MATERIALS.items():
        manifest["materials"][name] = {"base_color": color, "roughness": rough,
                                       "metallic": metal, "emissive": emit}
    for obj, ucx, mats in built:
        export_piece(obj, ucx, out_dir)
        tris, mn, mx = mesh_stats(obj)
        manifest["pieces"].append({
            "name": obj.name, "file": obj.name + ".fbx", "materials": mats,
            "collision_hulls": len(ucx), "triangles": tris, "bounds_min_m": mn, "bounds_max_m": mx,
        })
        print(f"[HH] exported {obj.name}: {tris} tris, {len(ucx)} collision hulls, materials {mats}")

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[HH] kit done: {len(built)} pieces -> {out_dir}")

    if args.preview:
        os.makedirs(os.path.dirname(os.path.abspath(args.preview)), exist_ok=True)
        render_lineup(built, os.path.abspath(args.preview))
        print(f"[HH] preview -> {args.preview}")


if __name__ == "__main__":
    main()
