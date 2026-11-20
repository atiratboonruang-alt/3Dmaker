ACCENT = "#2f6bff"

STYLE = """
* { font-family: "Segoe UI", "Leelawadee UI", "Noto Sans Thai", "Tahoma", sans-serif; font-size: 10pt; }
QMainWindow, QWidget { background: #f3f5f8; color: #1f2733; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #e3e7ed; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #e6eeff; color: #1f2733; }
QMenu { background: #ffffff; border: 1px solid #dde2ea; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 4px; }

QToolBar#topBar { background: #ffffff; border: none; border-bottom: 1px solid #e3e7ed; padding: 4px 8px;
                  spacing: 2px; }
QToolBar#toolRail { background: #ffffff; border: none; border-right: 1px solid #e3e7ed; padding: 6px 4px;
                    spacing: 2px; }
QToolButton { background: transparent; border: none; border-radius: 8px; padding: 6px 8px; color: #1f2733; }
QToolButton:hover { background: #eef2f8; }
QToolButton:pressed { background: #dfe7f7; }
QToolButton:checked { background: #2f6bff; color: white; }
QToolButton#railButton { min-width: 58px; font-size: 9pt; padding: 6px 2px; }
QToolButton#railButton::menu-indicator { image: none; }
QToolButton#primary { background: #2f6bff; color: white; font-weight: 600; padding: 6px 14px; }
QToolButton#primary:hover { background: #4a7fff; }
QLabel#railCaption { color: #8a94a3; font-size: 8pt; padding-top: 4px; background: transparent; }

QLabel#hintBar { background: #fffbe8; color: #5a4a12; border-bottom: 1px solid #f0e2a8;
                 padding: 7px 14px; font-size: 10pt; }
QFrame#contextBar { background: #ffffff; border-top: 1px solid #e3e7ed; min-height: 44px; }
QFrame#contextBar QLabel { background: transparent; }
QLabel#contextTitle { font-weight: 700; color: #1f2733; padding-right: 4px; }
QFrame#sep { color: #e3e7ed; }

QPushButton { background: #ffffff; border: 1px solid #d5dbe4; border-radius: 8px; padding: 6px 12px; }
QPushButton:hover { background: #f0f4fb; border-color: #b9c6dc; }
QPushButton:pressed { background: #e2eaf8; }
QPushButton#primaryButton { background: #2f6bff; border-color: #2f6bff; color: white; font-weight: 600; }
QPushButton#primaryButton:hover { background: #4a7fff; }

QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #ffffff; padding: 8px; font-weight: 700; border-bottom: 1px solid #e3e7ed; }
QSplitter::handle { background: #e3e7ed; height: 1px; }

QLabel#panelTitle { font-size: 13pt; font-weight: 700; padding: 4px 0; }
QLabel#hint { color: #8a94a3; }
QLabel#error { color: #b4232a; background: #fdecec; border: 1px solid #f6c7c9; border-radius: 6px; padding: 6px; }
QGroupBox { background: #ffffff; border: 1px solid #e3e7ed; border-radius: 10px; margin-top: 16px;
            padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #6b7685; font-weight: 600; }
QGroupBox QLabel, QGroupBox QCheckBox { background: transparent; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: #ffffff; border: 1px solid #d5dbe4; border-radius: 6px; padding: 4px 6px; min-height: 20px;
  selection-background-color: #2f6bff;
}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 0px; border: none; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #2f6bff; }
QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #e6eeff;
                              selection-color: #1f2733; }

QListWidget { background: #ffffff; border: 1px solid #e3e7ed; border-radius: 10px; padding: 4px; outline: 0; }
QListWidget::item { padding: 7px 6px; border-radius: 6px; }
QListWidget::item:hover { background: #f0f4fb; }
QListWidget::item:selected { background: #e6eeff; color: #1f2733; }

QStatusBar { background: #ffffff; border-top: 1px solid #e3e7ed; color: #4a5565; }
QStatusBar QLabel { background: transparent; padding: 0 4px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #cdd4de; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QWidget#spacer { background: transparent; }
QToolTip { background: #1f2733; color: white; border: none; padding: 6px; border-radius: 4px; }
"""
