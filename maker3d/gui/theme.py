STYLE = """
* { font-family: "Segoe UI", "Leelawadee UI", "Tahoma", sans-serif; font-size: 10pt; }
QMainWindow, QWidget { background: #1e2126; color: #e6e8eb; }
QMenuBar { background: #17191d; }
QMenuBar::item:selected, QMenu::item:selected { background: #3a6df0; }
QMenu { background: #24272d; border: 1px solid #333; }
QToolBar { background: #17191d; border: none; padding: 4px; spacing: 4px; }
QToolBar#shapeToolbar { background: #22252b; border-bottom: 1px solid #2f333a; }
QToolButton { background: transparent; border-radius: 6px; padding: 6px 10px; color: #e6e8eb; }
QToolButton:hover { background: #2f343c; }
QToolButton:pressed { background: #3a6df0; }
QToolButton#shapeButton { min-width: 64px; padding: 6px 4px; font-size: 9pt; }
QToolButton#primary { background: #3a6df0; font-weight: 600; }
QToolButton#primary:hover { background: #4f80ff; }
QLabel#barCaption { color: #8a919c; font-size: 8pt; padding: 0 4px; }
QLabel#panelTitle { font-size: 13pt; font-weight: 600; padding: 4px 0; }
QLabel#hint { color: #8a919c; }
QLabel#error { color: #ff7676; background: #3a2226; border-radius: 6px; padding: 6px; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #17191d; padding: 6px; font-weight: 600; }
QGroupBox { border: 1px solid #30343b; border-radius: 8px; margin-top: 14px; padding: 8px 6px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa3ae; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: #2a2e35; border: 1px solid #3a3f47; border-radius: 5px; padding: 4px 6px; min-height: 20px;
  selection-background-color: #3a6df0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #3a6df0; }
QComboBox QAbstractItemView { background: #2a2e35; selection-background-color: #3a6df0; }
QPushButton { background: #2f343c; border: 1px solid #3a3f47; border-radius: 6px; padding: 6px; }
QPushButton:hover { background: #3a404a; }
QListWidget { background: #23262c; border: 1px solid #30343b; border-radius: 6px; padding: 4px; }
QListWidget::item { padding: 6px 4px; border-radius: 4px; }
QListWidget::item:selected { background: #3a6df0; color: white; }
QStatusBar { background: #17191d; color: #b8bec7; }
QStatusBar QLabel { background: transparent; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #1e2126; width: 10px; }
QScrollBar::handle:vertical { background: #3a3f47; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""
