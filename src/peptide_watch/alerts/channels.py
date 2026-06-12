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
        # The webhook URL carries a secret token, and httpx puts the full URL
        # in HTTP-error messages — so re-raise sanitized errors (status/type
        # only) to keep the token out of stored delivery errors and logs.
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(self.url, json={self.field: message})
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"webhook delivery failed: HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"webhook delivery failed: {type(exc).__name__}"
            ) from None


class TelegramChannel:
    """Send messages via the Telegram Bot API (sendMessage).

    Token and chat id come only from the environment:
    PEPTIDE_WATCH_TELEGRAM_TOKEN and PEPTIDE_WATCH_TELEGRAM_CHAT_ID. The token
    is part of the API URL, so errors are sanitized to keep it out of stored
    delivery errors and logs. Messages are truncated to Telegram's limit.
    """

    name = "telegram"
    MAX_LEN = 4096

    def __init__(
        self,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = token or os.environ.get("PEPTIDE_WATCH_TELEGRAM_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("PEPTIDE_WATCH_TELEGRAM_CHAT_ID", "")
        if not self.token or not self.chat_id:
            raise ValueError(
                "telegram channel needs PEPTIDE_WATCH_TELEGRAM_TOKEN and "
                "PEPTIDE_WATCH_TELEGRAM_CHAT_ID environment variables"
            )
        self._timeout = timeout
        self._transport = transport

    def send(self, message: str) -> None:
        if len(message) > self.MAX_LEN:
            message = message[: self.MAX_LEN - 20].rstrip() + "\n…(truncated)"
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The bot token is in the URL — never include it in the error.
            raise RuntimeError(
                f"telegram delivery failed: HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"telegram delivery failed: {type(exc).__name__}"
            ) from None


def get_channel(name: str, *, directory: str | Path | None = None) -> Channel:
    if name == "console":
        return ConsoleChannel()
    if name == "file":
        return FileChannel(directory or "alerts_outbox")
    if name == "webhook":
        return WebhookChannel()
    if name == "telegram":
        return TelegramChannel()
    raise ValueError(f"unknown channel: {name} (available: console, file, webhook, telegram)")
