"""Start the desktop app:  python -m maintdesk.desktop --url http://127.0.0.1:8000"""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication

from ..client import ApiClient
from .window import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintenance desk desktop client")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="address of the API server")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv[:1])
    window = MainWindow(ApiClient(args.url))
    window.show()
    window.refresh()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
