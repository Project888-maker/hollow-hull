"""Hollow Hull modular ship kit.

Every piece is built procedurally from boxes, cylinders and convex hulls, so the
whole kit is reproducible from this file alone. Units are Blender metres; the FBX
export converts them to Unreal centimetres.

Grid rules (shared with level/layout.py and unreal/hh_setup.py):
  * one cell = 4 m x 4 m, one storey = 3 m
  * floor/ceiling/water pieces are centred on the cell, top of floor at z = 0
  * wall pieces run along X, centred on the cell edge, thickness along Y
  * pieces are symmetric across Y, because Unreal mirrors Y on FBX import
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

CELL = 4.0
HALF = CELL / 2
STOREY = 3.0
WALL_T = 0.2

# name: (linear base colour, roughness, metallic, emission strength)
# Unreal builds a material instance per entry, named MI_<name without "M_">.
MATERIALS = {
    "M_Steel_Paint": ((0.16, 0.19, 0.17), 0.70, 0.25, 0.0),
    "M_Steel_Dark": ((0.05, 0.055, 0.06), 0.50, 0.90, 0.0),
    "M_Steel_Rust": ((0.22, 0.08, 0.035), 0.80, 0.50, 0.0),
    "M_Wood_Wet": ((0.09, 0.05, 0.028), 0.45, 0.00, 0.0),
    "M_Brass": ((0.55, 0.38, 0.12), 0.35, 1.00, 0.0),
    "M_Fabric": ((0.30, 0.27, 0.20), 0.90, 0.00, 0.0),
    "M_Glass_Ice": ((0.20, 0.35, 0.45), 0.08, 0.00, 0.6),
    "M_Lamp_Glow": ((1.00, 0.62, 0.30), 0.30, 0.00, 12.0),
    "M_Flesh": ((0.12, 0.02, 0.06), 0.25, 0.00, 0.0),
    "M_Flesh_Glow": ((0.25, 0.90, 0.60), 0.30, 0.00, 4.0),
    "M_Water": ((0.02, 0.05, 0.05), 0.04, 0.00, 0.0),
}

UV_METRES_PER_TILE = 2.0


def get_material(name):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    color, rough, metal, emit = MATERIALS[name]
    mat = bpy.data.materials.new(name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit
    mat.diffuse_color = (*color, 1.0)
    return mat


class Piece:
    """Accumulates render geometry and convex collision hulls for one mesh."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.mats = []
        self.hulls = []

    def _mat(self, name):
        if name not in self.mats:
            self.mats.append(name)
        return self.mats.index(name)

    def _tag(self, verts, mat, smooth_axis=None):
        idx = self._mat(mat)
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            f.material_index = idx
            if smooth_axis is not None:
                f.normal_update()
                f.smooth = abs(f.normal.dot(smooth_axis)) < 0.5
        return faces

    # --- render primitives -------------------------------------------------

    def box(self, mn, mx, mat, collide=False):
        mn, mx = Vector(mn), Vector(mx)
        size = mx - mn
        m = Matrix.Translation((mn + mx) / 2) @ Matrix.Diagonal((*size, 1.0))
        verts = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)["verts"]
        self._tag(verts, mat)
        if collide:
            self.collide_box(mn, mx)

    def cyl(self, p0, p1, radius, mat, segments=12, radius2=None):
        """Cylinder (or cone when radius2 is given) from point p0 to point p1."""
        p0, p1 = Vector(p0), Vector(p1)
        axis = p1 - p0
        rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2) @ rot
        verts = bmesh.ops.create_cone(
            self.bm, cap_ends=True, segments=segments, radius1=radius,
            radius2=radius if radius2 is None else radius2,
            depth=axis.length, matrix=m)["verts"]
        self._tag(verts, mat, smooth_axis=axis.normalized())

    def sphere(self, center, radius, mat, scale=(1, 1, 1), segments=12):
        m = Matrix.Translation(center) @ Matrix.Diagonal((*scale, 1.0))
        verts = bmesh.ops.create_uvsphere(
            self.bm, u_segments=segments, v_segments=max(6, segments // 2),
            radius=radius, matrix=m)["verts"]
        faces = self._tag(verts, mat)
        for f in faces:
            f.smooth = True

    def hull(self, points, mat):
        _hull_into(self.bm, points, self._mat(mat))

    # --- collision -----------------------------------------------------------

    def collide_box(self, mn, mx):
        (x0, y0, z0), (x1, y1, z1) = mn, mx
        self.hulls.append([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])

    def collide_hull(self, points):
        self.hulls.append([tuple(p) for p in points])

    # --- output --------------------------------------------------------------

    def build(self, collection):
        bm = self.bm
        bm.normal_update()
        uv = bm.loops.layers.uv.new("UVMap")
        for f in bm.faces:
            axis = max(range(3), key=lambda i: abs(f.normal[i]))
            a, b = [(1, 2), (0, 2), (0, 1)][axis]
            for loop in f.loops:
                co = loop.vert.co
                loop[uv].uv = (co[a] / UV_METRES_PER_TILE, co[b] / UV_METRES_PER_TILE)
        mesh = bpy.data.meshes.new(self.name)
        bm.to_mesh(mesh)
        bm.free()
        for name in self.mats:
            mesh.materials.append(get_material(name))
        obj = bpy.data.objects.new(self.name, mesh)
        collection.objects.link(obj)

        ucx = []
        for i, pts in enumerate(self.hulls):
            hbm = bmesh.new()
            _hull_into(hbm, pts, 0)
            hmesh = bpy.data.meshes.new(f"UCX_{self.name}_{i:02d}")
            hbm.to_mesh(hmesh)
            hbm.free()
            hobj = bpy.data.objects.new(hmesh.name, hmesh)
            hobj.display_type = "WIRE"
            hobj.hide_render = True
            collection.objects.link(hobj)
            ucx.append(hobj)
        return obj, ucx


def _hull_into(bm, points, mat_index):
    verts = [bm.verts.new(p) for p in points]
    res = bmesh.ops.convex_hull(bm, input=verts)
    junk = [g for g in res["geom_interior"] + res["geom_unused"]
            if isinstance(g, bmesh.types.BMVert) and g.is_valid]
    if junk:
        bmesh.ops.delete(bm, geom=junk, context="VERTS")
    for g in res["geom"]:
        if isinstance(g, bmesh.types.BMFace) and g.is_valid:
            g.material_index = mat_index


def _both_sides(fn):
    for s in (1, -1):
        fn(s)


def _span(a, b):
    return (min(a, b), max(a, b))


# ---------------------------------------------------------------------------
# Structural pieces
# ---------------------------------------------------------------------------

def floor_steel():
    p = Piece("SM_Floor_Steel")
    p.box((-HALF, -HALF, -0.1), (HALF, HALF, 0), "M_Steel_Dark", collide=True)
    p.box((-HALF, -0.02, 0), (HALF, 0.02, 0.01), "M_Steel_Rust")
    p.box((-0.02, -HALF, 0), (0.02, HALF, 0.01), "M_Steel_Rust")
    return p


def floor_wood():
    p = Piece("SM_Floor_Wood")
    p.box((-HALF, -HALF, -0.1), (HALF, HALF, -0.03), "M_Steel_Dark")
    plank, gap = 0.2, 0.015
    for i in range(int(CELL / plank)):
        y0 = -HALF + i * plank + gap / 2
        # stagger plank joints so the deck does not read as a grid
        split = -1.0 if i % 2 else 1.0
        p.box((-HALF, y0, -0.03), (split - gap / 2, y0 + plank - gap, 0), "M_Wood_Wet")
        p.box((split + gap / 2, y0, -0.03), (HALF, y0 + plank - gap, 0), "M_Wood_Wet")
    p.collide_box((-HALF, -HALF, -0.1), (HALF, HALF, 0))
    return p


def floor_grate():
    p = Piece("SM_Floor_Grate")
    t = 0.08
    p.box((-HALF, -HALF, -t), (HALF, -HALF + t, 0), "M_Steel_Dark")
    p.box((-HALF, HALF - t, -t), (HALF, HALF, 0), "M_Steel_Dark")
    p.box((-HALF, -HALF, -t), (-HALF + t, HALF, 0), "M_Steel_Dark")
    p.box((HALF - t, -HALF, -t), (HALF, HALF, 0), "M_Steel_Dark")
    y = -HALF + t + 0.06
    while y < HALF - t:
        p.box((-HALF + t, y - 0.0125, -0.06), (HALF - t, y + 0.0125, 0), "M_Steel_Rust")
        y += 0.12
    for x in (-1.0, 0.0, 1.0):
        p.box((x - 0.02, -HALF + t, -0.07), (x + 0.02, HALF - t, -0.005), "M_Steel_Dark")
    for yb in (-1.0, 1.0):
        p.box((-HALF, yb - 0.03, -0.28), (HALF, yb + 0.03, -t), "M_Steel_Dark")
        p.box((-HALF, yb - 0.08, -0.3), (HALF, yb + 0.08, -0.28), "M_Steel_Dark")
    p.collide_box((-HALF, -HALF, -t), (HALF, HALF, 0))
    return p


def ceiling():
    p = Piece("SM_Ceiling")
    p.box((-HALF, -HALF, 0), (HALF, HALF, 0.1), "M_Steel_Paint", collide=True)
    for x in (-1.0, 1.0):
        p.box((x - 0.03, -HALF, -0.25), (x + 0.03, HALF, 0), "M_Steel_Rust")
        p.box((x - 0.08, -HALF, -0.27), (x + 0.08, HALF, -0.25), "M_Steel_Rust")
    return p


def _wall_trim(p, segments):
    """Baseboard, top rail and riveted frames on both faces of the given X spans."""
    t = WALL_T / 2

    def side(s):
        y = _span(s * t, s * (t + 0.03))
        for x0, x1 in segments:
            p.box((x0, y[0], 0), (x1, y[1], 0.2), "M_Steel_Rust")
        p.box((-HALF, y[0], 2.55), (HALF, y[1], 2.65), "M_Steel_Rust")
        fy = _span(s * t, s * (t + 0.06))
        for fx in (-1.0, 1.0):
            if any(x0 <= fx - 0.06 and fx + 0.06 <= x1 for x0, x1 in segments):
                p.box((fx - 0.06, fy[0], 0), (fx + 0.06, fy[1], STOREY), "M_Steel_Rust")

    _both_sides(side)


def wall():
    p = Piece("SM_Wall")
    t = WALL_T / 2
    p.box((-HALF, -t, 0), (HALF, t, STOREY), "M_Steel_Paint")
    _wall_trim(p, [(-HALF, HALF)])
    p.collide_box((-HALF, -t - 0.06, 0), (HALF, t + 0.06, STOREY))
    return p


DOOR_HW, DOOR_H, SILL_H = 0.7, 2.2, 0.12


def wall_door():
    p = Piece("SM_Wall_Door")
    t, c = WALL_T / 2, 0.16
    hw, fw = DOOR_HW, DOOR_HW + 0.12
    p.box((-HALF, -t, 0), (-hw, t, STOREY), "M_Steel_Paint")
    p.box((hw, -t, 0), (HALF, t, STOREY), "M_Steel_Paint")
    p.box((-hw, -t, DOOR_H), (hw, t, STOREY), "M_Steel_Paint")
    # raised bulkhead coaming around the opening
    p.box((-fw, -c, 0), (-hw, c, DOOR_H + 0.12), "M_Steel_Dark")
    p.box((hw, -c, 0), (fw, c, DOOR_H + 0.12), "M_Steel_Dark")
    p.box((-fw, -c, DOOR_H), (fw, c, DOOR_H + 0.12), "M_Steel_Dark")
    p.box((-hw, -c, 0), (hw, c, SILL_H), "M_Steel_Dark")
    _wall_trim(p, [(-HALF, -fw), (fw, HALF)])
    p.collide_box((-HALF, -c, 0), (-hw, c, STOREY))
    p.collide_box((hw, -c, 0), (HALF, c, STOREY))
    p.collide_box((-hw, -c, DOOR_H), (hw, c, STOREY))
    p.collide_box((-hw, -c, 0), (hw, c, SILL_H))
    return p


def wall_porthole():
    p = wall()
    p.name = "SM_Wall_Porthole"
    z = 1.6
    p.cyl((0, -0.15, z), (0, 0.15, z), 0.34, "M_Brass", segments=24)
    p.cyl((0, -0.155, z), (0, 0.155, z), 0.27, "M_Glass_Ice", segments=24)
    for i in range(8):
        a = i * math.tau / 8
        bx, bz = 0.305 * math.cos(a), z + 0.305 * math.sin(a)
        p.cyl((bx, -0.165, bz), (bx, 0.165, bz), 0.018, "M_Steel_Dark", segments=6)
    return p


def pillar():
    p = Piece("SM_Pillar")
    p.box((-0.16, -0.16, 0), (0.16, 0.16, STOREY), "M_Steel_Dark", collide=True)
    for z in (0.3, 2.7):
        p.box((-0.19, -0.19, z - 0.05), (0.19, 0.19, z + 0.05), "M_Steel_Rust")
    return p


STEPS = 12
STAIR_HW = 0.75


def stairs():
    """Rises one storey along +X across a full cell (bottom at x=-2, top at x=+2)."""
    p = Piece("SM_Stairs")
    run = CELL / STEPS
    rise = STOREY / STEPS
    for i in range(STEPS):
        x0 = -HALF + i * run
        z = (i + 1) * rise
        p.box((x0, -STAIR_HW, z - 0.05), (x0 + run + 0.02, STAIR_HW, z), "M_Steel_Rust")

    def stringer(s):
        y0, y1 = _span(s * STAIR_HW, s * (STAIR_HW + 0.06))
        pts = []
        for y in (y0, y1):
            pts += [(-HALF, y, 0), (-HALF, y, 0.35), (HALF, y, STOREY - 0.3), (HALF, y, STOREY)]
        p.hull(pts, "M_Steel_Dark")
        # handrail posts and rail following the slope
        yr = s * (STAIR_HW + 0.03)
        posts = (-1.8, 0.0, 1.8)
        for x in posts:
            zb = (x + HALF) / CELL * STOREY
            p.cyl((x, yr, zb), (x, yr, zb + 1.0), 0.025, "M_Steel_Dark", segments=8)
        za, zb = (posts[0] + HALF) / CELL * STOREY + 1.0, (posts[-1] + HALF) / CELL * STOREY + 1.0
        p.cyl((posts[0], yr, za), (posts[-1], yr, zb), 0.03, "M_Brass", segments=8)

    _both_sides(stringer)
    w = STAIR_HW + 0.06
    p.collide_hull([(-HALF, y, 0) for y in (-w, w)] + [(HALF, y, 0) for y in (-w, w)]
                   + [(HALF, y, STOREY) for y in (-w, w)])
    return p


def railing():
    p = Piece("SM_Railing")
    for x in (-1.95, -1.0, 0.0, 1.0, 1.95):
        p.cyl((x, 0, 0), (x, 0, 1.05), 0.025, "M_Steel_Dark", segments=8)
    p.cyl((-HALF, 0, 1.05), (HALF, 0, 1.05), 0.03, "M_Brass", segments=8)
    p.cyl((-HALF, 0, 0.55), (HALF, 0, 0.55), 0.02, "M_Steel_Dark", segments=8)
    p.collide_box((-HALF, -0.05, 0), (HALF, 0.05, 1.1))
    return p


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------

def pipe_straight():
    p = Piece("SM_Pipe_Straight")
    p.cyl((-HALF, 0, 0), (HALF, 0, 0), 0.12, "M_Steel_Rust", segments=16)
    for x in (-1.95, 1.95):
        p.cyl((x - 0.03, 0, 0), (x + 0.03, 0, 0), 0.17, "M_Steel_Dark", segments=16)
    p.collide_box((-HALF, -0.17, -0.17), (HALF, 0.17, 0.17))
    return p


def pipe_vertical():
    p = Piece("SM_Pipe_Vertical")
    p.cyl((0, 0, 0), (0, 0, STOREY), 0.12, "M_Steel_Rust", segments=16)
    for z in (0.05, STOREY - 0.05):
        p.cyl((0, 0, z - 0.03), (0, 0, z + 0.03), 0.17, "M_Steel_Dark", segments=16)
    p.box((-0.2, -0.04, 1.45), (0.2, 0.04, 1.55), "M_Steel_Dark")
    p.collide_box((-0.17, -0.17, 0), (0.17, 0.17, STOREY))
    return p


def _wheel(p, center, radius):
    cx, cy, cz = center
    n = 16
    pts = []
    for i in range(n):
        a = i * math.tau / n
        pts.append((cx + radius * math.cos(a), cy, cz + radius * math.sin(a)))
    for i in range(n):
        p.cyl(pts[i], pts[(i + 1) % n], 0.022, "M_Brass", segments=6)
    for i in range(0, n, 4):
        p.cyl((cx, cy, cz), pts[i], 0.015, "M_Brass", segments=6)
    p.cyl((cx, cy - 0.05, cz), (cx, cy + 0.05, cz), 0.05, "M_Steel_Dark", segments=10)


def valve_wheel():
    p = Piece("SM_Valve_Wheel")
    _wheel(p, (0, 0, 0), 0.25)
    p.cyl((0, -0.2, 0), (0, 0.2, 0), 0.02, "M_Steel_Dark", segments=8)
    return p


def crate():
    p = Piece("SM_Crate")
    p.box((-0.47, -0.47, 0.03), (0.47, 0.47, 0.97), "M_Wood_Wet")
    e = 0.05
    for z0, z1 in ((0, e), (1 - e, 1)):
        p.box((-0.5, -0.5, z0), (0.5, -0.5 + e, z1), "M_Steel_Dark")
        p.box((-0.5, 0.5 - e, z0), (0.5, 0.5, z1), "M_Steel_Dark")
        p.box((-0.5, -0.5, z0), (-0.5 + e, 0.5, z1), "M_Steel_Dark")
        p.box((0.5 - e, -0.5, z0), (0.5, 0.5, z1), "M_Steel_Dark")
    for x in (-0.5, 0.5 - e):
        for y in (-0.5, 0.5 - e):
            p.box((x, y, 0), (x + e, y + e, 1), "M_Steel_Dark")
    p.collide_box((-0.5, -0.5, 0), (0.5, 0.5, 1))
    return p


def barrel():
    p = Piece("SM_Barrel")
    p.cyl((0, 0, 0), (0, 0, 0.9), 0.3, "M_Steel_Rust", segments=18)
    for z in (0.15, 0.75):
        p.cyl((0, 0, z - 0.02), (0, 0, z + 0.02), 0.315, "M_Steel_Dark", segments=18)
    p.collide_hull([(0.31 * math.cos(a), 0.31 * math.sin(a), z)
                    for a in (i * math.tau / 8 for i in range(8)) for z in (0, 0.9)])
    return p


def bunk():
    p = Piece("SM_Bunk")
    for x in (-0.95, 0.9):
        for y in (-0.42, 0.37):
            p.box((x, y, 0), (x + 0.05, y + 0.05, 1.8), "M_Steel_Dark")
    for h in (0.4, 1.35):
        p.box((-0.95, -0.42, h - 0.05), (0.95, 0.42, h), "M_Steel_Dark")
        p.box((-0.9, -0.38, h), (0.9, 0.38, h + 0.14), "M_Fabric")
        p.box((-0.85, -0.3, h + 0.14), (-0.5, 0.3, h + 0.22), "M_Fabric")
    p.collide_box((-0.97, -0.44, 0), (0.97, 0.44, 1.8))
    return p


def lamp_cage():
    """Hangs from the ceiling: pivot at the mounting plate, body below z=0."""
    p = Piece("SM_Lamp_Cage")
    p.cyl((0, 0, -0.04), (0, 0, 0), 0.1, "M_Brass", segments=12)
    p.cyl((0, 0, -0.3), (0, 0, -0.04), 0.012, "M_Steel_Dark", segments=6)
    p.cyl((0, 0, -0.38), (0, 0, -0.3), 0.14, "M_Brass", segments=12, radius2=0.05)
    p.sphere((0, 0, -0.45), 0.07, "M_Lamp_Glow")
    for i in range(4):
        a = i * math.tau / 4 + math.pi / 4
        x, y = 0.1 * math.cos(a), 0.1 * math.sin(a)
        p.cyl((x, y, -0.56), (x, y, -0.38), 0.008, "M_Steel_Dark", segments=5)
    p.cyl((0, 0, -0.57), (0, 0, -0.55), 0.105, "M_Steel_Dark", segments=12)
    return p


def boiler():
    p = Piece("SM_Boiler")
    r, hl, zc = 1.3, 1.75, 1.55
    p.cyl((-hl, 0, zc), (hl, 0, zc), r, "M_Steel_Dark", segments=28)
    for x in (-1.5, -0.5, 0.5, 1.5):
        p.cyl((x - 0.04, 0, zc), (x + 0.04, 0, zc), r + 0.04, "M_Steel_Rust", segments=28)
    p.box((hl, -0.4, 0.9), (hl + 0.07, 0.4, 1.6), "M_Steel_Rust")
    p.box((hl + 0.07, 0.25, 1.2), (hl + 0.15, 0.32, 1.3), "M_Brass")
    for x in (-1.1, 1.1):
        p.box((x - 0.15, -1.0, 0), (x + 0.15, 1.0, 0.7), "M_Steel_Rust")
    p.cyl((0.8, 0, zc + r - 0.1), (0.8, 0, 2 * STOREY), 0.2, "M_Steel_Rust", segments=16)
    for y in (-0.6, 0.6):
        p.cyl((hl + 0.05, y, 2.2), (hl + 0.12, y, 2.2), 0.09, "M_Brass", segments=12)
    ring = [(r + 0.02) * Vector((0, math.cos(a), math.sin(a))) for a in (i * math.tau / 8 for i in range(8))]
    p.collide_hull([(x, v.y, zc + v.z) for v in ring for x in (-hl, hl)])
    p.collide_box((-1.25, -1.0, 0), (1.25, 1.0, 0.7))
    return p


def door_bulkhead():
    p = Piece("SM_Door_Bulkhead")
    p.box((-DOOR_HW, -0.05, SILL_H), (DOOR_HW, 0.05, DOOR_H), "M_Steel_Paint", collide=True)
    for s in (1, -1):
        _wheel(p, (0, s * 0.1, 1.2), 0.2)
        y0, y1 = _span(s * 0.05, s * 0.09)
        for x in (-0.6, 0.6):
            for z in (0.5, 1.9):
                p.box((x - 0.04, y0, z - 0.03), (x + 0.04, y1, z + 0.03), "M_Steel_Rust")
    return p


def growth():
    """Corruption cluster: wet flesh lumps, glowing pustules, creeping tendrils."""
    p = Piece("SM_Growth")
    rng = random.Random(7)
    for _ in range(9):
        a, d = rng.uniform(0, math.tau), rng.uniform(0, 0.6)
        s = rng.uniform(0.18, 0.4)
        p.sphere((d * math.cos(a), d * math.sin(a), s * 0.4), s, "M_Flesh",
                 scale=(1, rng.uniform(0.7, 1.3), rng.uniform(0.5, 0.9)))
    for _ in range(6):
        a, d = rng.uniform(0, math.tau), rng.uniform(0.1, 0.7)
        p.sphere((d * math.cos(a), d * math.sin(a), rng.uniform(0.15, 0.35)), 0.06, "M_Flesh_Glow", segments=8)
    for _ in range(5):
        a = rng.uniform(0, math.tau)
        pts = [Vector((0, 0, 0.05))]
        for k in range(1, 4):
            a += rng.uniform(-0.5, 0.5)
            pts.append(Vector((k * 0.4 * math.cos(a), k * 0.4 * math.sin(a), 0.04)))
        for k in range(3):
            p.cyl(pts[k], pts[k + 1], 0.06 - k * 0.015, "M_Flesh", segments=8, radius2=0.05 - k * 0.015)
    return p


def water_tile():
    p = Piece("SM_Water_Tile")
    n = 8
    bm = p.bm
    verts = [[bm.verts.new((-HALF + i * CELL / n, -HALF + j * CELL / n, 0)) for j in range(n + 1)]
             for i in range(n + 1)]
    idx = p._mat("M_Water")
    for i in range(n):
        for j in range(n):
            f = bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
            f.material_index = idx
    return p


KIT = [
    floor_steel, floor_wood, floor_grate, ceiling,
    wall, wall_door, wall_porthole, pillar, stairs, railing,
    pipe_straight, pipe_vertical, valve_wheel, crate, barrel, bunk,
    lamp_cage, boiler, door_bulkhead, growth, water_tile,
]
