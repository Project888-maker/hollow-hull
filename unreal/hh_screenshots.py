"""Capture the four review shots of L_FloodedDeck from inside the Unreal editor.

Run after hh_setup.py, with L_FloodedDeck open (Tools > Execute Python Script).
Same viewpoints as blender/build_level_preview.py so the two can be compared.
Shots are taken one at a time on editor ticks, waiting for Lumen to settle;
files land in <Project>/Saved/Screenshots/<Platform>/HH_*.png.
"""

import unreal

# (name, camera location, look-at target) in Unreal centimetres
SHOTS = [
    ("HH_cabin", (-40, 60, 170), (960, 60, 120)),
    ("HH_engine_room", (2400, 1450, 170), (2100, 2600, 80)),
    ("HH_engine_mezzanine", (1320, 2400, 470), (2500, 1700, 250)),
    ("HH_hold", (3600, 3880, 170), (3200, 4900, 100)),
]
SETTLE_TICKS = 90
TAG = "HH_ShotCam"

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
state = {"i": 0, "wait": SETTLE_TICKS, "cams": [], "handle": None}

for name, loc, target in SHOTS:
    loc_v, tgt_v = unreal.Vector(*loc), unreal.Vector(*target)
    rot = unreal.MathLibrary.find_look_at_rotation(loc_v, tgt_v)
    cam = eas.spawn_actor_from_class(unreal.CameraActor, loc_v, rot)
    cam.set_editor_property("tags", [unreal.Name(TAG)])
    cam.camera_component.set_editor_property("field_of_view", 90.0)
    state["cams"].append((name, cam))


def _tick(_dt):
    if state["wait"] > 0:
        state["wait"] -= 1
        return
    if state["i"] >= len(state["cams"]):
        unreal.unregister_slate_post_tick_callback(state["handle"])
        for _, cam in state["cams"]:
            eas.destroy_actor(cam)
        unreal.log("[HH] screenshots done -> Saved/Screenshots")
        return
    name, cam = state["cams"][state["i"]]
    unreal.AutomationLibrary.take_high_res_screenshot(1920, 1080, name + ".png", camera=cam)
    unreal.log(f"[HH] screenshot requested: {name}")
    state["i"] += 1
    state["wait"] = SETTLE_TICKS


state["handle"] = unreal.register_slate_post_tick_callback(_tick)
