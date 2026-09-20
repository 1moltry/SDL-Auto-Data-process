"""GUI entry point: ``python -m nanopore.gui [file.abf]``."""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    data = None
    for a in args[1:]:
        if a and not a.startswith("-"):
            data = a
            break
    win = MainWindow(data=data)
    win.resize(1500, 950)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
