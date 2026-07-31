#!/usr/bin/env python3
"""Fail-closed lightweight secret scan for the standalone product tree."""

from __future__ import annotations

import re
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "node_modules", ".next", "__pycache__", ".pytest_cache"}
ALLOW_MARKER = "secret-scan: allow-test-fixture"
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "bearer": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|private[_-]?key|session[_-]?token)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}"
    ),
}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP for part in path.parts):
            continue
        if path.name == ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {name}"
                    )
    if findings:
        print("SECRET SCAN: FAIL")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("SECRET SCAN: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
