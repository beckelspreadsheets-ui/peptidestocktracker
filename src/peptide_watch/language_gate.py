"""Shared forbidden-language patterns and matching.

The single authority for both the CI source-code gate (tools/check_language.py)
and the runtime `peptide-watch check-language --stdin` that the alert agent
pipes its drafts through. Both read the same pattern files, so file-time and
run-time enforcement can never drift.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FILE = _REPO_ROOT / "tools" / "forbidden_language.txt"
ALLOWED_FILE = _REPO_ROOT / "tools" / "allowed_language.txt"


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load_patterns(path: Path = FORBIDDEN_FILE) -> list[re.Pattern[str]]:
    return [re.compile(line, re.IGNORECASE) for line in _load_lines(path)]


def load_allowed(path: Path = ALLOWED_FILE) -> list[str]:
    return _load_lines(path)


def check_text(
    text: str,
    *,
    patterns: list[re.Pattern[str]] | None = None,
    allowed: list[str] | None = None,
) -> list[str]:
    """Return the forbidden phrases found in raw text.

    Allowed disclaimer phrases are removed first (same as the file gate), then
    every forbidden pattern is searched. Empty list == clean.
    """

    patterns = patterns if patterns is not None else load_patterns()
    allowed = allowed if allowed is not None else load_allowed()
    scrubbed = text
    for phrase in allowed:
        scrubbed = re.sub(re.escape(phrase), " ", scrubbed, flags=re.IGNORECASE)
    found: list[str] = []
    for pattern in patterns:
        match = pattern.search(scrubbed)
        if match:
            found.append(match.group(0))
    return found
