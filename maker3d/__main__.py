"""Start the app:  python -m maker3d [project.3dmk]"""
import os
import sys


def main():
    os.environ.setdefault("QT_API", "pyside6")
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import APP_NAME, MainWindow
    from .gui.theme import STYLE

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".3dmk"):
        win.file_open(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
