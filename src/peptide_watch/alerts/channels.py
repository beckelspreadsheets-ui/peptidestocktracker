"""Delivery channels.

Built-ins are local (console/file). A real chat or webhook channel plugs in
here later; its token must come from an environment variable, never config
(enforced by config validation).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx


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


class WebhookChannel:
    """POST messages as JSON to a webhook (Discord, Slack, etc.).

    The URL is a secret and comes only from the environment:
    PEPTIDE_WATCH_WEBHOOK_URL. The JSON field name defaults to "content"
    (Discord); set PEPTIDE_WATCH_WEBHOOK_FIELD=text for Slack-style hooks.
    A failed POST raises, which leaves the outbox rows pending for retry.
    """

    name = "webhook"

    def __init__(
        self,
        *,
        url: str | None = None,
        field: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url or os.environ.get("PEPTIDE_WATCH_WEBHOOK_URL", "")
        if not self.url:
            raise ValueError(
                "webhook channel needs the PEPTIDE_WATCH_WEBHOOK_URL environment variable"
            )
        self.field = field or os.environ.get("PEPTIDE_WATCH_WEBHOOK_FIELD", "content")
        self._timeout = timeout
        self._transport = transport

    def send(self, message: str) -> None:
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            response = client.post(self.url, json={self.field: message})
            response.raise_for_status()


def get_channel(name: str, *, directory: str | Path | None = None) -> Channel:
    if name == "console":
        return ConsoleChannel()
    if name == "file":
        return FileChannel(directory or "alerts_outbox")
    if name == "webhook":
        return WebhookChannel()
    raise ValueError(f"unknown channel: {name} (available: console, file, webhook)")
