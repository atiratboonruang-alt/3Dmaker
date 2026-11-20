"""Visual design tokens and the Qt stylesheet.

Direction: a dark, quiet modelling studio so the part and the sketch
(light grey body, amber sketch lines, cobalt selection) carry all the colour.
"""
import os

from PySide6.QtGui import QFont, QFontDatabase

# --- tokens -----------------------------------------------------------------
INK = "#e8e9ec"        # primary text
INK_SOFT = "#9a9ea8"   # secondary text
LINE = "#33363c"       # hairlines
CHROME = "#1b1c1f"     # window background
PANEL = "#232428"      # panels
RAISED = "#2c2e33"     # buttons, inputs
COBALT = "#3d8bff"     # selection + primary action
AMBER = "#ffb02e"      # sketches
ADD_GREEN = "#2fbf71"
CUT_RED = "#ff5a4e"

FONT_FAMILY = "IBM Plex Sans Thai"
_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")


def load_fonts() -> str:
    family = None
    if os.path.isdir(_FONT_DIR):
        for name in sorted(os.listdir(_FONT_DIR)):
            if name.endswith(".ttf"):
                fid = QFontDatabase.addApplicationFont(os.path.join(_FONT_DIR, name))
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    family = family or fams[0]
    return family or "Segoe UI"


def _check_image() -> str:
    """Render the checkbox tick once to a PNG the stylesheet can reference."""
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    folder = os.path.join(os.path.expanduser("~"), ".3dmaker")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "check.png")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" '
           'stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    img = QImage(32, 32, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, 32, 32))
    p.end()
    img.save(path)
    return path.replace("\\", "/")


def apply_theme(app):
    family = load_fonts()
    app.setStyle("Fusion")
    font = QFont(family, 10)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    try:
        check = _check_image()
    except Exception:
        check = ""
    app.setStyleSheet(STYLE.replace("__FONT__", family).replace("__CHECK__", check))


STYLE = f"""
* {{ font-family: "__FONT__", "Segoe UI", sans-serif; font-size: 10pt; }}
QMainWindow, QWidget {{ background: {CHROME}; color: {INK}; }}
QMenuBar {{ background: {CHROME}; border-bottom: 1px solid {LINE}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {RAISED}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {COBALT}; color: white; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QToolBar#topBar {{ background: {CHROME}; border: none; border-bottom: 1px solid {LINE}; padding: 4px 10px;
                   spacing: 2px; }}
QWidget#spacer {{ background: transparent; }}
QLabel#docName {{ background: transparent; color: {INK}; font-weight: 600; padding: 0 12px; }}
QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 6px 8px; color: {INK}; }}
QToolButton:hover {{ background: {RAISED}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#primary {{ background: {COBALT}; color: white; font-weight: 600; padding: 6px 14px; }}
QToolButton#primary:hover {{ background: #5a9cff; }}

/* tool panel (left) */
QStackedWidget#toolPanel, QWidget#panelPage {{ background: {CHROME}; }}
QFrame#panelItem {{ background: transparent; border-radius: 9px; }}
QFrame#panelItem:hover {{ background: #24262a; }}
QFrame#panelItem[active="true"] {{ background: #26303f; }}
QToolButton#panelIcon {{ background: {RAISED}; border-radius: 9px; padding: 7px; }}
QToolButton#panelIcon:checked {{ background: {COBALT}; }}
QLabel#panelName {{ background: transparent; font-weight: 600; }}
QLabel#panelSub {{ background: transparent; color: {INK_SOFT}; font-size: 8.5pt; }}
QLabel#keyChip {{ background: {RAISED}; color: {INK_SOFT}; border-radius: 4px; padding: 0 5px; font-size: 8pt; }}
QFrame#panelSep {{ background: {LINE}; }}

/* instructions, centred above the viewport */
QFrame#hintStrip {{ background: {CHROME}; border-bottom: 1px solid {LINE}; }}
QLabel#hintBar {{ background: {PANEL}; color: {INK}; border: 1px solid {LINE}; border-radius: 9px;
                  padding: 8px 16px; }}

/* command bar under the viewport */
QFrame#contextBar {{ background: {PANEL}; border-top: 1px solid {LINE}; min-height: 50px; }}
QFrame#contextBar QLabel {{ background: transparent; color: {INK_SOFT}; }}
QFrame#contextBar QLabel#contextTitle {{ color: {INK}; font-weight: 600; font-size: 10.5pt; padding-right: 6px; }}
QFrame#contextBar QFrame#sep {{ background: {LINE}; }}
QPushButton {{ background: {RAISED}; color: {INK}; border: 1px solid #3a3d44; border-radius: 8px; padding: 7px 13px; }}
QPushButton:hover {{ background: #363940; border-color: #4a4e57; }}
QPushButton:pressed {{ background: #3e424a; }}
QPushButton:focus {{ border-color: {COBALT}; }}
QPushButton#primaryButton {{ background: {COBALT}; border-color: {COBALT}; color: white; font-weight: 600; }}
QPushButton#primaryButton:hover {{ background: #5a9cff; }}
QPushButton#dangerButton {{ background: transparent; border-color: #5a3434; color: #ff9b92; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {RAISED}; color: {INK}; border: 1px solid #3a3d44; border-radius: 7px; padding: 5px 8px;
  min-height: 20px; selection-background-color: {COBALT}; selection-color: white;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {COBALT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {INK}; selection-background-color: {COBALT}; }}

/* history + properties (right) */
QDockWidget {{ titlebar-close-icon: none; color: {INK}; }}
QDockWidget::title {{ background: {CHROME}; padding: 9px 10px; border-bottom: 1px solid {LINE}; }}
QSplitter::handle {{ background: {LINE}; height: 1px; }}
QListWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 7px 6px; border-radius: 6px; }}
QListWidget::item:hover {{ background: #2a2c31; }}
QListWidget::item:selected {{ background: #26303f; color: {INK}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {CHROME}; border: none; }}
QLabel#panelTitle {{ font-size: 12.5pt; font-weight: 600; padding: 4px 0; background: transparent; }}
QLabel#hint {{ color: {INK_SOFT}; background: transparent; }}
QLabel#error {{ color: #ffb4ab; background: #3a2224; border: 1px solid #5a3434; border-radius: 8px; padding: 7px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; margin-top: 16px;
             padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {INK_SOFT}; }}
QGroupBox QLabel, QGroupBox QCheckBox {{ background: transparent; }}
QCheckBox::indicator, QListWidget::indicator {{ width: 16px; height: 16px; border: 1.5px solid #5a5e66;
                                              border-radius: 4px; background: {RAISED}; }}
QCheckBox::indicator:hover, QListWidget::indicator:hover {{ border-color: {COBALT}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{ background: {COBALT}; border-color: {COBALT};
                                                              image: url(__CHECK__); }}

QStatusBar {{ background: {CHROME}; border-top: 1px solid {LINE}; color: {INK_SOFT}; }}
QStatusBar QLabel {{ background: transparent; padding: 0 4px; color: {INK_SOFT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #44474e; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: #0f1012; color: white; border: 1px solid {LINE}; padding: 7px; }}
"""
