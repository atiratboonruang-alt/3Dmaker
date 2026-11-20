"""Visual design tokens and the Qt stylesheet.

Direction: a calm, light workshop (cool grey studio light around the print
bed) with one strong element — the dark command bar under the viewport that
always shows what you can do with the current selection.
"""
import os

from PySide6.QtGui import QFont, QFontDatabase

# --- tokens -----------------------------------------------------------------
INK = "#17202b"        # text, command bar
INK_SOFT = "#5b6878"   # secondary text
LINE = "#e1e6ec"       # hairlines
CHROME = "#f5f7fa"     # window background
PANEL = "#ffffff"      # panels, inputs
COBALT = "#1f5bff"     # selection + primary action
AMBER = "#f2a81d"      # sketches
ADD_GREEN = "#1e9e5a"
CUT_RED = "#de4a3c"

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
* {{ font-family: "__FONT__", "Leelawadee UI", "Segoe UI", sans-serif; font-size: 10pt; }}
QMainWindow, QWidget {{ background: {CHROME}; color: {INK}; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: #e9efff; color: {INK}; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

/* top bar */
QToolBar#topBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {LINE}; padding: 4px 10px;
                   spacing: 2px; }}
QWidget#spacer {{ background: transparent; }}
QLabel#docName {{ background: transparent; color: {INK}; font-weight: 600; padding: 0 12px; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px 9px; color: {INK}; }}
QToolButton:hover {{ background: #eef2f7; }}
QToolButton:pressed {{ background: #e2e8f1; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#primary {{ background: {COBALT}; color: white; font-weight: 600; padding: 7px 16px; }}
QToolButton#primary:hover {{ background: #3a6fff; }}

/* tool rail */
QToolBar#toolRail {{ background: {PANEL}; border: none; border-right: 1px solid {LINE}; padding: 8px 6px;
                     spacing: 4px; }}
QToolBar#toolRail QToolButton {{ min-width: 60px; max-width: 64px; padding: 8px 2px 6px 2px; font-size: 9pt;
                                 border-radius: 10px; }}
QToolBar#toolRail QToolButton:checked {{ background: {INK}; color: white; }}
QLabel#railCaption {{ color: {INK_SOFT}; font-size: 8pt; padding-top: 6px; background: transparent; }}

/* coach line above the viewport */
QLabel#hintBar {{ background: {PANEL}; color: {INK}; border-bottom: 1px solid {LINE};
                  border-left: 4px solid {COBALT}; padding: 8px 14px; }}

/* the signature element: dark command bar under the viewport */
QFrame#contextBar {{ background: {INK}; min-height: 50px; }}
QFrame#contextBar QLabel {{ background: transparent; color: #c9d2de; }}
QFrame#contextBar QLabel#contextTitle {{ color: white; font-weight: 600; font-size: 10.5pt; padding-right: 6px; }}
QFrame#contextBar QFrame#sep {{ background: #33404f; max-width: 1px; min-width: 1px; }}
QFrame#contextBar QPushButton {{ background: #26303d; color: white; border: 1px solid #33404f;
                                border-radius: 8px; padding: 7px 13px; }}
QFrame#contextBar QPushButton:hover {{ background: #33404f; border-color: #4a596b; }}
QFrame#contextBar QPushButton:pressed {{ background: #3d4b5d; }}
QFrame#contextBar QPushButton#primaryButton {{ background: {COBALT}; border-color: {COBALT}; font-weight: 600; }}
QFrame#contextBar QPushButton#primaryButton:hover {{ background: #3a6fff; }}
QFrame#contextBar QPushButton#dangerButton {{ background: transparent; border-color: #5a3a3a; color: #ffb4ab; }}
QFrame#contextBar QDoubleSpinBox {{ background: #26303d; color: white; border: 1px solid #3d4b5d;
                                   selection-background-color: {COBALT}; }}
QFrame#contextBar QDoubleSpinBox:focus {{ border-color: {COBALT}; }}

/* general controls */
QPushButton {{ background: {PANEL}; border: 1px solid #d3dae3; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ background: #f1f5fa; border-color: #b8c4d4; }}
QPushButton:focus {{ border-color: {COBALT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {PANEL}; border: 1px solid #d3dae3; border-radius: 7px; padding: 5px 8px; min-height: 20px;
  selection-background-color: {COBALT}; selection-color: white;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {COBALT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: #e9efff; selection-color: {INK}; }}

/* right side: history + properties */
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {PANEL}; padding: 9px 10px; font-weight: 600; border-bottom: 1px solid {LINE}; }}
QSplitter::handle {{ background: {LINE}; height: 1px; }}
QListWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 7px 6px; border-radius: 6px; }}
QListWidget::item:hover {{ background: #f1f5fa; }}
QListWidget::item:selected {{ background: #e9efff; color: {INK}; }}
QLabel#panelTitle {{ font-size: 12.5pt; font-weight: 600; padding: 4px 0; background: transparent; }}
QLabel#hint {{ color: {INK_SOFT}; background: transparent; }}
QLabel#error {{ color: #9f1f17; background: #fdeceb; border: 1px solid #f5c6c2; border-radius: 8px; padding: 7px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; margin-top: 16px;
             padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {INK_SOFT}; }}
QGroupBox QLabel, QGroupBox QCheckBox {{ background: transparent; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {INK_SOFT}; }}
QStatusBar QLabel {{ background: transparent; padding: 0 4px; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #cbd3dd; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox::indicator, QListWidget::indicator {{ width: 16px; height: 16px; border: 1.5px solid #9aa7b8;
                                              border-radius: 4px; background: {PANEL}; }}
QCheckBox::indicator:hover, QListWidget::indicator:hover {{ border-color: {COBALT}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked {{ background: {COBALT}; border-color: {COBALT};
                                                              image: url(__CHECK__); }}
QToolTip {{ background: {INK}; color: white; border: none; padding: 7px; }}
"""
