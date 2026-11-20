"""3D viewport based on PyVista (VTK) embedded in Qt."""
from __future__ import annotations

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

PART_COLOR = "#8fb8ff"
TOOL_ADD_COLOR = "#4cd97b"
TOOL_CUT_COLOR = "#ff5c5c"
BG_TOP = "#2b2f36"
BG_BOTTOM = "#15171b"


def to_polydata(shape, tolerance=0.05, angular=0.2) -> pv.PolyData | None:
    if shape is None:
        return None
    verts, tris = shape.tessellate(tolerance, angular)
    if not tris:
        return None
    pts = np.array([(v.X, v.Y, v.Z) for v in verts], dtype=float)
    faces = np.hstack([np.full((len(tris), 1), 3), np.array(tris, dtype=np.int64)]).ravel()
    return pv.PolyData(pts, faces)


class Viewport(QtInteractor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_background(BG_BOTTOM, top=BG_TOP)
        self.enable_anti_aliasing("msaa")
        self.add_axes(interactive=False, line_width=2, color="white")
        self.bed_size = (220.0, 220.0)
        self.show_bed = True
        self.show_edges = True
        self._actors = []
        self._bed_actors = []
        self._has_fit = False
        self._bounds = None
        self._draw_bed()
        self.view_isometric()

    # --- print bed -------------------------------------------------------
    def _draw_bed(self):
        for a in self._bed_actors:
            self.remove_actor(a)
        self._bed_actors = []
        if not self.show_bed:
            return
        w, d = self.bed_size
        plate = pv.Plane(center=(0, 0, -0.05), direction=(0, 0, 1), i_size=w, j_size=d)
        self._bed_actors.append(self.add_mesh(plate, color="#30343c", opacity=0.9, pickable=False,
                                              reset_camera=False))
        lines = []
        step = 10.0
        for x in np.arange(-w / 2, w / 2 + 0.01, step):
            lines.append(pv.Line((x, -d / 2, 0), (x, d / 2, 0)))
        for y in np.arange(-d / 2, d / 2 + 0.01, step):
            lines.append(pv.Line((-w / 2, y, 0), (w / 2, y, 0)))
        grid = lines[0].merge(lines[1:])
        self._bed_actors.append(self.add_mesh(grid, color="#4a505a", line_width=1, pickable=False,
                                              reset_camera=False))

    def set_bed(self, width, depth, visible=True):
        self.bed_size = (width, depth)
        self.show_bed = visible
        self._draw_bed()
        self.render()

    # --- content -----------------------------------------------------------
    def show_model(self, part, tool=None, tool_mode="add"):
        for a in self._actors:
            self.remove_actor(a)
        self._actors = []
        mesh = to_polydata(part)
        self._bounds = mesh.bounds if mesh is not None else None
        if mesh is not None:
            mesh = mesh.compute_normals(split_vertices=True, feature_angle=30, auto_orient_normals=False)
            self._actors.append(self.add_mesh(mesh, color=PART_COLOR, smooth_shading=True,
                                              specular=0.3, specular_power=20, reset_camera=False))
            if self.show_edges:
                edges = mesh.extract_feature_edges(feature_angle=30, boundary_edges=True,
                                                   non_manifold_edges=False, manifold_edges=False)
                if edges.n_points:
                    self._actors.append(self.add_mesh(edges, color="#1d2633", line_width=1.5,
                                                      reset_camera=False))
        tmesh = to_polydata(tool, 0.1, 0.3) if tool is not None else None
        if tmesh is not None:
            color = TOOL_CUT_COLOR if tool_mode == "cut" else TOOL_ADD_COLOR
            self._actors.append(self.add_mesh(tmesh, color=color, opacity=0.35, reset_camera=False))
            self._actors.append(self.add_mesh(tmesh.extract_feature_edges(30), color=color,
                                              line_width=2, reset_camera=False))
        if not self._has_fit and mesh is not None:
            self._has_fit = True
            self.fit()
        self.render()

    def fit(self):
        """Zoom to the model (or to the whole bed when empty)."""
        if self._bounds is not None:
            self.reset_camera(bounds=self._bounds)
        else:
            self.reset_camera()
        self.render()

    def set_view(self, name: str):
        {
            "iso": self.view_isometric,
            "top": self.view_xy,
            "bottom": lambda: self.view_xy(negative=True),
            "front": lambda: self.view_xz(negative=True),
            "back": self.view_xz,
            "right": self.view_yz,
            "left": lambda: self.view_yz(negative=True),
        }[name]()
        self.render()
