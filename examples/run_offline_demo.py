#!/usr/bin/env python3
"""Repo-local one-command launcher for the Autonomerce offline demo."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (
    PROJECT_ROOT / "apps" / "api",
    PROJECT_ROOT / "packages",
):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from autonomerce.demo.cli import main  # noqa: E402


raise SystemExit(main())
