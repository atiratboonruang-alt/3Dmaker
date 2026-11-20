"""End-to-end UI test driven ONLY by real Qt mouse/keyboard events (the path Windows uses).

Run headless:  xvfb-run -a python tools/ui_e2e.py [out_dir]
Simulate 150% Windows scaling:  QT_SCALE_FACTOR=1.5 xvfb-run -a python tools/ui_e2e.py
"""
import os
import sys

os.environ["QT_API"] = "pyside6"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from maker3d.gui.main_window import MainWindow  # noqa: E402
from maker3d.gui.theme import apply_theme  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "build", "ui-shots")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
apply_theme(app)
w = MainWindow()
w.resize(1440, 900)
w.show()
w.activateWindow()
vp = w.viewport
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info if not cond else "")
    if not cond:
        fails.append(name)


def pump(n=3):
    for _ in range(n):
        app.processEvents()


def wait(ms=700):
    QTest.qWait(ms)
    pump()


def to_qt(p):
    x, y = vp.world_to_display([p])[0]
    w_, h_ = vp._display_size()
    return QPointF(x * vp.width() / w_, vp.height() - y * vp.height() / h_)


def send(kind, pos, button=Qt.NoButton, buttons=Qt.NoButton, mods=Qt.NoModifier):
    t = {"press": QEvent.MouseButtonPress, "release": QEvent.MouseButtonRelease,
         "move": QEvent.MouseMove, "dbl": QEvent.MouseButtonDblClick}[kind]
    gp = QPointF(vp.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(vp, QMouseEvent(t, pos, gp, button, buttons, mods))
    pump(1)


def move(pos, mods=Qt.NoModifier):
    send("move", pos, mods=mods)


def click(pos, mods=Qt.NoModifier):
    move(pos, mods)
    send("press", pos, Qt.LeftButton, Qt.LeftButton, mods)
    send("release", pos, Qt.LeftButton, Qt.NoButton, mods)


def dblclick(pos):
    click(pos)
    send("dbl", pos, Qt.LeftButton, Qt.LeftButton)
    send("release", pos, Qt.LeftButton, Qt.NoButton)
    wait()


def drag(a, b, button=Qt.LeftButton, steps=10, mods=Qt.NoModifier):
    move(a, mods)
    send("press", a, button, button, mods)
    for i in range(1, steps + 1):
        t = i / steps
        send("move", QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), Qt.NoButton, button, mods)
    send("release", b, button, Qt.NoButton, mods)


def wheel(pos, delta):
    gp = QPointF(vp.mapToGlobal(pos.toPoint()))
    ev = QWheelEvent(pos, gp, QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)
    pump(1)


def key(k, mods=Qt.NoModifier):
    QTest.keyClick(vp, k, mods)
    pump(2)


def type_text(t):
    for ch in t:
        QTest.keyClicks(vp, ch)
        pump(1)


def button(text):
    for b in w.context.findChildren(QPushButton):
        if b.isVisible() and b.text() == text:
            b.click()
            pump(5)
            return True
    return False


def shot(name):
    pump(3)
    w.grab().save(f"{OUT}/{name}.png")


def bed(u, v):
    """Point on the bed sketch plane (z = 0)."""
    return (u, v, 0.0)


def shapes():
    return [s for f in w.doc.features if f.type_id == "sketch" for s in f.params["shapes"]]


def arrow_drag(mm):
    anchor, n, L = vp._arrow
    drag(to_qt(anchor + n * L * 0.55), to_qt(anchor + n * L * (0.55 + mm / L)), steps=12)


pump(10)
shot("00_start")

# 1) double-click the bed -> sketch mode looking straight down, grid on
dblclick(to_qt((0, 0, 0)))
cam = vp.renderer.GetActiveCamera()
view = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
check("double-click bed enters sketch mode", vp.mode == "sketch" and vp.tool == "line")
check("camera looks straight at the sketch plane", abs(view[2] / np.linalg.norm(view) + 1) < 1e-6, view)
check("grid shown", len(vp._grid_actors) >= 2)
check("tool panel switched to sketching", w.tool_stack.currentIndex() == 1)
shot("01_sketch_mode")

# 2) rectangle snapped to the grid
key(Qt.Key_R)
click(to_qt(bed(-30.3, -19.8)))
move(to_qt(bed(29.7, 20.2)))
shot("02_rect")
click(to_qt(bed(29.7, 20.2)))
check("rectangle on the grid", shapes() and shapes()[-1] == {"kind": "rect", "c": [0.0, 0.0], "w": 60.0, "h": 40.0},
      shapes())
check("tool stays active after drawing", vp.tool == "rect")

# 3) circle snapped to the rectangle centre, typed diameter
key(Qt.Key_C)
move(to_qt(bed(0.6, -0.5)))
check("snaps to the rectangle centre (point snap)", vp._snap_info and vp._snap_info["kind"] == "point"
      and np.allclose(vp.draw["cursor"], [0, 0]), (vp._snap_info, vp.draw["cursor"]))
click(to_qt(bed(0.6, -0.5)))
move(to_qt(bed(5, 3)))
type_text("8")
shot("03_circle_typing")
key(Qt.Key_Return)
check("typed circle diameter 8", shapes()[-1] == {"kind": "circle", "c": [0.0, 0.0], "r": 4.0}, shapes()[-1])

# 4) line tool: snap onto an edge, H/V guides, close the loop
key(Qt.Key_L)
move(to_qt(bed(12.3, 19.6)))
check("cursor snaps onto the rectangle's edge line", vp.draw["cursor"] is not None
      and abs(vp.draw["cursor"][1] - 20) < 1e-9, (vp._snap_info, vp.draw["cursor"]))
click(to_qt(bed(40, 0)))
click(to_qt(bed(60, 0)))
move(to_qt(bed(40.4, 14.6)))
check("vertical guide aligns with the first point", abs(vp.draw["cursor"][0] - 40) < 1e-9
      and vp._snap_info["kind"] == "guide", (vp._snap_info, vp.draw["cursor"]))
shot("04_guides")
click(to_qt(bed(60, 15)))
click(to_qt(bed(40, 15)))
click(to_qt(bed(40.2, 0.3)))  # back onto the start point closes it
check("closing the line makes a region", shapes()[-1]["kind"] == "poly" and len(shapes()[-1]["pts"]) == 4,
      shapes()[-1])

# 5) Esc twice: tool -> select, then exit sketching; drawn regions are ready to extrude
key(Qt.Key_Escape)
check("Esc leaves the tool", vp.tool == "select" and vp.mode == "sketch")
key(Qt.Key_Escape)
wait(100)
check("Esc again exits sketching", vp.mode == "model" and w.tool_stack.currentIndex() == 0)
check("drawn regions are selected after exiting", len(vp.selection) == 3 and vp.pull_target() is not None,
      vp.selection)
vp.set_view("iso")
pump()
click(to_qt(bed(-20, -12)))  # just the rectangle
check("click selects one region", len(vp.selection) == 1 and vp.selection[0]["kind"] == "profile")
arrow_drag(20)
check("drag the arrow extrudes 20 mm", w.part is not None and abs(w.part.bounding_box().size.Z - 20) < 1e-6,
      w.part and w.part.bounding_box().size)
shot("05_extruded")

# 6) double-click the top face -> sketch on it, snap to the face centre, cut through
dblclick(to_qt((-20, 10, 20)))
view = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
check("double-click a face sketches on that face", vp.mode == "sketch" and vp.sketch["fid"] is not None
      and abs(vp.sketch["frame"][0][2] - 20) < 1e-6)
check("face turned towards the camera", abs(view[2] / np.linalg.norm(view) + 1) < 1e-6)
shot("06_face_sketch")
key(Qt.Key_C)
move(to_qt((-0.4, 0.5, 20)))
check("snaps to the face centre", np.allclose(vp.draw["cursor"], [0, 0]), vp.draw["cursor"])
click(to_qt((-0.4, 0.5, 20)))
move(to_qt((3, 0, 20)))
type_text("6")
key(Qt.Key_Return)
key(Qt.Key_Escape)
key(Qt.Key_Escape)
wait(100)
vol0 = w.part.volume
check("cut-through button", button("Cut Through"))
check("hole cut through", w.part.volume < vol0 - 50, f"{vol0:.0f} -> {w.part.volume:.0f}")

# 7) side face: sketch via double-click, blind hole by dragging the arrow down
vp.set_view("iso")
pump()
dblclick(to_qt((-15, -20, 10)))
check("front face sketch", vp.mode == "sketch" and abs(vp.sketch["frame"][3][1] + 1) < 1e-6, vp.sketch)
key(Qt.Key_C)
click(to_qt((-15, -20, 10)))
move(to_qt((-12, -20, 10)))
type_text("5")
key(Qt.Key_Return)
key(Qt.Key_Escape)
key(Qt.Key_Escape)
wait(100)
vp.set_view("iso")
pump()
vol1 = w.part.volume
arrow_drag(-6)
check("drag down cuts a blind hole", w.part.volume < vol1 - 50, f"{vol1:.0f} -> {w.part.volume:.0f}")

# 8) polygon and slot on the bed
dblclick(to_qt((80, 60, 0)))
key(Qt.Key_G)
click(to_qt(bed(80, 60)))
move(to_qt(bed(86, 60)))
type_text("5")
key(Qt.Key_Return)
key(Qt.Key_S)
click(to_qt(bed(70, -40)))
click(to_qt(bed(90, -40)))
move(to_qt(bed(85, -37)))
shot("07_slot")
type_text("4")
key(Qt.Key_Return)
kinds = [s["kind"] for s in shapes()]
check("polygon and slot drawn", "ngon" in kinds and "slot" in kinds, kinds)
key(Qt.Key_Escape)
key(Qt.Key_Escape)
wait(100)
check("sketch has no errors", all(f.error is None for f in w.doc.features), [(f.name, f.error) for f in w.doc.features])

# 9) modelling: orbit stays level, hover/select face and edge, fillet
vp.set_view("iso")
pump()
drag(QPointF(400, 300), QPointF(650, 380), Qt.RightButton, steps=15)
view = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
right = np.cross(view / np.linalg.norm(view), np.array(cam.GetViewUp()))
check("orbit keeps the horizon level", abs(right[2]) < 1e-6, right)
vp.set_view("iso")
pump()
top = to_qt((-20, 12, 20))
move(top)
check("hover highlights a face", vp.hover and vp.hover["kind"] == "face", vp.hover)
click(top)
check("click selects the face", vp.selection and vp.selection[0]["kind"] == "face")
shot("08_face_selected")
key(Qt.Key_Escape)
edge = next((e for e in vp.edges if abs(e.position_at(0.5).Z - 20) < 1e-6 and abs(e.position_at(0.5).Y + 20) < 1e-6
             and e.length > 30), None)
m = edge.position_at(0.5)
pt = to_qt((m.X, m.Y, m.Z))
move(pt)
check("hover finds the edge", vp.hover and vp.hover["kind"] == "edge", vp.hover)
click(pt)
check("fillet the edge", button("Fillet") and w.doc.features[-1].type_id == "fillet"
      and w.doc.features[-1].error is None, w.doc.features[-1].error)
fp0 = np.array(cam.GetFocalPoint())
drag(QPointF(500, 400), QPointF(560, 400), Qt.MiddleButton)
check("middle drag pans", np.linalg.norm(np.array(cam.GetFocalPoint()) - fp0) > 1)
d0 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()))
wheel(QPointF(500, 400), 240)
check("wheel zooms", np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint())) < d0)

# 10) undo / redo
n = len(w.doc.features)
QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier)
pump(5)
check("Ctrl+Z undo", len(w.doc.features) == n - 1)
QTest.keyClick(w, Qt.Key_Y, Qt.ControlModifier)
pump(5)
vp.set_view("iso")
vp.clear_selection()
shot("09_final")
print("history:", [(f.name, f.error) for f in w.doc.features])
print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
w.doc.dirty = False
sys.exit(1 if fails else 0)
