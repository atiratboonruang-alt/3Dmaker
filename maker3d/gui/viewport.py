"""Interactive 3D viewport: hover/click selection of faces, edges and sketch
profiles, drawing sketches on faces, and drag-to-pull (Shapr3D style).

Mouse:  left = select / draw / drag the arrow · right-drag = orbit ·
        middle-drag = pan · wheel = zoom to cursor.
"""
from __future__ import annotations

import math

import numpy as np
import pyvista as pv
from build123d import GeomType, extrude
from PySide6.QtCore import Qt, Signal
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleUser
from vtkmodules.vtkRenderingCore import vtkCellPicker, vtkTextActor

from ..model import make_plane, plane_axes, shape_face

# --- colours (light theme, Shapr3D-like) -----------------------------------
BG_TOP = "#eef2f6"
BG_BOTTOM = "#cdd6e0"
PART = "#e4e8ed"
EDGE = "#2a3440"
HOVER = "#8fb0ff"
SELECT = "#1f5bff"
SKETCH_FILL = "#f2a81d"
SKETCH_LINE = "#c98200"
ADD = "#1e9e5a"
CUT = "#de4a3c"
BED_PLATE = "#dfe5ec"
BED_GRID = "#c3ccd7"

DRAW_TOOLS = ("circle", "rect", "poly")

def _k(key):
    return f'<span style="background:#e8edf3; color:#17202b;">&nbsp;{key}&nbsp;</span>'


def _b(text):
    return f"<b>{text}</b>"


HINTS = {
    "select": f"{_b('คลิกหน้า ขอบ หรือรูปสเก็ตช์')} เพื่อเลือก · เริ่มชิ้นใหม่ด้วย {_k('R')} สี่เหลี่ยม หรือ {_k('C')} วงกลม · "
              f"คลิกขวาค้างลาก = หมุน · ปุ่มกลาง = เลื่อน · ล้อ = ซูม",
    "select_pull": f"{_b('ลากลูกศรสีน้ำเงิน')} ขึ้นเพื่อเพิ่มเนื้อ ลงเพื่อเจาะ · หรือใส่ระยะแล้วกดปุ่มในแถบล่าง · "
                   f"{_k('Shift')} ลากละเอียด 0.1 mm",
    "select_edge": f"{_b('เลือกขอบแล้ว')} ตั้งรัศมีแล้วกด ลบมุมโค้ง หรือ ลบมุมเฉียง · {_k('Shift')}+คลิกเพื่อเลือกขอบเพิ่ม",
    "circle0": f"{_b('วงกลม')} คลิกบนหน้าของชิ้นงานหรือบนฐานเพื่อวางจุดศูนย์กลาง · จุดสีเขียว = ดูดเข้ากึ่งกลาง/มุม",
    "circle1": f"{_b('ขยับเมาส์แล้วคลิก')} เพื่อกำหนดขนาด · หรือพิมพ์เส้นผ่านศูนย์กลาง เช่น 5 แล้วกด {_k('Enter')} · "
               f"{_k('Esc')} ยกเลิก",
    "rect0": f"{_b('สี่เหลี่ยม')} คลิกมุมแรกบนหน้าของชิ้นงานหรือบนฐาน · จุดสีเขียว = ดูดเข้ากึ่งกลาง/มุม",
    "rect1": f"{_b('คลิกมุมตรงข้าม')} · หรือพิมพ์ กว้าง,ยาว เช่น 30,20 แล้วกด {_k('Enter')} · {_k('Esc')} ยกเลิก",
    "poly0": f"{_b('เส้น')} คลิกวางจุดแรกบนหน้าของชิ้นงานหรือบนฐาน",
    "poly1": f"{_b('คลิกวางจุดต่อไป')} · คลิกจุดแรก ดับเบิลคลิก หรือกด {_k('Enter')} เพื่อปิดรูป · "
             f"{_k('Backspace')} ลบจุดล่าสุด · {_k('Esc')} ยกเลิก",
}


def _np(v):
    return np.array([v.X, v.Y, v.Z], dtype=float)


def tessellate(shape, tol=0.03, ang=0.15):
    """Mesh a shape; returns (PolyData, per-cell face index, list of faces)."""
    faces = list(shape.faces())
    shape.tessellate(tol, ang)
    pts_all, tris_all, fid_all = [], [], []
    offset = 0
    for i, f in enumerate(faces):
        verts, tris = f.tessellate(tol, ang)
        if not tris:
            continue
        pts_all.append(np.array([(v.X, v.Y, v.Z) for v in verts], dtype=float))
        tris_all.append(np.asarray(tris, dtype=np.int64) + offset)
        fid_all.append(np.full(len(tris), i, dtype=np.int32))
        offset += len(verts)
    if not tris_all:
        return None, None, faces
    pts = np.vstack(pts_all)
    tris = np.vstack(tris_all)
    cells = np.hstack([np.full((len(tris), 1), 3, dtype=np.int64), tris]).ravel()
    mesh = pv.PolyData(pts, faces=cells)
    fids = np.concatenate(fid_all)
    mesh.cell_data["fid"] = fids
    return mesh, fids, faces


def edge_polylines(shape):
    edges = list(shape.edges())
    lines = []
    for e in edges:
        n = 2 if e.geom_type == GeomType.LINE else 40
        lines.append(np.array([_np(e.position_at(t)) for t in np.linspace(0, 1, n)]))
    return edges, lines


def polyline_mesh(lines):
    pts, cells, off = [], [], 0
    for ln in lines:
        pts.append(ln)
        cells.append(np.concatenate([[len(ln)], np.arange(off, off + len(ln))]))
        off += len(ln)
    if not pts:
        return None
    return pv.PolyData(np.vstack(pts), lines=np.concatenate(cells))


class Viewport(QtInteractor):
    selectionChanged = Signal()
    shapeDrawn = Signal(object, object)  # plane {"origin","normal"}, shape dict
    pullDragged = Signal(object, float)  # selection items, distance
    hintChanged = Signal(str)
    toolChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_background(BG_BOTTOM, top=BG_TOP)
        try:
            self.enable_anti_aliasing("msaa")
        except Exception:
            pass
        self.add_axes(interactive=False, line_width=2, color="#3d4652")
        self.setFocusPolicy(Qt.StrongFocus)

        self.bed_size = (220.0, 220.0)
        self.show_bed = True
        self.show_edges = True
        self.snap = 1.0

        self.part = None
        self.part_mesh = None
        self.fids = None
        self.faces = []
        self.edges = []
        self.edge_lines = []
        self.profiles = []  # dicts: uid, idx, plane, shape, face, outline
        self.selection: list[dict] = []
        self.hover: dict | None = None
        self.tool = "select"
        self.draw = None
        self._bounds = None
        self._has_fit = False

        self._scene_actors = []
        self._bed_actors = []
        self._profile_actor_map = {}
        self._part_actor = None
        self._hover_actors = []
        self._sel_actors = []
        self._arrow_actor = None
        self._arrow = None  # (anchor, normal, length)
        self._draw_actors = []
        self._preview_actors = []
        self._press = None
        self._mode = None  # None | "orbit_left" | "orbit_right" | "pan" | "pull"
        self._pull = None

        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.0005)
        self._picker.PickFromListOn()

        self._label = vtkTextActor()
        tp = self._label.GetTextProperty()
        tp.SetFontSize(16)
        tp.SetColor(0.1, 0.12, 0.16)
        tp.SetBackgroundColor(1, 1, 1)
        tp.SetBackgroundOpacity(0.9)
        tp.SetFrame(True)
        tp.SetFrameColor(0.18, 0.42, 1.0)
        tp.BoldOn()
        self._label.SetVisibility(False)
        self.renderer.AddViewProp(self._label)

        # VTK gets no mouse input at all (see the Qt event handlers below)
        self.iren.interactor.SetInteractorStyle(vtkInteractorStyleUser())
        self.setMouseTracking(True)
        self._scale = 1.0
        self._last = None
        self._pivot = np.zeros(3)

        self._draw_bed()
        self.set_view("iso")

    # ------------------------------------------------------------------ bed
    def _draw_bed(self):
        for a in self._bed_actors:
            self.remove_actor(a)
        self._bed_actors = []
        if not self.show_bed:
            return
        w, d = self.bed_size
        plate = pv.Plane(center=(0, 0, -0.05), direction=(0, 0, 1), i_size=w, j_size=d)
        self._bed_actors.append(self.add_mesh(plate, color=BED_PLATE, pickable=False, reset_camera=False,
                                              ambient=0.6, diffuse=0.4))
        lines = [np.array([[x, -d / 2, 0], [x, d / 2, 0]]) for x in np.arange(-w / 2, w / 2 + 0.01, 10)]
        lines += [np.array([[-w / 2, y, 0], [w / 2, y, 0]]) for y in np.arange(-d / 2, d / 2 + 0.01, 10)]
        self._bed_actors.append(self.add_mesh(polyline_mesh(lines), color=BED_GRID, line_width=1,
                                              pickable=False, reset_camera=False))

    def set_bed(self, width, depth, visible=True):
        self.bed_size = (width, depth)
        self.show_bed = visible
        self._draw_bed()
        self.render()

    # ---------------------------------------------------------------- scene
    def set_scene(self, part, profiles, tool=None, tool_mode="add", keep_selection=False):
        """profiles: list of dict(uid, idx, origin, normal, shape)."""
        for a in self._scene_actors:
            self.remove_actor(a)
        self._scene_actors = []
        self._profile_actor_map = {}
        self._part_actor = None
        self.part = part
        self.part_mesh, self.fids, self.faces = (None, None, [])
        self.edges, self.edge_lines = [], []
        if part is not None:
            self.part_mesh, self.fids, self.faces = tessellate(part)
            self.edges, self.edge_lines = edge_polylines(part)
        segs = [(ln[:-1], ln[1:], np.full(len(ln) - 1, i)) for i, ln in enumerate(self.edge_lines)]
        if segs:
            self._seg_a = np.vstack([a for a, _, _ in segs])
            self._seg_b = np.vstack([b for _, b, _ in segs])
            self._seg_owner = np.concatenate([o for _, _, o in segs])
        else:
            self._seg_a = None
        if self.part_mesh is not None:
            shaded = self.part_mesh.compute_normals(cell_normals=False, split_vertices=True, feature_angle=35)
            self._part_actor = self.add_mesh(shaded, color=PART, smooth_shading=True, specular=0.25,
                                             specular_power=25, ambient=0.35, diffuse=0.7,
                                             reset_camera=False)
            self._scene_actors.append(self._part_actor)
            self._bounds = self.part_mesh.bounds
            if self.show_edges and self.edge_lines:
                self._scene_actors.append(self.add_mesh(polyline_mesh(self.edge_lines), color=EDGE,
                                                        line_width=1.4, pickable=False, reset_camera=False))
        else:
            self._bounds = None

        self.profiles = []
        for pr in profiles:
            try:
                plane = make_plane({"origin": pr["origin"], "normal": pr["normal"]})
                face = shape_face(plane, pr["shape"])
            except Exception:
                continue
            n, x = plane_axes(pr["normal"])
            o, n, x = np.array(pr["origin"], float), _np(n), _np(x)
            y = np.cross(n, x)
            outline = self._shape_outline(pr["shape"], o, x, y) + n * self._eps()
            entry = dict(pr, plane=(o, x, y, n), face=face, outline=outline)
            fmesh, _, _ = tessellate(face, 0.05, 0.2)
            if fmesh is None:
                continue
            fmesh.points = fmesh.points + n * self._eps()
            actor = self.add_mesh(fmesh, color=SKETCH_FILL, opacity=0.35, reset_camera=False)
            self._scene_actors.append(actor)
            self._scene_actors.append(self.add_mesh(polyline_mesh([outline]), color=SKETCH_LINE, line_width=2.5,
                                                    pickable=False, reset_camera=False))
            self._profile_actor_map[actor] = (pr["uid"], pr["idx"])
            self.profiles.append(entry)
            if self._bounds is None:
                self._bounds = fmesh.bounds

        if tool is not None:
            tmesh, _, _ = tessellate(tool, 0.1, 0.3)
            if tmesh is not None:
                color = CUT if tool_mode == "cut" else ADD
                self._scene_actors.append(self.add_mesh(tmesh, color=color, opacity=0.3, pickable=False,
                                                        reset_camera=False))
        self._picker.InitializePickList()
        for a in [self._part_actor, *self._profile_actor_map]:
            if a is not None:
                self._picker.AddPickList(a)

        if keep_selection:
            keys = {self._key(p) for p in self._profile_items()}
            self.selection = [s for s in self.selection if s["kind"] == "profile" and self._key(s) in keys]
        else:
            self.selection = []
        self.hover = None
        self._refresh_highlights()
        self.selectionChanged.emit()
        if not self._has_fit and self._bounds is not None:
            self._has_fit = True
            self.fit()
        self.render()

    def _profile_items(self):
        return [{"kind": "profile", "uid": p["uid"], "idx": p["idx"]} for p in self.profiles]

    @staticmethod
    def _shape_outline(s, o, x, y):
        k = s["kind"]
        if k == "circle":
            t = np.linspace(0, 2 * math.pi, 73)
            uv = np.c_[s["c"][0] + s["r"] * np.cos(t), s["c"][1] + s["r"] * np.sin(t)]
        elif k == "rect":
            cx, cy, w, h = s["c"][0], s["c"][1], s["w"] / 2, s["h"] / 2
            uv = np.array([[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h], [cx - w, cy - h]])
        else:
            uv = np.array(list(s["pts"]) + [s["pts"][0]], float)
        return o + np.outer(uv[:, 0], x) + np.outer(uv[:, 1], y)

    def _eps(self):
        if self._bounds is None:
            return 0.02
        b = self._bounds
        return max(0.01, 0.0015 * math.dist((b[0], b[2], b[4]), (b[1], b[3], b[5])))

    # ------------------------------------------------------------ geometry
    def _display_size(self):
        w, h = self.renderer.GetSize()
        return max(w, 1), max(h, 1)

    def world_to_display(self, pts):
        pts = np.atleast_2d(np.asarray(pts, float))
        w, h = self._display_size()
        cam = self.renderer.GetActiveCamera()
        m = cam.GetCompositeProjectionTransformMatrix(w / h, -1, 1)
        M = np.array([[m.GetElement(i, j) for j in range(4)] for i in range(4)])
        P = np.c_[pts, np.ones(len(pts))] @ M.T
        P = P[:, :3] / P[:, 3:4]
        ox, oy = self.renderer.GetOrigin()
        return np.c_[(P[:, 0] + 1) * 0.5 * w + ox, (P[:, 1] + 1) * 0.5 * h + oy]

    def ray(self, x, y):
        r = self.renderer
        out = []
        for z in (0.0, 1.0):
            r.SetDisplayPoint(x, y, z)
            r.DisplayToWorld()
            p = np.array(r.GetWorldPoint())
            out.append(p[:3] / p[3])
        return out[0], out[1] - out[0]

    def pixel_size(self, point):
        cam = self.renderer.GetActiveCamera()
        _, h = self._display_size()
        if cam.GetParallelProjection():
            return 2 * cam.GetParallelScale() / h
        dist = np.linalg.norm(np.array(cam.GetPosition()) - point)
        return dist * 2 * math.tan(math.radians(cam.GetViewAngle()) / 2) / h

    @staticmethod
    def ray_plane(o, d, po, n):
        den = np.dot(d, n)
        if abs(den) < 1e-12:
            return None
        t = np.dot(po - o, n) / den
        return o + t * d

    # -------------------------------------------------------------- picking
    def pick(self, x, y):
        self._picker.Pick(x, y, 0, self.renderer)
        actor = self._picker.GetActor()
        hit = np.array(self._picker.GetPickPosition()) if actor is not None else None
        if actor is not None and actor in self._profile_actor_map:
            uid, idx = self._profile_actor_map[actor]
            return {"kind": "profile", "uid": uid, "idx": idx, "point": hit}
        eid = self._pick_edge(x, y, hit)
        if eid is not None:
            return {"kind": "edge", "eid": eid}
        if actor is not None and actor is self._part_actor and self.fids is not None:
            cid = self._picker.GetCellId()
            if 0 <= cid < len(self.fids):
                return {"kind": "face", "fid": int(self.fids[cid]), "point": hit}
        return None

    def _pick_edge(self, x, y, hit, px=8.0):
        if getattr(self, "_seg_a", None) is None:
            return None
        px *= self._scale
        m = np.array([x, y], float)
        a = self.world_to_display(self._seg_a)
        b = self.world_to_display(self._seg_b)
        ab = b - a
        l2 = np.maximum((ab * ab).sum(1), 1e-9)
        t = np.clip(((m - a) * ab).sum(1) / l2, 0, 1)
        dist = np.linalg.norm(a + ab * t[:, None] - m, axis=1)
        for k in np.argsort(dist)[:8]:
            if dist[k] > px:
                break
            if hit is not None:
                # visible only if the surface under the cursor touches this edge
                sa, sb = self._seg_a[k], self._seg_b[k]
                seg = sb - sa
                u = np.clip(np.dot(hit - sa, seg) / max(np.dot(seg, seg), 1e-12), 0, 1)
                if np.linalg.norm(sa + seg * u - hit) > self.pixel_size(hit) * 12:
                    continue  # hidden behind another surface
            return int(self._seg_owner[k])
        return None

    @staticmethod
    def _key(item):
        if item is None:
            return None
        if item["kind"] == "face":
            return ("face", item["fid"])
        if item["kind"] == "edge":
            return ("edge", item["eid"])
        return ("profile", item["uid"], item["idx"])

    def is_planar_face(self, fid):
        return 0 <= fid < len(self.faces) and self.faces[fid].geom_type == GeomType.PLANE

    # ------------------------------------------------------------ highlight
    def _item_actors(self, item, color, width, opacity):
        actors = []
        if item["kind"] == "face" and item["fid"] < len(self.faces) and self.part_mesh is not None:
            sub = self.part_mesh.extract_cells(np.where(self.fids == item["fid"])[0]).extract_surface(algorithm="dataset_surface")
            sub = sub.compute_normals(cell_normals=False, auto_orient_normals=False)
            sub.points = sub.points + sub.point_data["Normals"] * self._eps()
            actors.append(self.add_mesh(sub, color=color, opacity=opacity, pickable=False, reset_camera=False,
                                        lighting=False))
        elif item["kind"] == "edge" and item["eid"] < len(self.edge_lines):
            actors.append(self.add_mesh(polyline_mesh([self.edge_lines[item["eid"]]]), color=color,
                                        line_width=width, pickable=False, reset_camera=False,
                                        render_lines_as_tubes=True))
        elif item["kind"] == "profile":
            pr = self.profile_entry(item)
            if pr is not None:
                actors.append(self.add_mesh(polyline_mesh([pr["outline"]]), color=color, line_width=width,
                                            pickable=False, reset_camera=False, render_lines_as_tubes=True))
        return actors

    def profile_entry(self, item):
        return next((p for p in self.profiles if p["uid"] == item["uid"] and p["idx"] == item["idx"]), None)

    def _refresh_highlights(self):
        for a in self._sel_actors + self._hover_actors:
            self.remove_actor(a)
        self._sel_actors, self._hover_actors = [], []
        for it in self.selection:
            self._sel_actors += self._item_actors(it, SELECT, 7, 0.55)
        if self.hover is not None and self._key(self.hover) not in {self._key(s) for s in self.selection}:
            self._hover_actors = self._item_actors(self.hover, HOVER, 4, 0.4)
        self._update_arrow()

    def _set_hover(self, item):
        if self._key(item) == self._key(self.hover):
            return
        self.hover = item
        for a in self._hover_actors:
            self.remove_actor(a)
        self._hover_actors = []
        if item is not None and self._key(item) not in {self._key(s) for s in self.selection}:
            self._hover_actors = self._item_actors(item, HOVER, 4, 0.4)
        self.render()

    # ---------------------------------------------------------- pull arrow
    def pull_target(self):
        """(anchor, normal, faces) when the selection can be pulled, else None."""
        sel = self.selection
        if not sel:
            return None
        if all(s["kind"] == "profile" for s in sel) and len({s["uid"] for s in sel}) == 1:
            prs = [self.profile_entry(s) for s in sel]
            if None in prs:
                return None
            anchor = np.mean([_np(p["face"].center()) for p in prs], axis=0)
            return anchor, prs[0]["plane"][3], [p["face"] for p in prs]
        if all(s["kind"] == "face" for s in sel) and all(self.is_planar_face(s["fid"]) for s in sel):
            faces = [self.faces[s["fid"]] for s in sel]
            n0 = _np(faces[0].normal_at())
            if all(np.dot(_np(f.normal_at()), n0) > 0.999 for f in faces):
                anchor = sel[-1]["point"] if sel[-1].get("point") is not None else _np(faces[-1].center())
                return np.asarray(anchor, float), n0, faces
        return None

    def _update_arrow(self):
        if self._arrow_actor is not None:
            self.remove_actor(self._arrow_actor)
            self._arrow_actor = None
        self._arrow = None
        tgt = self.pull_target() if self.tool == "select" else None
        if tgt is None:
            return
        anchor, n, _ = tgt
        length = self.pixel_size(anchor) * 70
        arrow = pv.Arrow(start=anchor, direction=n, scale=length, tip_length=0.3, tip_radius=0.12,
                         shaft_radius=0.035)
        self._arrow_actor = self.add_mesh(arrow, color=SELECT, reset_camera=False, ambient=0.6, diffuse=0.5,
                                          specular=0.3)
        self._picker.AddPickList(self._arrow_actor)
        self._arrow = (anchor, n, length)

    # ------------------------------------------------------------ selection
    def clear_selection(self):
        if self.selection:
            self.selection = []
            self._refresh_highlights()
            self.selectionChanged.emit()
            self.render()
        self._emit_hint()

    def select_items(self, items):
        self.selection = list(items)
        self._refresh_highlights()
        self.selectionChanged.emit()
        self._emit_hint()
        self.render()

    def _click_select(self, item, additive):
        if item is None:
            if not additive:
                self.clear_selection()
            return
        key = self._key(item)
        keys = [self._key(s) for s in self.selection]
        if additive:
            if key in keys:
                self.selection.pop(keys.index(key))
            else:
                # keep a single kind of thing selected at once
                self.selection = [s for s in self.selection if s["kind"] == item["kind"]] + [item]
        else:
            self.selection = [item]
        self._refresh_highlights()
        self.selectionChanged.emit()
        self._emit_hint()
        self.render()

    # ----------------------------------------------------------------- tools
    def set_tool(self, tool):
        self._cancel_draw()
        self.tool = tool
        if tool in DRAW_TOOLS:
            self.draw = {"plane": None, "pts": [], "typed": "", "cursor": None}
            self.setCursor(Qt.CrossCursor)
        else:
            self.draw = None
            self.setCursor(Qt.ArrowCursor)
        self._refresh_highlights()
        self._emit_hint()
        self.toolChanged.emit(tool)
        self.render()

    def _emit_hint(self):
        if self.tool in DRAW_TOOLS:
            stage = 1 if self.draw and self.draw["pts"] else 0
            self.hintChanged.emit(HINTS[f"{self.tool}{stage}"])
        elif self.pull_target() is not None:
            self.hintChanged.emit(HINTS["select_pull"])
        elif self.selection and self.selection[0]["kind"] == "edge":
            self.hintChanged.emit(HINTS["select_edge"])
        else:
            self.hintChanged.emit(HINTS["select"])

    def _cancel_draw(self):
        for a in self._draw_actors:
            self.remove_actor(a)
        self._draw_actors = []
        self._label.SetVisibility(False)
        if self.draw is not None:
            self.draw.update(plane=None, pts=[], typed="", fid=None)

    def _plane_under(self, x, y):
        """Sketch plane under the cursor: a planar face or the print bed."""
        item = self.pick(x, y)
        if item and item["kind"] == "face" and self.is_planar_face(item["fid"]):
            f = self.faces[item["fid"]]
            n = _np(f.normal_at())
            o = np.round(_np(f.center()), 6)
            return (o, n), item
        if item and item["kind"] == "profile":
            pr = self.profile_entry(item)
            return (pr["plane"][0], pr["plane"][3]), None
        return (np.zeros(3), np.array([0.0, 0.0, 1.0])), None

    @staticmethod
    def _frame(o, n):
        nn, x = plane_axes(n)
        n, x = _np(nn), _np(x)
        return o, x, np.cross(n, x), n

    def _snap_points(self, frame, fid=None):
        """Points worth snapping to on this sketch plane: face centre, corners,
        edge midpoints, hole centres and the points of coplanar sketches."""
        o, ax, ay, n = frame
        key = (tuple(np.round(o, 5)), tuple(np.round(n, 5)), fid)
        if getattr(self, "_snap_key", None) == key:
            return self._snap_cache
        pts = [o]
        faces = [self.faces[fid]] if fid is not None and fid < len(self.faces) else []
        for f in faces:
            for v in f.vertices():
                pts.append(_np(v.center()))
            for e in f.edges():
                pts.append(_np(e.position_at(0.5)))
                if e.geom_type == GeomType.CIRCLE:
                    try:
                        pts.append(_np(e.arc_center))
                    except Exception:
                        pass
        for pr in self.profiles:
            po, _px, _py, pn = pr["plane"]
            if np.dot(pn, n) > 0.9999 and abs(np.dot(po - o, n)) < 1e-6:
                pts.append(_np(pr["face"].center()))
                pts.extend(pr["outline"][:-1:max(1, len(pr["outline"]) // 4)])
        pts = np.array(pts, float)
        uv = np.c_[(pts - o) @ ax, (pts - o) @ ay]
        on_plane = np.abs((pts - o) @ n) < 1e-3 + self._eps() * 3
        self._snap_key, self._snap_cache = key, uv[on_plane]
        return self._snap_cache

    def _cursor_uv(self, x, y, frame, fine, fid=None):
        o, ax, ay, n = frame
        ro, rd = self.ray(x, y)
        p = self.ray_plane(ro, rd, o, n)
        if p is None:
            return None
        uv = np.array([np.dot(p - o, ax), np.dot(p - o, ay)])
        self._snapped = False
        if not fine:
            cands = self._snap_points(frame, fid)
            if len(cands):
                scr = self.world_to_display(o + np.outer(cands[:, 0], ax) + np.outer(cands[:, 1], ay))
                dist = np.linalg.norm(scr - [x, y], axis=1)
                k = int(np.argmin(dist))
                if dist[k] < 12 * self._scale:
                    self._snapped = True
                    return cands[k].copy()
        step = 0.1 if fine else self.snap
        if step > 0:
            uv = np.round(uv / step) * step + 0.0
        return uv

    def _uv_world(self, frame, uv):
        o, ax, ay, n = frame
        uv = np.atleast_2d(uv)
        return o + np.outer(uv[:, 0], ax) + np.outer(uv[:, 1], ay) + n * self._eps() * 2

    def _draw_move(self, x, y, fine):
        d = self.draw
        if d["plane"] is None:
            (o, n), item = self._plane_under(x, y)
            frame = self._frame(o, n)
            self._set_hover(item)
            fid = item["fid"] if item else None
        else:
            frame = d["plane"]
            fid = d.get("fid")
        uv = self._cursor_uv(x, y, frame, fine, fid)
        if uv is None:
            return
        d["cursor"] = uv
        self._render_draw(frame, uv, x, y)

    def _render_draw(self, frame, cur, x, y):
        d = self.draw
        for a in self._draw_actors:
            self.remove_actor(a)
        self._draw_actors = []
        pts = d["pts"]
        shape = self._pending_shape(cur)
        label = ""
        if shape is not None:
            o, ax, ay, n = frame
            outline = self._shape_outline(shape, o, ax, ay) + n * self._eps() * 2
            self._draw_actors.append(self.add_mesh(polyline_mesh([outline]), color=SKETCH_LINE, line_width=3,
                                                   pickable=False, reset_camera=False))
            if shape["kind"] == "circle":
                label = f"D {shape['r'] * 2:.1f} mm"
            elif shape["kind"] == "rect":
                label = f"{shape['w']:.1f} x {shape['h']:.1f} mm"
        if self.tool == "poly" and pts:
            chain = np.array(pts + [list(cur)])
            self._draw_actors.append(self.add_mesh(polyline_mesh([self._uv_world(frame, chain)]),
                                                   color=SKETCH_LINE, line_width=3, pickable=False,
                                                   reset_camera=False))
            seg = np.array(cur) - np.array(pts[-1])
            label = f"{np.linalg.norm(seg):.1f} mm"
        marker = pv.PolyData(self._uv_world(frame, cur))
        snapped = getattr(self, "_snapped", False)
        self._draw_actors.append(self.add_mesh(marker, color=ADD if snapped else SELECT,
                                               point_size=16 if snapped else 11, render_points_as_spheres=True,
                                               pickable=False, reset_camera=False))
        if d["typed"]:
            label = {"circle": "D = ", "rect": "W,H = "}.get(self.tool, "") + d["typed"] + "_"
        if label:
            self._label.SetInput(label)
            self._label.SetDisplayPosition(int(x) + 18, int(y) + 14)
            self._label.SetVisibility(True)
        else:
            self._label.SetVisibility(False)
        self.render()

    def _pending_shape(self, cur):
        d = self.draw
        pts = d["pts"]
        if not pts or cur is None:
            return None
        a, b = np.array(pts[0]), np.array(cur)
        if self.tool == "circle":
            r = float(np.linalg.norm(b - a))
            return {"kind": "circle", "c": [float(a[0]), float(a[1])], "r": r} if r > 1e-6 else None
        if self.tool == "rect":
            w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
            if w < 1e-6 or h < 1e-6:
                return None
            c = (a + b) / 2
            return {"kind": "rect", "c": [float(c[0]), float(c[1])], "w": float(w), "h": float(h)}
        return None

    def _draw_click(self, x, y, fine):
        d = self.draw
        if d["plane"] is None:
            (o, n), item = self._plane_under(x, y)
            d["plane"] = self._frame(o, n)
            d["fid"] = item["fid"] if item else None
            self._set_hover(None)
        uv = self._cursor_uv(x, y, d["plane"], fine, d.get("fid"))
        if uv is None:
            return
        if not d["pts"]:
            d["pts"].append([float(uv[0]), float(uv[1])])
            self._emit_hint()
            self._render_draw(d["plane"], uv, x, y)
            return
        if self.tool in ("circle", "rect"):
            shape = self._pending_shape(uv)
            if shape is not None:
                self._commit(shape)
            return
        # polygon
        first = self.world_to_display(self._uv_world(d["plane"], d["pts"][0]))[0]
        if len(d["pts"]) >= 3 and np.linalg.norm(first - [x, y]) < 12 * self._scale:
            self._commit({"kind": "poly", "pts": [list(p) for p in d["pts"]]})
            return
        if np.linalg.norm(np.array(d["pts"][-1]) - uv) > 1e-6:
            d["pts"].append([float(uv[0]), float(uv[1])])
        self._render_draw(d["plane"], uv, x, y)

    def _commit(self, shape):
        o, ax, ay, n = self.draw["plane"]
        plane = {"origin": [float(v) for v in o], "normal": [float(v) for v in n]}
        self._cancel_draw()
        self.shapeDrawn.emit(plane, shape)

    def _typed_commit(self):
        d = self.draw
        txt = d["typed"].replace("x", ",").replace("X", ",").replace("*", ",")
        d["typed"] = ""
        try:
            vals = [float(v) for v in txt.split(",") if v.strip()]
        except ValueError:
            return
        if not vals or not d["pts"]:
            return
        a = np.array(d["pts"][0])
        cur = d["cursor"] if d["cursor"] is not None else a + 1
        if self.tool == "circle" and vals[0] > 0:
            self._commit({"kind": "circle", "c": list(map(float, a)), "r": vals[0] / 2})
        elif self.tool == "rect":
            w = vals[0]
            h = vals[1] if len(vals) > 1 else vals[0]
            sx = 1.0 if cur[0] >= a[0] else -1.0
            sy = 1.0 if cur[1] >= a[1] else -1.0
            c = a + np.array([sx * w / 2, sy * h / 2])
            if w > 0 and h > 0:
                self._commit({"kind": "rect", "c": [float(c[0]), float(c[1])], "w": w, "h": h})

    # --------------------------------------------------------------- events
    # All mouse input comes straight from Qt; VTK never sees it, so its
    # interactor style can never move the camera or swallow events.
    def _xy(self, ev):
        """Qt logical widget coords -> VTK display coords (physical pixels)."""
        pos = ev.position()
        w, h = self._display_size()
        sx = w / max(self.width(), 1)
        sy = h / max(self.height(), 1)
        self._scale = sx
        return pos.x() * sx, (self.height() - pos.y()) * sy

    @staticmethod
    def _mods(ev):
        m = ev.modifiers()
        return bool(m & Qt.ShiftModifier), bool(m & (Qt.ControlModifier | Qt.MetaModifier))

    def mousePressEvent(self, ev):  # noqa: N802 - Qt API
        x, y = self._xy(ev)
        shift, ctrl = self._mods(ev)
        self.setFocus()
        self._press = (x, y)
        self._last = ev.position()
        b = ev.button()
        if b == Qt.LeftButton:
            self._left_down(x, y, shift, ctrl)
        elif b == Qt.RightButton:
            self._mode = "pan" if shift else "orbit_right"
            self._set_pivot(x, y)
        elif b == Qt.MiddleButton:
            self._mode = "pan"
            self._set_pivot(x, y)
        ev.accept()

    def mouseDoubleClickEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton and self.tool == "poly" and self.draw and len(self.draw["pts"]) >= 3:
            self._commit({"kind": "poly", "pts": [list(p) for p in self.draw["pts"]]})
            ev.accept()
            return
        self.mousePressEvent(ev)

    def mouseMoveEvent(self, ev):  # noqa: N802
        x, y = self._xy(ev)
        shift, _ctrl = self._mods(ev)
        pos = ev.position()
        last = getattr(self, "_last", None) or pos
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        self._last = pos
        mode = self._mode
        if mode in ("orbit_left", "orbit_right"):
            self._orbit(dx, dy)
        elif mode == "pan":
            self._pan(dx, dy)
        elif mode == "pull":
            self._drag_pull(x, y, shift)
        elif self.tool in DRAW_TOOLS:
            self._draw_move(x, y, shift)
        else:
            self._hover_at(x, y)
        ev.accept()

    def mouseReleaseEvent(self, ev):  # noqa: N802
        x, y = self._xy(ev)
        moved = self._press is not None and math.dist(self._press, (x, y)) > 4 * self._scale
        mode, self._mode = self._mode, None
        if mode == "orbit_left" and not moved:
            self.clear_selection()
        elif mode == "orbit_right" and not moved:
            self.escape()
        elif mode == "pull":
            self._finish_pull()
        if mode in ("orbit_left", "orbit_right", "pan"):
            self._update_arrow()
            self.render()
        ev.accept()

    def wheelEvent(self, ev):  # noqa: N802
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if delta:
            pos = ev.position()
            w, h = self._display_size()
            x = pos.x() * w / max(self.width(), 1)
            y = (self.height() - pos.y()) * h / max(self.height(), 1)
            self._zoom(x, y, 1.15 ** (delta / 120.0))
        ev.accept()

    def leaveEvent(self, ev):  # noqa: N802
        if self._mode is None:
            self._set_hover(None)
        super().leaveEvent(ev)

    def _hover_at(self, x, y):
        item = self._pick_with_handle(x, y)
        if item == "handle":
            self.setCursor(Qt.SizeVerCursor)
            self._set_hover(None)
            return
        self.setCursor(Qt.PointingHandCursor if item is not None else Qt.ArrowCursor)
        self._set_hover(item)

    def _left_down(self, x, y, shift, ctrl):
        if self.tool in DRAW_TOOLS:
            self._draw_click(x, y, shift)
            return
        item = self._pick_with_handle(x, y)
        selected = item not in (None, "handle") and self._key(item) in {self._key(s) for s in self.selection}
        if item == "handle" or (selected and self.pull_target() is not None and not (shift or ctrl)):
            self._start_pull(x, y)
            return
        if item is None:
            self._mode = "orbit_left"
            self._set_pivot(x, y)
            return
        self._click_select(item, shift or ctrl)

    def _pick_with_handle(self, x, y):
        if self._arrow_actor is not None:
            self._picker.Pick(x, y, 0, self.renderer)
            if self._picker.GetActor() is self._arrow_actor:
                return "handle"
        return self.pick(x, y)

    # ------------------------------------------------------------- camera
    def _set_pivot(self, x, y):
        """Orbit around the point under the cursor (or the model centre)."""
        self._picker.Pick(x, y, 0, self.renderer)
        if self._picker.GetActor() is not None:
            self._pivot = np.array(self._picker.GetPickPosition())
        elif self._bounds is not None:
            b = self._bounds
            self._pivot = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        else:
            self._pivot = np.array(self.renderer.GetActiveCamera().GetFocalPoint())

    @staticmethod
    def _rot(axis, deg):
        axis = np.asarray(axis, float)
        axis = axis / np.linalg.norm(axis)
        a = math.radians(deg)
        k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        return np.eye(3) + math.sin(a) * k + (1 - math.cos(a)) * (k @ k)

    def _orbit(self, dx, dy):
        """Turntable orbit: Z always stays up, like Shapr3D (no tilting)."""
        cam = self.renderer.GetActiveCamera()
        pos, fp = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())
        pivot = getattr(self, "_pivot", fp)
        z = np.array([0.0, 0.0, 1.0])
        rz = self._rot(z, -dx * 0.35)
        pos, fp = pivot + rz @ (pos - pivot), pivot + rz @ (fp - pivot)
        view = (fp - pos) / np.linalg.norm(fp - pos)
        right = np.cross(view, z)
        if np.linalg.norm(right) > 1e-6:
            re = self._rot(right, -dy * 0.35)
            new_view = re @ view
            if abs(np.dot(new_view, z)) < 0.995:  # never flip over the top
                pos, fp = pivot + re @ (pos - pivot), pivot + re @ (fp - pivot)
        cam.SetPosition(*pos)
        cam.SetFocalPoint(*fp)
        cam.SetViewUp(0, 0, 1)
        cam.OrthogonalizeViewUp()
        self.renderer.ResetCameraClippingRange()
        self.render()

    def _pan(self, dx, dy):
        cam = self.renderer.GetActiveCamera()
        pos, fp = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())
        view = (fp - pos) / np.linalg.norm(fp - pos)
        up = np.array(cam.GetViewUp())
        right = np.cross(view, up)
        step = self.pixel_size(fp) * self._scale
        delta = (-dx * right + dy * up) * step
        cam.SetPosition(*(pos + delta))
        cam.SetFocalPoint(*(fp + delta))
        self.renderer.ResetCameraClippingRange()
        self.render()

    def _zoom(self, x, y, factor):
        """Zoom towards the point under the cursor."""
        cam = self.renderer.GetActiveCamera()
        pos, fp = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())
        o, d = self.ray(x, y)
        view = fp - pos
        p = self.ray_plane(o, d, fp, view / np.linalg.norm(view))
        if p is None:
            p = fp
        if cam.GetParallelProjection():
            cam.SetParallelScale(cam.GetParallelScale() / factor)
            shift = (p - fp) * (1 - 1 / factor)
            cam.SetPosition(*(pos + shift))
            cam.SetFocalPoint(*(fp + shift))
        else:
            cam.SetPosition(*(p + (pos - p) / factor))
            cam.SetFocalPoint(*(p + (fp - p) / factor))
        self.renderer.ResetCameraClippingRange()
        if self._arrow is not None:
            self._update_arrow()
        self.render()

    def set_parallel(self, on: bool):
        self.renderer.GetActiveCamera().SetParallelProjection(bool(on))
        self.fit()

    def escape(self):
        if self.tool in DRAW_TOOLS:
            if self.draw and self.draw["pts"]:
                self._cancel_draw()
                self._emit_hint()
                self.render()
            else:
                self.set_tool("select")
        else:
            self.clear_selection()

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        k = event.key()
        if k == Qt.Key_Escape:
            self.escape()
            return
        d = self.draw
        if self.tool in DRAW_TOOLS and d is not None:
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if d["typed"]:
                    self._typed_commit()
                elif self.tool == "poly" and len(d["pts"]) >= 3:
                    self._commit({"kind": "poly", "pts": [list(p) for p in d["pts"]]})
                return
            if k == Qt.Key_Backspace:
                if d["typed"]:
                    d["typed"] = d["typed"][:-1]
                elif self.tool == "poly" and len(d["pts"]) > 1:
                    d["pts"].pop()
                elif d["pts"]:
                    self._cancel_draw()
                    self._emit_hint()
                self._refresh_draw()
                return
            txt = event.text()
            if d["pts"] and txt and txt in "0123456789.,xX*":
                d["typed"] += txt
                self._refresh_draw()
                return
        event.ignore()  # let the window handle shortcuts; never pass to VTK key bindings

    def _refresh_draw(self):
        d = self.draw
        if d and d["plane"] is not None and d["cursor"] is not None:
            p = self.world_to_display(self._uv_world(d["plane"], d["cursor"]))[0]
            self._render_draw(d["plane"], d["cursor"], p[0], p[1])
        else:
            self.render()

    def enterEvent(self, event):  # noqa: N802
        self.setFocus()
        super().enterEvent(event)

    # ----------------------------------------------------------------- pull
    def _line_param(self, x, y, anchor, n):
        """Parameter t of the point on the 3D line anchor + t*n closest to the
        mouse ray: exact distance along the arrow, independent of perspective."""
        o, d = self.ray(x, y)
        d = d / np.linalg.norm(d)
        w0 = anchor - o
        b = np.dot(n, d)
        denom = 1.0 - b * b
        if denom < 1e-6:  # looking straight along the arrow
            return None
        return (b * np.dot(d, w0) - np.dot(n, w0)) / denom

    def _start_pull(self, x, y):
        tgt = self.pull_target()
        if tgt is None or self._arrow is None:
            return
        anchor, n, faces = tgt
        n = n / np.linalg.norm(n)
        t0 = self._line_param(x, y, anchor, n)
        self._mode = "pull"
        self._pull = {"start": np.array([x, y], float), "t0": t0, "n": n, "faces": faces, "d": 0.0,
                      "anchor": anchor, "len": self._arrow[2]}

    def _drag_pull(self, x, y, fine=False):
        p = self._pull
        t = self._line_param(x, y, p["anchor"], p["n"])
        if t is None or p["t0"] is None:  # fall back to screen-space movement
            s = self.world_to_display([p["anchor"], p["anchor"] + p["n"] * p["len"]])
            sdir = s[1] - s[0]
            if np.dot(sdir, sdir) < 4:
                sdir = np.array([0.0, 60.0])
            m = np.array([x, y], float) - p["start"]
            raw = np.dot(m, sdir) / np.dot(sdir, sdir) * p["len"]
        else:
            raw = t - p["t0"]
        step = 0.1 if fine else max(self.snap, 0.1)
        d = round(raw / step) * step
        if abs(d - p["d"]) < 1e-9:
            return
        p["d"] = d
        for a in self._preview_actors:
            self.remove_actor(a)
        self._preview_actors = []
        if abs(d) > 1e-9:
            try:
                tool = None
                for f in p["faces"]:
                    t_ = extrude(f, amount=abs(d), dir=tuple(p["n"] * (1 if d > 0 else -1)))
                    tool = t_ if tool is None else tool + t_
                mesh, _, _ = tessellate(tool, 0.1, 0.3)
                if mesh is not None:
                    self._preview_actors.append(self.add_mesh(mesh, color=ADD if d > 0 else CUT, opacity=0.45,
                                                              pickable=False, reset_camera=False))
            except Exception:
                pass
        self._label.SetInput(f"{d:+.1f} mm" if d > 0 else f"{d:.1f} mm  (cut)")
        self._label.SetDisplayPosition(int(x) + 18, int(y) + 14)
        self._label.SetVisibility(True)
        self.render()

    def _finish_pull(self):
        for a in self._preview_actors:
            self.remove_actor(a)
        self._preview_actors = []
        self._label.SetVisibility(False)
        p, self._pull = self._pull, None
        self.render()
        if p and abs(p["d"]) > 1e-9:
            self.pullDragged.emit(list(self.selection), float(p["d"]))

    # ----------------------------------------------------------------- view
    def fit(self):
        if self._bounds is not None:
            self.reset_camera(bounds=self._bounds)
        else:
            self.reset_camera()
        self._update_arrow()
        self.render()

    def set_view(self, name: str, normal=None):
        vecs = {"iso": ((1, -1.4, 1.0), (0, 0, 1)), "top": ((0, 0, 1), (0, 1, 0)),
                "front": ((0, -1, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 0, 1)),
                "back": ((0, 1, 0), (0, 0, 1)), "left": ((-1, 0, 0), (0, 0, 1)),
                "bottom": ((0, 0, -1), (0, -1, 0))}
        if name == "normal" and normal is not None:
            n = np.asarray(normal, float)
            up = (0, 1, 0) if abs(n[2]) > 0.99 else (0, 0, 1)
            self.view_vector(tuple(n), viewup=up)
        else:
            v, up = vecs[name]
            self.view_vector(v, viewup=up)
        self.fit()
