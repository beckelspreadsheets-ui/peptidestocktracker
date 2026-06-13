#!/usr/bin/env python3
"""Long-poll Telegram slash commands for the Peptide Watch HQ group.

The bot token and destination chat id come from .env or the process
environment. This script never prints either value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from peptide_watch.language_gate import check_text
from peptide_watch.operator_commands import handle_command


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    url = f"https://api.telegram.org/bot{token}/{method}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError("telegram API returned ok=false")
    return body


def send_message(token: str, chat_id: str, text: str, *, reply_to: int | None = None) -> None:
    violations = check_text(text)
    if violations:
        raise RuntimeError("command response failed language gate")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_parameters"] = {"message_id": reply_to}
    api_call(token, "sendMessage", payload)


def read_offset(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return int(value) if value else None


def write_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{offset}\n", encoding="utf-8")


def should_handle(message: dict[str, Any], target_chat_id: str) -> bool:
    chat = message.get("chat") or {}
    if str(chat.get("id")) != str(target_chat_id):
        return False
    text = (message.get("text") or "").strip()
    return text.startswith("/")


def poll_once(
    *,
    token: str,
    chat_id: str,
    offset_path: Path,
    db_path: Path,
    config_dir: Path,
    operator_db_path: Path,
    timeout: int,
) -> int:
    offset = read_offset(offset_path)
    payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    body = api_call(token, "getUpdates", payload)
    updates = body.get("result", [])
    next_offset = offset
    handled = 0
    for update in updates:
        update_id = int(update["update_id"])
        next_offset = max(next_offset or 0, update_id + 1)
        message = update.get("message") or {}
        if not should_handle(message, chat_id):
            continue
        text = message.get("text") or ""
        try:
            result = handle_command(
                text,
                db_path=db_path,
                config_dir=config_dir,
                operator_db_path=operator_db_path,
                message_id=str(message.get("message_id", "")),
            )
            reply = result.text
        except Exception as exc:
            reply = f"Command failed safely: {type(exc).__name__}. Check service logs."
        send_message(token, chat_id, reply, reply_to=message.get("message_id"))
        handled += 1
    if next_offset is not None:
        write_offset(offset_path, next_offset)
    return handled


def skip_existing(token: str, offset_path: Path) -> None:
    body = api_call(token, "getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    updates = body.get("result", [])
    if not updates:
        return
    last = max(int(update["update_id"]) for update in updates)
    write_offset(offset_path, last + 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--db", default="data/watch.db")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--operator-db", default="data/operator_state.db")
    parser.add_argument("--offset-file", default="data/telegram_command_offset.txt")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=25)
    args = parser.parse_args(argv)

    load_env_file(Path(args.env_file))
    token = os.environ.get("PEPTIDE_WATCH_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("PEPTIDE_WATCH_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("missing Telegram token or chat id", file=sys.stderr)
        return 3

    offset_path = Path(args.offset_file)
    if args.skip_existing and read_offset(offset_path) is None:
        skip_existing(token, offset_path)

    while True:
        try:
            handled = poll_once(
                token=token,
                chat_id=chat_id,
                offset_path=offset_path,
                db_path=Path(args.db),
                config_dir=Path(args.config_dir),
                operator_db_path=Path(args.operator_db),
                timeout=0 if args.once else args.poll_timeout,
            )
            if handled:
                print(f"handled {handled} command(s)", flush=True)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"telegram command poll failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            if args.once:
                return 4
            time.sleep(5)
        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
