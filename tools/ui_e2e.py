"""End-to-end UI test driven ONLY by real Qt mouse/keyboard events (the path Windows uses).

Run headless:  xvfb-run -a python tools/ui_e2e.py [out_dir]
Simulate 150% Windows scaling:  QT_SCALE_FACTOR=1.5 xvfb-run -a python tools/ui_e2e.py
"""
import os, sys
os.environ["QT_API"] = "pyside6"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from maker3d.gui.main_window import MainWindow
from maker3d.gui.theme import apply_theme

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "build", "ui-shots")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
apply_theme(app)
w = MainWindow(); w.resize(1440, 900); w.show(); w.activateWindow()
for _ in range(10): app.processEvents()
vp = w.viewport
dpr = vp.devicePixelRatioF()
fails = []

def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info)
    if not cond:
        fails.append(name)

def pump(n=3):
    for _ in range(n): app.processEvents()

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
    QApplication.sendEvent(vp, ev); pump(1)

def key(k, text=""):
    QTest.keyClick(vp, k, Qt.NoModifier); pump(2)

def type_text(t):
    for ch in t:
        QTest.keyClicks(vp, ch); pump(1)

def button(text):
    for b in w.context.findChildren(QPushButton):
        if b.isVisible() and b.text().startswith(text):
            b.click(); pump(5); return True
    return False

def shot(name):
    pump(3)
    w.grab().save(f"{OUT}/{name}.png")

def arrow_drag(mm):
    anchor, n, L = vp._arrow
    a = to_qt(anchor + n * L * 0.55)
    b_ = to_qt(anchor + n * L * (0.55 + mm / L))
    drag(a, b_, steps=12)

# 1) press R, draw 60x40 on the bed
vp.setFocus(); key(Qt.Key_R)
check("R selects rectangle tool", vp.tool == "rect")
move(to_qt((-30, -20, 0))); click(to_qt((-30, -20, 0)))
move(to_qt((10, 5, 0))); shot("01_rect_drawing")
click(to_qt((30, 20, 0)))
sk = w.doc.features[-1] if w.doc.features else None
check("rectangle sketch created", sk is not None and sk.type_id == "sketch",
      sk.params["shapes"] if sk else "")
check("profile auto-selected", vp.selection and vp.selection[0]["kind"] == "profile")
# 2) drag arrow up 20 mm
arrow_drag(20)
info = w.part and w.part.bounding_box().size
check("pull up by dragging arrow", w.part is not None and abs(info.Z - 20) < 1.01, info)
vp.set_view("iso"); pump()
# 3) hover + click top face
top = to_qt((8, 6, 20))
move(top)
check("hover highlights top face", vp.hover and vp.hover["kind"] == "face")
shot("02_hover_face")
click(top)
check("click selects top face", vp.selection and vp.selection[0]["kind"] == "face")
shot("03_face_selected")
key(Qt.Key_Escape)
check("Esc clears selection", not vp.selection)
# 4) orbit with right drag: no roll
drag(QPointF(400, 300), QPointF(650, 380), Qt.RightButton, steps=15)
cam = vp.renderer.GetActiveCamera()
view = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
right = np.cross(view / np.linalg.norm(view), np.array(cam.GetViewUp()))
check("orbit keeps horizon level (no tilt)", abs(right[2]) < 1e-6, f"right.z={right[2]:.2e}")
pos_before = np.array(cam.GetPosition())
drag(QPointF(500, 300), QPointF(500, 420), Qt.RightButton, steps=10)
check("drag down raises the camera", cam.GetPosition()[2] > pos_before[2])
for _ in range(30):
    drag(QPointF(500, 300), QPointF(500, 700), Qt.RightButton, steps=4)
view = np.array(cam.GetFocalPoint()) - np.array(cam.GetPosition())
check("cannot flip over the top", abs(np.dot(view / np.linalg.norm(view), [0, 0, 1])) < 0.999)
vp.set_view("iso"); pump()
# 5) middle pan + wheel zoom
fp0 = np.array(cam.GetFocalPoint())
drag(QPointF(500, 400), QPointF(560, 400), Qt.MiddleButton)
check("middle drag pans", np.linalg.norm(np.array(cam.GetFocalPoint()) - fp0) > 1)
d0 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()))
wheel(QPointF(500, 400), 240)
d1 = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()))
check("wheel zooms in", d1 < d0)
vp.set_view("iso"); pump()
# 6) circle on the top face: snap to face centre, type 8, Enter, cut through
key(Qt.Key_C)
check("C selects circle tool", vp.tool == "circle")
near_centre = to_qt((0.6, -0.4, 20))
move(near_centre)
check("snaps to face centre", getattr(vp, "_snapped", False) and vp.draw["cursor"] is not None
      and np.allclose(vp.draw["cursor"], [0, 0], atol=1e-6), vp.draw["cursor"])
shot("04_circle_snap")
click(near_centre)
move(to_qt((5, 3, 20)))
type_text("8")
shot("05_circle_typing")
key(Qt.Key_Return)
circ = w.doc.features[-1].params["shapes"][-1] if w.doc.features[-1].type_id == "sketch" else None
check("typed diameter 8 -> r 4", circ is not None and abs(circ["r"] - 4) < 1e-9, circ)
check("circle selected after drawing", vp.selection and vp.selection[0]["kind"] == "profile")
shot("06_circle_selected")
vol0 = w.part.volume
check("cut-through button exists", button("เจาะทะลุ"))
check("hole cut", w.part.volume < vol0 - 50, f"{vol0:.0f} -> {w.part.volume:.0f}")
shot("07_hole")
# 7) circle on the front face + drag down = blind hole
key(Qt.Key_C)
fr = to_qt((-15, -20, 10)); move(fr); click(fr)
move(to_qt((-12, -20, 10))); type_text("6"); key(Qt.Key_Return)
vol1 = w.part.volume
arrow_drag(-5)
check("drag arrow into face cuts a blind hole", w.part.volume < vol1 - 50, f"{vol1:.0f} -> {w.part.volume:.0f}")
# 8) edge: hover + click + fillet
best = None
for i, e in enumerate(vp.edges):
    m = e.position_at(0.5)
    if abs(m.Z - 20) < 1e-6 and abs(m.Y + 20) < 1e-6 and e.length > 30:
        best = (m.X, m.Y, m.Z)
pt = to_qt(best)
move(pt)
check("hover finds the edge", vp.hover and vp.hover["kind"] == "edge", vp.hover)
click(pt)
check("click selects the edge", vp.selection and vp.selection[0]["kind"] == "edge")
shot("08_edge_selected")
check("fillet button", button("ลบมุมโค้ง"))
check("fillet ok", w.doc.features[-1].type_id == "fillet" and w.doc.features[-1].error is None,
      w.doc.features[-1].error)
# 9) undo
n = len(w.doc.features)
QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier); pump(5)
check("Ctrl+Z undo", len(w.doc.features) == n - 1)
QTest.keyClick(w, Qt.Key_Y, Qt.ControlModifier); pump(5)
# 10) poly via double click
key(Qt.Key_L)
for p in [(60, 0, 0), (90, 0, 0), (75, 25, 0)]:
    click(to_qt(p))
q = to_qt((75, 25, 0))
send("dbl", q, Qt.LeftButton, Qt.LeftButton); send("release", q, Qt.LeftButton, Qt.NoButton)
polys = [s_ for f in w.doc.features if f.type_id == "sketch" for s_ in f.params["shapes"] if s_["kind"] == "poly"]
check("double-click closes polygon", len(polys) == 1 and len(polys[0]["pts"]) == 3, polys)
check("polygon is selected for pulling", vp.selection and vp.selection[0]["kind"] == "profile")
arrow_drag(8)
check("pull polygon up 8", abs(w.part.bounding_box().max.Z - 20) < 1e-6 and w.doc.features[-1].error is None)
vp.clear_selection(); vp.set_view("iso"); shot("09_final")
print("history:", [(f.name, f.error) for f in w.doc.features])
print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
w.doc.dirty = False
sys.exit(1 if fails else 0)
w.doc.dirty = False
