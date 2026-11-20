"""Interactive 3D viewport.

Two modes, like a direct-modelling CAD app:

* Modeling – hover/click faces, edges and sketch regions; drag the arrow to
  extrude or cut. Double-click a planar face (or the bed) to sketch on it.
* Sketching – the camera looks straight at the sketch plane, a grid appears,
  and the drawing tools snap to points, lines, grid and horizontal/vertical
  alignments. A live dimension box follows the cursor; type to set it exactly.

Mouse: left = select / draw / drag arrow · right-drag = orbit (turntable) ·
middle-drag or Shift+right-drag = pan · wheel = zoom to cursor.
All input comes from Qt; VTK never receives mouse events.
"""
from __future__ import annotations

import math

import numpy as np
import pyvista as pv
from build123d import GeomType, extrude, fillet
from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleUser
from vtkmodules.vtkRenderingCore import vtkCellPicker, vtkTextActor

from ..model import make_plane, plane_axes, shape_face

# --- colours (dark studio) ---------------------------------------------------
BG_TOP = "#26282d"
BG_BOTTOM = "#18191c"
PART = "#c9ccd1"
EDGE = "#2a2c31"
HOVER = "#7fb2ff"
SELECT = "#3d8bff"
SKETCH_FILL = "#ffb02e"
SKETCH_LINE = "#ffb02e"
SKETCH_VERTEX = "#b07cff"
ADD = "#2fbf71"
CUT = "#ff5a4e"
BED_PLATE = "#2b2d32"
BED_GRID = "#3a3d44"
GRID_MINOR = "#5a5e66"
GRID_MAJOR = "#8a8f99"
AXIS_U = "#e5484d"
AXIS_V = "#3d8bff"
SNAP_POINT = "#b07cff"
SNAP_LINE = "#3d8bff"

SKETCH_TOOLS = ("line", "rect", "circle", "polygon", "slot")
TOOL_NAMES = {"select": "Select", "line": "Line", "rect": "Rectangle", "circle": "Circle",
              "polygon": "Polygon", "slot": "Slot"}


def _k(key):
    return f'<span style="background:#3a3d44; color:#ffffff;">&nbsp;{key}&nbsp;</span>'


HINTS = {
    "model": f"Click a face, edge or sketch region to select it. Double-click a face to sketch on it. "
             f"Right-drag to orbit, middle-drag to pan, scroll to zoom.",
    "model_pull": f"Drag the blue arrow up to add material or down to cut. Hold {_k('Shift')} for 0.1 mm steps.",
    "model_edge": f"Drag the arrow to round the edge, or type a size and choose Fillet or Chamfer. "
                  f"{_k('Shift')}+click to add edges.",
    "pick_plane": f"Click a face or the grid to start sketching. {_k('Esc')} to cancel.",
    "sketch": f"Pick a tool on the left, or click a shape to select it. {_k('Delete')} removes it. "
              f"{_k('Esc')} exits sketching.",
    "line0": f"Place the line's start point.",
    "line1": f"Place the line's endpoints. Click the first point to close the shape. "
             f"To finish, press {_k('Enter')}. To cancel the last segment, press {_k('Esc')}.",
    "rect0": "Place the first corner of the rectangle.",
    "rect1": f"Place the opposite corner, or type width,height and press {_k('Enter')}.",
    "circle0": "Place the center of the circle.",
    "circle1": f"Set the size, or type the diameter and press {_k('Enter')}.",
    "polygon0": "Place the center of the polygon.",
    "polygon1": f"Set the size and rotation, or type the radius and press {_k('Enter')}.",
    "slot0": "Place the center of the slot's first end.",
    "slot1": f"Place the center of the other end, or type the length and press {_k('Enter')}.",
    "slot2": f"Set the slot width, or type it and press {_k('Enter')}.",
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
        if len(ln) < 2:
            continue
        pts.append(ln)
        cells.append(np.concatenate([[len(ln)], np.arange(off, off + len(ln))]))
        off += len(ln)
    if not pts:
        return None
    return pv.PolyData(np.vstack(pts), lines=np.concatenate(cells))


def shape_outline_uv(s):
    """Outline of a sketch shape in plane (u, v) coordinates."""
    k = s["kind"]
    if k == "circle":
        t = np.linspace(0, 2 * math.pi, 97)
        return np.c_[s["c"][0] + s["r"] * np.cos(t), s["c"][1] + s["r"] * np.sin(t)]
    if k == "rect":
        cx, cy, w, h = s["c"][0], s["c"][1], s["w"] / 2, s["h"] / 2
        return np.array([[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h], [cx - w, cy - h]])
    if k == "ngon":
        n = int(s["n"])
        t = np.radians(s.get("rot", 0.0)) + np.linspace(0, 2 * math.pi, n + 1)
        return np.c_[s["c"][0] + s["r"] * np.cos(t), s["c"][1] + s["r"] * np.sin(t)]
    if k == "slot":
        a, b = np.array(s["c1"], float), np.array(s["c2"], float)
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-9:
            return np.array([a, a])
        d /= L
        nrm = np.array([-d[1], d[0]])
        r = s["w"] / 2
        base = math.atan2(nrm[1], nrm[0])
        arc_b = [b + r * np.array([math.cos(base - t), math.sin(base - t)]) for t in np.linspace(0, math.pi, 25)]
        arc_a = [a + r * np.array([math.cos(base + math.pi - t), math.sin(base + math.pi - t)])
                 for t in np.linspace(0, math.pi, 25)]
        pts = arc_b + arc_a
        return np.array(pts + [pts[0]])
    if k == "path":
        return np.array(s["pts"], float)
    pts = list(s["pts"])
    return np.array(pts + [pts[0]], float)


def shape_points_uv(s):
    """Characteristic points of a sketch shape (vertices, centres, midpoints)."""
    k = s["kind"]
    if k in ("circle", "ngon"):
        c = np.array(s["c"], float)
        pts = [c]
        if k == "circle":
            pts += [c + s["r"] * np.array(v) for v in ((1, 0), (0, 1), (-1, 0), (0, -1))]
        else:
            pts += list(shape_outline_uv(s)[:-1])
        return np.array(pts)
    if k == "slot":
        return np.array([s["c1"], s["c2"], (np.array(s["c1"]) + np.array(s["c2"])) / 2], float)
    out = shape_outline_uv(s)
    pts = list(out)
    pts += [(out[i] + out[i + 1]) / 2 for i in range(len(out) - 1)]
    if k == "rect":
        pts.append(np.array(s["c"], float))
    return np.array(pts, float)


class Viewport(QtInteractor):
    selectionChanged = Signal()
    shapeDrawn = Signal(object, object)  # plane {"origin","normal"}, shape dict
    pullDragged = Signal(object, float)  # selection items, distance
    roundDragged = Signal(object, float)  # edge selection, fillet radius
    hintChanged = Signal(str)
    toolChanged = Signal(str)
    modeChanged = Signal(str)  # "model" | "sketch"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_background(BG_BOTTOM, top=BG_TOP)
        try:
            self.enable_anti_aliasing("msaa")
        except Exception:
            pass
        self.add_axes(interactive=False, line_width=2, color="#c9ccd1")
        self.setFocusPolicy(Qt.StrongFocus)

        self.bed_size = (220.0, 220.0)
        self.show_bed = True
        self.show_edges = True
        self.snap = 0.0  # 0 = follow the visible grid
        self.polygon_sides = 6
        self.animate = True

        self.part = None
        self.part_mesh = None
        self.fids = None
        self.faces = []
        self.edges = []
        self.edge_lines = []
        self.profiles = []  # dicts: uid, idx, origin, normal, shape, plane, face, outline
        self.selection: list[dict] = []
        self.hover: dict | None = None
        self.mode = "model"
        self.tool = "select"
        self.pending_tool = None  # sketch tool waiting for a plane to be picked
        self.sketch = None  # {"frame": (o, x, y, n), "fid": int | None, "parallel": bool}
        self.draw = None
        self.grid_step = 1.0
        self._bounds = None
        self._has_fit = False

        self._scene_actors = []
        self._bed_actors = []
        self._grid_actors = []
        self._profile_actor_map = {}
        self._part_actor = None
        self._hover_actors = []
        self._sel_actors = []
        self._arrow_actor = None
        self._arrow = None
        self._draw_actors = []
        self._preview_actors = []
        self._press = None
        self._mode = None  # drag state: None | "orbit_left" | "orbit_right" | "pan" | "pull"
        self._pull = None
        self._round = None
        self._arrow_kind = "pull"
        self._snap_info = None
        self._seg_a = None

        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.0005)
        self._picker.PickFromListOn()

        self._label = vtkTextActor()
        tp = self._label.GetTextProperty()
        tp.SetFontSize(15)
        tp.SetFontFamilyToCourier()
        tp.SetColor(1, 1, 1)
        tp.SetBackgroundColor(0.07, 0.08, 0.1)
        tp.SetBackgroundOpacity(0.92)
        tp.SetFrame(True)
        tp.SetFrameColor(0.24, 0.55, 1.0)
        tp.BoldOn()
        self._label.SetVisibility(False)
        self.renderer.AddViewProp(self._label)

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
                                              ambient=0.7, diffuse=0.3))
        if self.mode != "sketch":
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
        self._snap_key = None
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
            self._part_actor = self.add_mesh(shaded, color=PART, smooth_shading=True, specular=0.2,
                                             specular_power=20, ambient=0.3, diffuse=0.75, reset_camera=False)
            self._scene_actors.append(self._part_actor)
            self._bounds = self.part_mesh.bounds
            if self.show_edges and self.edge_lines:
                self._scene_actors.append(self.add_mesh(polyline_mesh(self.edge_lines), color=EDGE,
                                                        line_width=1.4, pickable=False, reset_camera=False))
        else:
            self._bounds = None

        self.profiles = []
        vertex_pts = []
        for pr in profiles:
            n, x = plane_axes(pr["normal"])
            o, n, x = np.array(pr["origin"], float), _np(n), _np(x)
            y = np.cross(n, x)
            try:
                uv = shape_outline_uv(pr["shape"])
            except Exception:
                continue
            lift = n * self._eps()
            outline = o + np.outer(uv[:, 0], x) + np.outer(uv[:, 1], y) + lift
            face = None
            if pr["shape"]["kind"] != "path":
                try:
                    face = shape_face(make_plane({"origin": pr["origin"], "normal": pr["normal"]}), pr["shape"])
                except Exception:
                    face = None
            entry = dict(pr, plane=(o, x, y, n), face=face, outline=outline)
            if face is not None:
                fmesh, _, _ = tessellate(face, 0.05, 0.2)
                if fmesh is not None:
                    fmesh.points = fmesh.points + lift
                    actor = self.add_mesh(fmesh, color=SKETCH_FILL, opacity=0.22, reset_camera=False,
                                          lighting=False)
                    self._scene_actors.append(actor)
                    self._profile_actor_map[actor] = (pr["uid"], pr["idx"])
                    if self._bounds is None:
                        self._bounds = fmesh.bounds
            self._scene_actors.append(self.add_mesh(polyline_mesh([outline]), color=SKETCH_LINE, line_width=2,
                                                    pickable=False, reset_camera=False))
            spts = shape_points_uv(pr["shape"])
            if pr["shape"]["kind"] not in ("circle",):
                vertex_pts.append(o + np.outer(spts[:, 0], x) + np.outer(spts[:, 1], y) + lift * 2)
            self.profiles.append(entry)
        if vertex_pts and self.mode == "sketch":
            self._scene_actors.append(self.add_mesh(pv.PolyData(np.vstack(vertex_pts)), color=SKETCH_VERTEX,
                                                    point_size=7, render_points_as_spheres=True, pickable=False,
                                                    reset_camera=False))

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
            keys = {("profile", p["uid"], p["idx"]) for p in self.profiles}
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
        """Face, edge or sketch region under the cursor (ignores the arrow)."""
        arrow = self._arrow_actor
        if arrow is not None:
            self._picker.DeletePickList(arrow)
        self._picker.Pick(x, y, 0, self.renderer)
        if arrow is not None:
            self._picker.AddPickList(arrow)
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
        if self._seg_a is None:
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
                sa, sb = self._seg_a[k], self._seg_b[k]
                seg = sb - sa
                u = np.clip(np.dot(hit - sa, seg) / max(np.dot(seg, seg), 1e-12), 0, 1)
                if np.linalg.norm(sa + seg * u - hit) > self.pixel_size(hit) * 12:
                    continue  # hidden behind another surface
            return int(self._seg_owner[k])
        return None

    def _pick_sketch_shape(self, x, y, px=9.0):
        """Sketch shape whose outline is nearest the cursor (sketch mode)."""
        best = None
        m = np.array([x, y], float)
        for pr in self.profiles:
            if not self._on_sketch_plane(pr):
                continue
            s = self.world_to_display(pr["outline"])
            a, b = s[:-1], s[1:]
            ab = b - a
            l2 = np.maximum((ab * ab).sum(1), 1e-9)
            t = np.clip(((m - a) * ab).sum(1) / l2, 0, 1)
            d = float(np.min(np.linalg.norm(a + ab * t[:, None] - m, axis=1)))
            if d < px * self._scale and (best is None or d < best[0]):
                best = (d, pr)
        if best is None:
            item = self.pick(x, y)
            return item if item and item["kind"] == "profile" else None
        return {"kind": "profile", "uid": best[1]["uid"], "idx": best[1]["idx"], "point": None}

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

    def profile_entry(self, item):
        return next((p for p in self.profiles if p["uid"] == item["uid"] and p["idx"] == item["idx"]), None)

    # ------------------------------------------------------------ highlight
    def _item_actors(self, item, color, width, opacity):
        actors = []
        if item["kind"] == "face" and item["fid"] < len(self.faces) and self.part_mesh is not None:
            sub = self.part_mesh.extract_cells(np.where(self.fids == item["fid"])[0])
            sub = sub.extract_surface(algorithm="dataset_surface")
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

    def _refresh_highlights(self):
        for a in self._sel_actors + self._hover_actors:
            self.remove_actor(a)
        self._sel_actors, self._hover_actors = [], []
        for it in self.selection:
            self._sel_actors += self._item_actors(it, SELECT, 6, 0.5)
        if self.hover is not None and self._key(self.hover) not in {self._key(s) for s in self.selection}:
            self._hover_actors = self._item_actors(self.hover, HOVER, 4, 0.35)
        self._update_arrow()

    def _set_hover(self, item):
        if self._key(item) == self._key(self.hover):
            return
        self.hover = item
        for a in self._hover_actors:
            self.remove_actor(a)
        self._hover_actors = []
        if item is not None and self._key(item) not in {self._key(s) for s in self.selection}:
            self._hover_actors = self._item_actors(item, HOVER, 4, 0.35)
        self.render()

    # ---------------------------------------------------------- pull arrow
    def pull_target(self):
        """(anchor, normal, faces) when the selection can be pulled, else None."""
        sel = self.selection
        if not sel or self.mode != "model":
            return None
        if all(s["kind"] == "profile" for s in sel) and len({s["uid"] for s in sel}) == 1:
            prs = [self.profile_entry(s) for s in sel]
            if None in prs or any(p["face"] is None for p in prs):
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

    def round_target(self):
        """(anchor, direction, edges) when only edges are selected: the handle sits on
        the last edge and points out along the bisector of its two faces."""
        sel = self.selection
        if not sel or self.mode != "model" or not all(s["kind"] == "edge" for s in sel):
            return None
        if self.part is None or any(s["eid"] >= len(self.edges) for s in sel):
            return None
        edge = self.edges[sel[-1]["eid"]]
        mid = edge.position_at(0.5)
        normals = []
        for f in self.part.faces():
            if any(e.is_same(edge) for e in f.edges()):
                try:
                    normals.append(_np(f.normal_at(mid)))
                except Exception:
                    pass
        d = np.sum(normals, axis=0) if normals else np.zeros(3)
        if np.linalg.norm(d) < 1e-6:  # fall back to "towards the camera"
            cam = self.renderer.GetActiveCamera()
            d = np.array(cam.GetPosition()) - _np(mid)
        return _np(mid), d / np.linalg.norm(d), [self.edges[s["eid"]] for s in sel]

    def _update_arrow(self):
        if self._arrow_actor is not None:
            self.remove_actor(self._arrow_actor)
            self._picker.DeletePickList(self._arrow_actor)
            self._arrow_actor = None
        self._arrow = None
        kind = "pull"
        tgt = self.pull_target() if self.tool == "select" else None
        if tgt is None and self.tool == "select":
            tgt = self.round_target()
            kind = "round"
        if tgt is None:
            return
        anchor, n, _ = tgt
        length = self.pixel_size(anchor) * 70 * self._scale
        start = anchor + n * length * (0.15 if kind == "round" else 0.0)
        if kind == "round":
            arrow = pv.Arrow(start=start, direction=n, scale=length * 1.1, tip_length=0.35, tip_radius=0.17,
                             shaft_radius=0.05)
        else:
            arrow = pv.Arrow(start=start, direction=n, scale=length, tip_length=0.3, tip_radius=0.12,
                             shaft_radius=0.035)
        if kind == "round":  # thin leader from the edge to the handle
            arrow = arrow.merge(pv.Line(anchor, start)).extract_surface(algorithm="dataset_surface")
        self._arrow_actor = self.add_mesh(arrow, color=SELECT, reset_camera=False, ambient=0.6, diffuse=0.5,
                                          specular=0.3)
        self._picker.AddPickList(self._arrow_actor)
        self._arrow = (anchor, n, length)
        self._arrow_kind = kind

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
                self.selection = [s for s in self.selection if s["kind"] == item["kind"]] + [item]
        else:
            self.selection = [item]
        self._refresh_highlights()
        self.selectionChanged.emit()
        self._emit_hint()
        self.render()

    # ----------------------------------------------------------- modes
    @staticmethod
    def _frame(o, n):
        nn, x = plane_axes(n)
        n, x = _np(nn), _np(x)
        return np.asarray(o, float), x, np.cross(n, x), n

    def _plane_under(self, x, y):
        """Sketch plane under the cursor: a planar face, a sketch region or the bed."""
        item = self.pick(x, y)
        if item and item["kind"] == "face" and self.is_planar_face(item["fid"]):
            f = self.faces[item["fid"]]
            return (np.round(_np(f.center()), 6), _np(f.normal_at())), item["fid"]
        if item and item["kind"] == "profile":
            pr = self.profile_entry(item)
            return (pr["plane"][0], pr["plane"][3]), None
        return (np.zeros(3), np.array([0.0, 0.0, 1.0])), None

    def enter_sketch(self, origin, normal, fid=None, tool="line"):
        frame = self._frame(origin, normal)
        cam = self.renderer.GetActiveCamera()
        was_parallel = bool(cam.GetParallelProjection())
        self.sketch = {"frame": frame, "fid": fid, "parallel": was_parallel}
        self.mode = "sketch"
        self.pending_tool = None
        self.selection = []
        self.hover = None
        o, ax, ay, n = frame
        # where the camera should end up: looking straight at the face
        start = (cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetParallelScale())
        cam.SetParallelProjection(True)
        self.view_vector(tuple(n), viewup=tuple(ay))
        self.fit(update_grid=False)
        end = (cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetParallelScale())
        self._draw_bed()
        self.modeChanged.emit("sketch")
        self.set_tool(tool)
        if self.animate and not was_parallel:
            cam.SetParallelProjection(False)
            self._animate_camera(start, end, then=lambda: (cam.SetParallelProjection(True),
                                                           cam.SetParallelScale(end[3]), self._draw_grid()))
        else:
            self._draw_grid()
        self.render()

    def _animate_camera(self, start, end, then=None, duration=300, steps=15):
        """Smoothly turn the camera from start to end (pos, focal, up, scale)."""
        cam = self.renderer.GetActiveCamera()
        p0, f0, u0 = (np.array(v, float) for v in start[:3])
        p1, f1, u1 = (np.array(v, float) for v in end[:3])
        d0, d1 = p0 - f0, p1 - f1
        r0, r1 = np.linalg.norm(d0), np.linalg.norm(d1)
        d0, d1 = d0 / r0, d1 / r1
        clock = QElapsedTimer()
        clock.start()
        timer = QTimer(self)
        self._anim_timer = timer

        def step():
            t = min(1.0, clock.elapsed() / duration)
            done = t >= 1.0
            t = t * t * (3 - 2 * t)  # ease in-out
            d = d0 * (1 - t) + d1 * t
            if np.linalg.norm(d) < 1e-6:
                d = d1
            d /= np.linalg.norm(d)
            f = f0 * (1 - t) + f1 * t
            u = u0 * (1 - t) + u1 * t
            cam.SetFocalPoint(*f)
            cam.SetPosition(*(f + d * (r0 * (1 - t) + r1 * t)))
            cam.SetViewUp(*(u if np.linalg.norm(u) > 1e-6 else u1))
            cam.OrthogonalizeViewUp()
            self.renderer.ResetCameraClippingRange()
            self.render()
            if done:
                timer.stop()
                cam.SetPosition(*p1)
                cam.SetFocalPoint(*f1)
                cam.SetViewUp(*u1)
                if then:
                    then()
                self.renderer.ResetCameraClippingRange()
                self.render()

        timer.timeout.connect(step)
        cam.SetPosition(*p0)
        cam.SetFocalPoint(*f0)
        cam.SetViewUp(*u0)
        timer.start(max(1, duration // steps))

    def exit_sketch(self):
        if self.mode != "sketch":
            return
        self._cancel_draw()
        self._clear_grid()
        self.renderer.GetActiveCamera().SetParallelProjection(self.sketch.get("parallel", False))
        self.sketch = None
        self.mode = "model"
        self.selection = []
        self._draw_bed()
        self.modeChanged.emit("model")
        self.set_tool("select")
        self.renderer.ResetCameraClippingRange()
        self.render()

    def _on_sketch_plane(self, pr):
        if self.sketch is None:
            return False
        o, _x, _y, n = self.sketch["frame"]
        po, _px, _py, pn = pr["plane"]
        return np.dot(pn, n) > 0.9999 and abs(np.dot(po - o, n)) < 1e-6

    def set_tool(self, tool):
        self._cancel_draw()
        if tool in SKETCH_TOOLS and self.mode != "sketch":
            # choose a plane first, then start the tool there
            self.pending_tool = tool
            self.tool = "select"
            self.setCursor(Qt.CrossCursor)
            self.hintChanged.emit(HINTS["pick_plane"])
            self.toolChanged.emit(tool)
            self._refresh_highlights()
            self.render()
            return
        self.pending_tool = None
        self.tool = tool
        if tool in SKETCH_TOOLS:
            self.draw = {"pts": [], "typed": "", "cursor": None}
            self.setCursor(Qt.CrossCursor)
            self.selection = []
        else:
            self.draw = None
            self.setCursor(Qt.ArrowCursor)
        self._refresh_highlights()
        self._emit_hint()
        self.toolChanged.emit(tool)
        self.render()

    def _emit_hint(self):
        if self.tool in SKETCH_TOOLS:
            stage = min(len(self.draw["pts"]) if self.draw else 0, 2 if self.tool == "slot" else 1)
            self.hintChanged.emit(HINTS[f"{self.tool}{stage}"])
        elif self.pending_tool:
            self.hintChanged.emit(HINTS["pick_plane"])
        elif self.mode == "sketch":
            self.hintChanged.emit(HINTS["sketch"])
        elif self.pull_target() is not None:
            self.hintChanged.emit(HINTS["model_pull"])
        elif self.round_target() is not None:
            self.hintChanged.emit(HINTS["model_edge"])
        elif self.selection and self.selection[0]["kind"] == "edge":
            self.hintChanged.emit(HINTS["model_edge"])
        else:
            self.hintChanged.emit(HINTS["model"])

    # ------------------------------------------------------------- grid
    def _clear_grid(self):
        for a in self._grid_actors:
            self.remove_actor(a)
        self._grid_actors = []

    def _visible_uv(self):
        o, ax, ay, n = self.sketch["frame"]
        w, h = self._display_size()
        uvs = []
        for x, y in ((0, 0), (w, 0), (0, h), (w, h)):
            ro, rd = self.ray(x, y)
            p = self.ray_plane(ro, rd, o, n)
            if p is not None:
                uvs.append([np.dot(p - o, ax), np.dot(p - o, ay)])
        if not uvs:
            return -100, 100, -100, 100
        uvs = np.array(uvs)
        return uvs[:, 0].min(), uvs[:, 0].max(), uvs[:, 1].min(), uvs[:, 1].max()

    def _draw_grid(self):
        self._clear_grid()
        if self.sketch is None:
            return
        o, ax, ay, n = self.sketch["frame"]
        mm_per_px = self.pixel_size(o) * self._scale
        step = 1.0
        for cand in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200):
            step = cand
            if cand / mm_per_px >= 14:
                break
        self.grid_step = step
        u0, u1, v0, v1 = self._visible_uv()
        major = step * (5 if str(step)[0] in "2" else 10)
        lift = n * self._eps() * 1.2
        minor_lines, major_lines = [], []
        for u in np.arange(math.floor(u0 / step) * step, u1 + step, step):
            seg = np.array([o + ax * u + ay * v0, o + ax * u + ay * v1]) + lift
            (major_lines if abs(round(u / major) * major - u) < step * 1e-3 else minor_lines).append(seg)
        for v in np.arange(math.floor(v0 / step) * step, v1 + step, step):
            seg = np.array([o + ax * u0 + ay * v, o + ax * u1 + ay * v]) + lift
            (major_lines if abs(round(v / major) * major - v) < step * 1e-3 else minor_lines).append(seg)
        for lines, color, op in ((minor_lines, GRID_MINOR, 0.35), (major_lines, GRID_MAJOR, 0.55)):
            mesh = polyline_mesh(lines)
            if mesh is not None:
                self._grid_actors.append(self.add_mesh(mesh, color=color, opacity=op, line_width=1,
                                                       pickable=False, reset_camera=False, lighting=False))
        axes = [(np.array([o + ax * u0, o + ax * u1]) + lift * 1.5, AXIS_U),
                (np.array([o + ay * v0, o + ay * v1]) + lift * 1.5, AXIS_V)]
        for seg, color in axes:
            self._grid_actors.append(self.add_mesh(polyline_mesh([seg]), color=color, line_width=1.5,
                                                   pickable=False, reset_camera=False, lighting=False))

    # ---------------------------------------------------------- snapping
    def _uv_world(self, uv, lift=2.0):
        o, ax, ay, n = self.sketch["frame"]
        uv = np.atleast_2d(uv)
        return o + np.outer(uv[:, 0], ax) + np.outer(uv[:, 1], ay) + n * self._eps() * lift

    def _to_uv(self, pts):
        o, ax, ay, _n = self.sketch["frame"]
        pts = np.atleast_2d(pts)
        return np.c_[(pts - o) @ ax, (pts - o) @ ay]

    def _snap_geometry(self):
        """Points and segments (plane uv) that the cursor can snap to."""
        o, ax, ay, n = self.sketch["frame"]
        key = (tuple(np.round(o, 5)), tuple(np.round(n, 5)), len(self.profiles), id(self.part))
        if getattr(self, "_snap_key", None) == key:
            return self._snap_cache
        pts = [np.zeros(2)]
        segs = []
        # edges of the model lying in the sketch plane
        for e, ln in zip(self.edges, self.edge_lines):
            d = (ln - o) @ n
            if np.all(np.abs(d) < 1e-3):
                uv = self._to_uv(ln)
                segs += [(uv[i], uv[i + 1]) for i in range(len(uv) - 1)]
                pts += [uv[0], uv[-1], self._to_uv(_np(e.position_at(0.5)))[0]]
                if e.geom_type == GeomType.CIRCLE:
                    try:
                        pts.append(self._to_uv(_np(e.arc_center))[0])
                    except Exception:
                        pass
        fid = self.sketch.get("fid")
        if fid is not None and fid < len(self.faces):
            pts.append(self._to_uv(_np(self.faces[fid].center()))[0])
        # coplanar sketch shapes
        for pr in self.profiles:
            if not self._on_sketch_plane(pr):
                continue
            uv = shape_outline_uv(pr["shape"])
            po, px_, py_, _pn = pr["plane"]
            off = np.array([np.dot(po - o, ax), np.dot(po - o, ay)])
            uv = uv + off
            segs += [(uv[i], uv[i + 1]) for i in range(len(uv) - 1)]
            pts += list(shape_points_uv(pr["shape"]) + off)
        pts = np.array(pts, float)
        if segs:
            seg_a = np.array([a for a, _ in segs])
            seg_b = np.array([b for _, b in segs])
        else:
            seg_a = seg_b = np.zeros((0, 2))
        self._snap_key = key
        self._snap_cache = (pts, seg_a, seg_b)
        return self._snap_cache

    def _snap(self, x, y, fine):
        """Snap the cursor on the sketch plane. Returns (uv, info)."""
        o, ax, ay, n = self.sketch["frame"]
        ro, rd = self.ray(x, y)
        p = self.ray_plane(ro, rd, o, n)
        if p is None:
            return None, None
        raw = np.array([np.dot(p - o, ax), np.dot(p - o, ay)])
        if fine:
            return np.round(raw, 1) + 0.0, {"kind": "free"}
        mm_px = self.pixel_size(o) * self._scale
        tol_pt = 12 * mm_px
        tol_line = 8 * mm_px
        pts, seg_a, seg_b = self._snap_geometry()
        chain = np.array(self.draw["pts"], float) if self.draw and self.draw["pts"] else np.zeros((0, 2))
        allpts = np.vstack([pts, chain]) if len(chain) else pts
        # 1. points (corners, midpoints, centres, chain start)
        if len(allpts):
            d = np.linalg.norm(allpts - raw, axis=1)
            k = int(np.argmin(d))
            if d[k] < tol_pt:
                return allpts[k].copy(), {"kind": "point", "pt": allpts[k]}
        # 2. horizontal / vertical alignment with existing points
        uv = raw.copy()
        guides = []
        if len(allpts):
            du = np.abs(allpts[:, 0] - raw[0])
            dv = np.abs(allpts[:, 1] - raw[1])
            ku, kv = int(np.argmin(du)), int(np.argmin(dv))
            if du[ku] < tol_line:
                uv[0] = allpts[ku, 0]
                guides.append(allpts[ku])
            if dv[kv] < tol_line:
                uv[1] = allpts[kv, 1]
                guides.append(allpts[kv])
        # 3. onto lines (model edges and sketch outlines)
        if not guides and len(seg_a):
            ab = seg_b - seg_a
            l2 = np.maximum((ab * ab).sum(1), 1e-12)
            t = np.clip(((raw - seg_a) * ab).sum(1) / l2, 0, 1)
            proj = seg_a + ab * t[:, None]
            d = np.linalg.norm(proj - raw, axis=1)
            k = int(np.argmin(d))
            if d[k] < tol_line:
                return proj[k], {"kind": "line"}
        step = self.snap if self.snap > 0 else self.grid_step
        if guides:
            for i in range(2):
                if not any(abs(g[i] - uv[i]) < 1e-9 for g in guides):
                    uv[i] = round(uv[i] / step) * step
            return uv + 0.0, {"kind": "guide", "guides": guides}
        return np.round(raw / step) * step + 0.0, {"kind": "grid"}

    # ----------------------------------------------------------- drawing
    def _cancel_draw(self):
        for a in self._draw_actors:
            self.remove_actor(a)
        self._draw_actors = []
        self._label.SetVisibility(False)
        if self.draw is not None:
            self.draw.update(pts=[], typed="")

    def _pending_shape(self, cur):
        d = self.draw
        pts = d["pts"]
        if not pts or cur is None:
            return None
        a, b = np.array(pts[0], float), np.array(cur, float)
        t = self.tool
        if t == "circle":
            r = float(np.linalg.norm(b - a))
            return {"kind": "circle", "c": [float(a[0]), float(a[1])], "r": r} if r > 1e-6 else None
        if t == "rect":
            w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
            if w < 1e-6 or h < 1e-6:
                return None
            c = (a + b) / 2
            return {"kind": "rect", "c": [float(c[0]), float(c[1])], "w": float(w), "h": float(h)}
        if t == "polygon":
            r = float(np.linalg.norm(b - a))
            rot = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            return ({"kind": "ngon", "c": [float(a[0]), float(a[1])], "r": r, "n": int(self.polygon_sides),
                     "rot": rot} if r > 1e-6 else None)
        if t == "slot":
            if len(pts) == 1:
                return None
            c1, c2 = np.array(pts[0]), np.array(pts[1])
            dvec = c2 - c1
            L = np.linalg.norm(dvec)
            if L < 1e-9:
                return None
            nrm = np.array([-dvec[1], dvec[0]]) / L
            w = 2 * abs(np.dot(b - c1, nrm))
            return ({"kind": "slot", "c1": list(map(float, c1)), "c2": list(map(float, c2)), "w": float(w)}
                    if w > 1e-6 else None)
        return None

    def _draw_move(self, x, y, fine):
        uv, info = self._snap(x, y, fine)
        if uv is None:
            return
        self.draw["cursor"] = uv
        self._snap_info = info
        self._render_draw(uv, info)

    def _render_draw(self, cur, info=None):
        d = self.draw
        for a in self._draw_actors:
            self.remove_actor(a)
        self._draw_actors = []
        pts = d["pts"]
        label, label_at = "", cur
        shape = self._pending_shape(cur)
        if shape is not None:
            outline = self._uv_world(shape_outline_uv(shape), 3)
            self._draw_actors.append(self.add_mesh(polyline_mesh([outline]), color=SELECT, line_width=2.5,
                                                   pickable=False, reset_camera=False, lighting=False))
            k = shape["kind"]
            if k == "circle":
                label = f"D {shape['r'] * 2:.2f} mm"
            elif k == "rect":
                label = f"{shape['w']:.2f} x {shape['h']:.2f} mm"
            elif k == "ngon":
                label = f"R {shape['r']:.2f} mm  {int(shape['n'])} sides"
            elif k == "slot":
                label = f"W {shape['w']:.2f} mm"
        if self.tool in ("line", "slot") and pts and (self.tool == "line" or len(pts) == 1):
            chain = np.array(pts + [list(cur)])
            self._draw_actors.append(self.add_mesh(polyline_mesh([self._uv_world(chain, 3)]), color=SELECT,
                                                   line_width=2.5, pickable=False, reset_camera=False,
                                                   lighting=False))
            seg = np.array(cur) - np.array(pts[-1])
            label = f"{np.linalg.norm(seg):.2f} mm"
            label_at = (np.array(cur) + np.array(pts[-1])) / 2
        if pts:
            self._draw_actors.append(self.add_mesh(pv.PolyData(self._uv_world(np.array(pts, float), 4)),
                                                   color=SKETCH_VERTEX, point_size=9, render_points_as_spheres=True,
                                                   pickable=False, reset_camera=False))
        # snapping feedback
        kind = (info or {}).get("kind", "grid")
        if kind == "guide":
            for g in info["guides"]:
                seg = self._uv_world(np.array([g, cur]), 3)
                self._draw_actors.append(self.add_mesh(polyline_mesh([seg]), color=SNAP_LINE, line_width=1.2,
                                                       pickable=False, reset_camera=False, lighting=False,
                                                       opacity=0.9))
        color = {"point": SNAP_POINT, "line": SNAP_LINE, "guide": SNAP_LINE}.get(kind, "#ffffff")
        size = {"point": 17, "line": 13, "guide": 13}.get(kind, 9)
        self._draw_actors.append(self.add_mesh(pv.PolyData(self._uv_world(cur, 5)), color=color, point_size=size,
                                               render_points_as_spheres=True, pickable=False, reset_camera=False))
        if d["typed"]:
            label = d["typed"] + "_ mm"
        if label:
            sx, sy = self.world_to_display(self._uv_world(label_at))[0]
            self._label.SetInput(label)
            self._place_label(sx, sy)
            self._label.SetVisibility(True)
        else:
            self._label.SetVisibility(False)
        self.render()

    def _place_label(self, x, y):
        """Put the dimension box next to (x, y) but always inside the viewport."""
        w, h = self._display_size()
        tw = (len(self._label.GetInput() or "") * 10 + 16) * self._scale
        th = 26 * self._scale
        px = x + 16 * self._scale
        py = y + 14 * self._scale
        if px + tw > w:
            px = x - tw - 16 * self._scale
        if py + th > h:
            py = y - th - 14 * self._scale
        self._label.SetDisplayPosition(int(max(4, px)), int(max(4, py)))

    def _draw_click(self, x, y, fine):
        d = self.draw
        uv, info = self._snap(x, y, fine)
        if uv is None:
            return
        uv = [float(uv[0]), float(uv[1])]
        t = self.tool
        if t == "line":
            if len(d["pts"]) >= 3 and np.linalg.norm(np.array(d["pts"][0]) - uv) < 1e-6:
                self._commit({"kind": "poly", "pts": [list(p) for p in d["pts"]]})
                return
            if d["pts"] and np.linalg.norm(np.array(d["pts"][-1]) - uv) < 1e-6:
                return
            d["pts"].append(uv)
        elif t == "slot":
            if len(d["pts"]) < 2:
                if not d["pts"] or np.linalg.norm(np.array(d["pts"][0]) - uv) > 1e-6:
                    d["pts"].append(uv)
            else:
                shape = self._pending_shape(uv)
                if shape is not None:
                    self._commit(shape)
                return
        else:
            if not d["pts"]:
                d["pts"].append(uv)
            else:
                shape = self._pending_shape(uv)
                if shape is not None:
                    self._commit(shape)
                return
        self._emit_hint()
        self._render_draw(np.array(uv), info)

    def finish_line(self):
        d = self.draw
        if self.tool != "line" or not d or len(d["pts"]) < 2:
            return False
        pts = [list(p) for p in d["pts"]]
        if len(pts) >= 3 and np.linalg.norm(np.array(pts[0]) - np.array(pts[-1])) < 1e-6:
            self._commit({"kind": "poly", "pts": pts[:-1]})
        else:
            self._commit({"kind": "path", "pts": pts}, keep_tool=True)
        return True

    def _commit(self, shape, keep_tool=True):
        o, ax, ay, n = self.sketch["frame"]
        plane = {"origin": [float(v) for v in o], "normal": [float(v) for v in n]}
        self._cancel_draw()
        self._emit_hint()
        self.shapeDrawn.emit(plane, shape)

    def _typed_commit(self):
        d = self.draw
        txt = d["typed"].replace("x", ",").replace("X", ",").replace("*", ",")
        d["typed"] = ""
        try:
            vals = [float(v) for v in txt.split(",") if v.strip()]
        except ValueError:
            return
        if not vals or not d["pts"] or vals[0] <= 0:
            self._refresh_draw()
            return
        a = np.array(d["pts"][-1], float)
        cur = np.array(d["cursor"], float) if d["cursor"] is not None else a + [1, 0]
        direction = cur - a
        if np.linalg.norm(direction) < 1e-9:
            direction = np.array([1.0, 0.0])
        direction /= np.linalg.norm(direction)
        t = self.tool
        if t == "line" or (t == "slot" and len(d["pts"]) == 1):
            p = a + direction * vals[0]
            d["pts"].append([float(p[0]), float(p[1])])
            self._emit_hint()
            self._render_draw(p)
        elif t == "circle":
            self._commit({"kind": "circle", "c": list(map(float, a)), "r": vals[0] / 2})
        elif t == "polygon":
            rot = math.degrees(math.atan2(direction[1], direction[0]))
            self._commit({"kind": "ngon", "c": list(map(float, a)), "r": vals[0], "n": int(self.polygon_sides),
                          "rot": rot})
        elif t == "rect":
            w = vals[0]
            h = vals[1] if len(vals) > 1 else vals[0]
            sx = 1.0 if cur[0] >= a[0] else -1.0
            sy = 1.0 if cur[1] >= a[1] else -1.0
            c = a + np.array([sx * w / 2, sy * h / 2])
            self._commit({"kind": "rect", "c": [float(c[0]), float(c[1])], "w": w, "h": h})
        elif t == "slot":
            c1, c2 = d["pts"][0], d["pts"][1]
            self._commit({"kind": "slot", "c1": list(map(float, c1)), "c2": list(map(float, c2)), "w": vals[0]})

    def _refresh_draw(self):
        d = self.draw
        if d and d["cursor"] is not None and self.sketch is not None:
            self._render_draw(d["cursor"], self._snap_info)
        else:
            self.render()

    # --------------------------------------------------------------- events
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
        if ev.button() != Qt.LeftButton:
            return self.mousePressEvent(ev)
        x, y = self._xy(ev)
        if self.mode == "sketch":
            if self.tool == "line" and self.draw and len(self.draw["pts"]) >= 2:
                self.finish_line()
                ev.accept()
                return
            if self.tool == "select" and self._pick_sketch_shape(x, y) is None:
                item = self.pick(x, y)
                if item is None:
                    self.exit_sketch()
                elif item["kind"] == "face" and self.is_planar_face(item["fid"]):
                    (o, n), fid = self._plane_under(x, y)  # move to another face
                    keep = self.sketch["parallel"]
                    self.renderer.GetActiveCamera().SetParallelProjection(False)
                    self.enter_sketch(o, n, fid, tool="select")
                    self.sketch["parallel"] = keep
                ev.accept()
                return
            return self.mousePressEvent(ev)
        # modeling: double-click a planar face / region / the bed to sketch on it
        (o, n), fid = self._plane_under(x, y)
        self._mode = None
        self.enter_sketch(o, n, fid, tool="line")
        ev.accept()

    def mouseMoveEvent(self, ev):  # noqa: N802
        x, y = self._xy(ev)
        shift, _ctrl = self._mods(ev)
        pos = ev.position()
        last = self._last or pos
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        self._last = pos
        mode = self._mode
        if mode in ("orbit_left", "orbit_right"):
            self._orbit(dx, dy)
        elif mode == "pan":
            self._pan(dx, dy)
        elif mode == "pull":
            self._drag_pull(x, y, shift)
        elif mode == "round":
            self._drag_round(x, y, shift)
        elif self.mode == "sketch" and self.tool in SKETCH_TOOLS:
            self._draw_move(x, y, shift)
        elif self.mode == "sketch":
            self.setCursor(Qt.ArrowCursor)
            self._set_hover(self._pick_sketch_shape(x, y))
        elif self.pending_tool:
            (_o, _n), fid = self._plane_under(x, y)
            self._set_hover({"kind": "face", "fid": fid, "point": None} if fid is not None else None)
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
        elif mode == "round":
            self._finish_round()
        if mode in ("orbit_left", "orbit_right", "pan"):
            self._after_camera_move()
        ev.accept()

    def wheelEvent(self, ev):  # noqa: N802
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if delta:
            pos = ev.position()
            w, h = self._display_size()
            x = pos.x() * w / max(self.width(), 1)
            y = (self.height() - pos.y()) * h / max(self.height(), 1)
            self._zoom(x, y, 1.15 ** (delta / 120.0))
            self._after_camera_move()
        ev.accept()

    def leaveEvent(self, ev):  # noqa: N802
        if self._mode is None:
            self._set_hover(None)
        super().leaveEvent(ev)

    def enterEvent(self, ev):  # noqa: N802
        self.setFocus()
        super().enterEvent(ev)

    def _after_camera_move(self):
        if self.mode == "sketch":
            self._draw_grid()
        self._update_arrow()
        self.render()

    def _hover_at(self, x, y):
        item = self._pick_with_handle(x, y)
        if item == "handle":
            self.setCursor(Qt.SizeVerCursor)
            self._set_hover(None)
            return
        self.setCursor(Qt.PointingHandCursor if item is not None else Qt.ArrowCursor)
        self._set_hover(item)

    def _left_down(self, x, y, shift, ctrl):
        if self.mode == "sketch":
            if self.tool in SKETCH_TOOLS:
                self._draw_click(x, y, shift)
                return
            item = self._pick_sketch_shape(x, y)
            if item is None:
                self._mode = "orbit_left"
                self._set_pivot(x, y)
                return
            self._click_select(item, shift or ctrl)
            return
        if self.pending_tool:
            (o, n), fid = self._plane_under(x, y)
            self.enter_sketch(o, n, fid, tool=self.pending_tool)
            return
        item = self._pick_with_handle(x, y)
        selected = item not in (None, "handle") and self._key(item) in {self._key(s) for s in self.selection}
        if item == "handle" and getattr(self, "_arrow_kind", "pull") == "round":
            self._start_round(x, y)
            return
        if item == "handle" or (selected and self.pull_target() is not None and not (shift or ctrl)):
            self._start_pull(x, y, None if item == "handle" else item)
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

    def escape(self):
        if self.mode == "sketch":
            d = self.draw
            if self.tool in SKETCH_TOOLS and d and d["pts"]:
                if self.tool == "line" and len(d["pts"]) > 1:
                    d["pts"].pop()  # cancel the last temporary segment
                    self._refresh_draw()
                else:
                    self._cancel_draw()
                self._emit_hint()
                self.render()
            elif self.tool in SKETCH_TOOLS:
                self.set_tool("select")
            elif self.selection:
                self.clear_selection()
            else:
                self.exit_sketch()
            return
        if self.pending_tool:
            self.set_tool("select")
            return
        self.clear_selection()

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        k = event.key()
        if k == Qt.Key_Escape:
            self.escape()
            return
        d = self.draw
        if self.mode == "sketch" and self.tool in SKETCH_TOOLS and d is not None:
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if d["typed"]:
                    self._typed_commit()
                elif self.tool == "line":
                    if not self.finish_line():
                        self.set_tool("select")
                return
            if k == Qt.Key_Backspace:
                if d["typed"]:
                    d["typed"] = d["typed"][:-1]
                elif d["pts"]:
                    d["pts"].pop()
                    self._emit_hint()
                self._refresh_draw()
                return
            txt = event.text()
            if d["pts"] and txt and txt in "0123456789.,xX*":
                d["typed"] += txt
                self._refresh_draw()
                return
        event.ignore()  # let the window handle shortcuts; never pass keys to VTK

    # ----------------------------------------------------------------- pull
    def _line_param(self, x, y, anchor, n):
        o, d = self.ray(x, y)
        d = d / np.linalg.norm(d)
        w0 = anchor - o
        b = np.dot(n, d)
        denom = 1.0 - b * b
        if denom < 1e-6:
            return None
        return (b * np.dot(d, w0) - np.dot(n, w0)) / denom

    def _start_pull(self, x, y, clicked=None):
        tgt = self.pull_target()
        if tgt is None or self._arrow is None:
            return
        anchor, n, faces = tgt
        n = n / np.linalg.norm(n)
        self._mode = "pull"
        self._pull = {"start": np.array([x, y], float), "t0": self._line_param(x, y, anchor, n), "n": n,
                      "faces": faces, "d": 0.0, "anchor": anchor, "len": self._arrow[2], "clicked": clicked}

    def _drag_pull(self, x, y, fine=False):
        p = self._pull
        t = self._line_param(x, y, p["anchor"], p["n"])
        if t is None or p["t0"] is None:
            s = self.world_to_display([p["anchor"], p["anchor"] + p["n"] * p["len"]])
            sdir = s[1] - s[0]
            if np.dot(sdir, sdir) < 4:
                sdir = np.array([0.0, 60.0])
            m = np.array([x, y], float) - p["start"]
            raw = np.dot(m, sdir) / np.dot(sdir, sdir) * p["len"]
        else:
            raw = t - p["t0"]
        step = 0.1 if fine else (self.snap if self.snap > 0 else 1.0)
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
        self._label.SetInput(f"{d:+.2f} mm" if d > 0 else f"{d:.2f} mm cut")
        self._place_label(x, y)
        self._label.SetVisibility(True)
        self.render()

    # ---------------------------------------------------- drag to fillet
    def _start_round(self, x, y):
        tgt = self.round_target()
        if tgt is None or self._arrow is None:
            return
        anchor, n, edges = tgt
        self._mode = "round"
        self._round = {"t0": self._line_param(x, y, anchor, n), "anchor": anchor, "n": n, "edges": edges,
                       "r": 0.0, "ok": 0.0, "start": np.array([x, y], float), "len": self._arrow[2]}
        self._show_round_label(x, y, 0.0, True)

    def _show_round_label(self, x, y, r, ok):
        self._label.SetInput(f"R {r:.1f} mm" if ok else f"R {r:.1f} mm  too large")
        self._label.GetTextProperty().SetFrameColor(*((0.24, 0.55, 1.0) if ok else (1.0, 0.35, 0.3)))
        self._place_label(x, y)
        self._label.SetVisibility(True)

    def _drag_round(self, x, y, fine=False):
        p = self._round
        t = self._line_param(x, y, p["anchor"], p["n"])
        if t is None or p["t0"] is None:
            raw = np.linalg.norm(np.array([x, y], float) - p["start"]) * self.pixel_size(p["anchor"])
        else:
            raw = abs(t - p["t0"])
        step = 0.1 if fine else 0.5
        r = round(raw / step) * step
        if abs(r - p["r"]) < 1e-9:
            return
        p["r"] = r
        for a in self._preview_actors:
            self.remove_actor(a)
        self._preview_actors = []
        ok = True
        if r > 1e-9:
            try:
                rounded = fillet(p["edges"], r)
                mesh, _, _ = tessellate(rounded, 0.05, 0.2)
                if mesh is None:
                    raise ValueError("empty")
                p["ok"] = r
                if self._part_actor is not None:
                    self._part_actor.SetVisibility(False)
                mesh = mesh.compute_normals(cell_normals=False, split_vertices=True, feature_angle=35)
                self._preview_actors.append(self.add_mesh(mesh, color=PART, smooth_shading=True, ambient=0.3,
                                                          diffuse=0.75, specular=0.2, pickable=False,
                                                          reset_camera=False))
            except Exception:
                ok = False
                if self._part_actor is not None:
                    self._part_actor.SetVisibility(True)
        elif self._part_actor is not None:
            self._part_actor.SetVisibility(True)
        self._show_round_label(x, y, r, ok)
        self.render()

    def _finish_round(self):
        for a in self._preview_actors:
            self.remove_actor(a)
        self._preview_actors = []
        if self._part_actor is not None:
            self._part_actor.SetVisibility(True)
        self._label.SetVisibility(False)
        self._label.GetTextProperty().SetFrameColor(0.24, 0.55, 1.0)
        p, self._round = self._round, None
        self.render()
        if p and p["ok"] > 1e-9:
            self.roundDragged.emit(list(self.selection), float(p["ok"]))

    def _finish_pull(self):
        for a in self._preview_actors:
            self.remove_actor(a)
        self._preview_actors = []
        self._label.SetVisibility(False)
        p, self._pull = self._pull, None
        self.render()
        if p and abs(p["d"]) > 1e-9:
            self.pullDragged.emit(list(self.selection), float(p["d"]))
        elif p and p.get("clicked") is not None and len(self.selection) > 1:
            self._click_select(p["clicked"], False)  # a plain click picks just that one

    # ------------------------------------------------------------- camera
    def _set_pivot(self, x, y):
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
        """Turntable orbit: Z always stays up (no tilting)."""
        cam = self.renderer.GetActiveCamera()
        pos, fp = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())
        pivot = self._pivot
        z = np.array([0.0, 0.0, 1.0])
        rz = self._rot(z, -dx * 0.35)
        pos, fp = pivot + rz @ (pos - pivot), pivot + rz @ (fp - pivot)
        view = (fp - pos) / np.linalg.norm(fp - pos)
        right = np.cross(view, z)
        if np.linalg.norm(right) > 1e-6:
            re = self._rot(right, -dy * 0.35)
            if abs(np.dot(re @ view, z)) < 0.995:
                pos, fp = pivot + re @ (pos - pivot), pivot + re @ (fp - pivot)
        else:  # looking straight up/down: tilt away from the pole first
            up = np.array(cam.GetViewUp())
            re = self._rot(np.cross(view, up), -dy * 0.35)
            pos, fp = pivot + re @ (pos - pivot), pivot + re @ (fp - pivot)
        cam.SetPosition(*pos)
        cam.SetFocalPoint(*fp)
        view = (fp - pos) / np.linalg.norm(fp - pos)
        if abs(np.dot(view, z)) < 0.999:
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
        self.render()

    def set_parallel(self, on: bool):
        self.renderer.GetActiveCamera().SetParallelProjection(bool(on))
        self.fit()

    # ----------------------------------------------------------------- view
    def fit(self, update_grid=True):
        if self._bounds is not None:
            self.reset_camera(bounds=self._bounds)
        else:
            w, d = self.bed_size
            self.reset_camera(bounds=(-w / 4, w / 4, -d / 4, d / 4, 0, 10))
        if update_grid and self.mode == "sketch":
            self._draw_grid()
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
