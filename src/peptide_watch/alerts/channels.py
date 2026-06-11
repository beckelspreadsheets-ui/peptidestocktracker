"""Delivery channels.

Built-ins are local (console/file). A real chat or webhook channel plugs in
here later; its token must come from an environment variable, never config
(enforced by config validation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class Channel(Protocol):
    name: str

    def send(self, message: str) -> None: ...


class ConsoleChannel:
    """Print messages to stdout; useful for cron mail and manual runs."""

    name = "console"

    def send(self, message: str) -> None:
        print(message)


class FileChannel:
    """Append messages to a dated markdown file in an outbox directory."""

    name = "file"

    def __init__(self, directory: str | Path = "alerts_outbox") -> None:
        self.directory = Path(directory)

    def send(self, message: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        target = self.directory / f"alerts-{stamp}.md"
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n\n---\n\n")


def get_channel(name: str, *, directory: str | Path | None = None) -> Channel:
    if name == "console":
        return ConsoleChannel()
    if name == "file":
        return FileChannel(directory or "alerts_outbox")
    raise ValueError(f"unknown channel: {name} (available: console, file)")
