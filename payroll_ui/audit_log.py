"""Local operational logging that never writes names, amounts, or paths."""
from __future__ import annotations

import logging
from pathlib import Path


def make_logger(root: Path) -> logging.Logger:
    logger = logging.getLogger(f"payroll_ui.{root.resolve()}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(root / "payroll-ui.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
