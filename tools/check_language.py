#!/usr/bin/env python3
"""Product-rule regression gate: user-facing strings must not contain
recommendation/advice language.

Scans string literals (via ast, so comments and test fixtures never trip it)
in the modules that produce user-facing text. A line containing a
``# lang-ok: <reason>`` comment is skipped; exact phrases in
``allowed_language.txt`` (disclaimers) are removed before matching.

Usage: check_language.py [FILE_OR_DIR ...]   (defaults to the configured targets)
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILE = ROOT / "tools" / "forbidden_language.txt"
ALLOWED_FILE = ROOT / "tools" / "allowed_language.txt"
DEFAULT_TARGETS = (
    ROOT / "src" / "peptide_watch" / "alerts",
    ROOT / "src" / "peptide_watch" / "sources",
    ROOT / "src" / "peptide_watch" / "cli.py",
    ROOT / "src" / "peptide_watch" / "events.py",
    ROOT / "src" / "peptide_watch" / "operator_commands.py",
    ROOT / "src" / "peptide_watch" / "replay.py",
    ROOT / "src" / "peptide_watch" / "relevance.py",
)
LANG_OK_MARKER = "lang-ok:"


def load_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load_patterns(path: Path = FORBIDDEN_FILE) -> list[re.Pattern[str]]:
    return [re.compile(line, re.IGNORECASE) for line in load_lines(path)]


def load_allowed(path: Path = ALLOWED_FILE) -> list[str]:
    return load_lines(path)


def find_violations(
    source: str,
    filename: str,
    patterns: list[re.Pattern[str]],
    allowed: list[str],
) -> list[str]:
    lines = source.splitlines()
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        source_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
        if LANG_OK_MARKER in source_line:
            continue
        text = node.value
        for phrase in allowed:
            text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                violations.append(
                    f"{filename}:{node.lineno}: forbidden language {match.group(0)!r}"
                )
    return violations


def iter_python_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.suffix == ".py":
            files.append(target)
    return files


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv] or list(DEFAULT_TARGETS)
    patterns = load_patterns()
    allowed = load_allowed()
    violations: list[str] = []
    for path in iter_python_files(targets):
        violations.extend(
            find_violations(path.read_text(encoding="utf-8"), str(path), patterns, allowed)
        )
    for violation in violations:
        print(violation)
    if violations:
        print(f"{len(violations)} forbidden-language violation(s).")
        return 1
    print("Language gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
