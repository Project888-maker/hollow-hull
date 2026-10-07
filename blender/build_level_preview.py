"""Assemble the level in Blender from level/placements.json and render previews.

    blender --background --factory-startup --python build_level_preview.py -- \
        --placements ../level/placements.json --out ../preview [--save ../preview/level.blend]

Renders a top-down cutaway (no ceilings) and first-person views, so the layout
can be checked without opening Unreal. Unreal mirrors Y relative to Blender, so
Unreal (x, y, yaw) becomes Blender (x, -y, -yaw) here.
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
    ap.add_argument("--placements", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--save", help="optional .blend path to save the assembled level")
    ap.add_argument("--samples", type=int, default=32)
    return ap.parse_args(argv)


def ue_to_blender(x, y, z):
    return Vector((x / 100.0, -y / 100.0, z / 100.0))


def assemble(data):
    scene = bpy.context.scene
    kit_col = bpy.data.collections.new("Kit")
    scene.collection.children.link(kit_col)
    kit = {}
    for make in hh_kit.KIT:
        obj, ucx = make().build(kit_col)
        kit[obj.name] = obj
    kit_col.hide_render = True
    bpy.context.view_layer.layer_collection.children["Kit"].exclude = True

    level_col = bpy.data.collections.new("Level")
    scene.collection.children.link(level_col)
    by_tag = {}
    for i, m in enumerate(data["meshes"]):
        src = kit[m["mesh"]]
        obj = bpy.data.objects.new(f"{m['mesh']}_{i:04d}", src.data)
        obj.location = ue_to_blender(m["x"], m["y"], m["z"])
        obj.rotation_euler = (0, 0, math.radians(-m["yaw"]))
        level_col.objects.link(obj)
        by_tag.setdefault(m["tag"], []).append(obj)

    for i, li in enumerate(data["lights"]):
        ld = bpy.data.lights.new(f"Lamp_{i:02d}", "POINT")
        ld.color = li["color"]
        ld.energy = li["intensity_cd"] * 12.0
        ld.shadow_soft_size = 0.1
        lo = bpy.data.objects.new(ld.name, ld)
        lo.location = ue_to_blender(li["x"], li["y"], li["z"])
        level_col.objects.link(lo)
    return by_tag


def make_camera(name, loc, target, lens=18, ortho_scale=None):
    cd = bpy.data.cameras.new(name)
    if ortho_scale:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho_scale
    else:
        cd.lens = lens
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    cam.rotation_euler = (cam.location - Vector(target)).to_track_quat("Z", "Y").to_euler()
    return cam


def render(cam, path, res=(1600, 900)):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print(f"[HH] preview -> {path}")


def main():
    args = parse_args()
    with open(args.placements) as f:
        data = json.load(f)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 88
    world = bpy.data.worlds.new("World")
    world.color = (0.0, 0.0, 0.0)
    scene.world = world
    os.makedirs(args.out, exist_ok=True)

    by_tag = assemble(data)
    bmin, bmax = data["bounds"]["min"], data["bounds"]["max"]
    centre = ue_to_blender((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, 0)
    span = max(bmax[0] - bmin[0], bmax[1] - bmin[1]) / 100.0

    # 1) top-down cutaway: hide ceilings, add a soft fill so the layout reads
    for o in by_tag.get("ceiling", []):
        o.hide_render = True
    world.color = (0.25, 0.25, 0.28)
    top = make_camera("TopCam", centre + Vector((0, 0, 40)), centre, ortho_scale=span * 1.05)
    render(top, os.path.join(args.out, "level_topdown.jpg"), res=(1100, 1400))

    # 2) first-person shots with ceilings back and only the level lamps
    for o in by_tag.get("ceiling", []):
        o.hide_render = False
    world.color = (0.004, 0.005, 0.007)
    ps = data["player_start"]
    eye = ue_to_blender(ps["x"], ps["y"], 170)
    shots = [
        ("view_cabin.jpg", eye, eye + Vector((10, 0, -0.5))),
        ("view_engine_room.jpg", ue_to_blender(2400, 1450, 170), ue_to_blender(2100, 2600, 80)),
        ("view_engine_mezzanine.jpg", ue_to_blender(1320, 2400, 470), ue_to_blender(2500, 1700, 250)),
        ("view_hold.jpg", ue_to_blender(3600, 3880, 170), ue_to_blender(3200, 4900, 100)),
    ]
    for name, loc, target in shots:
        render(make_camera(name, loc, target, lens=16), os.path.join(args.out, name))

    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))
        print(f"[HH] saved {args.save}")


if __name__ == "__main__":
    main()
