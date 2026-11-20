"""Parametric model: a list of features that is rebuilt into one solid.

This module has no GUI dependency so it can be tested on its own.
"""
from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from build123d import (
    Align,
    Axis,
    Box,
    Circle,
    Cone,
    Cylinder,
    GeomType,
    Part,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    RectangleRounded,
    RegularPolygon,
    Rot,
    SlotCenterToCenter,
    SlotOverall,
    Sphere,
    Text,
    Torus,
    Vector,
    chamfer,
    extrude,
    fillet,
    import_step,
    mirror,
    offset,
)

PROJECT_VERSION = 1
BED = (Align.CENTER, Align.CENTER, Align.MIN)  # sit objects on the print bed


# ---------------------------------------------------------------------------
# Parameter / feature type definitions
# ---------------------------------------------------------------------------

@dataclass
class Param:
    key: str
    label: str
    kind: str = "float"  # float | int | choice | str | bool | file | hidden
    default: Any = 0.0
    min: float = -10000.0
    max: float = 10000.0
    step: float = 1.0
    suffix: str = " mm"
    choices: list[tuple[str, str]] | None = None  # (value, label)
    group: str = "Shape"


@dataclass
class FeatureType:
    type_id: str
    label: str
    category: str  # "body" (placed tool solid), "modify" (changes the part),
    #                "sketch" (2D profiles), "op" (uses other features via ctx)
    params: list[Param]
    build: Callable
    icon: str = "■"


MODE_CHOICES = [("add", "Add (union)"), ("cut", "Cut"), ("intersect", "Intersect")]
EDGE_CHOICES = [
    ("picked", "Picked"),
    ("all", "All edges"),
    ("top", "Top edges"),
    ("bottom", "Bottom edges"),
    ("vertical", "Vertical edges"),
    ("horizontal", "Horizontal edges"),
]
PATTERN_CHOICES = [
    ("none", "None"),
    ("linear", "Row (X)"),
    ("grid", "Grid (X×Y)"),
    ("circular", "Circular (around Z)"),
]


def _dim(key, label, default, mn=0.1, mx=5000.0, step=1.0):
    return Param(key, label, "float", default, mn, mx, step)


def placement_params() -> list[Param]:
    g = "Position"
    g2 = "Pattern"
    return [
        Param("mode", "Operation", "choice", "add", choices=MODE_CHOICES, group="Operation"),
        Param("x", "X", "float", 0.0, group=g),
        Param("y", "Y", "float", 0.0, group=g),
        Param("z", "Z", "float", 0.0, group=g),
        Param("rx", "Rotate X", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("ry", "Rotate Y", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("rz", "Rotate Z", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("pattern", "Type", "choice", "none", choices=PATTERN_CHOICES, group=g2),
        Param("count_x", "Count (X / around)", "int", 3, 1, 500, 1, "", group=g2),
        Param("count_y", "Count (Y)", "int", 2, 1, 500, 1, "", group=g2),
        Param("spacing_x", "Spacing X", "float", 20.0, -5000, 5000, 1, group=g2),
        Param("spacing_y", "Spacing Y", "float", 20.0, -5000, 5000, 1, group=g2),
    ]


# ---------------------------------------------------------------------------
# Body builders: return a tool solid at the origin (placement is applied later)
# ---------------------------------------------------------------------------

def _box(p):
    return Box(p["length"], p["width"], p["height"], align=BED)


def _cylinder(p):
    return Cylinder(p["radius"], p["height"], align=BED)


def _sphere(p):
    return Sphere(p["radius"], align=BED)


def _cone(p):
    top = max(p["top_radius"], 0.0)
    return Cone(p["bottom_radius"], top, p["height"], align=BED)


def _torus(p):
    return Torus(p["major_radius"], p["minor_radius"], align=BED)


def _parse_points(text: str, min_pts: int = 3) -> list[tuple[float, float]]:
    pts = []
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        xy = [c for c in chunk.replace(",", " ").split() if c]
        if len(xy) != 2:
            raise ValueError(f"Point '{chunk}' must be x,y")
        pts.append((float(xy[0]), float(xy[1])))
    if len(pts) < min_pts:
        raise ValueError(f"Needs at least {min_pts} points")
    return pts


PROFILE_CHOICES = [
    ("rect", "Rectangle"),
    ("rounded", "Rounded rectangle"),
    ("circle", "Circle"),
    ("polygon", "Regular polygon"),
    ("slot", "Slot"),
    ("custom", "Custom points"),
]


def _profile(p):
    kind = p["profile"]
    w, h = p["width"], p["depth"]
    if kind == "rect":
        return Rectangle(w, h)
    if kind == "rounded":
        r = min(p["corner_radius"], min(w, h) / 2 - 0.01)
        return RectangleRounded(w, h, max(r, 0.01))
    if kind == "circle":
        return Circle(w / 2)
    if kind == "polygon":
        return RegularPolygon(w / 2, int(p["sides"]))
    if kind == "slot":
        return SlotOverall(max(w, h + 0.01), h)
    if kind == "custom":
        return Polygon(*_parse_points(p["points"]), align=None)
    raise ValueError(f"Unknown shape {kind}")


def _extrude(p):
    sk = _profile(p)
    if abs(p["taper"]) > 1e-9:
        return extrude(sk, amount=p["height"], taper=p["taper"])
    return extrude(sk, amount=p["height"])


def _text(p):
    if not p["text"].strip():
        raise ValueError("Type some text")
    sk = Text(p["text"], p["font_size"], font=p["font"] or "Arial")
    return extrude(sk, amount=p["height"])


def _hole(p):
    d = p["diameter"]
    depth = p["depth"]
    hole = Cylinder(d / 2, depth, align=(Align.CENTER, Align.CENTER, Align.MAX))
    if p["countersink"] > d:
        cs = p["countersink"]
        hole += Cone(d / 2, cs / 2, (cs - d) / 2, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return hole


def _import_step(p):
    if not p["path"]:
        raise ValueError("Choose a STEP file")
    shape = import_step(p["path"])
    return shape * p["scale"] if p["scale"] != 1 else shape


# ---------------------------------------------------------------------------
# Modifier builders: (part, params) -> part
# ---------------------------------------------------------------------------

def find_face(part, ref):
    """Find the planar face that best matches a stored reference
    {"p": point on face, "n": outward normal}."""
    n = Vector(*ref["n"])
    pt = Vector(*ref["p"])
    best = None
    for f in part.faces():
        if f.geom_type != GeomType.PLANE:
            continue
        if f.normal_at().dot(n) < 0.999:
            continue
        d = f.distance_to(pt)
        if best is None or d < best[0]:
            best = (d, f)
    if best is None:
        raise ValueError("Picked face not found (the shape changed). Pick the face again")
    return best[1]


def find_edges(part, refs, tol=2.0):
    edges = part.edges()
    out = []
    for r in refs:
        pt = Vector(*r)
        e = min(edges, key=lambda e: e.distance_to(pt))
        if e.distance_to(pt) > tol:
            raise ValueError("Picked edge not found (the shape changed). Pick the edge again")
        if not any(e.is_same(o) for o in out):
            out.append(e)
    return out


def face_ref(face, point=None):
    c = Vector(*point) if point is not None else face.center()
    n = face.normal_at()
    return {"p": [c.X, c.Y, c.Z], "n": [n.X, n.Y, n.Z]}


def edge_ref(edge):
    m = edge.position_at(0.5)
    return [m.X, m.Y, m.Z]


def select_edges(part, which, refs=None):
    if which == "picked":
        if not refs:
            raise ValueError("No edges picked")
        return find_edges(part, refs)
    edges = part.edges()
    if which == "top":
        return edges.group_by(Axis.Z)[-1]
    if which == "bottom":
        return edges.group_by(Axis.Z)[0]
    if which == "vertical":
        return edges.filter_by(Axis.Z)
    if which == "horizontal":
        return edges.filter_by(Plane.XY)
    return edges


def _need_part(part):
    if part is None:
        raise ValueError("Needs a body first")


def _fillet(part, p):
    _need_part(part)
    return fillet(select_edges(part, p["edges"], p.get("edge_refs")), p["radius"])


def _chamfer(part, p):
    _need_part(part)
    return chamfer(select_edges(part, p["edges"], p.get("edge_refs")), p["length"])


def _shell(part, p):
    _need_part(part)
    faces = part.faces()
    openings = None
    if p["opening"] == "top":
        openings = faces.sort_by(Axis.Z)[-1]
    elif p["opening"] == "bottom":
        openings = faces.sort_by(Axis.Z)[0]
    elif p["opening"] == "picked":
        if not p.get("face_refs"):
            raise ValueError("No face picked to open")
        openings = [find_face(part, r) for r in p["face_refs"]]
    return offset(part, amount=-abs(p["thickness"]), openings=openings)


MIRROR_PLANES = {"YZ": Plane.YZ, "XZ": Plane.XZ, "XY": Plane.XY}


def _mirror(part, p):
    _need_part(part)
    plane = MIRROR_PLANES[p["plane"]]
    if p["offset"]:
        plane = plane.offset(p["offset"])
    m = mirror(part, about=plane)
    return part + m if p["keep"] else m


def _scale(part, p):
    _need_part(part)
    return part.scale(p["factor"] / 100.0)


# ---------------------------------------------------------------------------
# Sketches drawn on faces and the operations that use them
# ---------------------------------------------------------------------------

def plane_axes(normal):
    """Deterministic in-plane X axis for a sketch plane with this normal."""
    n = Vector(*normal).normalized()
    if abs(n.Z) > 0.999:
        x = Vector(1, 0, 0)
    else:
        x = Vector(0, 0, 1).cross(n).normalized()
    return n, x


def make_plane(p) -> Plane:
    n, x = plane_axes(p["normal"])
    return Plane(origin=Vector(*p["origin"]), x_dir=x, z_dir=n)


def shape_face(plane: Plane, s: dict):
    kind = s["kind"]
    if kind == "circle":
        if s["r"] <= 0:
            raise ValueError("Radius must be greater than 0")
        sk = Pos(s["c"][0], s["c"][1]) * Circle(s["r"])
    elif kind == "rect":
        if s["w"] <= 0 or s["h"] <= 0:
            raise ValueError("Rectangle size must be greater than 0")
        sk = Pos(s["c"][0], s["c"][1]) * Rectangle(s["w"], s["h"])
    elif kind == "poly":
        if len(s["pts"]) < 3:
            raise ValueError("A polygon needs at least 3 points")
        sk = Polygon(*[tuple(pt) for pt in s["pts"]], align=None)
    elif kind == "ngon":
        if s["r"] <= 0:
            raise ValueError("Radius must be greater than 0")
        sk = Pos(s["c"][0], s["c"][1]) * RegularPolygon(s["r"], int(s["n"]), rotation=s.get("rot", 0.0))
    elif kind == "slot":
        (x1, y1), (x2, y2) = s["c1"], s["c2"]
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist <= 1e-9 or s["w"] <= 0:
            raise ValueError("Slot length and width must be greater than 0")
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        sk = Pos((x1 + x2) / 2, (y1 + y2) / 2) * SlotCenterToCenter(dist, s["w"], rotation=ang)
    elif kind == "path":
        return None  # open line chain: drawn and snapped to, but not a region
    else:
        raise ValueError(f"Unknown shape {kind}")
    return plane * sk


def build_sketch(p):
    plane = make_plane(p)
    faces = []
    errors = []
    for i, s in enumerate(p["shapes"]):
        if s.get("kind") == "path":
            faces.append(None)
            continue
        try:
            faces.append(shape_face(plane, s))
        except Exception as exc:
            faces.append(None)
            errors.append(f"Shape {i + 1}: {exc}")
    return plane, faces, errors


def _sign(d):
    return 1.0 if d > 0 else -1.0


def _through_distance(part, d):
    size = part.bounding_box().diagonal if part is not None else 100.0
    return _sign(d if d else -1) * (size * 2 + 10)


def _apply(part, tool, mode, d):
    if mode == "auto":
        mode = "add" if d > 0 else "cut"
    if part is None:
        if mode != "add":
            raise ValueError("There's no body to cut yet — pull up instead")
        return tool
    if mode == "add":
        return part + tool
    if mode == "cut":
        return part - tool
    return part & tool


def _pull(part, p, ctx):
    sk = ctx["sketches"].get(p["sketch"])
    if sk is None:
        raise ValueError("Sketch not found (deleted or turned off)")
    plane, faces = sk
    d = float(p["distance"])
    if p.get("through"):
        d = _through_distance(part, d)
    if abs(d) < 1e-6:
        raise ValueError("Distance can't be 0")
    tool = None
    for idx in p["shapes"]:
        if not (0 <= idx < len(faces)) or faces[idx] is None:
            raise ValueError("Shape not found in the sketch")
        t = extrude(faces[idx], amount=abs(d), dir=plane.z_dir * _sign(d))
        tool = t if tool is None else tool + t
    return _apply(part, tool, p.get("mode", "auto"), d), tool


def _pushpull(part, p, ctx):
    _need_part(part)
    d = float(p["distance"])
    if p.get("through"):
        d = _through_distance(part, d)
    if abs(d) < 1e-6:
        raise ValueError("Distance can't be 0")
    tool = None
    for ref in p["face_refs"]:
        face = find_face(part, ref)
        t = extrude(face, amount=abs(d), dir=face.normal_at() * _sign(d))
        tool = t if tool is None else tool + t
    return _apply(part, tool, p.get("mode", "auto"), d), tool


PULL_MODES = [("auto", "Auto"), ("add", "Add"), ("cut", "Cut"),
              ("intersect", "Intersect")]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FEATURE_TYPES: dict[str, FeatureType] = {}


def _reg(ft: FeatureType):
    if ft.category == "body":
        ft.params = ft.params + placement_params()
    FEATURE_TYPES[ft.type_id] = ft


_reg(FeatureType("box", "Box", "body", [
    _dim("length", "Length (X)", 40), _dim("width", "Width (Y)", 30), _dim("height", "Height (Z)", 20),
], _box, "▣"))
_reg(FeatureType("cylinder", "Cylinder", "body", [
    _dim("radius", "Radius", 15), _dim("height", "Height", 30),
], _cylinder, "⬤"))
_reg(FeatureType("sphere", "Sphere", "body", [_dim("radius", "Radius", 15)], _sphere, "●"))
_reg(FeatureType("cone", "Cone", "body", [
    _dim("bottom_radius", "Bottom radius", 15), _dim("top_radius", "Top radius", 0, 0.0), _dim("height", "Height", 30),
], _cone, "▲"))
_reg(FeatureType("torus", "Torus", "body", [
    _dim("major_radius", "Ring radius", 20), _dim("minor_radius", "Tube radius", 5),
], _torus, "◎"))
_reg(FeatureType("extrude", "Profile extrude", "body", [
    Param("profile", "Profile", "choice", "rounded", choices=PROFILE_CHOICES),
    _dim("width", "Width / diameter", 40), _dim("depth", "Depth (Y)", 25),
    _dim("corner_radius", "Corner radius", 4, 0.0), Param("sides", "Sides", "int", 6, 3, 64, 1, ""),
    Param("points", "Points (x,y; x,y; ...)", "str", "0,0; 30,0; 30,10; 10,25; 0,25", suffix=""),
    Param("height", "Extrude height", "float", 10, -5000, 5000),
    Param("taper", "Draft angle", "float", 0, -45, 45, 1, "°"),
], _extrude, "⬓"))
_reg(FeatureType("text", "Text", "body", [
    Param("text", "Text", "str", "3D", suffix=""), _dim("font_size", "Font size", 12),
    Param("font", "Font", "str", "Arial", suffix=""), Param("height", "Thickness", "float", 2, -500, 500),
], _text, "A"))
_reg(FeatureType("hole", "Hole", "body", [
    _dim("diameter", "Hole Ø", 5, step=0.5), _dim("depth", "Depth", 20),
    _dim("countersink", "Countersink Ø (0 = none)", 0, 0.0),
], _hole, "◌"))
_reg(FeatureType("import_step", "Import STEP", "body", [
    Param("path", "File", "file", "", suffix=""),
    Param("scale", "Scale", "float", 1.0, 0.001, 1000, 0.1, "×"),
], _import_step, "⇩"))
for _p in FEATURE_TYPES["hole"].params:  # holes cut by default
    if _p.key == "mode":
        _p.default = "cut"

_reg(FeatureType("fillet", "Fillet", "modify", [
    Param("edges", "Edges", "choice", "vertical", choices=EDGE_CHOICES), _dim("radius", "Radius", 2, 0.01, step=0.5),
    Param("edge_refs", "", "hidden", []),
], _fillet, "◜"))
_reg(FeatureType("chamfer", "Chamfer", "modify", [
    Param("edges", "Edges", "choice", "top", choices=EDGE_CHOICES), _dim("length", "Distance", 1, 0.01, step=0.5),
    Param("edge_refs", "", "hidden", []),
], _chamfer, "◸"))
_reg(FeatureType("shell", "Shell", "modify", [
    _dim("thickness", "Wall thickness", 1.6, 0.01, step=0.2),
    Param("opening", "Open side", "choice", "top",
          choices=[("top", "Open top"), ("bottom", "Open bottom"), ("picked", "Picked faces"),
                   ("none", "Closed")]),
    Param("face_refs", "", "hidden", []),
], _shell, "▢"))
_reg(FeatureType("mirror", "Mirror", "modify", [
    Param("plane", "Plane", "choice", "YZ", choices=[("YZ", "YZ (left–right)"), ("XZ", "XZ (front–back)"), ("XY", "XY (top–bottom)")]),
    Param("offset", "Plane offset", "float", 0.0),
    Param("keep", "Keep original", "bool", True, suffix=""),
], _mirror, "⇋"))
_reg(FeatureType("scale", "Scale", "modify", [
    Param("factor", "Scale", "float", 100.0, 1, 10000, 5, " %"),
], _scale, "⤢"))
_reg(FeatureType("sketch", "Sketch", "sketch", [
    Param("origin", "", "hidden", [0.0, 0.0, 0.0]),
    Param("normal", "", "hidden", [0.0, 0.0, 1.0]),
    Param("shapes", "", "hidden", []),
], build_sketch, "✎"))
_reg(FeatureType("pull", "Extrude", "op", [
    Param("distance", "Distance (+up / −down)", "float", 10.0, -10000, 10000, 1),
    Param("through", "Cut through", "bool", False, suffix=""),
    Param("mode", "Operation", "choice", "auto", choices=PULL_MODES),
    Param("sketch", "", "hidden", ""),
    Param("shapes", "", "hidden", [0]),
], _pull, "⇧"))
_reg(FeatureType("pushpull", "Push/Pull face", "op", [
    Param("distance", "Distance (+out / −in)", "float", 5.0, -10000, 10000, 1),
    Param("through", "Through all", "bool", False, suffix=""),
    Param("mode", "Operation", "choice", "auto", choices=PULL_MODES),
    Param("face_refs", "", "hidden", []),
], _pushpull, "⇕"))


# ---------------------------------------------------------------------------
# Feature instances and the document
# ---------------------------------------------------------------------------

@dataclass
class Feature:
    type_id: str
    name: str
    params: dict[str, Any]
    enabled: bool = True
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    error: str | None = field(default=None, compare=False)

    @property
    def ftype(self) -> FeatureType:
        return FEATURE_TYPES[self.type_id]

    @classmethod
    def new(cls, type_id: str, name: str | None = None, **overrides) -> "Feature":
        ft = FEATURE_TYPES[type_id]
        params = {p.key: copy.deepcopy(p.default) for p in ft.params}
        params.update(copy.deepcopy(overrides))
        return cls(type_id, name or ft.label, params)

    def to_dict(self):
        return {"type": self.type_id, "name": self.name, "enabled": self.enabled, "uid": self.uid,
                "params": self.params}

    @classmethod
    def from_dict(cls, d):
        f = cls.new(d["type"], d.get("name"))
        f.params.update(d.get("params", {}))
        f.enabled = d.get("enabled", True)
        if d.get("uid"):
            f.uid = d["uid"]
        return f


def place(tool, p):
    """Apply rotation, position and pattern to a tool solid."""
    tool = Rot(p.get("rx", 0), p.get("ry", 0), p.get("rz", 0)) * tool
    base = Pos(p.get("x", 0), p.get("y", 0), p.get("z", 0))
    pattern = p.get("pattern", "none")
    nx = max(int(p.get("count_x", 1)), 1)
    ny = max(int(p.get("count_y", 1)), 1)
    dx, dy = p.get("spacing_x", 0), p.get("spacing_y", 0)
    locs = []
    if pattern == "linear":
        locs = [Pos(i * dx, 0, 0) for i in range(nx)]
    elif pattern == "grid":
        locs = [Pos(i * dx, j * dy, 0) for i in range(nx) for j in range(ny)]
    elif pattern == "circular":
        locs = [Rot(0, 0, 360.0 * i / nx) for i in range(nx)]
    if not locs:
        return base * tool
    result = None
    for loc in locs:
        if pattern == "circular":
            inst = loc * (base * tool)
        else:
            inst = base * (loc * tool)
        result = inst if result is None else result + inst
    return result


def build_feature(part, feat: Feature, ctx=None):
    ft = feat.ftype
    p = feat.params
    if ft.category == "modify":
        return ft.build(part, p), None
    if ft.category == "op":
        return ft.build(part, p, ctx)
    tool = place(ft.build(p), p)
    mode = p.get("mode", "add")
    if part is None:
        if mode != "add":
            raise ValueError("Needs a body first to cut or intersect")
        return tool, tool
    if mode == "add":
        return part + tool, tool
    if mode == "cut":
        return part - tool, tool
    return part & tool, tool


def friendly_error(exc: Exception) -> str:
    msg = str(exc).strip()
    if any("\u0e00" <= ch <= "\u0e7f" for ch in msg):  # our own Thai messages
        return msg
    hint = "Couldn't build this step. Try a smaller radius or thickness, or move it / change the order"
    return f"{hint} ({msg or exc.__class__.__name__})"


def rebuild(features: list[Feature]):
    """Rebuild all features. Returns (part, tools) where tools[i] is the tool
    solid of feature i (or None). Errors are stored on each feature."""
    part = None
    tools: list = []
    ctx = {"sketches": {}}
    for feat in features:
        feat.error = None
        if not feat.enabled:
            tools.append(None)
            continue
        if feat.ftype.category == "sketch":
            plane, faces, errors = build_sketch(feat.params)
            ctx["sketches"][feat.uid] = (plane, faces)
            if errors:
                feat.error = "; ".join(errors)
            tools.append(None)
            continue
        try:
            new_part, tool = build_feature(part, feat, ctx)
            if new_part is not None and getattr(new_part, "volume", 1) <= 1e-9 and part is not None:
                raise ValueError("Nothing would be left of the body")
            part = new_part
            tools.append(tool)
        except Exception as exc:  # keep going with the last good part
            feat.error = friendly_error(exc)
            tools.append(None)
    return part, tools


class Document:
    """Feature list with undo/redo and JSON save/load."""

    def __init__(self):
        self.features: list[Feature] = []
        self.path: str | None = None
        self._undo: list[str] = []
        self._redo: list[str] = []
        self.dirty = False

    # --- history ---------------------------------------------------------
    def _snapshot(self) -> str:
        return json.dumps([f.to_dict() for f in self.features])

    def _restore(self, snap: str):
        self.features = [Feature.from_dict(d) for d in json.loads(snap)]

    def checkpoint(self):
        """Call before every change."""
        self._undo.append(self._snapshot())
        if len(self._undo) > 200:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self.dirty = True
        return True

    # --- editing -----------------------------------------------------------
    def unique_name(self, base: str) -> str:
        names = {f.name for f in self.features}
        i = 1
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def add(self, type_id: str, index: int | None = None, checkpoint=True, **overrides) -> Feature:
        if checkpoint:
            self.checkpoint()
        f = Feature.new(type_id, self.unique_name(FEATURE_TYPES[type_id].label), **overrides)
        if index is None:
            self.features.append(f)
        else:
            self.features.insert(index, f)
        return f

    def by_uid(self, uid):
        return next((f for f in self.features if f.uid == uid), None)

    def consumed_shapes(self) -> set[tuple[str, int]]:
        """Sketch shapes already used by an enabled pull."""
        used = set()
        for f in self.features:
            if f.type_id == "pull" and f.enabled:
                used |= {(f.params["sketch"], i) for i in f.params["shapes"]}
        return used

    def add_sketch_shape(self, plane: dict, shape: dict) -> tuple[Feature, int]:
        """Add a drawn shape to an existing coplanar sketch, or start a new one."""
        n_new, x = plane_axes(plane["normal"])
        o_new = Vector(*plane["origin"])
        y = n_new.cross(x)
        for f in reversed(self.features):
            if f.type_id != "sketch":
                continue
            n_old = Vector(*f.params["normal"]).normalized()
            o_old = Vector(*f.params["origin"])
            if n_old.dot(n_new) > 0.9999 and abs((o_new - o_old).dot(n_old)) < 1e-6:
                du, dv = (o_new - o_old).dot(x), (o_new - o_old).dot(y)
                s = copy.deepcopy(shape)
                if "c" in s:
                    s["c"] = [s["c"][0] + du, s["c"][1] + dv]
                if "pts" in s:
                    s["pts"] = [[p[0] + du, p[1] + dv] for p in s["pts"]]
                for key in ("c1", "c2"):
                    if key in s:
                        s[key] = [s[key][0] + du, s[key][1] + dv]
                self.checkpoint()
                f.params["shapes"].append(s)
                f.enabled = True
                return f, len(f.params["shapes"]) - 1
        f = self.add("sketch", origin=list(plane["origin"]), normal=list(plane["normal"]), shapes=[shape])
        return f, 0

    def delete_shapes(self, uid: str, idxs: list[int]):
        """Remove shapes from a sketch and fix up the pulls that use them."""
        sk = self.by_uid(uid)
        if sk is None:
            return
        self.checkpoint()
        idxs = sorted(set(idxs), reverse=True)
        for i in idxs:
            if 0 <= i < len(sk.params["shapes"]):
                del sk.params["shapes"][i]
        for f in list(self.features):
            if f.type_id == "pull" and f.params["sketch"] == uid:
                kept = [i - sum(1 for d in idxs if d < i) for i in f.params["shapes"] if i not in idxs]
                if kept:
                    f.params["shapes"] = kept
                else:
                    self.features.remove(f)
        if not sk.params["shapes"]:
            self.features.remove(sk)

    def remove(self, index: int):
        self.checkpoint()
        del self.features[index]

    def duplicate(self, index: int) -> Feature:
        self.checkpoint()
        src = self.features[index]
        f = Feature.from_dict(copy.deepcopy(src.to_dict()))
        f.uid = uuid.uuid4().hex[:8]
        f.name = self.unique_name(src.ftype.label)
        self.features.insert(index + 1, f)
        return f

    def move(self, index: int, delta: int) -> int:
        j = index + delta
        if not (0 <= j < len(self.features)):
            return index
        self.checkpoint()
        self.features[index], self.features[j] = self.features[j], self.features[index]
        return j

    # --- files -------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({"app": "3DMaker", "version": PROJECT_VERSION,
                           "features": [f.to_dict() for f in self.features]}, ensure_ascii=False, indent=2)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
        self.path = path
        self.dirty = False

    def load(self, path: str):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.features = [Feature.from_dict(d) for d in data.get("features", [])]
        self.path = path
        self._undo.clear()
        self._redo.clear()
        self.dirty = False


# ---------------------------------------------------------------------------
# Info helpers
# ---------------------------------------------------------------------------

MATERIALS = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "TPU": 1.21, "Resin": 1.10}


def part_info(part, material="PLA"):
    if part is None:
        return None
    bb = part.bounding_box()
    vol_mm3 = abs(part.volume)
    return {
        "size": (bb.size.X, bb.size.Y, bb.size.Z),
        "min": (bb.min.X, bb.min.Y, bb.min.Z),
        "volume_cm3": vol_mm3 / 1000.0,
        "weight_g": vol_mm3 / 1000.0 * MATERIALS.get(material, 1.24),
    }


# ---------------------------------------------------------------------------
# Dotted parameter paths (used to edit sketch shapes in the property panel)
# ---------------------------------------------------------------------------

def get_path(params, key):
    cur = params
    for part in key.split("."):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def set_path(params, key, value):
    parts = key.split(".")
    cur = params
    for part in parts[:-1]:
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    last = parts[-1]
    if last == "pts" and isinstance(value, str):
        value = [list(p) for p in _parse_points(value, 2)]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


SHAPE_LABELS = {"ngon": "Polygon", "slot": "Slot", "path": "Lines", "circle": "Circle", "rect": "Rectangle", "poly": "Polygon"}


def sketch_params(feat: Feature) -> list[Param]:
    out = []
    for i, s in enumerate(feat.params.get("shapes", [])):
        g = f"{i + 1}. {SHAPE_LABELS.get(s['kind'], s['kind'])}"
        k = f"shapes.{i}"
        if s["kind"] in ("circle", "rect"):
            out += [Param(f"{k}.c.0", "Center X", "float", 0.0, group=g),
                    Param(f"{k}.c.1", "Center Y", "float", 0.0, group=g)]
        if s["kind"] == "circle":
            out.append(Param(f"{k}.r", "Radius", "float", 5.0, 0.01, 10000, 0.5, group=g))
        elif s["kind"] == "rect":
            out += [Param(f"{k}.w", "Width", "float", 10.0, 0.01, 10000, group=g),
                    Param(f"{k}.h", "Height", "float", 10.0, 0.01, 10000, group=g)]
        elif s["kind"] in ("poly", "path"):
            out.append(Param(f"{k}.pts", "Points (x,y; ...)", "points", "", suffix="", group=g))
        elif s["kind"] == "ngon":
            out += [Param(f"{k}.c.0", "Center X", "float", 0.0, group=g),
                    Param(f"{k}.c.1", "Center Y", "float", 0.0, group=g),
                    Param(f"{k}.r", "Radius", "float", 5.0, 0.01, 10000, 0.5, group=g),
                    Param(f"{k}.n", "Sides", "int", 6, 3, 64, 1, "", group=g)]
        elif s["kind"] == "slot":
            out += [Param(f"{k}.c1.0", "Start X", "float", 0.0, group=g),
                    Param(f"{k}.c1.1", "Start Y", "float", 0.0, group=g),
                    Param(f"{k}.c2.0", "End X", "float", 0.0, group=g),
                    Param(f"{k}.c2.1", "End Y", "float", 0.0, group=g),
                    Param(f"{k}.w", "Width", "float", 5.0, 0.01, 10000, 0.5, group=g)]
    return out


def format_points(pts):
    return "; ".join(f"{x:g},{y:g}" for x, y in pts)
