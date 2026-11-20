"""Main application window."""
from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..export import FORMATS, export_part
from ..model import FEATURE_TYPES, MATERIALS, Document, part_info, rebuild
from .properties import PropertyPanel
from .viewport import Viewport

APP_NAME = "3D Maker"
FILE_FILTER = "โปรเจกต์ 3D Maker (*.3dmk)"

BODY_BUTTONS = ["box", "cylinder", "sphere", "cone", "torus", "extrude", "text", "hole", "import_step"]
MODIFY_BUTTONS = ["fillet", "chamfer", "shell", "mirror", "scale"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.part = None
        self.tools: list = []
        self.settings = QSettings("3DMaker", "3DMaker")
        self._rebuild_timer = QTimer(self, singleShot=True, interval=150)
        self._rebuild_timer.timeout.connect(self.regenerate)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport.interactor if hasattr(self.viewport, "interactor") else self.viewport)

        self._build_actions()
        self._build_toolbar()
        self._build_shape_bar()
        self._build_tree_dock()
        self._build_props_dock()
        self._build_status()
        self.resize(1400, 860)
        self.update_title()
        self.refresh_tree()

    # ------------------------------------------------------------------ UI
    def _act(self, text, slot, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setToolTip(tip or text)
        self.addAction(a)
        return a

    def _build_actions(self):
        self.a_new = self._act("ใหม่", self.file_new, QKeySequence.New)
        self.a_open = self._act("เปิด", self.file_open, QKeySequence.Open)
        self.a_save = self._act("บันทึก", self.file_save, QKeySequence.Save)
        self.a_save_as = self._act("บันทึกเป็น…", self.file_save_as, QKeySequence.SaveAs)
        self.a_export = self._act("ส่งออก STL / 3MF / STEP", self.file_export, "Ctrl+E")
        self.a_undo = self._act("↶ ย้อนกลับ", self.undo, QKeySequence.Undo)
        self.a_redo = self._act("↷ ทำซ้ำ", self.redo, QKeySequence.Redo)
        self.a_delete = self._act("ลบ", self.delete_selected, QKeySequence.Delete)
        self.a_dup = self._act("คัดลอก", self.duplicate_selected, "Ctrl+D")
        self.a_fit = self._act("พอดีจอ", self.viewport.fit, "F")

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
        m.addAction(self._act("วิธีใช้", self.show_help, "F1"))

    def _build_toolbar(self):
        tb = QToolBar("หลัก", self)
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        exp = QToolButton()
        exp.setDefaultAction(self.a_export)
        exp.setObjectName("primary")
        tb.addWidget(exp)
        tb.addSeparator()
        for key, label, sc in [("iso", "3D", "0"), ("top", "บน", "1"), ("front", "หน้า", "2"),
                               ("right", "ขวา", "3")]:
            a = self._act(label, lambda _=False, k=key: self.viewport.set_view(k), sc, f"มุมมอง{label} ({sc})")
            tb.addAction(a)
        tb.addAction(self.a_fit)
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _shape_button(self, type_id):
        ft = FEATURE_TYPES[type_id]
        b = QToolButton()
        b.setText(f"{ft.icon}\n{ft.label}")
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setObjectName("shapeButton")
        b.setToolTip(f"เพิ่ม{ft.label}")
        b.clicked.connect(lambda _=False, t=type_id: self.add_feature(t))
        return b

    def _build_shape_bar(self):
        tb = QToolBar("รูปทรง", self)
        tb.setObjectName("shapeToolbar")
        tb.setMovable(False)
        cap = QLabel(" สร้าง ")
        cap.setObjectName("barCaption")
        tb.addWidget(cap)
        for t in BODY_BUTTONS:
            tb.addWidget(self._shape_button(t))
        tb.addSeparator()
        cap = QLabel(" ปรับแต่ง ")
        cap.setObjectName("barCaption")
        tb.addWidget(cap)
        for t in MODIFY_BUTTONS:
            tb.addWidget(self._shape_button(t))
        self.addToolBarBreak()
        self.addToolBar(Qt.TopToolBarArea, tb)

    def _build_tree_dock(self):
        dock = QDockWidget("ขั้นตอนการสร้าง", self)
        dock.setObjectName("treeDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tree = QListWidget()
        self.tree.currentRowChanged.connect(self.on_select)
        self.tree.itemChanged.connect(self.on_item_changed)
        lay.addWidget(self.tree, 1)
        g = QGridLayout()
        for i, (label, slot) in enumerate([("▲ ขึ้น", lambda: self.move_selected(-1)),
                                          ("▼ ลง", lambda: self.move_selected(1)),
                                          ("คัดลอก", self.duplicate_selected),
                                          ("ลบ", self.delete_selected)]):
            b = QPushButton(label)
            b.clicked.connect(slot)
            g.addWidget(b, i // 2, i % 2)
        lay.addLayout(g)
        tip = QLabel("ติ๊กช่องเพื่อเปิด/ปิดขั้นตอนชั่วคราว")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        dock.setWidget(w)
        dock.setMinimumWidth(230)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_props_dock(self):
        dock = QDockWidget("คุณสมบัติ", self)
        dock.setObjectName("propsDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.props = PropertyPanel()
        self.props.changed.connect(self.on_param_changed)
        self.props.renamed.connect(self.on_renamed)
        dock.setWidget(self.props)
        dock.setMinimumWidth(320)
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
        bed = QWidget()
        h = QHBoxLayout(bed)
        h.setContentsMargins(0, 0, 0, 0)
        self.bed_combo = QComboBox()
        for label in ["220×220", "256×256", "180×180", "300×300", "350×350"]:
            self.bed_combo.addItem(label)
        self.bed_combo.currentTextChanged.connect(self.on_bed_changed)
        h.addWidget(QLabel("ฐานพิมพ์:"))
        h.addWidget(self.bed_combo)
        sb.addPermanentWidget(bed)

    # ------------------------------------------------------------ helpers
    def current_index(self) -> int:
        return self.tree.currentRow()

    def current_feature(self):
        i = self.current_index()
        return self.doc.features[i] if 0 <= i < len(self.doc.features) else None

    def refresh_tree(self, select: int | None = None):
        if select is None:
            select = self.current_index()
        self.tree.blockSignals(True)
        self.tree.clear()
        for f in self.doc.features:
            mode = f.params.get("mode")
            tag = {"cut": "  ✂", "intersect": "  ∩"}.get(mode, "")
            item = QListWidgetItem(f"{f.ftype.icon}  {f.name}{tag}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if f.enabled else Qt.Unchecked)
            if f.error:
                item.setForeground(Qt.red)
                item.setToolTip(f"⚠ {f.error}")
            elif not f.enabled:
                item.setForeground(Qt.gray)
            self.tree.addItem(item)
        self.tree.blockSignals(False)
        if self.doc.features:
            select = min(max(select, 0), len(self.doc.features) - 1)
            self.tree.setCurrentRow(select)
        self.on_select(self.tree.currentRow(), rebuild_props=True)

    def update_title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else "ไม่มีชื่อ"
        self.setWindowTitle(f"{'● ' if self.doc.dirty else ''}{name} — {APP_NAME}")

    def update_info(self):
        info = part_info(self.part, self.material.currentText())
        if info is None:
            self.info_label.setText("ยังไม่มีรูปทรง")
            return
        x, y, z = info["size"]
        txt = (f"ขนาด {x:.1f} × {y:.1f} × {z:.1f} mm   ·   ปริมาตร {info['volume_cm3']:.2f} cm³   ·   "
               f"น้ำหนักโดยประมาณ {info['weight_g']:.1f} g (เนื้อเต็ม 100%)")
        if info["min"][2] < -0.01:
            txt += "   ·   ⚠ มีส่วนต่ำกว่าฐานพิมพ์"
        bw, bd = self.viewport.bed_size
        if x > bw or y > bd:
            txt += "   ·   ⚠ ใหญ่กว่าฐานพิมพ์"
        self.info_label.setText(txt)

    # ----------------------------------------------------------- modelling
    def regenerate(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.part, self.tools = rebuild(self.doc.features)
        except Exception:
            traceback.print_exc()
        finally:
            QApplication.restoreOverrideCursor()
        self._show()
        self._refresh_tree_status()
        self.update_info()
        self.update_title()
        f = self.current_feature()
        self.props.set_error(f.error if f is not None else None)

    def _show(self):
        i = self.current_index()
        tool, mode = None, "add"
        if 0 <= i < len(self.tools):
            f = self.doc.features[i]
            if f.ftype.category == "body" and i != 0:
                tool, mode = self.tools[i], f.params.get("mode", "add")
        self.viewport.show_model(self.part, tool, mode)

    def _refresh_tree_status(self):
        self.tree.blockSignals(True)
        for i, f in enumerate(self.doc.features):
            item = self.tree.item(i)
            if item is None:
                continue
            mode = f.params.get("mode")
            tag = {"cut": "  ✂", "intersect": "  ∩"}.get(mode, "")
            item.setText(f"{f.ftype.icon}  {f.name}{tag}")
            if f.error:
                item.setForeground(Qt.red)
                item.setToolTip(f"⚠ {f.error}")
                self.statusBar().showMessage(f"⚠ {f.name}: {f.error}", 6000)
            else:
                item.setForeground(Qt.gray if not f.enabled else self.tree.palette().text().color())
                item.setToolTip("")
        self.tree.blockSignals(False)

    def add_feature(self, type_id):
        i = self.current_index()
        index = i + 1 if 0 <= i < len(self.doc.features) - 1 else None
        f = self.doc.add(type_id, index)
        # holes and text start on the top surface of the current model
        if type_id in ("hole", "text") and self.part is not None:
            bb = self.part.bounding_box()
            f.params["z"] = round(bb.max.Z, 3)
        new_index = self.doc.features.index(f)
        self.refresh_tree(new_index)
        self.regenerate()

    def on_select(self, row, rebuild_props=True):
        f = self.doc.features[row] if 0 <= row < len(self.doc.features) else None
        if rebuild_props:
            self.props.set_feature(f)
        self._show()

    def on_item_changed(self, item):
        row = self.tree.row(item)
        f = self.doc.features[row]
        enabled = item.checkState() == Qt.Checked
        if enabled != f.enabled:
            self.doc.checkpoint()
            self.doc.features[row].enabled = enabled
            self._rebuild_timer.start()

    def on_param_changed(self, key, value):
        f = self.current_feature()
        if f is None or f.params.get(key) == value:
            return
        self.doc.checkpoint()
        f = self.current_feature()
        f.params[key] = value
        self.props.feature = f
        self._rebuild_timer.start()

    def on_renamed(self, name):
        f = self.current_feature()
        if f is None or f.name == name:
            return
        self.doc.checkpoint()
        self.current_feature().name = name
        self._refresh_tree_status()
        self.update_title()

    def delete_selected(self):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            self.doc.remove(i)
            self.refresh_tree(max(i - 1, 0))
            self.regenerate()

    def duplicate_selected(self):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            self.doc.duplicate(i)
            self.refresh_tree(i + 1)
            self.regenerate()

    def move_selected(self, delta):
        i = self.current_index()
        if 0 <= i < len(self.doc.features):
            j = self.doc.move(i, delta)
            self.refresh_tree(j)
            self.regenerate()

    def undo(self):
        if self.doc.undo():
            self.refresh_tree()
            self.regenerate()

    def redo(self):
        if self.doc.redo():
            self.refresh_tree()
            self.regenerate()

    # ---------------------------------------------------------------- view
    def toggle_edges(self):
        self.viewport.show_edges = self.a_edges.isChecked()
        self._show()

    def toggle_bed(self):
        self.viewport.set_bed(*self.viewport.bed_size, visible=self.a_bed.isChecked())

    def on_bed_changed(self, text):
        w, d = (float(v) for v in text.split("×"))
        self.viewport.set_bed(w, d, self.a_bed.isChecked())
        self.update_info()

    # --------------------------------------------------------------- files
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
        self.refresh_tree(0)
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
        self.refresh_tree(len(doc.features) - 1)
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
            QMessageBox.information(self, APP_NAME, "ยังไม่มีรูปทรงให้ส่งออก")
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


HELP_TEXT = """<b>เริ่มต้นใช้งาน</b><br>
1. กดปุ่มรูปทรงด้านบน (กล่อง, ทรงกระบอก, ...) เพื่อเพิ่มชิ้นส่วน<br>
2. ปรับขนาด/ตำแหน่งที่แผง <i>คุณสมบัติ</i> ทางขวา<br>
3. เปลี่ยน <i>การทำงาน</i> เป็น “ตัดออก” เพื่อเจาะหรือคว้านเนื้อ<br>
4. ใช้ ลบมุมโค้ง / ลบมุมเฉียง / ทำให้กลวง เพื่อตกแต่ง<br>
5. กด <b>ส่งออก</b> เป็น STL หรือ 3MF แล้วนำไปเข้าสไลเซอร์<br><br>
<b>เมาส์</b>: ลากซ้าย = หมุน · ลากกลาง/Shift+ลาก = เลื่อน · ล้อ = ซูม<br>
<b>คีย์ลัด</b>: Ctrl+Z ย้อน · Ctrl+Y ทำซ้ำ · Ctrl+D คัดลอก · Del ลบ · F พอดีจอ · 0/1/2/3 มุมมอง<br><br>
ขั้นตอนจะคำนวณจากบนลงล่าง ลากลำดับด้วยปุ่ม ▲▼ ได้ และสามารถปิดขั้นตอนชั่วคราวด้วยช่องติ๊ก
"""
