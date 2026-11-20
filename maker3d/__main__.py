"""Start the app:  python -m maker3d [project.3dmk]"""
import logging
import os
import sys
import traceback

LOG_DIR = os.path.join(os.path.expanduser("~"), ".3dmaker")
LOG_FILE = os.path.join(LOG_DIR, "3dmaker.log")


def _setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.info("start python=%s platform=%s", sys.version.split()[0], sys.platform)


def _install_excepthook():
    shown = set()

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error("unhandled error\n%s", text)
        sys.__stderr__ and sys.__stderr__.write(text)
        key = (exc_type.__name__, str(exc))
        if key in shown:
            return
        shown.add(key)
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "3D Maker — เกิดข้อผิดพลาด",
                                f"{exc_type.__name__}: {exc}\n\nบันทึกรายละเอียดไว้ที่\n{LOG_FILE}\n"
                                "ส่งไฟล์นี้ให้ผู้พัฒนาเพื่อช่วยแก้ไขได้")
        except Exception:
            pass

    sys.excepthook = hook


def main():
    os.environ.setdefault("QT_API", "pyside6")
    _setup_logging()
    _install_excepthook()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    from .gui.main_window import APP_NAME, MainWindow
    from .gui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    win = MainWindow()
    win.show()
    logging.info("window shown dpr=%.2f", win.devicePixelRatioF())
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".3dmk"):
        win.file_open(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
