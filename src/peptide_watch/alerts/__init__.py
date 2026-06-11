"""Outbox-based alert delivery."""

from peptide_watch.alerts.channels import Channel, ConsoleChannel, FileChannel, get_channel
from peptide_watch.alerts.outbox import (
    build_digest,
    deliver_immediate,
    enqueue_undelivered,
    mark_digest_sent,
)

__all__ = [
    "Channel",
    "ConsoleChannel",
    "FileChannel",
    "get_channel",
    "build_digest",
    "deliver_immediate",
    "enqueue_undelivered",
    "mark_digest_sent",
]
