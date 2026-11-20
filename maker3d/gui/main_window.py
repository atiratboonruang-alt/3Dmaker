"""Main application window.

Layout:  top bar · [tool panel | coach line / viewport / command bar] · history
The tool panel switches between Modeling and Sketching, like a direct-modelling
CAD app: double-click a face to sketch on it, draw, exit, then drag to extrude.
"""
from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..export import FORMATS, export_part
from ..model import (
    FEATURE_TYPES,
    MATERIALS,
    Document,
    edge_ref,
    face_ref,
    get_path,
    part_info,
    rebuild,
    set_path,
)
from .icons import icon
from .properties import PropertyPanel
from .viewport import SKETCH_TOOLS, TOOL_NAMES, Viewport

APP_NAME = "3D Maker"
FILE_FILTER = "3D Maker project (*.3dmk)"

INSERT_MENU = ["box", "cylinder", "sphere", "cone", "torus", "text", "extrude", "import_step"]
TOOLS_MENU = ["hole", "fillet", "chamfer", "shell", "mirror", "scale"]


class PanelItem(QFrame):
    """One row of the tool panel: square icon button, name, shortcut chip."""

    clicked = Signal()

    def __init__(self, icon_name, text, shortcut="", sub="", menu=None, parent=None):
        super().__init__(parent)
        self.setObjectName("panelItem")
        self.setCursor(Qt.PointingHandCursor)
        self.menu = menu
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 8, 3)
        lay.setSpacing(10)
        self.btn = QToolButton()
        self.btn.setObjectName("panelIcon")
        self.btn.setIcon(icon(icon_name, "#e8e9ec"))
        self.btn.setIconSize(QSize(22, 22))
        self.btn.setCheckable(True)
        self.btn.clicked.connect(self._click)
        lay.addWidget(self.btn)
        col = QVBoxLayout()
        col.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.name = QLabel(text)
        self.name.setObjectName("panelName")
        row.addWidget(self.name)
        for part in [p for p in shortcut.split("+") if p]:
            chip = QLabel(part)
            chip.setObjectName("keyChip")
            chip.setFixedHeight(18)
            chip.setAlignment(Qt.AlignCenter)
            row.addWidget(chip, 0, Qt.AlignVCenter)
        if menu is not None:
            arrow = QLabel("▸")
            arrow.setObjectName("panelSub")
            row.addWidget(arrow)
        row.addStretch(1)
        col.addLayout(row)
        self.sub = QLabel(sub)
        self.sub.setObjectName("panelSub")
        self.sub.setVisible(bool(sub))
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        tip = text + (f" ({shortcut})" if shortcut else "")
        self.setToolTip(tip)

    def set_sub(self, text):
        self.sub.setText(text)
        self.sub.setVisible(bool(text))

    def set_checked(self, on):
        self.btn.setChecked(on)
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def _click(self):
        self.btn.setChecked(self.property("active") is True)
        if self.menu is not None:
            self.menu.exec(self.mapToGlobal(self.rect().topRight()))
        else:
            self.clicked.emit()

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._click()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.part = None
        self.tools: list = []
        self.settings = QSettings("3DMaker", "3DMaker")
        self._show_tool = False
        self._session_shapes: list[tuple[str, int]] = []
        self._rebuild_timer = QTimer(self, singleShot=True, interval=120)
        self._rebuild_timer.timeout.connect(self.regenerate)

        self.viewport = Viewport(self)
        self.viewport.selectionChanged.connect(self.update_context)
        self.viewport.hintChanged.connect(self.set_hint)
        self.viewport.shapeDrawn.connect(self.on_shape_drawn)
        self.viewport.pullDragged.connect(self.on_pull_dragged)
        self.viewport.roundDragged.connect(lambda sel, r: self.round_edges(sel, r, "fillet"))
        self.viewport.toolChanged.connect(self.on_tool_changed)
        self.viewport.modeChanged.connect(self.on_mode_changed)

        self._build_actions()
        self._build_top_bar()
        self._build_center()
        self._build_side_dock()
        self._build_status()
        self.resize(1440, 900)
        self.refresh_history()
        self.regenerate()
        self.viewport.set_tool("select")
        self.on_mode_changed("model")

    # ------------------------------------------------------------------ UI
    def _act(self, text, slot, shortcut=None, icon_name=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon_name:
            a.setIcon(icon(icon_name, "#e8e9ec"))
        sc = f" ({QKeySequence(shortcut).toString()})" if shortcut else ""
        a.setToolTip((tip or text) + sc)
        self.addAction(a)
        return a

    def _build_actions(self):
        self.a_new = self._act("New", self.file_new, QKeySequence.New, "new")
        self.a_open = self._act("Open…", self.file_open, QKeySequence.Open, "open")
        self.a_save = self._act("Save", self.file_save, QKeySequence.Save, "save")
        self.a_save_as = self._act("Save As…", self.file_save_as, QKeySequence.SaveAs)
        self.a_export = self._act("Export", self.file_export, "Ctrl+E", "export", "Export STL / 3MF / STEP")
        self.a_undo = self._act("Undo", self.undo, QKeySequence.Undo, "undo")
        self.a_redo = self._act("Redo", self.redo, "Ctrl+Y", "redo")
        self.a_delete = self._act("Delete", self.delete_selected, QKeySequence.Delete, "trash")
        self.a_dup = self._act("Duplicate Step", self.duplicate_selected, "Ctrl+D")
        self.a_fit = self._act("Fit View", self.viewport.fit, "F", "fit")
        self.a_help = self._act("Quick Guide", self.show_help, "F1", "help")
        self.tool_shortcuts = {}
        for key, sc in [("select", "V"), ("line", "L"), ("rect", "R"), ("circle", "C"), ("polygon", "G"),
                        ("slot", "S")]:
            self.tool_shortcuts[key] = self._act(TOOL_NAMES[key], lambda _=False, k=key: self.viewport.set_tool(k),
                                                 sc)
        self._act("Sketch", self.start_sketch, "K")
        self._act("Exit Sketching", self.viewport.exit_sketch, "Ctrl+Return")

        menu = self.menuBar()
        m = menu.addMenu("File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_export)
        m.addSeparator()
        m.addAction(self._act("Quit", self.close, QKeySequence.Quit))
        m = menu.addMenu("Edit")
        for a in (self.a_undo, self.a_redo, self.a_dup, self.a_delete):
            m.addAction(a)
        m = menu.addMenu("Insert")
        for t in INSERT_MENU + TOOLS_MENU:
            m.addAction(FEATURE_TYPES[t].label, lambda t=t: self.add_feature(t))
        m = menu.addMenu("View")
        for key, label, sc in [("iso", "Isometric", "Ctrl+0"), ("top", "Top", "Ctrl+1"), ("front", "Front", "Ctrl+2"),
                               ("right", "Right", "Ctrl+3"), ("back", "Back", None), ("left", "Left", None),
                               ("bottom", "Bottom", None)]:
            m.addAction(self._act(label, lambda _=False, k=key: self.viewport.set_view(k), sc))
        m.addSeparator()
        m.addAction(self.a_fit)
        self.a_edges = self._act("Show Edges", self.toggle_edges)
        self.a_edges.setCheckable(True)
        self.a_edges.setChecked(True)
        m.addAction(self.a_edges)
        self.a_bed = self._act("Show Print Bed", self.toggle_bed)
        self.a_bed.setCheckable(True)
        self.a_bed.setChecked(True)
        m.addAction(self.a_bed)
        self.a_ortho = self._act("Orthographic", lambda: self.viewport.set_parallel(self.a_ortho.isChecked()),
                                 "Ctrl+P")
        self.a_ortho.setCheckable(True)
        m.addAction(self.a_ortho)
        m = menu.addMenu("Help")
        m.addAction(self.a_help)
        m.addAction(self._act("Open Error Log Folder", self.open_log_folder))

    def _build_top_bar(self):
        tb = QToolBar("Main", self)
        tb.setObjectName("topBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        for i in range(2):
            spacer = QWidget()
            spacer.setObjectName("spacer")
            spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            tb.addWidget(spacer)
            if i == 0:
                self.doc_label = QLabel("Untitled")
                self.doc_label.setObjectName("docName")
                tb.addWidget(self.doc_label)
        tb.addAction(self.a_fit)
        exp = QToolButton()
        exp.setDefaultAction(self.a_export)
        exp.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        exp.setIcon(icon("export", "#ffffff"))
        exp.setObjectName("primary")
        tb.addWidget(exp)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _panel_menu(self, entries):
        m = QMenu(self)
        for t in entries:
            m.addAction(FEATURE_TYPES[t].label, lambda t=t: self.add_feature(t))
        return m

    def _build_tool_panel(self):
        self.panel_items: dict[str, PanelItem] = {}
        stack = QStackedWidget()
        stack.setObjectName("toolPanel")

        def page(rows):
            w = QWidget()
            w.setObjectName("panelPage")
            lay = QVBoxLayout(w)
            lay.setContentsMargins(8, 10, 8, 10)
            lay.setSpacing(2)
            for row in rows:
                if row is None:
                    line = QFrame()
                    line.setObjectName("panelSep")
                    line.setFixedHeight(1)
                    lay.addSpacing(6)
                    lay.addWidget(line)
                    lay.addSpacing(6)
                    continue
                key, item, slot = row
                if slot is not None:
                    item.clicked.connect(slot)
                self.panel_items[key] = item
                lay.addWidget(item)
            lay.addStretch(1)
            return w

        model_rows = [
            ("m_sketch", PanelItem("sketch", "Sketch", "K", "Double-click a face"), self.start_sketch),
            ("m_insert", PanelItem("plus", "Insert", "", "Box, cylinder, text…", self._panel_menu(INSERT_MENU)),
             None),
            ("m_tools", PanelItem("tools", "Tools", "", "Hole, shell, mirror…", self._panel_menu(TOOLS_MENU)),
             None),
            None,
            ("m_select", PanelItem("select", "Select", "V"), lambda: self.viewport.set_tool("select")),
            ("m_fit", PanelItem("fit", "Fit View", "F"), self.viewport.fit),
            None,
            ("m_help", PanelItem("help", "Quick Guide", "F1"), self.show_help),
        ]
        sketch_rows = [
            ("s_exit", PanelItem("close", "Exit Sketching", "Esc"), self.viewport.exit_sketch),
            None,
            ("select", PanelItem("select", "Select", "V"), lambda: self.viewport.set_tool("select")),
            ("line", PanelItem("line", "Line", "L"), lambda: self.viewport.set_tool("line")),
            ("rect", PanelItem("rect", "Rectangle", "R", "Corner to corner"), lambda: self.viewport.set_tool("rect")),
            ("circle", PanelItem("circle", "Circle", "C", "Center and diameter"),
             lambda: self.viewport.set_tool("circle")),
            ("polygon", PanelItem("polygon", "Polygon", "G", "Hexagon"), lambda: self.viewport.set_tool("polygon")),
            ("slot", PanelItem("slot", "Slot", "S", "Center to center"), lambda: self.viewport.set_tool("slot")),
            None,
            ("s_delete", PanelItem("trash", "Delete", "Del"), self.delete_selected_shapes),
        ]
        stack.addWidget(page(model_rows))
        stack.addWidget(page(sketch_rows))
        stack.setFixedWidth(208)
        self.tool_stack = stack
        return stack

    def _build_center(self):
        center = QWidget()
        outer = QHBoxLayout(center)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_tool_panel())
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        strip = QFrame()
        strip.setObjectName("hintStrip")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.addStretch(1)
        self.hint = QLabel()
        self.hint.setObjectName("hintBar")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setMaximumWidth(820)
        self.hint.setMinimumWidth(560)
        sl.addWidget(self.hint)
        sl.addStretch(1)
        lay.addWidget(strip)
        lay.addWidget(self.viewport, 1)
        self.context = QFrame()
        self.context.setObjectName("contextBar")
        self.context_lay = QHBoxLayout(self.context)
        self.context_lay.setContentsMargins(14, 8, 14, 8)
        self.context_lay.setSpacing(8)
        lay.addWidget(self.context)
        outer.addWidget(col, 1)
        self.setCentralWidget(center)

    def _build_side_dock(self):
        dock = QDockWidget("History", self)
        dock.setObjectName("sideDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(8, 8, 8, 4)
        self.history = QListWidget()
        self.history.currentRowChanged.connect(self.on_history_select)
        self.history.itemChanged.connect(self.on_item_changed)
        self.history.itemClicked.connect(lambda _: self._history_clicked())
        tl.addWidget(self.history, 1)
        row = QHBoxLayout()
        for label, slot, tip in [("▲", lambda: self.move_selected(-1), "Move up"),
                                 ("▼", lambda: self.move_selected(1), "Move down"),
                                 ("Duplicate", self.duplicate_selected, "Duplicate step"),
                                 ("Delete", self.delete_history_item, "Delete step")]:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        tl.addLayout(row)
        split.addWidget(top)
        self.props = PropertyPanel()
        self.props.changed.connect(self.on_param_changed)
        self.props.renamed.connect(self.on_renamed)
        split.addWidget(self.props)
        split.setSizes([300, 500])
        dock.setWidget(split)
        dock.setMinimumWidth(320)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_status(self):
        sb = self.statusBar()
        self.info_label = QLabel("")
        sb.addPermanentWidget(self.info_label)
        self.material = QComboBox()
        self.material.addItems(list(MATERIALS))
        self.material.currentTextChanged.connect(lambda _: self.update_info())
        sb.addPermanentWidget(QLabel("Material"))
        sb.addPermanentWidget(self.material)
        self.bed_combo = QComboBox()
        for label in ["220×220", "256×256", "180×180", "300×300", "350×350"]:
            self.bed_combo.addItem(label)
        self.bed_combo.currentTextChanged.connect(self.on_bed_changed)
        sb.addPermanentWidget(QLabel("Bed"))
        sb.addPermanentWidget(self.bed_combo)
        self.snap_combo = QComboBox()
        self.snap_combo.addItem("Grid (auto)", 0.0)
        for v in ["0.1", "0.5", "1", "5", "10"]:
            self.snap_combo.addItem(f"{v} mm", float(v))
        self.snap_combo.currentIndexChanged.connect(
            lambda i: setattr(self.viewport, "snap", self.snap_combo.itemData(i)))
        sb.addPermanentWidget(QLabel("Snap"))
        sb.addPermanentWidget(self.snap_combo)

    def set_hint(self, text):
        self.hint.setText(text)

    # ------------------------------------------------------- command bar
    def _clear_context(self):
        while self.context_lay.count():
            it = self.context_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _cbtn(self, text, slot, icon_name=None, primary=False, tip=None, danger=False):
        b = QPushButton(text)
        if icon_name:
            b.setIcon(icon(icon_name, "#ffffff"))
        if primary:
            b.setObjectName("primaryButton")
        elif danger:
            b.setObjectName("dangerButton")
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(slot)
        self.context_lay.addWidget(b)
        return b

    def _cspin(self, label, value, suffix=" mm", mn=-10000.0, mx=10000.0, step=1.0):
        self.context_lay.addWidget(QLabel(label))
        sp = QDoubleSpinBox()
        sp.setRange(mn, mx)
        sp.setDecimals(2)
        sp.setSingleStep(step)
        sp.setSuffix(suffix)
        sp.setValue(value)
        sp.setMinimumWidth(90)
        self.context_lay.addWidget(sp)
        return sp

    def _ctitle(self, text):
        t = QLabel(text)
        t.setObjectName("contextTitle")
        self.context_lay.addWidget(t)
        line = QFrame()
        line.setObjectName("sep")
        line.setFixedWidth(1)
        self.context_lay.addWidget(line)

    def update_context(self):
        self._clear_context()
        vp = self.viewport
        sel = vp.selection
        if vp.mode == "sketch":
            where = "a face" if vp.sketch and vp.sketch.get("fid") is not None else "the bed"
            self._ctitle(f"Sketching on {where}")
            if vp.tool == "polygon":
                self.context_lay.addWidget(QLabel("Sides"))
                sides = QSpinBox()
                sides.setRange(3, 64)
                sides.setValue(vp.polygon_sides)
                sides.valueChanged.connect(self._set_sides)
                self.context_lay.addWidget(sides)
            if sel:
                self.context_lay.addWidget(QLabel(f"{len(sel)} selected"))
                self._cbtn("Delete", self.delete_selected_shapes, "trash", danger=True)
            step = vp.snap if vp.snap > 0 else vp.grid_step
            self.context_lay.addStretch(1)
            self.context_lay.addWidget(QLabel(f"Grid {step:g} mm · Shift = free"))
            self._cbtn("Exit Sketching", vp.exit_sketch, "close", primary=True)
            return
        if vp.pending_tool:
            self._ctitle("Pick a plane")
            self.context_lay.addWidget(QLabel("Click a face of the model or the grid"))
            self.context_lay.addStretch(1)
            self._cbtn("Cancel", lambda: vp.set_tool("select"), "close")
            return
        if not sel:
            self._ctitle("Start")
            self._cbtn("Sketch", self.start_sketch, "sketch", primary=True)
            self._cbtn("Box", lambda: self.add_feature("box"), "shapes")
            self._cbtn("Cylinder", lambda: self.add_feature("cylinder"), "shapes")
            self.context_lay.addStretch(1)
            self.context_lay.addWidget(QLabel("Double-click a face to sketch on it"))
            return
        kind = sel[0]["kind"]
        n = len(sel)
        if kind == "profile":
            self._ctitle(f"{n} sketch region{'s' if n > 1 else ''}")
            sp = self._cspin("Distance", 10.0, step=1.0, mn=0.01)
            self._cbtn("Extrude", lambda: self.pull_profiles(sel, sp.value()), "pull", True, "Add material")
            self._cbtn("Cut", lambda: self.pull_profiles(sel, -sp.value()), "hole", tip="Cut into the body")
            self._cbtn("Cut Through", lambda: self.pull_profiles(sel, -1, through=True), "hole",
                       tip="Cut through the whole body")
            self.context_lay.addStretch(1)
            self._cbtn("Edit Sketch", lambda: self.edit_sketch_of(sel[0]), "sketch")
            self._cbtn("Delete", self.delete_selected_shapes, "trash", danger=True)
        elif kind == "face":
            planar = all(vp.is_planar_face(s["fid"]) for s in sel)
            self._ctitle(f"{n} face{'s' if n > 1 else ''}")
            if vp.pull_target() is not None:
                sp = self._cspin("Distance", 5.0, mn=0.01)
                self._cbtn("Pull", lambda: self.pushpull_faces(sel, sp.value()), "pull", True)
                self._cbtn("Push", lambda: self.pushpull_faces(sel, -sp.value()), "hole")
            if planar and n == 1:
                self._cbtn("Sketch Here", lambda: self.sketch_on_face(sel[0]), "sketch")
            self._cbtn("Shell", lambda: self.shell_faces(sel), "shell", tip="Hollow the body, leaving this face open")
            rb = self._cbtn("Round Edges ▾", lambda: None, "fillet", tip="Fillet or chamfer every edge of the face")
            m = QMenu(rb)
            for r in (0.5, 1, 2, 3, 5):
                m.addAction(f"Fillet {r:g} mm", lambda r=r: self.round_face_edges(sel, r, "fillet"))
            m.addSeparator()
            for r in (0.5, 1, 2):
                m.addAction(f"Chamfer {r:g} mm", lambda r=r: self.round_face_edges(sel, r, "chamfer"))
            rb.setMenu(m)
            self.context_lay.addStretch(1)
        elif kind == "edge":
            self._ctitle(f"{n} edge{'s' if n > 1 else ''}")
            r = self._cspin("Size", 2.0, mn=0.01, step=0.5)
            self._cbtn("Fillet", lambda: self.round_edges(sel, r.value(), "fillet"), "fillet", True)
            self._cbtn("Chamfer", lambda: self.round_edges(sel, r.value(), "chamfer"), "chamfer")
            self.context_lay.addStretch(1)
        self._cbtn("✕", vp.clear_selection, tip="Clear selection (Esc)")

    def _set_sides(self, n):
        self.viewport.polygon_sides = n
        if "polygon" in self.panel_items:
            names = {3: "Triangle", 4: "Square", 5: "Pentagon", 6: "Hexagon", 8: "Octagon"}
            self.panel_items["polygon"].set_sub(names.get(n, f"{n} sides"))

    def on_tool_changed(self, tool):
        active = self.viewport.pending_tool or tool
        for key, item in self.panel_items.items():
            if key in SKETCH_TOOLS or key == "select":
                item.set_checked(key == active)
        if "m_sketch" in self.panel_items:
            self.panel_items["m_sketch"].set_checked(bool(self.viewport.pending_tool))
        self.update_context()

    def on_mode_changed(self, mode):
        self.tool_stack.setCurrentIndex(1 if mode == "sketch" else 0)
        if mode == "sketch":
            self._session_shapes = []
        self._show(keep_selection=False)
        if mode == "model" and self._session_shapes:
            # hand the regions you just drew straight to the extrude arrow
            vis = {(p["uid"], p["idx"]) for p in self.viewport.profiles if p["face"] is not None}
            items = [{"kind": "profile", "uid": u, "idx": i} for u, i in self._session_shapes if (u, i) in vis]
            uids = {it["uid"] for it in items}
            if items and len(uids) == 1:
                self.viewport.select_items(items)
        self.update_context()

    # ------------------------------------------------------- operations
    def start_sketch(self):
        self.viewport.set_tool("line")

    def sketch_on_face(self, item):
        f = self.viewport.faces[item["fid"]]
        c, n = f.center(), f.normal_at()
        self.viewport.enter_sketch((c.X, c.Y, c.Z), (n.X, n.Y, n.Z), item["fid"])

    def edit_sketch_of(self, item):
        pr = self.viewport.profile_entry(item)
        if pr is not None:
            self.viewport.enter_sketch(pr["plane"][0], pr["plane"][3], None, tool="select")

    def _added(self, feature):
        self._show_tool = False
        self.refresh_history(self.doc.features.index(feature))
        self.regenerate()

    def pull_profiles(self, sel, distance, through=False):
        by_sketch: dict[str, list[int]] = {}
        for s in sel:
            by_sketch.setdefault(s["uid"], []).append(s["idx"])
        self.doc.checkpoint()
        last = None
        for uid, idxs in by_sketch.items():
            name = "Extrude" if distance > 0 and not through else ("Cut Through" if through else "Cut")
            last = self.doc.add("pull", checkpoint=False, sketch=uid, shapes=sorted(idxs),
                                distance=float(distance), through=through)
            last.name = self.doc.unique_name(name)
        self._added(last)

    def pushpull_faces(self, sel, distance):
        refs = [face_ref(self.viewport.faces[s["fid"]], s.get("point")) for s in sel]
        f = self.doc.add("pushpull", face_refs=refs, distance=float(distance))
        f.name = self.doc.unique_name("Pull Face" if distance > 0 else "Push Face")
        self._added(f)

    def on_pull_dragged(self, sel, distance):
        if not sel:
            return
        if sel[0]["kind"] == "profile":
            self.pull_profiles(sel, distance)
        elif sel[0]["kind"] == "face":
            self.pushpull_faces(sel, distance)

    def round_edges(self, sel, value, kind):
        refs = [edge_ref(self.viewport.edges[s["eid"]]) for s in sel]
        key = "radius" if kind == "fillet" else "length"
        f = self.doc.add(kind, edges="picked", edge_refs=refs, **{key: float(value)})
        self._added(f)

    def round_face_edges(self, sel, value, kind):
        refs = []
        for s in sel:
            refs += [edge_ref(e) for e in self.viewport.faces[s["fid"]].edges()]
        key = "radius" if kind == "fillet" else "length"
        f = self.doc.add(kind, edges="picked", edge_refs=refs, **{key: float(value)})
        self._added(f)

    def shell_faces(self, sel):
        refs = [face_ref(self.viewport.faces[s["fid"]], s.get("point")) for s in sel]
        f = self.doc.add("shell", opening="picked", face_refs=refs)
        self._added(f)

    def on_shape_drawn(self, plane, shape):
        sk, idx = self.doc.add_sketch_shape(plane, shape)
        if shape["kind"] != "path":
            self._session_shapes.append((sk.uid, idx))
        self._show_tool = False
        self.refresh_history(self.doc.features.index(sk))
        self.regenerate()
        if self.viewport.mode != "sketch":
            self.viewport.select_items([{"kind": "profile", "uid": sk.uid, "idx": idx}])

    def delete_selected_shapes(self):
        sel = [s for s in self.viewport.selection if s["kind"] == "profile"]
        if not sel:
            return
        by: dict[str, list[int]] = {}
        for s in sel:
            by.setdefault(s["uid"], []).append(s["idx"])
        for uid, idxs in by.items():
            self.doc.delete_shapes(uid, idxs)
        self.refresh_history()
        self.regenerate()

    def add_feature(self, type_id):
        f = self.doc.add(type_id)
        if type_id in ("hole", "text") and self.part is not None:
            f.params["z"] = round(self.part.bounding_box().max.Z, 3)
        self._added(f)

    # --------------------------------------------------------- history
    def current_index(self) -> int:
        return self.history.currentRow()

    def current_feature(self):
        i = self.current_index()
        return self.doc.features[i] if 0 <= i < len(self.doc.features) else None

    @staticmethod
    def _label(f):
        tag = {"cut": "  ✂", "intersect": "  ∩"}.get(f.params.get("mode"), "")
        return f"{f.ftype.icon}   {f.name}{tag}"

    def refresh_history(self, select: int | None = None):
        if select is None:
            select = self.current_index()
        self.history.blockSignals(True)
        self.history.clear()
        for f in self.doc.features:
            item = QListWidgetItem(self._label(f))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if f.enabled else Qt.Unchecked)
            self.history.addItem(item)
        if self.doc.features:
            self.history.setCurrentRow(min(max(select, 0), len(self.doc.features) - 1))
        self.history.blockSignals(False)
        self.props.set_feature(self.current_feature())
        self._refresh_history_status()

    def _refresh_history_status(self):
        self.history.blockSignals(True)
        for i, f in enumerate(self.doc.features):
            item = self.history.item(i)
            if item is None:
                continue
            item.setText(self._label(f))
            if f.error:
                item.setForeground(Qt.red)
                item.setToolTip(f"⚠ {f.error}")
            else:
                item.setForeground(Qt.gray if not f.enabled else self.history.palette().text().color())
                item.setToolTip("Untick to turn this step off temporarily")
        self.history.blockSignals(False)

    def _history_clicked(self):
        self._show_tool = True
        self._show()

    def on_history_select(self, row):
        self.props.set_feature(self.current_feature())
        self._show_tool = True
        self._show()

    def on_item_changed(self, item):
        row = self.history.row(item)
        f = self.doc.features[row]
        enabled = item.checkState() == Qt.Checked
        if enabled != f.enabled:
            self.doc.checkpoint()
            f.enabled = enabled
            self._rebuild_timer.start()

    def on_param_changed(self, key, value):
        f = self.current_feature()
        if f is None:
            return
        try:
            if get_path(f.params, key) == value:
                return
        except (KeyError, IndexError):
            pass
        self.doc.checkpoint()
        f = self.current_feature()
        try:
            set_path(f.params, key, value)
        except ValueError as exc:
            self.statusBar().showMessage(f"⚠ {exc}", 5000)
            return
        self.props.feature = f
        self._rebuild_timer.start()

    def on_renamed(self, name):
        f = self.current_feature()
        if f is None or f.name == name:
            return
        self.doc.checkpoint()
        self.current_feature().name = name
        self._refresh_history_status()
        self.update_title()

    def delete_selected(self):
        vp = self.viewport
        if vp.selection and vp.selection[0]["kind"] == "profile" and self.focusWidget() is not self.history:
            self.delete_selected_shapes()
        elif self.focusWidget() is self.history or not vp.selection:
            if vp.mode != "sketch":
                self.delete_history_item()

    def delete_history_item(self):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            self.doc.remove(i)
            self.refresh_history(max(i - 1, 0))
            self.regenerate()

    def duplicate_selected(self):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            self.doc.duplicate(i)
            self.refresh_history(i + 1)
            self.regenerate()

    def move_selected(self, delta):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            j = self.doc.move(i, delta)
            self.refresh_history(j)
            self.regenerate()

    def undo(self):
        if self.doc.undo():
            self.refresh_history()
            self.regenerate()

    def redo(self):
        if self.doc.redo():
            self.refresh_history()
            self.regenerate()

    # ------------------------------------------------------- modelling
    def regenerate(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.part, self.tools = rebuild(self.doc.features)
        except Exception:
            traceback.print_exc()
        finally:
            QApplication.restoreOverrideCursor()
        self._show(keep_selection=True)
        self._refresh_history_status()
        errors = [f for f in self.doc.features if f.error]
        if errors:
            self.statusBar().showMessage(f"⚠ {errors[-1].name}: {errors[-1].error}", 8000)
        f = self.current_feature()
        self.props.set_error(f.error if f is not None else None)
        self.update_info()
        self.update_title()

    def _visible_profiles(self):
        used = self.doc.consumed_shapes()
        cur = self.current_feature()
        sketching = self.viewport.mode == "sketch"
        out = []
        for f in self.doc.features:
            if f.type_id != "sketch" or not f.enabled:
                continue
            show_all = sketching or (self._show_tool and cur is f)
            for i, s in enumerate(f.params["shapes"]):
                if show_all or (f.uid, i) not in used:
                    out.append({"uid": f.uid, "idx": i, "origin": f.params["origin"],
                                "normal": f.params["normal"], "shape": s})
        return out

    def _show(self, keep_selection=False):
        i = self.current_index()
        tool, mode = None, "add"
        if self._show_tool and 0 <= i < len(self.tools) and self.viewport.mode == "model":
            f = self.doc.features[i]
            tool = self.tools[i]
            mode = f.params.get("mode", "add")
            if mode == "auto":
                mode = "add" if f.params.get("distance", 1) > 0 and not f.params.get("through") else "cut"
            if f.ftype.category == "body" and i == 0:
                tool = None
        self.viewport.set_scene(self.part, self._visible_profiles(), tool, mode, keep_selection)

    def update_title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else "Untitled"
        self.setWindowTitle(f"{'● ' if self.doc.dirty else ''}{name} — {APP_NAME}")
        if hasattr(self, "doc_label"):
            self.doc_label.setText(("● " if self.doc.dirty else "") + name)

    def update_info(self):
        info = part_info(self.part, self.material.currentText())
        if info is None:
            self.info_label.setText("No body yet")
            return
        x, y, z = info["size"]
        txt = (f"{x:.1f} × {y:.1f} × {z:.1f} mm   {info['volume_cm3']:.2f} cm³   ≈ {info['weight_g']:.1f} g")
        if info["min"][2] < -0.01:
            txt += "   ⚠ below the bed"
        bw, bd = self.viewport.bed_size
        if x > bw or y > bd:
            txt += "   ⚠ larger than the bed"
        self.info_label.setText(txt)

    # ------------------------------------------------------------ view
    def toggle_edges(self):
        self.viewport.show_edges = self.a_edges.isChecked()
        self._show(keep_selection=True)

    def toggle_bed(self):
        self.viewport.set_bed(*self.viewport.bed_size, visible=self.a_bed.isChecked())

    def on_bed_changed(self, text):
        w, d = (float(v) for v in text.split("×"))
        self.viewport.set_bed(w, d, self.a_bed.isChecked())
        self.update_info()

    # ------------------------------------------------------------ files
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty or not self.doc.features:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this project before closing it?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def _last_dir(self):
        return self.settings.value("lastDir", os.path.expanduser("~"))

    def file_new(self):
        if not self._confirm_discard():
            return
        self.viewport.exit_sketch()
        self.doc = Document()
        self.viewport._has_fit = False
        self.refresh_history(0)
        self.regenerate()

    def file_open(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open Project", self._last_dir(), FILE_FILTER)
        if not path:
            return
        try:
            doc = Document()
            doc.load(path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Couldn't open the file:\n{exc}")
            return
        self.viewport.exit_sketch()
        self.settings.setValue("lastDir", os.path.dirname(path))
        self.doc = doc
        self.viewport._has_fit = False
        self.refresh_history(len(doc.features) - 1)
        self.regenerate()

    def file_save(self) -> bool:
        if not self.doc.path:
            return self.file_save_as()
        self.doc.save(self.doc.path)
        self.update_title()
        self.statusBar().showMessage(f"Saved {self.doc.path}", 4000)
        return True

    def file_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", self._last_dir(), FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".3dmk"):
            path += ".3dmk"
        self.settings.setValue("lastDir", os.path.dirname(path))
        self.doc.path = path
        return self.file_save()

    def file_export(self):
        if self.part is None:
            QMessageBox.information(self, APP_NAME, "There's nothing to export yet. Extrude a sketch first.")
            return
        base = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else "model"
        filters = ";;".join(FORMATS.values())
        path, chosen = QFileDialog.getSaveFileName(self, "Export", os.path.join(self._last_dir(), base + ".stl"),
                                                   filters)
        if not path:
            return
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in FORMATS and ext != "stp":
            ext = next(k for k, v in FORMATS.items() if v == chosen)
            path += "." + ext
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            export_part(self.part, path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Export failed:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.settings.setValue("lastDir", os.path.dirname(path))
        self.statusBar().showMessage(f"Exported {path}", 6000)

    def open_log_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ..__main__ import LOG_DIR
        os.makedirs(LOG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_DIR))

    def show_help(self):
        QMessageBox.information(self, "Quick Guide", HELP_TEXT)

    def closeEvent(self, event):  # noqa: N802
        if self._confirm_discard():
            self.viewport.close()
            event.accept()
        else:
            event.ignore()


HELP_TEXT = """<h3>Select something, then act on it</h3>
<b>Make a part</b><br>
1. Double-click the grid (or a face of your model) to start sketching on it.<br>
2. Draw with Line (L), Rectangle (R), Circle (C), Polygon (G) or Slot (S).
   Type a number while drawing to set the size exactly, then press Enter.<br>
3. Press Esc or Exit Sketching. Your shapes stay selected —
   <b>drag the blue arrow</b> up to extrude, or down to cut.<br><br>
<b>Drill a hole</b>: double-click a face → Circle (C) → click the center → type 5 → Enter →
Exit Sketching → <b>Cut Through</b>.<br><br>
<b>Snapping</b>: the cursor snaps to corners, midpoints and centers (purple), to lines and
horizontal/vertical alignments (blue), and to the grid. Hold Shift for free placement.<br><br>
<b>Mouse</b>: left = select / draw · right-drag = orbit · middle-drag = pan · wheel = zoom ·
right-click = cancel. A pen works as the left button; its barrel button orbits.<br>
<b>Keys</b>: V select · L R C G S tools · K sketch · Esc back · Del delete · Ctrl+Z / Ctrl+Y ·
F fit view<br><br>
Every step is listed in <b>History</b> on the right; click one to change its numbers.
"""
