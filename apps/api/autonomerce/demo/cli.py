"""Command-line entry point for the deterministic offline sale."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .scenario import run_offline_demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autonomerce-offline-demo",
        description=(
            "Run the credential-free Autonomerce Agent Card -> SKU -> offer -> "
            "mock payment -> fulfillment -> public receipt scenario."
        ),
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="directory containing the four offline JSON fixtures",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the JSON receipt bundle to this path",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print compact JSON instead of indented JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_offline_demo(fixture_dir=args.fixture_dir).to_dict()
    text = json.dumps(
        result,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0
