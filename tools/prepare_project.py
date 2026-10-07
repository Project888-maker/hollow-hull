"""Create (or patch) the HollowHull Unreal project.

New project from Epic's Third Person Blueprint template:
    python prepare_project.py --engine "C:/Program Files/Epic Games/UE_5.7" --dest "C:/Projects/HollowHull"

Patch a project you already made in the launcher:
    python prepare_project.py --existing "C:/Projects/HollowHull/HollowHull.uproject"

Either way it enables the Python and Editor Scripting plugins and makes
L_FloodedDeck the startup map. Plain Python 3, no Unreal needed.
"""

import argparse
import json
import os
import re
import shutil
import sys

PLUGINS = ["PythonScriptPlugin", "EditorScriptingUtilities"]
MAP = "/Game/HollowHull/Maps/L_FloodedDeck.L_FloodedDeck"
TEMPLATE_NAMES = ["TP_ThirdPersonBP", "TP_ThirdPerson"]


def find_template(engine):
    for name in TEMPLATE_NAMES:
        path = os.path.join(engine, "Templates", name)
        if os.path.isdir(path):
            return path, name
    raise SystemExit(f"no Third Person template under {engine}/Templates (looked for {TEMPLATE_NAMES})")


def copy_template(engine, dest):
    src, name = find_template(engine)
    if os.path.exists(dest) and os.listdir(dest):
        raise SystemExit(f"{dest} already exists and is not empty; use --existing to patch it")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("Media", "Binaries", "Intermediate",
                                                             "Saved", "DerivedDataCache", "TemplateDefs.ini"))
    old = os.path.join(dest, name + ".uproject")
    new = os.path.join(dest, "HollowHull.uproject")
    if not os.path.exists(old):
        found = [f for f in os.listdir(dest) if f.endswith(".uproject")]
        if not found:
            raise SystemExit(f"template at {src} has no .uproject")
        old = os.path.join(dest, found[0])
    os.rename(old, new)
    print(f"[HH] copied {src} -> {dest}")
    return new


def enable_plugins(uproject):
    with open(uproject, encoding="utf-8-sig") as f:
        data = json.load(f)
    plugins = data.setdefault("Plugins", [])
    for name in PLUGINS:
        entry = next((p for p in plugins if p.get("Name") == name), None)
        if entry:
            entry["Enabled"] = True
        else:
            plugins.append({"Name": name, "Enabled": True})
    with open(uproject, "w", encoding="utf-8") as f:
        json.dump(data, f, indent="\t")
    print(f"[HH] plugins enabled: {', '.join(PLUGINS)}")


def set_startup_map(project_dir):
    ini = os.path.join(project_dir, "Config", "DefaultEngine.ini")
    text = open(ini, encoding="utf-8-sig").read() if os.path.exists(ini) else ""
    section = "[/Script/EngineSettings.GameMapsSettings]"
    keys = {"EditorStartupMap": MAP, "GameDefaultMap": MAP}
    if section in text:
        start = text.index(section) + len(section)
        nxt = text.find("\n[", start)
        end = len(text) if nxt == -1 else nxt
        body = text[start:end]
        for k, v in keys.items():
            if re.search(rf"^{k}=", body, flags=re.M):
                body = re.sub(rf"^{k}=.*$", f"{k}={v}", body, flags=re.M)
            else:
                body = body.rstrip("\n") + f"\n{k}={v}\n"
        text = text[:start] + body + text[end:]
    else:
        text = text.rstrip("\n") + f"\n\n{section}\n" + "".join(f"{k}={v}\n" for k, v in keys.items())
    os.makedirs(os.path.dirname(ini), exist_ok=True)
    with open(ini, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[HH] startup map -> {MAP}")


def main(argv):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dest", help="folder for a new project (needs --engine)")
    g.add_argument("--existing", help="path to an existing .uproject to patch")
    ap.add_argument("--engine", help="Unreal install root, e.g. C:/Program Files/Epic Games/UE_5.7")
    args = ap.parse_args(argv)

    if args.dest:
        if not args.engine:
            ap.error("--dest needs --engine")
        uproject = copy_template(args.engine, args.dest)
    else:
        uproject = args.existing
    enable_plugins(uproject)
    set_startup_map(os.path.dirname(os.path.abspath(uproject)))
    print(f"[HH] project ready: {os.path.abspath(uproject)}")


if __name__ == "__main__":
    main(sys.argv[1:])
