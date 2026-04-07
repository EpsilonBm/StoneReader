"""Application bootstrap module."""

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QMessageBox

from .ui.main_window import MainWindow


def _crash_log_path() -> Path:
    root = Path.cwd() / ".local" / "library"
    root.mkdir(parents=True, exist_ok=True)
    return root / "crash.log"


def _log_crash(exc_type, exc_value, exc_tb, source: str) -> tuple[str, Path]:
    ts = datetime.now()
    code = f"SR-{ts.strftime('%Y%m%d-%H%M%S')}"
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    path = _crash_log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write("=" * 78 + "\n")
        f.write(f"code: {code}\n")
        f.write(f"time: {ts.isoformat(timespec='seconds')}\n")
        f.write(f"source: {source}\n")
        f.write(tb)
        f.write("\n")
    return code, path


def _install_crash_handlers() -> None:
    def _handle_main(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        code, path = _log_crash(exc_type, exc_value, exc_tb, "main-thread")
        QMessageBox.critical(
            None,
            "StoneReader 发生错误",
            f"错误代码：{code}\n\n程序发生未处理异常。\n日志已写入：\n{path}",
        )

    def _handle_thread(args: threading.ExceptHookArgs) -> None:
        code, path = _log_crash(args.exc_type, args.exc_value, args.exc_traceback, f"thread:{args.thread.name}")
        print(
            f"[StoneReader] 后台线程未处理异常，错误代码={code}，日志={path}",
            file=sys.stderr,
        )

    sys.excepthook = _handle_main
    threading.excepthook = _handle_thread


def run() -> int:
    """Create and run QApplication."""
    app = QApplication(sys.argv)
    app.setApplicationName("StoneReader")
    _install_crash_handlers()

    window = MainWindow()
    window.show()

    return app.exec()
