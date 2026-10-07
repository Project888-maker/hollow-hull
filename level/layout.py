"""Turn a grid map (flooded_deck.json) into exact mesh/light placements.

Pure Python, no Blender or Unreal needed:
    python layout.py flooded_deck.json placements.json

All output coordinates are Unreal units: centimetres, Z up, yaw in degrees
(0 = +X/east, 90 = +Y/south). Both unreal/hh_setup.py and
blender/build_level_preview.py read placements.json, so the Blender preview
and the Unreal level always match.
"""

import json
import sys

DIRS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
YAW = {"E": 0, "S": 90, "W": 180, "N": 270}
LAMP_DROP_CM = 50


class Grid:
    def __init__(self, spec):
        self.spec = spec
        self.cell = spec["cell_cm"]
        self.storey = spec["storey_cm"]
        self.cells = {}
        for r, row in enumerate(spec["map"]):
            for c, ch in enumerate(row):
                if ch != ".":
                    self.cells[(c, r)] = ch

    def zone(self, cell):
        ch = self.cells.get(cell)
        return self.spec["zones"][ch] if ch else None

    def storeys(self, cell):
        z = self.zone(cell)
        return z["storeys"] if z else 0

    def centre(self, cell):
        return cell[0] * self.cell, cell[1] * self.cell

    def edge(self, cell, d):
        """Canonical key for the edge on side d of cell: ('h'|'v', c, r)."""
        c, r = cell
        return {"N": ("h", c, r), "S": ("h", c, r + 1), "W": ("v", c, r), "E": ("v", c + 1, r)}[d]

    def edge_pos(self, key):
        kind, c, r = key
        h = self.cell / 2
        return (c * self.cell, r * self.cell - h) if kind == "h" else (c * self.cell - h, r * self.cell)

    def edge_corners(self, key):
        kind, c, r = key
        h = self.cell / 2
        if kind == "h":
            y = r * self.cell - h
            return [(c * self.cell - h, y), (c * self.cell + h, y)]
        x = c * self.cell - h
        return [(x, r * self.cell - h), (x, r * self.cell + h)]


def neighbour(cell, d):
    dx, dy = DIRS[d]
    return cell[0] + dx, cell[1] + dy


def direction_between(a, b):
    for d, (dx, dy) in DIRS.items():
        if (a[0] + dx, a[1] + dy) == tuple(b):
            return d
    raise ValueError(f"cells {a} and {b} are not adjacent")


def build(spec):
    g = Grid(spec)
    meshes, lights = [], []

    def put(mesh, x, y, z, yaw=0, collision=True, tag=""):
        meshes.append({"mesh": mesh, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                       "yaw": yaw % 360, "collision": collision, "tag": tag})

    doors = set()
    for a, b in spec["doors"]:
        a, b = tuple(a), tuple(b)
        for cell in (a, b):
            if cell not in g.cells:
                raise ValueError(f"door cell {cell} is empty in the map")
        doors.add(g.edge(a, direction_between(a, b)))
    sealed = {g.edge(tuple(cell), d) for cell, d in spec.get("sealed_doors", [])}

    stair_cells, stair_arrivals = {}, set()
    for s in spec.get("stairs", []):
        cell = tuple(s["cell"])
        stair_cells[cell] = s["up"]
        stair_arrivals.add(g.edge(cell, s["up"]))

    # floors, ceilings, mezzanines, water
    for cell, ch in sorted(g.cells.items()):
        z = g.zone(cell)
        x, y = g.centre(cell)
        put(z["floor"], x, y, 0, tag="floor")
        put("SM_Ceiling", x, y, z["storeys"] * g.storey, tag="ceiling")
        if z.get("mezzanine"):
            put("SM_Floor_Grate", x, y, g.storey, tag="mezzanine")
        if z.get("water_cm"):
            put("SM_Water_Tile", x, y, z["water_cm"], collision=False, tag="water")
        if cell in stair_cells:
            put("SM_Stairs", x, y, 0, YAW[stair_cells[cell]], tag="stairs")

    # walls: one stack per edge where the zone changes or the hull ends
    walls = {}
    for cell in g.cells:
        for d in DIRS:
            key = g.edge(cell, d)
            if key in walls:
                continue
            other = neighbour(cell, d)
            if g.cells.get(other) and g.zone(other)["id"] == g.zone(cell)["id"]:
                continue
            walls[key] = (cell, d, other)

    corners = set()
    for key, (cell, d, other) in sorted(walls.items()):
        ex, ey = g.edge_pos(key)
        yaw = 0 if key[0] == "h" else 90
        exterior = other not in g.cells
        zone = g.zone(cell)
        for k in range(max(g.storeys(cell), g.storeys(other))):
            zb = k * g.storey
            if k == 0 and (key in doors or key in sealed):
                put("SM_Wall_Door", ex, ey, zb, yaw, tag="door")
                if key in sealed:
                    put("SM_Door_Bulkhead", ex, ey, zb, yaw, tag="sealed_door")
            elif k == 0 and exterior and zone["portholes"] and (cell[0] + cell[1]) % 2:
                put("SM_Wall_Porthole", ex, ey, zb, yaw, tag="wall")
            else:
                put("SM_Wall", ex, ey, zb, yaw, tag="wall")
            for corner in g.edge_corners(key):
                corners.add((corner, k))
    for (cx, cy), k in sorted(corners):
        put("SM_Pillar", cx, cy, k * g.storey, tag="pillar")

    # railings on mezzanine edges that overlook the open engine floor
    for cell, ch in g.cells.items():
        if not g.zone(cell).get("mezzanine"):
            continue
        for d in DIRS:
            other = neighbour(cell, d)
            oz = g.zone(other)
            key = g.edge(cell, d)
            if oz and oz["id"] == g.zone(cell)["id"] and not oz.get("mezzanine") and key not in stair_arrivals:
                ex, ey = g.edge_pos(key)
                put("SM_Railing", ex, ey, g.storey, 0 if key[0] == "h" else 90, tag="railing")

    # lamps on a checkerboard (plus the first cell of any zone the pattern
    # misses); under a mezzanine they hang from the grate
    lit_zones = {g.zone(c)["id"] for c in g.cells if not (c[0] + c[1]) % 2}
    for cell in sorted(g.cells):
        zid = g.zone(cell)["id"]
        if (cell[0] + cell[1]) % 2 and zid in lit_zones:
            continue
        lit_zones.add(zid)
        z = g.zone(cell)
        x, y = g.centre(cell)
        top = g.storey if z.get("mezzanine") else z["storeys"] * g.storey
        top -= 8 if z.get("mezzanine") else 0
        put("SM_Lamp_Cage", x, y, top, collision=False, tag="lamp")
        lights.append({"x": x, "y": y, "z": top - LAMP_DROP_CM, "color": z["light"],
                       "intensity_cd": z["lamp_cd"], "radius_cm": 900 if z["storeys"] == 1 else 1400,
                       "zone": z["id"]})

    for p in spec.get("props", []):
        x, y = g.centre(tuple(p["cell"]))
        dx, dy, dz = p.get("offset", (0, 0, 0))
        put(p["mesh"], x + dx, y + dy, dz, p.get("yaw", 0), p.get("collision", True), tag="prop")

    ps = spec["player_start"]
    x, y = g.centre(tuple(ps["cell"]))
    dx, dy, dz = ps.get("offset", (0, 0, 100))

    zones = {}
    for cell in g.cells:
        z = g.zone(cell)
        x0, y0 = g.centre(cell)
        h = g.cell / 2
        b = zones.setdefault(z["id"], {"min": [x0 - h, y0 - h, 0], "max": [x0 + h, y0 + h, 0]})
        b["min"] = [min(b["min"][0], x0 - h), min(b["min"][1], y0 - h), 0]
        b["max"] = [max(b["max"][0], x0 + h), max(b["max"][1], y0 + h), z["storeys"] * g.storey]

    xs = [m["x"] for m in meshes]
    ys = [m["y"] for m in meshes]
    return {
        "level": spec["level"],
        "meshes": meshes,
        "lights": lights,
        "player_start": {"x": x + dx, "y": y + dy, "z": dz, "yaw": ps.get("yaw", 0)},
        "zones": zones,
        "bounds": {"min": [min(xs) - 200, min(ys) - 200, -50],
                   "max": [max(xs) + 200, max(ys) + 200, 2 * g.storey + 50]},
    }


def main(src, dst):
    with open(src) as f:
        spec = json.load(f)
    out = build(spec)
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    counts = {}
    for m in out["meshes"]:
        counts[m["mesh"]] = counts.get(m["mesh"], 0) + 1
    print(f"[HH] {len(out['meshes'])} meshes, {len(out['lights'])} lights -> {dst}")
    for name, n in sorted(counts.items()):
        print(f"[HH]   {name}: {n}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
