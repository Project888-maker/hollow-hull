"""Make realistic 3D kit pieces with fal.ai (meshes/models.json).

    python tools/fal_models.py [--only SM_Heart] [--force] [--refit]

Needs Blender's Python module (bpy; `pip install bpy` or Blender's own python) for the
fitting step. For each model: a concept picture (fal-ai/flux/dev) is turned into a
textured model (fal-ai/hunyuan3d/v2), saved raw in meshes/raw/ (not committed), then
fitted: joined, decimated to max_tris, then either stretched to fill the box of the
hand-built piece it replaces ("fit": "piece") or scaled to height_m (and width_m) with
the pivot at its top or bottom; material renamed. Writes meshes/<piece>.glb (geometry + UVs)
and textures/<material>/source.png (the model's colour map); run tools/make_pbr.py
after it. --refit redoes only the fitting from the raw download.

The fal key comes from FAL_KEY or from a proxy that adds it; it is never written.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESHES = os.path.join(ROOT, "meshes")
TEX = os.path.join(ROOT, "textures")


def _req(url, data=None):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("FAL_KEY"):
        headers["Authorization"] = "Key " + os.environ["FAL_KEY"]
    r = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers,
                               method="GET" if data is None else "POST")
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.load(f)


def fal(model, payload):
    sub = _req(f"https://queue.fal.run/{model}", payload)
    while _req(sub["status_url"])["status"] != "COMPLETED":
        time.sleep(4)
    return _req(sub["response_url"])


def download(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, open(path, "wb") as f:
        f.write(r.read())


def generate(name, m, style):
    raw = os.path.join(MESHES, "raw")
    pics = fal("fal-ai/flux/dev", {"prompt": f"{m['prompt']}, {style}", "image_size": "square_hd",
                                   "num_images": m.get("image", 0) + 1, "seed": m.get("seed", 1),
                                   "enable_safety_checker": False})
    url = pics["images"][m.get("image", 0)]["url"]
    download(url, os.path.join(raw, name + "_concept.jpg"))
    print(f"{name}: concept picture ready, building the 3D model")
    model = fal("fal-ai/hunyuan3d/v2", {"input_image_url": url, "textured_mesh": True, "seed": m.get("seed", 1)})
    download(model["model_mesh"]["url"], os.path.join(raw, name + ".glb"))
    print(f"{name}: raw model saved")


def piece_bounds(name):
    """Bounding box of the hand-built kit piece called name (blender/hh_kit.py)."""
    from mathutils import Vector
    sys.path.insert(0, os.path.join(ROOT, "blender"))
    import hh_kit
    for make in hh_kit.PROCEDURAL_KIT:
        p = make()
        if p.name == name:
            xs = [v.co for v in p.bm.verts]
            p.bm.free()
            return (Vector([min(c[i] for c in xs) for i in range(3)]), Vector([max(c[i] for c in xs) for i in range(3)]))
        p.bm.free()
    raise KeyError(name)


def fit(name, m):
    import bpy
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(MESHES, "raw", name + ".glb"))
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # colour map out of the model, before anything is renamed
    img = next(n.image for mat in obj.data.materials for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
    mat_name = m["material"]
    os.makedirs(os.path.join(TEX, mat_name), exist_ok=True)
    img.filepath_raw = os.path.join(TEX, mat_name, "source.png")
    img.file_format = "PNG"
    img.save()

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > m["max_tris"]:
        mod = obj.modifiers.new("decimate", "DECIMATE")
        mod.ratio = m["max_tris"] / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)

    me = obj.data

    def bounds():
        xs = [v.co for v in me.vertices]
        return (Vector([min(c[i] for c in xs) for i in range(3)]), Vector([max(c[i] for c in xs) for i in range(3)]))

    mn, mx = bounds()
    size = mx - mn
    if m.get("fit") == "piece":
        # fill exactly the box of the hand-built piece it replaces, so placements still fit
        tmn, tmx = piece_bounds(name)
        tsize = tmx - tmn
        if (size.x > size.y) != (tsize.x > tsize.y):
            for v in me.vertices:
                v.co = Vector((-v.co.y, v.co.x, v.co.z))
            mn, mx = bounds()
            size = mx - mn
        for v in me.vertices:
            v.co = Vector([tmn[i] + (v.co[i] - mn[i]) / size[i] * tsize[i] for i in range(3)])
    else:
        s = m["height_m"] / size.z
        sxy = m.get("width_m", 0) / max(size.x, size.y) if m.get("width_m") else s
        pivot = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mx.z if m["pivot"] == "top" else mn.z))
        for v in me.vertices:
            d = v.co - pivot
            v.co = Vector((d.x * sxy, d.y * sxy, d.z * s))
    me.materials.clear()
    me.materials.append(bpy.data.materials.new(mat_name))
    for p in me.polygons:
        p.material_index = 0
        p.use_smooth = True
    obj.name = me.name = name
    me.validate()

    # the colour map's material entry, so make_pbr.py and the game pick it up
    tpath = os.path.join(TEX, "materials.json")
    with open(tpath, encoding="utf-8") as f:
        tex = json.load(f)
    if mat_name not in tex["materials"]:
        tex["materials"][mat_name] = {"atlas": True, "tile_m": 2.0, "roughness": m.get("roughness", [0.4, 0.85]),
                                      "bump": 3.0, "metallic": m.get("metallic", 0.0)}
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(tex, f, indent=2)

    out = os.path.join(MESHES, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=out, use_selection=True, export_format="GLB", export_image_format="NONE",
                              export_materials="PLACEHOLDER", export_yup=True)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    print(f"{name}: fitted, {tris} tris, colour map -> textures/{mat_name}/source.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true", help="generate again even if a raw model exists")
    ap.add_argument("--refit", action="store_true", help="only redo the fitting from meshes/raw")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    with open(os.path.join(MESHES, "models.json"), encoding="utf-8") as f:
        spec = json.load(f)
    only = {n for n in args.only.split(",") if n}
    for name, m in spec["models"].items():
        if only and name not in only:
            continue
        raw = os.path.join(MESHES, "raw", name + ".glb")
        if not args.refit and (args.force or not os.path.exists(raw)):
            try:
                generate(name, m, spec["style"])
            except urllib.error.HTTPError as e:
                print(f"{name}: fal refused ({e.code}) {e.read()[:300].decode(errors='replace')}")
                continue
        fit(name, m)


if __name__ == "__main__":
    main()
