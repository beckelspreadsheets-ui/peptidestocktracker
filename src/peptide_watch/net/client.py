"""Shared HTTP client: retries with backoff, hard timeouts, per-host throttling,
and conditional GETs. Every source client routes through this so no adapter
hand-rolls its own networking."""

from __future__ import annotations

import json
import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any, NamedTuple
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request as UrllibRequest
from urllib.request import urlopen

import httpx

DEFAULT_USER_AGENT = "peptide-watch/0.1 public-source research"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RATE_LIMIT_SECONDS = 0.5
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 30.0


class FetchResponse(NamedTuple):
    url: str
    status_code: int
    content_type: str
    body: bytes
    etag: str | None
    last_modified: str | None
    not_modified: bool


class UrllibTransport(httpx.BaseTransport):
    """httpx transport backed by stdlib urllib.

    Some hosts (e.g. clinicaltrials.gov behind Akamai) 403-block httpx's TLS
    fingerprint while accepting Python's stdlib client (live-verified). This
    transport lets the shared client fall back per host without losing the
    retry/throttle/conditional-GET layer.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        headers = {
            key: value
            for key, value in request.headers.items()
            # let urllib manage these itself; identity encoding keeps the
            # body bytes unprocessed
            if key.lower() not in {"host", "connection", "accept-encoding", "content-length"}
        }
        urllib_request = UrllibRequest(
            str(request.url), headers=headers, method=request.method
        )
        try:
            with urlopen(urllib_request, timeout=self._timeout) as response:
                body = response.read()
                status = response.status
                response_headers = [
                    (key, value)
                    for key, value in response.headers.items()
                    if key.lower() not in {"transfer-encoding", "content-encoding"}
                ]
        except HTTPError as error:
            body = error.read()
            status = error.code
            response_headers = list(error.headers.items()) if error.headers else []
        return httpx.Response(
            status, headers=response_headers, content=body, request=request
        )


class HttpClient:
    """One client wrapper providing retry/backoff (honoring Retry-After),
    connect/read timeouts, a per-host minimum request interval, conditional
    GETs from stored etag/last-modified, and a fixed honest User-Agent."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        max_attempts: int = MAX_ATTEMPTS,
        transport: httpx.BaseTransport | None = None,
        fallback_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._rate_limit_seconds = rate_limit_seconds
        self._max_attempts = max(1, max_attempts)
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            transport=transport,
        )
        # Hosts that 403-block httpx's TLS fingerprint fall back to a
        # urllib-backed transport (real network runs only, unless a test
        # injects its own fallback transport).
        if fallback_transport is None and transport is None:
            fallback_transport = UrllibTransport(timeout)
        self._fallback_client = (
            httpx.Client(
                timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
                headers={"User-Agent": user_agent},
                follow_redirects=True,
                transport=fallback_transport,
            )
            if fallback_transport is not None
            else None
        )
        self._urllib_hosts: set[str] = set()
        self._last_request_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "*/*",
        etag: str | None = None,
        last_modified: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResponse:
        headers = {"Accept": accept}
        if extra_headers:
            headers.update(extra_headers)
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        host = urlsplit(url).netloc
        attempt = 0
        while True:
            attempt += 1
            self._throttle(url)
            client = (
                self._fallback_client
                if self._fallback_client is not None and host in self._urllib_hosts
                else self._client
            )
            try:
                response = client.get(url, params=params, headers=headers)
            except httpx.TransportError:
                if attempt >= self._max_attempts:
                    raise
                time.sleep(self._backoff(attempt, None))
                continue
            if (
                response.status_code == 403
                and self._fallback_client is not None
                and host not in self._urllib_hosts
            ):
                # Possible TLS-fingerprint block: retry this host via urllib
                # without consuming a retry attempt.
                self._urllib_hosts.add(host)
                attempt -= 1
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_attempts:
                time.sleep(self._backoff(attempt, _retry_after_seconds(response)))
                continue
            if response.status_code == 304:
                return FetchResponse(
                    url=str(response.url),
                    status_code=304,
                    content_type="",
                    body=b"",
                    etag=etag,
                    last_modified=last_modified,
                    not_modified=True,
                )
            response.raise_for_status()
            return FetchResponse(
                url=str(response.url),
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                body=response.content,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                not_modified=False,
            )

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        result = self.get(
            url, params=params, accept="application/json", extra_headers=extra_headers
        )
        return json.loads(result.body.decode("utf-8"))

    def get_text(self, url: str, *, accept: str = "text/plain,*/*") -> str:
        result = self.get(url, accept=accept)
        return result.body.decode("utf-8", errors="ignore")

    def close(self) -> None:
        self._client.close()

    def _throttle(self, url: str) -> None:
        if self._rate_limit_seconds <= 0:
            return
        host = urlsplit(url).netloc
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at.get(host, 0.0)
            wait = self._rate_limit_seconds - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request_at[host] = time.monotonic()

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        base = min(2.0**attempt, MAX_BACKOFF_SECONDS) * random.uniform(0.5, 1.0)
        if retry_after is not None:
            return min(max(base, retry_after), MAX_BACKOFF_SECONDS * 2)
        return base


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    if value.strip().isdigit():
        return float(value.strip())
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    now = parsedate_to_datetime(response.headers.get("date")) if response.headers.get("date") else None
    if now is None:
        return None
    return max(0.0, (target - now).total_seconds())
