import sqlite3

import httpx
import pytest

import peptide_watch.net.client as net_client
from peptide_watch.cursors import get_cursor, save_cursor
from peptide_watch.database import init_db
from peptide_watch.net.client import HttpClient
from peptide_watch.sources.fda import FdaClient, scan_fda_sources

from test_change_detection import CONFIG_DIR


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(net_client.time, "sleep", sleeps.append)
    return sleeps


def _client(handler, **kwargs) -> HttpClient:
    kwargs.setdefault("rate_limit_seconds", 0)
    return HttpClient(transport=httpx.MockTransport(handler), **kwargs)


def test_transient_5xx_is_retried_with_backoff(no_sleep) -> None:
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok", headers={"content-type": "text/plain"})

    result = _client(handler).get("https://example.gov/page")

    assert result.body == b"ok"
    assert len(calls) == 3
    assert len(no_sleep) == 2
    assert no_sleep[1] > 0  # backoff waited between attempts


def test_429_retry_after_is_honored(no_sleep) -> None:
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, content=b"ok")

    result = _client(handler).get("https://example.gov/api")

    assert result.status_code == 200
    assert no_sleep[0] >= 7.0


def test_exhausted_retries_raise(no_sleep) -> None:
    def handler(request):
        return httpx.Response(500)

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler, max_attempts=3).get("https://example.gov/down")
    assert len(no_sleep) == 2


def test_transport_errors_are_retried_then_raised(no_sleep) -> None:
    def handler(request):
        raise httpx.ConnectTimeout("hung connection")

    with pytest.raises(httpx.ConnectTimeout):
        _client(handler, max_attempts=2).get("https://example.gov/hang")
    assert len(no_sleep) == 1


def test_conditional_get_sends_validators_and_returns_not_modified() -> None:
    def handler(request):
        assert request.headers["If-None-Match"] == 'W/"abc"'
        assert request.headers["If-Modified-Since"] == "Mon, 01 Jun 2026 00:00:00 GMT"
        return httpx.Response(304)

    result = _client(handler).get(
        "https://example.gov/page",
        etag='W/"abc"',
        last_modified="Mon, 01 Jun 2026 00:00:00 GMT",
    )

    assert result.not_modified is True
    assert result.etag == 'W/"abc"'


def test_fda_scan_304_touches_cursor_and_writes_no_snapshot(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")

    def handler(request):
        if "If-None-Match" in request.headers:
            return httpx.Response(304)
        return httpx.Response(
            200,
            content=b"<html><title>PCAC</title>BPC-157 meeting</html>",
            headers={"content-type": "text/html", "ETag": '"v1"'},
        )

    client = FdaClient(http=_client(handler))
    first = scan_fda_sources(
        db_path, config_dir=CONFIG_DIR, client=client, source_ids=["fda_pcac_2026"]
    )
    second = scan_fda_sources(
        db_path, config_dir=CONFIG_DIR, client=client, source_ids=["fda_pcac_2026"]
    )

    assert first.stored == 1
    assert second.fetched == 1 and second.stored == 0
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        snapshots = connection.execute(
            "SELECT COUNT(*) FROM regulatory_document_snapshots"
        ).fetchone()[0]
        cursor = get_cursor(connection, "fda_pcac_2026")
    assert snapshots == 1  # the 304 wrote nothing
    assert cursor is not None and cursor.etag == '"v1"'


def test_save_cursor_upserts(tmp_path) -> None:
    db_path = init_db(tmp_path / "watch.db")
    with sqlite3.connect(db_path) as connection:
        save_cursor(connection, "src", etag="a")
        save_cursor(connection, "src", etag="b", last_modified="yesterday")
        cursor = get_cursor(connection, "src")
    assert cursor.etag == "b" and cursor.last_modified == "yesterday"


def test_new_scanner_registers_without_touching_the_scan_loop() -> None:
    from peptide_watch.runtime.scan import SCANNER_REGISTRY, register_scanner

    @register_scanner("test_family")
    def _scan_test(db_path, config_dir, run_id):
        """Test family."""

    try:
        assert SCANNER_REGISTRY["test_family"] is _scan_test
        with pytest.raises(ValueError, match="already registered"):
            register_scanner("test_family")(_scan_test)
    finally:
        SCANNER_REGISTRY.pop("test_family", None)
