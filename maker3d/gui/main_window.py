"""Main application window (Shapr3D-style: select something, then act on it)."""
from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
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
    QSplitter,
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
from .viewport import DRAW_TOOLS, Viewport

APP_NAME = "3D Maker"
FILE_FILTER = "โปรเจกต์ 3D Maker (*.3dmk)"

SHAPE_MENU = ["box", "cylinder", "sphere", "cone", "torus", "extrude", "text"]
MORE_MENU = ["hole", "fillet", "chamfer", "shell", "mirror", "scale", "import_step"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.part = None
        self.tools: list = []
        self.settings = QSettings("3DMaker", "3DMaker")
        self._show_tool = False
        self._rebuild_timer = QTimer(self, singleShot=True, interval=120)
        self._rebuild_timer.timeout.connect(self.regenerate)

        self.viewport = Viewport(self)
        self.viewport.selectionChanged.connect(self.update_context)
        self.viewport.hintChanged.connect(self.set_hint)
        self.viewport.shapeDrawn.connect(self.on_shape_drawn)
        self.viewport.pullDragged.connect(self.on_pull_dragged)
        self.viewport.toolChanged.connect(self.on_tool_changed)

        self._build_actions()
        self._build_top_bar()
        self._build_tool_rail()
        self._build_center()
        self._build_side_dock()
        self._build_status()
        self.resize(1440, 900)
        self.refresh_history()
        self.regenerate()
        self.viewport.set_tool("select")

    # ------------------------------------------------------------------ UI
    def _act(self, text, slot, shortcut=None, icon_name=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon_name:
            a.setIcon(icon(icon_name))
        sc = f" ({QKeySequence(shortcut).toString()})" if shortcut else ""
        a.setToolTip((tip or text) + sc)
        self.addAction(a)
        return a

    def _build_actions(self):
        self.a_new = self._act("ใหม่", self.file_new, QKeySequence.New, "new")
        self.a_open = self._act("เปิด", self.file_open, QKeySequence.Open, "open")
        self.a_save = self._act("บันทึก", self.file_save, QKeySequence.Save, "save")
        self.a_save_as = self._act("บันทึกเป็น…", self.file_save_as, QKeySequence.SaveAs)
        self.a_export = self._act("ส่งออก", self.file_export, "Ctrl+E", "export", "ส่งออก STL / 3MF / STEP")
        self.a_undo = self._act("ย้อนกลับ", self.undo, QKeySequence.Undo, "undo")
        self.a_redo = self._act("ทำซ้ำ", self.redo, "Ctrl+Y", "redo")
        self.a_delete = self._act("ลบ", self.delete_selected, QKeySequence.Delete, "trash")
        self.a_dup = self._act("คัดลอกขั้นตอน", self.duplicate_selected, "Ctrl+D")
        self.a_fit = self._act("พอดีจอ", self.viewport.fit, "F", "fit")
        self.a_help = self._act("วิธีใช้", self.show_help, "F1", "help")

        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for key, label, sc, ic in [("select", "เลือก", "V", "select"), ("poly", "เส้น", "L", "line"),
                                   ("rect", "สี่เหลี่ยม", "R", "rect"), ("circle", "วงกลม", "C", "circle")]:
            a = self._act(label, lambda _=False, k=key: self.viewport.set_tool(k), sc, ic)
            a.setCheckable(True)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a

        menu = self.menuBar()
        m = menu.addMenu("ไฟล์")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_export)
        m.addSeparator()
        m.addAction(self._act("ออก", self.close, QKeySequence.Quit))
        m = menu.addMenu("แก้ไข")
        for a in (self.a_undo, self.a_redo, self.a_dup, self.a_delete):
            m.addAction(a)
        m = menu.addMenu("มุมมอง")
        m.addAction(self.a_fit)
        self.a_edges = self._act("แสดงเส้นขอบ", self.toggle_edges)
        self.a_edges.setCheckable(True)
        self.a_edges.setChecked(True)
        m.addAction(self.a_edges)
        self.a_bed = self._act("แสดงฐานพิมพ์", self.toggle_bed)
        self.a_bed.setCheckable(True)
        self.a_bed.setChecked(True)
        m.addAction(self.a_bed)
        m = menu.addMenu("ช่วยเหลือ")
        m.addAction(self.a_help)

    def _menu_button(self, text, icon_name, entries, tip):
        b = QToolButton()
        b.setText(text)
        b.setIcon(icon(icon_name))
        b.setToolTip(tip)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setObjectName("railButton")
        menu = QMenu(b)
        for type_id in entries:
            ft = FEATURE_TYPES[type_id]
            menu.addAction(f"{ft.icon}   {ft.label}", lambda t=type_id: self.add_feature(t))
        b.setMenu(menu)
        return b

    def _build_top_bar(self):
        tb = QToolBar("หลัก", self)
        tb.setObjectName("topBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        spacer = QWidget()
        spacer.setObjectName("spacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        views = QToolButton()
        views.setText("มุมมอง")
        views.setIcon(icon("view"))
        views.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        views.setPopupMode(QToolButton.InstantPopup)
        vm = QMenu(views)
        for key, label, sc in [("iso", "3 มิติ", "Ctrl+0"), ("top", "ด้านบน", "Ctrl+1"),
                               ("front", "ด้านหน้า", "Ctrl+2"), ("right", "ด้านขวา", "Ctrl+3"),
                               ("back", "ด้านหลัง", None), ("left", "ด้านซ้าย", None), ("bottom", "ด้านล่าง", None)]:
            vm.addAction(self._act(label, lambda _=False, k=key: self.viewport.set_view(k), sc))
        views.setMenu(vm)
        tb.addWidget(views)
        tb.addAction(self.a_fit)
        tb.addSeparator()
        exp = QToolButton()
        exp.setDefaultAction(self.a_export)
        exp.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        exp.setIcon(icon("export", "#ffffff"))
        exp.setObjectName("primary")
        tb.addWidget(exp)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _build_tool_rail(self):
        rail = QToolBar("เครื่องมือ", self)
        rail.setObjectName("toolRail")
        rail.setMovable(False)
        rail.setOrientation(Qt.Vertical)
        rail.setIconSize(QSize(26, 26))
        rail.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        cap = QLabel("วาด")
        cap.setObjectName("railCaption")
        cap.setAlignment(Qt.AlignCenter)
        rail.addWidget(cap)
        for key in ("select", "poly", "rect", "circle"):
            rail.addAction(self.tool_actions[key])
        rail.addSeparator()
        cap = QLabel("เพิ่ม")
        cap.setObjectName("railCaption")
        cap.setAlignment(Qt.AlignCenter)
        rail.addWidget(cap)
        rail.addWidget(self._menu_button("รูปทรง", "shapes", SHAPE_MENU, "รูปทรงสำเร็จรูป: กล่อง ทรงกระบอก ..."))
        rail.addWidget(self._menu_button("อื่นๆ", "more", MORE_MENU, "คำสั่งอื่นๆ: รูเจาะ สะท้อน ย่อขยาย ..."))
        rail.addSeparator()
        rail.addAction(self.a_help)
        for b in rail.findChildren(QToolButton):
            b.setObjectName("railButton")
        self.addToolBar(Qt.LeftToolBarArea, rail)

    def _build_center(self):
        center = QWidget()
        lay = QVBoxLayout(center)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.hint = QLabel()
        self.hint.setObjectName("hintBar")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addWidget(self.viewport, 1)
        self.context = QFrame()
        self.context.setObjectName("contextBar")
        self.context_lay = QHBoxLayout(self.context)
        self.context_lay.setContentsMargins(14, 8, 14, 8)
        self.context_lay.setSpacing(8)
        lay.addWidget(self.context)
        self.setCentralWidget(center)

    def _build_side_dock(self):
        dock = QDockWidget("ประวัติการสร้าง", self)
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
        for label, slot, tip in [("▲", lambda: self.move_selected(-1), "เลื่อนขึ้น"),
                                 ("▼", lambda: self.move_selected(1), "เลื่อนลง"),
                                 ("คัดลอก", self.duplicate_selected, "คัดลอกขั้นตอน"),
                                 ("ลบ", self.delete_history_item, "ลบขั้นตอน")]:
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
        dock.setMinimumWidth(330)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_status(self):
        sb = self.statusBar()
        self.info_label = QLabel("")
        sb.addPermanentWidget(self.info_label)
        self.material = QComboBox()
        self.material.addItems(list(MATERIALS))
        self.material.currentTextChanged.connect(lambda _: self.update_info())
        sb.addPermanentWidget(QLabel("วัสดุ:"))
        sb.addPermanentWidget(self.material)
        self.bed_combo = QComboBox()
        for label in ["220×220", "256×256", "180×180", "300×300", "350×350"]:
            self.bed_combo.addItem(label)
        self.bed_combo.currentTextChanged.connect(self.on_bed_changed)
        sb.addPermanentWidget(QLabel("ฐานพิมพ์:"))
        sb.addPermanentWidget(self.bed_combo)
        self.snap_combo = QComboBox()
        for v in ["1", "0.5", "0.1", "5", "10"]:
            self.snap_combo.addItem(f"{v} mm", float(v))
        self.snap_combo.currentIndexChanged.connect(
            lambda i: setattr(self.viewport, "snap", self.snap_combo.itemData(i)))
        sb.addPermanentWidget(QLabel("กริดดูด:"))
        sb.addPermanentWidget(self.snap_combo)

    def set_hint(self, text):
        self.hint.setText("💡  " + text)

    # ------------------------------------------------------- context bar
    def _clear_context(self):
        while self.context_lay.count():
            it = self.context_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _cbtn(self, text, slot, icon_name=None, primary=False, tip=None):
        b = QPushButton(text)
        if icon_name:
            b.setIcon(icon(icon_name, "#ffffff" if primary else "#2b3440"))
        if primary:
            b.setObjectName("primaryButton")
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(slot)
        self.context_lay.addWidget(b)
        return b

    def _cspin(self, label, value, suffix=" mm", mn=-10000.0, mx=10000.0, step=1.0):
        lab = QLabel(label)
        self.context_lay.addWidget(lab)
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
        line.setFrameShape(QFrame.VLine)
        line.setObjectName("sep")
        self.context_lay.addWidget(line)

    def update_context(self):
        self._clear_context()
        vp = self.viewport
        sel = vp.selection
        if vp.tool in DRAW_TOOLS:
            names = {"circle": "วงกลม", "rect": "สี่เหลี่ยม", "poly": "เส้น/หลายเหลี่ยม"}
            self._ctitle(f"กำลังวาด{names[vp.tool]}")
            self.context_lay.addWidget(QLabel("กด Shift ค้างเพื่อวางละเอียด 0.1 mm"))
            self.context_lay.addStretch(1)
            self._cbtn("เสร็จ / เลือก (Esc)", lambda: vp.set_tool("select"), "select")
            return
        if not sel:
            self._ctitle("เริ่มต้น")
            self._cbtn("วาดสี่เหลี่ยม", lambda: vp.set_tool("rect"), "rect")
            self._cbtn("วาดวงกลม", lambda: vp.set_tool("circle"), "circle")
            self._cbtn("กล่อง", lambda: self.add_feature("box"), "shapes")
            self._cbtn("ทรงกระบอก", lambda: self.add_feature("cylinder"), "shapes")
            self.context_lay.addStretch(1)
            self.context_lay.addWidget(QLabel("หรือคลิกที่หน้า/ขอบของชิ้นงานเพื่อดูคำสั่งที่ใช้ได้"))
            return
        kind = sel[0]["kind"]
        n = len(sel)
        if kind == "profile":
            self._ctitle(f"รูปสเก็ตช์ {n} รูป")
            sp = self._cspin("ระยะ", 10.0, step=1.0, mn=0.01)
            self._cbtn("ดึงขึ้น", lambda: self.pull_profiles(sel, sp.value()), "pull", True,
                       "เพิ่มเนื้อขึ้นจากรูปนี้")
            self._cbtn("เจาะลง", lambda: self.pull_profiles(sel, -sp.value()), "hole", tip="ตัดเนื้อลงไปตามระยะ")
            self._cbtn("เจาะทะลุ", lambda: self.pull_profiles(sel, -1, through=True), "hole",
                       tip="ตัดทะลุทั้งชิ้นงาน")
            self.context_lay.addStretch(1)
            self._cbtn("ลบรูป", self.delete_selected_shapes, "trash")
        elif kind == "face":
            planar = all(vp.is_planar_face(s["fid"]) for s in sel)
            self._ctitle(f"เลือก {n} หน้า")
            if vp.pull_target() is not None:
                sp = self._cspin("ระยะ", 5.0, mn=0.01)
                self._cbtn("ดึงออก", lambda: self.pushpull_faces(sel, sp.value()), "pull", True)
                self._cbtn("กดเข้า", lambda: self.pushpull_faces(sel, -sp.value()), "hole")
            if planar and n == 1:
                f = vp.faces[sel[0]["fid"]]
                nrm = f.normal_at()
                self._cbtn("มองตรง", lambda: vp.set_view("normal", (nrm.X, nrm.Y, nrm.Z)), "look",
                           tip="หันกล้องมองตั้งฉากกับหน้านี้ เหมาะสำหรับวาดสเก็ตช์")
            self._cbtn("ทำให้กลวง", lambda: self.shell_faces(sel), "shell", tip="คว้านด้านในโดยเปิดหน้าที่เลือก")
            rb = self._cbtn("ลบมุมขอบหน้า ▾", lambda: None, "fillet", tip="ลบมุมทุกขอบรอบหน้าที่เลือก")
            m = QMenu(rb)
            for r in (0.5, 1, 2, 3, 5):
                m.addAction(f"โค้ง R{r:g} mm", lambda r=r: self.round_face_edges(sel, r, "fillet"))
            m.addSeparator()
            for r in (0.5, 1, 2):
                m.addAction(f"เฉียง {r:g} mm", lambda r=r: self.round_face_edges(sel, r, "chamfer"))
            rb.setMenu(m)
            self.context_lay.addStretch(1)
        elif kind == "edge":
            self._ctitle(f"เลือก {n} ขอบ")
            r = self._cspin("รัศมี/ระยะ", 2.0, mn=0.01, step=0.5)
            self._cbtn("ลบมุมโค้ง", lambda: self.round_edges(sel, r.value(), "fillet"), "fillet", True)
            self._cbtn("ลบมุมเฉียง", lambda: self.round_edges(sel, r.value(), "chamfer"), "chamfer")
            self.context_lay.addStretch(1)
        self._cbtn("✕", vp.clear_selection, tip="ยกเลิกการเลือก (Esc)")

    def on_tool_changed(self, tool):
        a = self.tool_actions.get(tool)
        if a is not None and not a.isChecked():
            a.setChecked(True)
        self.update_context()

    # ------------------------------------------------------- operations
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
            name = "ดึงขึ้น" if distance > 0 and not through else ("เจาะทะลุ" if through else "เจาะ")
            last = self.doc.add("pull", checkpoint=False, sketch=uid, shapes=sorted(idxs),
                                distance=float(distance), through=through)
            last.name = self.doc.unique_name(name)
        self._added(last)

    def pushpull_faces(self, sel, distance):
        refs = [face_ref(self.viewport.faces[s["fid"]], s.get("point")) for s in sel]
        f = self.doc.add("pushpull", face_refs=refs, distance=float(distance))
        f.name = self.doc.unique_name("ดึงหน้า" if distance > 0 else "กดหน้า")
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
        self._show_tool = False
        self.refresh_history(self.doc.features.index(sk))
        self.regenerate()
        self.viewport.set_tool("select")
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
                item.setToolTip("ติ๊กออกเพื่อปิดขั้นตอนชั่วคราว")
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
        if self.focusWidget() is self.history or not self.viewport.selection:
            self.delete_history_item()
        elif self.viewport.selection[0]["kind"] == "profile":
            self.delete_selected_shapes()

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
        out = []
        for f in self.doc.features:
            if f.type_id != "sketch" or not f.enabled:
                continue
            show_all = self._show_tool and cur is f
            for i, s in enumerate(f.params["shapes"]):
                if show_all or (f.uid, i) not in used:
                    out.append({"uid": f.uid, "idx": i, "origin": f.params["origin"],
                                "normal": f.params["normal"], "shape": s})
        return out

    def _show(self, keep_selection=False):
        i = self.current_index()
        tool, mode = None, "add"
        if self._show_tool and 0 <= i < len(self.tools):
            f = self.doc.features[i]
            tool = self.tools[i]
            mode = f.params.get("mode", "add")
            if mode == "auto":
                mode = "add" if f.params.get("distance", 1) > 0 and not f.params.get("through") else "cut"
            if f.ftype.category == "body" and i == 0:
                tool = None
        self.viewport.set_scene(self.part, self._visible_profiles(), tool, mode, keep_selection)

    def update_title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else "ไม่มีชื่อ"
        self.setWindowTitle(f"{'● ' if self.doc.dirty else ''}{name} — {APP_NAME}")

    def update_info(self):
        info = part_info(self.part, self.material.currentText())
        if info is None:
            self.info_label.setText("ยังไม่มีชิ้นงาน")
            return
        x, y, z = info["size"]
        txt = (f"ขนาด {x:.1f} × {y:.1f} × {z:.1f} mm  ·  ปริมาตร {info['volume_cm3']:.2f} cm³  ·  "
               f"≈ {info['weight_g']:.1f} g")
        if info["min"][2] < -0.01:
            txt += "  ·  ⚠ มีส่วนต่ำกว่าฐาน"
        bw, bd = self.viewport.bed_size
        if x > bw or y > bd:
            txt += "  ·  ⚠ ใหญ่กว่าฐานพิมพ์"
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
        r = QMessageBox.question(self, APP_NAME, "มีการแก้ไขที่ยังไม่ได้บันทึก ต้องการบันทึกก่อนไหม?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def _last_dir(self):
        return self.settings.value("lastDir", os.path.expanduser("~"))

    def file_new(self):
        if not self._confirm_discard():
            return
        self.doc = Document()
        self.viewport._has_fit = False
        self.refresh_history(0)
        self.regenerate()

    def file_open(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "เปิดโปรเจกต์", self._last_dir(), FILE_FILTER)
        if not path:
            return
        try:
            doc = Document()
            doc.load(path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"เปิดไฟล์ไม่ได้:\n{exc}")
            return
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
        self.statusBar().showMessage(f"บันทึกแล้ว: {self.doc.path}", 4000)
        return True

    def file_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกโปรเจกต์", self._last_dir(), FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".3dmk"):
            path += ".3dmk"
        self.settings.setValue("lastDir", os.path.dirname(path))
        self.doc.path = path
        return self.file_save()

    def file_export(self):
        if self.part is None:
            QMessageBox.information(self, APP_NAME, "ยังไม่มีชิ้นงานให้ส่งออก")
            return
        base = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else "model"
        filters = ";;".join(FORMATS.values())
        path, chosen = QFileDialog.getSaveFileName(self, "ส่งออก", os.path.join(self._last_dir(), base + ".stl"),
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
            QMessageBox.critical(self, APP_NAME, f"ส่งออกไม่สำเร็จ:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.settings.setValue("lastDir", os.path.dirname(path))
        self.statusBar().showMessage(f"ส่งออกแล้ว: {path}", 6000)

    def show_help(self):
        QMessageBox.information(self, "วิธีใช้", HELP_TEXT)

    def closeEvent(self, event):  # noqa: N802
        if self._confirm_discard():
            self.viewport.close()
            event.accept()
        else:
            event.ignore()


HELP_TEXT = """<h3>ทำงานแบบ “เลือกก่อน แล้วค่อยสั่ง”</h3>
<b>สร้างชิ้นงานจากสเก็ตช์</b><br>
1. กด <b>สี่เหลี่ยม</b> (R) หรือ <b>วงกลม</b> (C) ทางซ้าย<br>
2. คลิกบนฐานพิมพ์ (หรือบนหน้าของชิ้นงาน) แล้วคลิกอีกครั้งเพื่อกำหนดขนาด
   หรือพิมพ์ตัวเลขแล้วกด Enter<br>
3. รูปที่วาดจะถูกเลือกไว้ — <b>ลากลูกศรสีน้ำเงิน</b> ขึ้นเพื่อดึงเป็นชิ้นงาน<br><br>
<b>เจาะรู</b><br>
กด <b>วงกลม</b> → คลิกบนหน้าของชิ้นงาน → พิมพ์ขนาด เช่น 5 แล้ว Enter →
ลากลูกศร <b>ลง</b> หรือกด <b>เจาะทะลุ</b> ที่แถบล่าง<br><br>
<b>คลิกหน้า</b> → ลากลูกศรเพื่อดึง/กดหน้า, ทำให้กลวง, ลบมุมขอบหน้า<br>
<b>คลิกขอบ</b> → ลบมุมโค้ง / ลบมุมเฉียง (Shift+คลิกเลือกหลายขอบ)<br><br>
<b>เมาส์</b>: คลิกซ้าย = เลือก/วาด · คลิกขวาค้างลาก = หมุน · ปุ่มกลาง = เลื่อน · ล้อ = ซูมตรงเคอร์เซอร์<br>
ใช้ปากกาบนแท็บเล็ต/จอสัมผัส Windows ได้เหมือนเมาส์ซ้าย (ปุ่มข้างปากกา = คลิกขวา)<br>
<b>คีย์ลัด</b>: V เลือก · L เส้น · R สี่เหลี่ยม · C วงกลม · Esc ยกเลิก · Ctrl+Z ย้อน · Ctrl+Y ทำซ้ำ · F พอดีจอ<br><br>
แก้ค่าย้อนหลังได้ทุกขั้นตอนใน <b>ประวัติการสร้าง</b> ทางขวา
"""
