#!/usr/bin/env python3
"""Send a checked Telegram message through the peptide-watch bot.

The bot token and destination chat id come from a local env file or process
environment. The script intentionally never prints either value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from peptide_watch.language_gate import check_text


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def send_telegram(message: str) -> int:
    token = os.environ.get("PEPTIDE_WATCH_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("PEPTIDE_WATCH_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(
            "missing PEPTIDE_WATCH_TELEGRAM_TOKEN or PEPTIDE_WATCH_TELEGRAM_CHAT_ID",
            file=sys.stderr,
        )
        return 3

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"telegram send failed: HTTP {exc.code}", file=sys.stderr)
        return 4
    except urllib.error.URLError as exc:
        print(f"telegram send failed: {type(exc.reason).__name__}", file=sys.stderr)
        return 4

    if not result.get("ok"):
        print("telegram send failed: API returned ok=false", file=sys.stderr)
        return 4
    message_id = result.get("result", {}).get("message_id", "unknown")
    print(f"telegram send ok message_id={message_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    message = sys.stdin.read().strip()
    if not message:
        print("empty message", file=sys.stderr)
        return 2

    violations = check_text(message)
    if violations:
        print("language gate failed", file=sys.stderr)
        return 2

    load_env_file(Path(args.env_file))
    if args.dry_run:
        token_configured = bool(os.environ.get("PEPTIDE_WATCH_TELEGRAM_TOKEN", ""))
        chat_configured = bool(os.environ.get("PEPTIDE_WATCH_TELEGRAM_CHAT_ID", ""))
        if not token_configured or not chat_configured:
            print(
                "missing PEPTIDE_WATCH_TELEGRAM_TOKEN or PEPTIDE_WATCH_TELEGRAM_CHAT_ID",
                file=sys.stderr,
            )
            return 3
        print("telegram send dry-run ok")
        return 0

    return send_telegram(message)


if __name__ == "__main__":
    raise SystemExit(main())
