"""Ask fal.ai for a realistic surface picture per material (textures/materials.json).

    FAL_KEY=... python tools/fal_textures.py [--only M_Bone,M_Flesh] [--force] [--model fal-ai/flux/dev]

Saves textures/<material>/source.png (skipped when it already exists, unless --force),
then run tools/make_pbr.py to make the colour, bump and shine maps from it.
Plain Python 3, no extra packages. The key is read from the FAL_KEY environment
variable and never written anywhere. Without FAL_KEY the request goes out with no
key, for setups where a proxy adds the Authorization header itself.
"""

import argparse
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX = os.path.join(ROOT, "textures")


def call(model, payload, key):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Key {key}"
    req = urllib.request.Request(f"https://fal.run/{model}", data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--model", default="fal-ai/flux/dev")
    args = ap.parse_args()
    key = os.environ.get("FAL_KEY")
    with open(os.path.join(TEX, "materials.json"), encoding="utf-8") as f:
        spec = json.load(f)
    only = {n for n in args.only.split(",") if n}
    for i, (name, m) in enumerate(spec["materials"].items()):
        if (only and name not in only) or m.get("atlas"):
            continue
        out = os.path.join(TEX, name, "source.png")
        if os.path.exists(out) and not args.force:
            print(f"{name}: already has source.png")
            continue
        payload = {"prompt": f"{m['prompt']}, {m.get('style', spec['style'])}", "image_size": "square_hd", "num_images": 1,
                   "seed": m.get("seed", 1000 + i), "num_inference_steps": 32, "enable_safety_checker": False}
        try:
            result = call(args.model, payload, key)
        except urllib.error.HTTPError as e:
            print(f"{name}: fal refused ({e.code}) {e.read()[:300].decode(errors='replace')}")
            continue
        url = result["images"][0]["url"]
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(out, "wb") as f:
            f.write(r.read())
        print(f"{name}: saved {out}")


if __name__ == "__main__":
    main()
