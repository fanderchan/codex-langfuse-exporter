#!/usr/bin/env python3
"""Compatibility wrapper for the packaged exporter CLI."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if SRC_DIR.is_dir():
    sys.path.insert(0, str(SRC_DIR))

from codex_langfuse_exporter.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
