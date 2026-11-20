"""Auto-generated property editor for the selected feature."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model import Feature, format_points, get_path, sketch_params


def hidden_keys(feat: Feature) -> set[str]:
    """Parameters that don't apply with the current settings."""
    p = feat.params
    hide: set[str] = set()
    if feat.type_id == "extrude":
        prof = p["profile"]
        if prof != "rounded":
            hide.add("corner_radius")
        if prof != "polygon":
            hide.add("sides")
        if prof != "custom":
            hide.add("points")
        else:
            hide |= {"width", "depth"}
        if prof in ("circle", "polygon"):
            hide.add("depth")
    pat = p.get("pattern")
    if pat == "none":
        hide |= {"count_x", "count_y", "spacing_x", "spacing_y"}
    elif pat == "linear":
        hide |= {"count_y", "spacing_y"}
    elif pat == "circular":
        hide |= {"count_y", "spacing_x", "spacing_y"}
    return hide


class NoWheelMixin:
    """Ignore the mouse wheel unless focused, so scrolling the panel is safe."""

    def wheelEvent(self, event):  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class DSpin(NoWheelMixin, QDoubleSpinBox):
    pass


class ISpin(NoWheelMixin, QSpinBox):
    pass


class Combo(NoWheelMixin, QComboBox):
    pass


class PropertyPanel(QScrollArea):
    changed = Signal(str, object)  # key, value
    renamed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feature: Feature | None = None
        self._rows: dict[str, tuple[QFormLayout, QWidget]] = {}
        self._groups: dict[str, QGroupBox] = {}
        self.set_feature(None)

    def set_feature(self, feat: Feature | None):
        self.feature = feat
        self._error = None
        self._rows = {}
        self._groups = {}
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        if feat is None:
            hint = QLabel("เลือกขั้นตอนทางซ้าย\nหรือกดปุ่มรูปทรงด้านบนเพื่อเริ่ม")
            hint.setAlignment(Qt.AlignCenter)
            hint.setObjectName("hint")
            lay.addStretch(1)
            lay.addWidget(hint)
            lay.addStretch(2)
            self.setWidget(root)
            return

        title = QLabel(f"{feat.ftype.icon}  {feat.ftype.label}")
        title.setObjectName("panelTitle")
        lay.addWidget(title)
        name = QLineEdit(feat.name)
        name.editingFinished.connect(lambda: self.renamed.emit(name.text().strip() or feat.ftype.label))
        lay.addWidget(name)
        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setObjectName("error")
        lay.addWidget(self._error)
        self.set_error(feat.error)

        params = [p for p in feat.ftype.params if p.kind != "hidden"]
        if feat.type_id == "sketch":
            params += sketch_params(feat)
            if not params:
                lay.addWidget(QLabel("สเก็ตช์ว่าง"))
        for prm in params:
            box = self._groups.get(prm.group)
            if box is None:
                box = QGroupBox(prm.group)
                form = QFormLayout(box)
                form.setLabelAlignment(Qt.AlignRight)
                self._groups[prm.group] = box
                lay.addWidget(box)
            form = box.layout()
            try:
                value = get_path(feat.params, prm.key)
            except (KeyError, IndexError, ValueError):
                value = prm.default
            w = self._make_editor(prm, value)
            form.addRow(prm.label, w)
            self._rows[prm.key] = (form, w)
        lay.addStretch(1)
        self.setWidget(root)
        self._update_visibility()

    def set_error(self, msg):
        if self.feature is None or self._error is None:
            return
        self._error.setText(f"⚠ {msg}" if msg else "")
        self._error.setVisible(bool(msg))

    def _make_editor(self, prm, value):
        key = prm.key
        if prm.kind == "float":
            w = DSpin()
            w.setRange(prm.min, prm.max)
            w.setDecimals(2)
            w.setSingleStep(prm.step)
            w.setSuffix(prm.suffix)
            w.setValue(float(value))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v, k=key: self._emit(k, float(v)))
        elif prm.kind == "int":
            w = ISpin()
            w.setRange(int(prm.min), int(prm.max))
            w.setSuffix(prm.suffix)
            w.setValue(int(value))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v, k=key: self._emit(k, int(v)))
        elif prm.kind == "choice":
            w = Combo()
            w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(8)
            for val, label in prm.choices:
                w.addItem(label, val)
            idx = max(w.findData(value), 0)
            w.setCurrentIndex(idx)
            w.currentIndexChanged.connect(lambda i, k=key, c=w: self._emit(k, c.itemData(i)))
        elif prm.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(lambda v, k=key: self._emit(k, bool(v)))
        elif prm.kind == "file":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value))
            edit.setReadOnly(True)
            btn = QPushButton("เลือก…")

            def pick(_=False, k=key, e=edit):
                path, _f = QFileDialog.getOpenFileName(self, "เลือกไฟล์ STEP", "", "STEP (*.step *.stp)")
                if path:
                    e.setText(path)
                    self._emit(k, path)

            btn.clicked.connect(pick)
            h.addWidget(edit, 1)
            h.addWidget(btn)
        elif prm.kind == "points":
            w = QLineEdit(format_points(value))
            w.editingFinished.connect(lambda k=key, e=w: self._emit(k, e.text()))
        else:
            w = QLineEdit(str(value))
            w.editingFinished.connect(lambda k=key, e=w: self._emit(k, e.text()))
        return w

    def _emit(self, key, value):
        if self.feature is None:
            return
        self.changed.emit(key, value)
        self._update_visibility()

    def _update_visibility(self):
        if self.feature is None:
            return
        hide = hidden_keys(self.feature)
        for key, (form, w) in self._rows.items():
            form.setRowVisible(w, key not in hide)
