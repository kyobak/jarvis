"""Console + rotating file logging (~/Library/Logs/Jarvis on macOS)."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from jarvis.core.config import default_data_dir

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def log_dir() -> Path:
    if sys.platform == "darwin" and not os.environ.get("JARVIS_DATA_DIR"):
        return Path.home() / "Library" / "Logs" / "Jarvis"
    return default_data_dir() / "logs"


def setup_logging(verbose: bool = False, to_file: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(console)
    if to_file:
        path = log_dir()
        path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path / "jarvis.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(file_handler)
    # Quiet chatty libraries; never log request bodies (they can carry message content).
    for name in ("httpx", "httpx2", "httpcore", "httpcore2", "urllib3", "huggingface_hub", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)
