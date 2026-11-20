"""Parametric model: a list of features that is rebuilt into one solid.

This module has no GUI dependency so it can be tested on its own.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from build123d import (
    Align,
    Axis,
    Box,
    Circle,
    Cone,
    Cylinder,
    Part,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    RectangleRounded,
    RegularPolygon,
    Rot,
    SlotOverall,
    Sphere,
    Text,
    Torus,
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
    kind: str = "float"  # float | int | choice | str | bool | file
    default: Any = 0.0
    min: float = -10000.0
    max: float = 10000.0
    step: float = 1.0
    suffix: str = " mm"
    choices: list[tuple[str, str]] | None = None  # (value, label)
    group: str = "รูปทรง"


@dataclass
class FeatureType:
    type_id: str
    label: str
    category: str  # "body" (adds/cuts geometry) or "modify" (changes the part)
    params: list[Param]
    build: Callable
    icon: str = "■"


MODE_CHOICES = [("add", "เพิ่มเนื้อ (Union)"), ("cut", "ตัดออก (Cut)"), ("intersect", "เหลือส่วนที่ซ้อนกัน")]
EDGE_CHOICES = [
    ("all", "ทุกขอบ"),
    ("top", "ขอบด้านบน"),
    ("bottom", "ขอบด้านล่าง"),
    ("vertical", "ขอบแนวตั้ง"),
    ("horizontal", "ขอบแนวนอน"),
]
PATTERN_CHOICES = [
    ("none", "ไม่ทำซ้ำ"),
    ("linear", "เรียงเป็นแถว (X)"),
    ("grid", "ตาราง (X×Y)"),
    ("circular", "รอบวง (รอบแกน Z)"),
]


def _dim(key, label, default, mn=0.1, mx=5000.0, step=1.0):
    return Param(key, label, "float", default, mn, mx, step)


def placement_params() -> list[Param]:
    g = "ตำแหน่ง"
    g2 = "ทำซ้ำ (Pattern)"
    return [
        Param("mode", "การทำงาน", "choice", "add", choices=MODE_CHOICES, group="การทำงาน"),
        Param("x", "X", "float", 0.0, group=g),
        Param("y", "Y", "float", 0.0, group=g),
        Param("z", "Z", "float", 0.0, group=g),
        Param("rx", "หมุนรอบ X", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("ry", "หมุนรอบ Y", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("rz", "หมุนรอบ Z", "float", 0.0, -360, 360, 15, "°", group=g),
        Param("pattern", "รูปแบบ", "choice", "none", choices=PATTERN_CHOICES, group=g2),
        Param("count_x", "จำนวน (X / รอบวง)", "int", 3, 1, 500, 1, "", group=g2),
        Param("count_y", "จำนวน (Y)", "int", 2, 1, 500, 1, "", group=g2),
        Param("spacing_x", "ระยะห่าง X", "float", 20.0, -5000, 5000, 1, group=g2),
        Param("spacing_y", "ระยะห่าง Y", "float", 20.0, -5000, 5000, 1, group=g2),
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


def _parse_points(text: str) -> list[tuple[float, float]]:
    pts = []
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        xy = [c for c in chunk.replace(",", " ").split() if c]
        if len(xy) != 2:
            raise ValueError(f"จุด '{chunk}' ต้องเป็นรูปแบบ x,y")
        pts.append((float(xy[0]), float(xy[1])))
    if len(pts) < 3:
        raise ValueError("ต้องมีอย่างน้อย 3 จุด")
    return pts


PROFILE_CHOICES = [
    ("rect", "สี่เหลี่ยม"),
    ("rounded", "สี่เหลี่ยมมุมมน"),
    ("circle", "วงกลม"),
    ("polygon", "หลายเหลี่ยมด้านเท่า"),
    ("slot", "ช่องยาว (Slot)"),
    ("custom", "กำหนดจุดเอง"),
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
    raise ValueError(f"ไม่รู้จักรูป {kind}")


def _extrude(p):
    sk = _profile(p)
    if abs(p["taper"]) > 1e-9:
        return extrude(sk, amount=p["height"], taper=p["taper"])
    return extrude(sk, amount=p["height"])


def _text(p):
    if not p["text"].strip():
        raise ValueError("ยังไม่ได้ใส่ข้อความ")
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
        raise ValueError("ยังไม่ได้เลือกไฟล์ STEP")
    shape = import_step(p["path"])
    return shape * p["scale"] if p["scale"] != 1 else shape


# ---------------------------------------------------------------------------
# Modifier builders: (part, params) -> part
# ---------------------------------------------------------------------------

def select_edges(part, which):
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
        raise ValueError("ต้องมีรูปทรงก่อน")


def _fillet(part, p):
    _need_part(part)
    return fillet(select_edges(part, p["edges"]), p["radius"])


def _chamfer(part, p):
    _need_part(part)
    return chamfer(select_edges(part, p["edges"]), p["length"])


def _shell(part, p):
    _need_part(part)
    faces = part.faces()
    openings = None
    if p["opening"] == "top":
        openings = faces.sort_by(Axis.Z)[-1]
    elif p["opening"] == "bottom":
        openings = faces.sort_by(Axis.Z)[0]
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
# Registry
# ---------------------------------------------------------------------------

FEATURE_TYPES: dict[str, FeatureType] = {}


def _reg(ft: FeatureType):
    if ft.category == "body":
        ft.params = ft.params + placement_params()
    FEATURE_TYPES[ft.type_id] = ft


_reg(FeatureType("box", "กล่อง", "body", [
    _dim("length", "ยาว (X)", 40), _dim("width", "กว้าง (Y)", 30), _dim("height", "สูง (Z)", 20),
], _box, "▣"))
_reg(FeatureType("cylinder", "ทรงกระบอก", "body", [
    _dim("radius", "รัศมี", 15), _dim("height", "สูง", 30),
], _cylinder, "⬤"))
_reg(FeatureType("sphere", "ทรงกลม", "body", [_dim("radius", "รัศมี", 15)], _sphere, "●"))
_reg(FeatureType("cone", "กรวย", "body", [
    _dim("bottom_radius", "รัศมีล่าง", 15), _dim("top_radius", "รัศมีบน", 0, 0.0), _dim("height", "สูง", 30),
], _cone, "▲"))
_reg(FeatureType("torus", "โดนัท", "body", [
    _dim("major_radius", "รัศมีวง", 20), _dim("minor_radius", "รัศมีท่อ", 5),
], _torus, "◎"))
_reg(FeatureType("extrude", "ดึงรูป 2D ขึ้น", "body", [
    Param("profile", "รูป 2D", "choice", "rounded", choices=PROFILE_CHOICES),
    _dim("width", "กว้าง / เส้นผ่านศูนย์กลาง", 40), _dim("depth", "ลึก (Y)", 25),
    _dim("corner_radius", "รัศมีมุม", 4, 0.0), Param("sides", "จำนวนด้าน", "int", 6, 3, 64, 1, ""),
    Param("points", "จุด (x,y; x,y; ...)", "str", "0,0; 30,0; 30,10; 10,25; 0,25", suffix=""),
    Param("height", "ความสูงที่ดึง", "float", 10, -5000, 5000),
    Param("taper", "มุมเอียง", "float", 0, -45, 45, 1, "°"),
], _extrude, "⬓"))
_reg(FeatureType("text", "ข้อความ", "body", [
    Param("text", "ข้อความ", "str", "3D", suffix=""), _dim("font_size", "ขนาดตัวอักษร", 12),
    Param("font", "ฟอนต์", "str", "Arial", suffix=""), Param("height", "ความหนา", "float", 2, -500, 500),
], _text, "A"))
_reg(FeatureType("hole", "รูเจาะ", "body", [
    _dim("diameter", "Ø รู", 5, step=0.5), _dim("depth", "ความลึก", 20),
    _dim("countersink", "ปากรูบาก Ø (0=ไม่มี)", 0, 0.0),
], _hole, "◌"))
_reg(FeatureType("import_step", "นำเข้า STEP", "body", [
    Param("path", "ไฟล์", "file", "", suffix=""),
    Param("scale", "สเกล", "float", 1.0, 0.001, 1000, 0.1, "×"),
], _import_step, "⇩"))
for _p in FEATURE_TYPES["hole"].params:  # holes cut by default
    if _p.key == "mode":
        _p.default = "cut"

_reg(FeatureType("fillet", "ลบมุมโค้ง", "modify", [
    Param("edges", "ขอบที่เลือก", "choice", "vertical", choices=EDGE_CHOICES), _dim("radius", "รัศมี", 2, 0.01),
], _fillet, "◜"))
_reg(FeatureType("chamfer", "ลบมุมเฉียง", "modify", [
    Param("edges", "ขอบที่เลือก", "choice", "top", choices=EDGE_CHOICES), _dim("length", "ระยะ", 1, 0.01),
], _chamfer, "◸"))
_reg(FeatureType("shell", "ทำให้กลวง", "modify", [
    _dim("thickness", "ความหนาผนัง", 1.6, 0.01, step=0.2),
    Param("opening", "ด้านที่เปิด", "choice", "top",
          choices=[("top", "เปิดด้านบน"), ("bottom", "เปิดด้านล่าง"), ("none", "ปิดทุกด้าน")]),
], _shell, "▢"))
_reg(FeatureType("mirror", "สะท้อน", "modify", [
    Param("plane", "ระนาบ", "choice", "YZ", choices=[("YZ", "YZ (ซ้าย-ขวา)"), ("XZ", "XZ (หน้า-หลัง)"), ("XY", "XY (บน-ล่าง)")]),
    Param("offset", "เลื่อนระนาบ", "float", 0.0),
    Param("keep", "เก็บของเดิมไว้ด้วย", "bool", True, suffix=""),
], _mirror, "⇋"))
_reg(FeatureType("scale", "ย่อ/ขยาย", "modify", [
    Param("factor", "สเกล", "float", 100.0, 1, 10000, 5, " %"),
], _scale, "⤢"))


# ---------------------------------------------------------------------------
# Feature instances and the document
# ---------------------------------------------------------------------------

@dataclass
class Feature:
    type_id: str
    name: str
    params: dict[str, Any]
    enabled: bool = True
    error: str | None = field(default=None, compare=False)

    @property
    def ftype(self) -> FeatureType:
        return FEATURE_TYPES[self.type_id]

    @classmethod
    def new(cls, type_id: str, name: str | None = None, **overrides) -> "Feature":
        ft = FEATURE_TYPES[type_id]
        params = {p.key: p.default for p in ft.params}
        params.update(overrides)
        return cls(type_id, name or ft.label, params)

    def to_dict(self):
        return {"type": self.type_id, "name": self.name, "enabled": self.enabled, "params": self.params}

    @classmethod
    def from_dict(cls, d):
        f = cls.new(d["type"], d.get("name"))
        f.params.update(d.get("params", {}))
        f.enabled = d.get("enabled", True)
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


def build_feature(part, feat: Feature):
    ft = feat.ftype
    p = feat.params
    if ft.category == "modify":
        return ft.build(part, p), None
    tool = place(ft.build(p), p)
    mode = p.get("mode", "add")
    if part is None:
        if mode != "add":
            raise ValueError("ต้องมีรูปทรงก่อนจึงจะตัดหรือหาส่วนซ้อนได้")
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
    hint = "คำนวณรูปทรงไม่สำเร็จ ลองลดค่ารัศมี/ความหนา หรือเปลี่ยนตำแหน่ง/ลำดับขั้นตอน"
    return f"{hint} ({msg or exc.__class__.__name__})"


def rebuild(features: list[Feature]):
    """Rebuild all features. Returns (part, tools) where tools[i] is the tool
    solid of feature i (or None). Errors are stored on each feature."""
    part = None
    tools: list = []
    for feat in features:
        feat.error = None
        if not feat.enabled:
            tools.append(None)
            continue
        try:
            new_part, tool = build_feature(part, feat)
            if new_part is not None and getattr(new_part, "volume", 1) <= 1e-9 and part is not None:
                raise ValueError("ผลลัพธ์ไม่มีเนื้อเหลือ")
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

    def add(self, type_id: str, index: int | None = None, **overrides) -> Feature:
        self.checkpoint()
        f = Feature.new(type_id, self.unique_name(FEATURE_TYPES[type_id].label), **overrides)
        if index is None:
            self.features.append(f)
        else:
            self.features.insert(index, f)
        return f

    def remove(self, index: int):
        self.checkpoint()
        del self.features[index]

    def duplicate(self, index: int) -> Feature:
        self.checkpoint()
        src = self.features[index]
        f = Feature.from_dict(copy.deepcopy(src.to_dict()))
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
