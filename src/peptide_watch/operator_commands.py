"""Deterministic HQ command surface for the Telegram operating room.

Commands read public-source tracker facts from watch.db and write only
operator workflow state to a separate SQLite database. They never mutate scan
facts, raw source records, or deliveries.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peptide_watch.config import load_config
from peptide_watch.database import connect, init_db
from peptide_watch.language_gate import check_text
from peptide_watch.relevance import DISCLAIMERS, briefing, discoveries_rows
from peptide_watch.runtime import ledger
from peptide_watch.web.queries import health_counts, source_health

VALID_STATUSES = {"watch", "ignore", "promoted", "archived"}
VALID_PRIORITIES = {"low", "normal", "high"}
MUTATING_COMMANDS = {"/watch", "/ignore", "/promote", "/archive", "/setpriority"}
DISCLAIMER = DISCLAIMERS["global"]


@dataclass(frozen=True)
class CommandResult:
    command: str
    text: str
    mutated: bool = False


def operator_key(value: str) -> str:
    """Normalize an operator entity key without losing the display name."""

    key = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not key:
        raise ValueError("entity is required")
    return key[:120]


def init_operator_db(path: str | Path) -> Path:
    target = Path(path)
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_entities (
              entity_key TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('watch', 'ignore', 'promoted', 'archived')),
              priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high')),
              user_notes TEXT,
              created_by TEXT NOT NULL DEFAULT 'telegram',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_interactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message_id TEXT,
              entity_key TEXT,
              command TEXT NOT NULL,
              user_text TEXT,
              response_summary TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_operator_entities_status ON operator_entities(status)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_operator_interactions_entity ON operator_interactions(entity_key)"
        )
        con.commit()
    return target


def handle_command(
    raw_text: str,
    *,
    db_path: str | Path = "data/watch.db",
    config_dir: str | Path = "config",
    operator_db_path: str | Path = "data/operator_state.db",
    message_id: str | None = None,
) -> CommandResult:
    """Handle one slash command and return Telegram-ready text."""

    text = raw_text.strip()
    if not text.startswith("/"):
        return _clean(CommandResult("", "Send a slash command such as /status."), operator_db_path)

    command_token, _, rest = text.partition(" ")
    command = command_token.split("@", 1)[0].lower()
    args = rest.strip()
    try:
        if command == "/help":
            result = CommandResult(command, _help_text())
        elif command == "/status":
            result = CommandResult(command, _status_text(db_path))
        elif command == "/briefing":
            result = CommandResult(command, _briefing_text(db_path, config_dir))
        elif command == "/discoveries":
            result = CommandResult(command, _discoveries_text(db_path))
        elif command == "/sourcehealth":
            result = CommandResult(command, _source_health_text(db_path))
        elif command == "/deadlines":
            result = CommandResult(command, _deadlines_text(db_path, config_dir))
        elif command in {"/watch", "/ignore", "/promote", "/archive"}:
            result = _set_status_command(command, args, operator_db_path)
        elif command == "/setpriority":
            result = _set_priority_command(args, operator_db_path)
        elif command == "/why":
            result = CommandResult(command, _why_text(args, db_path, operator_db_path))
        elif command == "/notes":
            result = CommandResult(command, _notes_text(args, db_path, operator_db_path))
        else:
            result = CommandResult(command, f"Unknown command: {command}\n\n{_help_text()}")
    except ValueError as exc:
        result = CommandResult(command, f"{exc}\n\n{_help_text()}")
    return _clean(result, operator_db_path, message_id=message_id, user_text=raw_text)


def _clean(
    result: CommandResult,
    operator_db_path: str | Path,
    *,
    message_id: str | None = None,
    user_text: str | None = None,
) -> CommandResult:
    violations = check_text(result.text)
    if violations:
        raise RuntimeError(f"command response failed language gate: {result.command}")
    if result.command:
        _record_interaction(operator_db_path, result, message_id=message_id, user_text=user_text)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _help_text() -> str:
    return (
        "Peptide Watch HQ commands:\n"
        "/status - latest run and storage\n"
        "/briefing - factual ranked snapshot\n"
        "/discoveries - non-watchlist public filers\n"
        "/sourcehealth - source failures and skips\n"
        "/deadlines - open public comment periods\n"
        "/watch <entity> [note] - add to operator watch list\n"
        "/ignore <entity> [reason] - keep lower prominence\n"
        "/promote <entity> [note] - mark for review queue\n"
        "/archive <entity> [reason] - hide from normal flow\n"
        "/why <entity> - show source facts behind a surfaced entity\n"
        "/notes <entity> - show operator notes and recurrence\n"
        "/setpriority <entity> low|normal|high - set workflow priority\n\n"
        f"{DISCLAIMER}"
    )


def _open_watch_db(db_path: str | Path) -> sqlite3.Connection:
    init_db(db_path)
    return connect(db_path)


def _status_text(db_path: str | Path) -> str:
    with _open_watch_db(db_path) as con:
        runs = ledger.list_runs(con, limit=1)
        counts = health_counts(con)
        alert_counts = dict(
            con.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall()
        )
    latest = runs[0] if runs else None
    lines = ["Peptide Watch HQ status"]
    if latest:
        summary = latest.get("summary") or {}
        lines.append(f"Latest run: {latest['run_id']} [{latest['status']}]")
        lines.append(f"Sources: {summary.get('tasks_by_status', {})}")
        if summary.get("errors"):
            for source_id, error in summary["errors"].items():
                lines.append(f"Error {source_id}: {error}")
        if summary.get("skipped"):
            for source_id, reason in summary["skipped"].items():
                lines.append(f"Skipped {source_id}: {reason}")
    else:
        lines.append("Latest run: none recorded")
    lines.append(
        "Storage: "
        f"{counts.get('events', 0)} events, "
        f"{counts.get('company_documents', 0)} company docs, "
        f"{counts.get('regulatory_documents', 0)} regulatory docs, "
        f"{counts.get('clinical_trials', 0)} trials"
    )
    if alert_counts:
        lines.append(f"Alerts: {alert_counts}")
    lines.append("Scheduled scans: 11:20 and 21:20 UTC daily; weekly hygiene Sunday 07:00 UTC.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _briefing_text(db_path: str | Path, config_dir: str | Path) -> str:
    config = load_config(config_dir)
    with _open_watch_db(db_path) as con:
        data = briefing(con, config, limit=5)
    lines = [f"Peptide Watch HQ briefing - {data['generated_at']}"]
    counts = data["counts"]
    lines.append(
        f"Counts: {counts['events_immediate']} immediate, {counts['events_digest']} digest, "
        f"{counts['discoveries']} discoveries, {counts['active_comment_periods']} comment periods."
    )
    lines.append("Top signals:")
    if not data["top_events"]:
        lines.append("(none in window)")
    for event in data["top_events"][:5]:
        lines.append(
            f"- [{event['score']}] {event['title']} ({event.get('severity') or 'unknown'}, "
            f"{event.get('event_type') or 'unknown'})"
        )
        if event.get("what_changed"):
            lines.append(f"  Fact: {event['what_changed']}")
    lines.append("Discovery queue:")
    if not data["discoveries"]:
        lines.append("(none)")
    for item in data["discoveries"][:5]:
        lines.append(
            f"- {item['company_name']}: {item['filings']} filing(s), latest {item.get('latest') or '?'}"
        )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _discoveries_text(db_path: str | Path) -> str:
    with _open_watch_db(db_path) as con:
        rows = discoveries_rows(con, limit=10)
    lines = ["Discovery queue: non-watchlist public filers with target peptide disclosures."]
    if not rows:
        lines.append("No discoveries currently recorded.")
    for row in rows:
        lines.append(
            f"- {row['company_name']}: {row['filings']} filing(s), latest {row.get('latest') or '?'}, "
            f"forms {row.get('forms') or '?'}"
        )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _source_health_text(db_path: str | Path) -> str:
    with _open_watch_db(db_path) as con:
        rows = source_health(con)
    lines = ["Source health:"]
    if not rows:
        lines.append("No source task history recorded.")
    for row in rows:
        line = f"- {row['source_id']}: {row['status']}"
        if row.get("last_error"):
            line += f" - {row['last_error']}"
        lines.append(line)
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _deadlines_text(db_path: str | Path, config_dir: str | Path) -> str:
    config = load_config(config_dir)
    with _open_watch_db(db_path) as con:
        data = briefing(con, config, limit=1)
    periods = data.get("active_comment_periods", [])
    lines = ["Open public comment periods:"]
    if not periods:
        lines.append("No open comment periods currently recorded.")
    for item in periods[:10]:
        lines.append(
            f"- {item.get('title') or 'Untitled'} - closes {item.get('comment_end_date') or '?'} "
            f"({item.get('docket_id') or 'no docket id'})"
        )
        if item.get("url"):
            lines.append(f"  {item['url']}")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _split_entity_note(args: str) -> tuple[str, str]:
    if not args:
        raise ValueError("entity is required")
    entity, _, note = args.partition(" ")
    return entity.strip(), note.strip()


def _set_status_command(command: str, args: str, operator_db_path: str | Path) -> CommandResult:
    entity, note = _split_entity_note(args)
    status = {
        "/watch": "watch",
        "/ignore": "ignore",
        "/promote": "promoted",
        "/archive": "archived",
    }[command]
    row = _upsert_operator_entity(operator_db_path, entity, status=status, note=note or None)
    label = {
        "watch": "watch list",
        "ignore": "lower prominence",
        "promoted": "review queue",
        "archived": "archive",
    }[status]
    note_line = f"\nNote: {row['user_notes']}" if row.get("user_notes") else ""
    return CommandResult(
        command,
        f"{row['display_name']} saved to operator {label}.\nPriority: {row['priority']}.{note_line}\n{DISCLAIMER}",
        mutated=True,
    )


def _set_priority_command(args: str, operator_db_path: str | Path) -> CommandResult:
    if not args:
        raise ValueError("usage: /setpriority <entity> low|normal|high")
    parts = args.split()
    priority = parts[-1].lower()
    if priority not in VALID_PRIORITIES:
        raise ValueError("priority must be low, normal, or high")
    entity = " ".join(parts[:-1]).strip()
    if not entity:
        raise ValueError("entity is required")
    row = _upsert_operator_entity(operator_db_path, entity, status="watch", priority=priority)
    return CommandResult(
        "/setpriority",
        f"{row['display_name']} operator priority set to {row['priority']}.\n{DISCLAIMER}",
        mutated=True,
    )


def _upsert_operator_entity(
    operator_db_path: str | Path,
    display_name: str,
    *,
    status: str,
    priority: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if priority is not None and priority not in VALID_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    init_operator_db(operator_db_path)
    key = operator_key(display_name)
    now = _now()
    with sqlite3.connect(operator_db_path) as con:
        con.row_factory = sqlite3.Row
        existing = con.execute(
            "SELECT * FROM operator_entities WHERE entity_key = ?", (key,)
        ).fetchone()
        merged_note = note
        if existing and note is None:
            merged_note = existing["user_notes"]
        con.execute(
            """
            INSERT INTO operator_entities (
              entity_key, display_name, status, priority, user_notes, created_at, updated_at
            )
            VALUES (?, ?, ?, COALESCE(?, 'normal'), ?, ?, ?)
            ON CONFLICT(entity_key) DO UPDATE SET
              display_name = excluded.display_name,
              status = excluded.status,
              priority = COALESCE(excluded.priority, operator_entities.priority),
              user_notes = COALESCE(excluded.user_notes, operator_entities.user_notes),
              updated_at = excluded.updated_at
            """,
            (key, display_name, status, priority, merged_note, now, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM operator_entities WHERE entity_key = ?", (key,)).fetchone()
        return dict(row)


def _notes_text(args: str, db_path: str | Path, operator_db_path: str | Path) -> str:
    entity = args.strip()
    if not entity:
        raise ValueError("entity is required")
    key = operator_key(entity)
    init_operator_db(operator_db_path)
    with sqlite3.connect(operator_db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM operator_entities WHERE entity_key = ?", (key,)).fetchone()
    appearances = _appearance_rows(entity, db_path, limit=3)
    lines = [f"Notes for {entity}:"]
    if row:
        lines.append(f"Status: {row['status']}; operator priority: {row['priority']}")
        lines.append(f"Note: {row['user_notes'] or '(none)'}")
        lines.append(f"Updated: {row['updated_at']}")
    else:
        lines.append("No operator note stored yet.")
    lines.append(f"Recent factual appearances: {len(appearances)} shown.")
    for item in appearances:
        lines.append(f"- {item['created_at']} {item['title']} ({item['source_id']})")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _why_text(args: str, db_path: str | Path, operator_db_path: str | Path) -> str:
    entity = args.strip()
    if not entity:
        raise ValueError("entity is required")
    key = operator_key(entity)
    init_operator_db(operator_db_path)
    with sqlite3.connect(operator_db_path) as con:
        con.row_factory = sqlite3.Row
        state = con.execute("SELECT * FROM operator_entities WHERE entity_key = ?", (key,)).fetchone()
    appearances = _appearance_rows(entity, db_path, limit=5)
    lines = [f"Why {entity} surfaced:"]
    if state:
        lines.append(f"Operator state: {state['status']}; priority {state['priority']}.")
    if not appearances:
        lines.append("No matching event facts found in the current tracker DB.")
    for item in appearances:
        lines.append(f"- {item['created_at']} {item['title']} ({item['event_type']}, {item['source_id']})")
        if item.get("what_changed"):
            lines.append(f"  Fact: {item['what_changed']}")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _appearance_rows(entity: str, db_path: str | Path, *, limit: int) -> list[dict[str, Any]]:
    like = f"%{entity}%"
    with _open_watch_db(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT created_at, title, what_changed, event_type, source_id, run_id
            FROM events
            WHERE title LIKE ?
               OR COALESCE(what_changed, '') LIKE ?
               OR COALESCE(why_it_matters, '') LIKE ?
               OR COALESCE(external_id, '') LIKE ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _record_interaction(
    operator_db_path: str | Path,
    result: CommandResult,
    *,
    message_id: str | None,
    user_text: str | None,
) -> None:
    init_operator_db(operator_db_path)
    now = _now()
    entity_key = None
    if user_text:
        parts = user_text.strip().split(maxsplit=2)
        if len(parts) >= 2 and result.command in MUTATING_COMMANDS.union({"/why", "/notes"}):
            try:
                entity_key = operator_key(parts[1])
            except ValueError:
                entity_key = None
    summary = result.text.splitlines()[0][:240] if result.text else ""
    with sqlite3.connect(operator_db_path) as con:
        con.execute(
            """
            INSERT INTO operator_interactions (
              message_id, entity_key, command, user_text, response_summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, entity_key, result.command, user_text, summary, now),
        )
        con.commit()
