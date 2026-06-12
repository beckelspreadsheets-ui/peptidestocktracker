import sqlite3

from typer.testing import CliRunner

from peptide_watch.alerts import build_digest, deliver_immediate, mark_digest_sent
from peptide_watch.alerts.outbox import enqueue_undelivered
from peptide_watch.cli import app
from peptide_watch.database import init_db
from peptide_watch.events import insert_event


class CollectingChannel:
    name = "console"

    def __init__(self):
        self.messages: list[str] = []

    def send(self, message: str) -> None:
        self.messages.append(message)


class FailingChannel:
    name = "console"

    def send(self, message: str) -> None:
        raise ConnectionError("channel unreachable")


def _add_event(
    connection,
    *,
    severity: str,
    source_id: str = "src_a",
    external_id: str = "doc-1",
    run_id: str = "run-1",
    event_type: str = "test_event",
    field: str = "content",
    new_value: str = "b",
) -> None:
    assert insert_event(
        connection,
        source_id=source_id,
        external_id=external_id,
        event_type=event_type,
        field=field,
        old_value="a",
        new_value=new_value,
        run_id=run_id,
        title=f"{event_type} for {external_id}",
        what_changed="test change",
        why_it_matters="test",
        confidence="high",
        severity=severity,
        directness="direct",
        stock_market_relevance="review only",
    )
    connection.commit()


def _connect(db_path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def test_channel_outage_keeps_events_pending_then_next_sweep_sends(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="critical")

    failed = deliver_immediate(connection, FailingChannel())
    assert failed["messages_sent"] == 0 and failed["batches_failed"] == 1
    row = connection.execute(
        "SELECT status, attempts, last_error FROM deliveries"
    ).fetchone()
    assert row[0] == "pending" and row[1] == 1 and "unreachable" in row[2]

    channel = CollectingChannel()
    retried = deliver_immediate(connection, channel)
    assert retried["events_sent"] == 1
    assert len(channel.messages) == 1
    connection.close()


def test_immediate_events_batch_one_message_per_source_per_run(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="critical", external_id="doc-1", new_value="b")
    _add_event(connection, severity="high", external_id="doc-2", new_value="c")
    _add_event(connection, severity="high", external_id="doc-3", new_value="d")
    _add_event(connection, severity="critical", source_id="src_b", external_id="doc-9")

    channel = CollectingChannel()
    result = deliver_immediate(connection, channel)

    assert result["events_sent"] == 4
    assert result["messages_sent"] == 2  # src_a batch + src_b batch
    src_a_message = next(m for m in channel.messages if "src_a" in m)
    assert "3 review event(s)" in src_a_message
    connection.close()


def test_redelivery_with_no_new_events_sends_nothing(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="critical")
    channel = CollectingChannel()

    deliver_immediate(connection, channel)
    second = deliver_immediate(connection, channel)

    assert second["messages_sent"] == 0 and second["events_sent"] == 0
    assert len(channel.messages) == 1
    connection.close()


def test_digest_collects_medium_and_low_then_marks_sent(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="medium", external_id="doc-m")
    _add_event(connection, severity="low", external_id="doc-l")
    _add_event(connection, severity="critical", external_id="doc-c")

    text, event_ids = build_digest(connection, "console")
    assert len(event_ids) == 2
    assert "doc-m" in text and "doc-l" in text and "doc-c" not in text

    mark_digest_sent(connection, "console", event_ids)
    text_after, remaining = build_digest(connection, "console")
    assert remaining == []
    assert "No digest-tier events pending" in text_after

    # the critical event is untouched by the digest and still pending
    pending = connection.execute(
        "SELECT COUNT(*) FROM deliveries WHERE status = 'pending'"
    ).fetchone()[0]
    assert pending == 1
    connection.close()


def test_replay_run_events_are_enqueued_suppressed(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="critical", run_id="replay-20260611-abc")

    enqueue_undelivered(connection, "console")
    channel = CollectingChannel()
    result = deliver_immediate(connection, channel)

    assert result["messages_sent"] == 0
    status = connection.execute("SELECT status FROM deliveries").fetchone()[0]
    assert status == "suppressed"
    connection.close()


def test_deliver_and_digest_cli_commands(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    connection = _connect(db_path)
    _add_event(connection, severity="critical", external_id="doc-cli")
    _add_event(connection, severity="medium", external_id="doc-digest")
    connection.close()
    runner = CliRunner()

    deliver_result = runner.invoke(app, ["deliver", "--db", str(db_path)])
    assert deliver_result.exit_code == 0, deliver_result.output
    assert "doc-cli" in deliver_result.output
    assert "Delivered 1 event(s) in 1 message(s)" in deliver_result.output

    dry = runner.invoke(app, ["digest", "--db", str(db_path), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "doc-digest" in dry.output

    real = runner.invoke(app, ["digest", "--db", str(db_path)])
    assert real.exit_code == 0, real.output
    assert "Digest delivered with 1 event(s)." in real.output

    file_channel = runner.invoke(
        app,
        ["deliver", "--db", str(db_path), "--channel", "bogus"],
    )
    assert file_channel.exit_code == 1


def test_webhook_failure_does_not_leak_token(monkeypatch) -> None:
    import httpx

    from peptide_watch.alerts.channels import WebhookChannel

    secret_url = "https://discord.com/api/webhooks/123/SECRETTOKEN_xyz"

    def handler(request):
        return httpx.Response(500, text="boom")

    channel = WebhookChannel(url=secret_url, transport=httpx.MockTransport(handler))
    import pytest

    with pytest.raises(RuntimeError) as excinfo:
        channel.send("alert")
    assert "SECRETTOKEN" not in str(excinfo.value)
    assert "500" in str(excinfo.value)
