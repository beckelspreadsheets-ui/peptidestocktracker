"""Deterministic HQ command surface for the Telegram operating room.

Commands read public-source tracker facts from watch.db and write only
operator workflow state to a separate SQLite database. They never mutate scan
facts, raw source records, or deliveries.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from peptide_watch.config import load_config
from peptide_watch.database import connect, init_db
from peptide_watch.language_gate import check_text
from peptide_watch.operator_memory import (
    VALID_PRIORITIES,
    briefing_digest,
    get_briefing_cursor,
    init_operator_memory,
    latest_run_id,
    list_entities,
    operator_key,
    record_entity_events,
    record_interaction,
    set_briefing_cursor,
    upsert_entity,
)
from peptide_watch.relevance import DISCLAIMERS, briefing, discoveries_rows
from peptide_watch.runtime import ledger
from peptide_watch.web.queries import health_counts, source_health

MUTATING_COMMANDS = {"/watch", "/ignore", "/promote", "/archive", "/setpriority"}
DISCLAIMER = DISCLAIMERS["global"]


@dataclass(frozen=True)
class CommandResult:
    command: str
    text: str
    mutated: bool = False


def init_operator_db(path: str | Path) -> Path:
    return init_operator_memory(path)


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
            result = CommandResult(command, _briefing_text(db_path, config_dir, operator_db_path))
        elif command == "/discoveries":
            result = CommandResult(command, _discoveries_text(db_path))
        elif command == "/sourcehealth":
            result = CommandResult(command, _source_health_text(db_path))
        elif command == "/deadlines":
            result = CommandResult(command, _deadlines_text(db_path, config_dir))
        elif command in {"/watch", "/ignore", "/promote", "/archive"}:
            result = _set_status_command(command, args, db_path, operator_db_path)
        elif command == "/setpriority":
            result = _set_priority_command(args, db_path, operator_db_path)
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


def _briefing_text(
    db_path: str | Path,
    config_dir: str | Path,
    operator_db_path: str | Path,
) -> str:
    config = load_config(config_dir)
    with _open_watch_db(db_path) as con:
        data = briefing(con, config, limit=5)
    digest = briefing_digest(data)
    cursor = get_briefing_cursor(operator_db_path)
    if cursor and cursor.get("last_posted_hash") == digest:
        posted = cursor.get("last_posted_at") or "previously"
        run = cursor.get("last_run_id") or latest_run_id(data) or "unknown run"
        return (
            f"No new Peptide Watch HQ briefing since {run} was posted at {posted}.\n"
            "Duplicate briefing suppressed by operator memory cursor.\n"
            f"{DISCLAIMER}"
        )
    ignored_keys = {
        row["entity_key"]
        for row in list_entities(operator_db_path, statuses=("ignore", "archived"))
    }
    followed = list_entities(operator_db_path, statuses=("watch", "promoted"))
    top_events = [
        event for event in data["top_events"] if not _matches_entity_keys(event, ignored_keys)
    ]
    discoveries = [
        item for item in data["discoveries"] if not _matches_entity_keys(item, ignored_keys)
    ]
    lines = [f"Peptide Watch HQ briefing - {data['generated_at']}"]
    counts = data["counts"]
    lines.append(
        f"Counts: {counts['events_immediate']} immediate, {counts['events_digest']} digest, "
        f"{counts['discoveries']} discoveries, {counts['active_comment_periods']} comment periods."
    )
    if followed:
        names = ", ".join(
            f"{row['display_name']} ({row['status']}, {row['priority']})" for row in followed[:8]
        )
        lines.append(f"Operator memory: following {names}.")
    if ignored_keys:
        lines.append(f"Operator memory: {len(ignored_keys)} ignored/archived item(s) kept out of normal prominence.")
    lines.append("Top signals:")
    if not top_events:
        lines.append("(none in window)")
    for event in top_events[:5]:
        lines.append(
            f"- [{event['score']}] {event['title']} ({event.get('severity') or 'unknown'}, "
            f"{event.get('event_type') or 'unknown'})"
        )
        if event.get("what_changed"):
            lines.append(f"  Fact: {event['what_changed']}")
    lines.append("Discovery queue:")
    if not discoveries:
        lines.append("(none)")
    for item in discoveries[:5]:
        lines.append(
            f"- {item['company_name']}: {item['filings']} filing(s), latest {item.get('latest') or '?'}"
        )
    lines.append(DISCLAIMER)
    set_briefing_cursor(operator_db_path, run_id=latest_run_id(data), digest=digest)
    return "\n".join(lines)


def _matches_entity_keys(item: dict[str, Any], keys: set[str]) -> bool:
    if not keys:
        return False
    candidates = [
        item.get("title"),
        item.get("external_id"),
        item.get("company_name"),
        item.get("what_changed"),
    ]
    text = " ".join(str(value) for value in candidates if value)
    if not text:
        return False
    normalized = operator_key(text)
    words = {operator_key(part) for part in re_split_entity_words(text)}
    for key in keys:
        if key in normalized or key in words:
            return True
    return False


def re_split_entity_words(text: str) -> list[str]:
    return [part for part in re.split(r"[^A-Za-z0-9]+", text) if part]


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


def _set_status_command(
    command: str,
    args: str,
    db_path: str | Path,
    operator_db_path: str | Path,
) -> CommandResult:
    entity, note = _split_entity_note(args)
    status = {
        "/watch": "watch",
        "/ignore": "ignore",
        "/promote": "promoted",
        "/archive": "archived",
    }[command]
    stats = _appearance_stats(entity, db_path)
    row = _upsert_operator_entity(
        operator_db_path,
        entity,
        status=status,
        note=note or None,
        appearance_count=stats["appearance_count"],
        source_url_count=stats["source_url_count"],
        first_seen_at=stats["first_seen_at"],
        last_seen_at=stats["last_seen_at"],
    )
    record_entity_events(operator_db_path, entity, stats["rows"][:10])
    label = {
        "watch": "watch list",
        "ignore": "lower prominence",
        "promoted": "review queue",
        "archived": "archive",
    }[status]
    note_line = f"\nNote: {row['user_notes']}" if row.get("user_notes") else ""
    return CommandResult(
        command,
        f"{row['display_name']} saved to operator {label}.\n"
        f"Priority: {row['priority']}. Factual appearances tracked: {row['appearance_count']}."
        f"{note_line}\n{DISCLAIMER}",
        mutated=True,
    )


def _set_priority_command(
    args: str,
    db_path: str | Path,
    operator_db_path: str | Path,
) -> CommandResult:
    if not args:
        raise ValueError("usage: /setpriority <entity> low|normal|high")
    parts = args.split()
    priority = parts[-1].lower()
    if priority not in VALID_PRIORITIES:
        raise ValueError("priority must be low, normal, or high")
    entity = " ".join(parts[:-1]).strip()
    if not entity:
        raise ValueError("entity is required")
    stats = _appearance_stats(entity, db_path)
    row = _upsert_operator_entity(
        operator_db_path,
        entity,
        status="watch",
        priority=priority,
        appearance_count=stats["appearance_count"],
        source_url_count=stats["source_url_count"],
        first_seen_at=stats["first_seen_at"],
        last_seen_at=stats["last_seen_at"],
    )
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
    appearance_count: int | None = None,
    source_url_count: int | None = None,
    first_seen_at: str | None = None,
    last_seen_at: str | None = None,
) -> dict[str, Any]:
    return upsert_entity(
        operator_db_path,
        display_name,
        status=status,
        priority=priority,
        note=note,
        appearance_count=appearance_count,
        source_url_count=source_url_count,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


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
            SELECT e.created_at, e.title, e.what_changed, e.event_type, e.source_id,
                   e.run_id, d.url AS source_url
            FROM events AS e
            LEFT JOIN source_documents AS d ON d.id = e.source_document_id
            WHERE e.title LIKE ?
               OR COALESCE(e.what_changed, '') LIKE ?
               OR COALESCE(e.why_it_matters, '') LIKE ?
               OR COALESCE(e.external_id, '') LIKE ?
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _appearance_stats(entity: str, db_path: str | Path) -> dict[str, Any]:
    rows = _appearance_rows(entity, db_path, limit=50)
    observed = [str(row["created_at"]) for row in rows if row.get("created_at")]
    urls = {
        row.get("source_url") or row.get("url")
        for row in rows
        if row.get("source_url") or row.get("url")
    }
    return {
        "rows": rows,
        "appearance_count": len(rows),
        "source_url_count": len(urls),
        "first_seen_at": min(observed) if observed else None,
        "last_seen_at": max(observed) if observed else None,
    }


def _record_interaction(
    operator_db_path: str | Path,
    result: CommandResult,
    *,
    message_id: str | None,
    user_text: str | None,
) -> None:
    init_operator_db(operator_db_path)
    entity_key = None
    if user_text:
        parts = user_text.strip().split(maxsplit=2)
        if len(parts) >= 2 and result.command in MUTATING_COMMANDS.union({"/why", "/notes"}):
            try:
                entity_key = operator_key(parts[1])
            except ValueError:
                entity_key = None
    summary = result.text.splitlines()[0][:240] if result.text else ""
    record_interaction(
        operator_db_path,
        command=result.command,
        message_id=message_id,
        entity_key=entity_key,
        user_text=user_text,
        response_summary=summary,
    )
