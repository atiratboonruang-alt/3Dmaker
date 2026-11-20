"""Export the finished part for 3D printing / other CAD programs."""
from __future__ import annotations

import os

from build123d import Mesher, export_step, export_stl

FORMATS = {
    "stl": "STL for slicers (*.stl)",
    "3mf": "3MF for slicers (*.3mf)",
    "step": "STEP for other CAD apps (*.step)",
}


def export_part(part, path: str, tolerance: float = 0.01, angular: float = 0.1):
    if part is None:
        raise ValueError("There's nothing to export yet")
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "stl":
        ok = export_stl(part, path, tolerance=tolerance, angular_tolerance=angular)
    elif ext == "3mf":
        mesher = Mesher()
        mesher.add_shape(part, linear_deflection=tolerance, angular_deflection=angular)
        mesher.write(path)
        ok = True
    elif ext in ("step", "stp"):
        ok = export_step(part, path)
    else:
        raise ValueError(f"Can't export .{ext} files")
    if ok is False or not os.path.exists(path):
        raise IOError(f"Couldn't write {path}")
    return path
