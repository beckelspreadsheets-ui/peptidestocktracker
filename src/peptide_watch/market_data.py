"""Market-data enrichment for configured public watchlist companies.

This is context only. It must not be used to create recommendations, ratings,
or price targets.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx

from peptide_watch.config import CompanyConfig, WatchConfig

USER_AGENT = "Mozilla/5.0 peptide-watch/0.1 market-context"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NASDAQ_SUMMARY_URL = "https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"


def provider_symbol(ticker: str | None) -> str | None:
    """Return the primary provider symbol from config ticker text."""
    if not ticker:
        return None
    first = re.split(r"\s*/\s*|,", ticker.strip(), maxsplit=1)[0].strip()
    if not first or first.upper() == "CVR":
        return None
    if not re.fullmatch(r"[A-Za-z0-9.\-]+", first):
        return None
    return first.upper()


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return ((current - previous) / previous) * 100


def close_at_or_before(
    timestamps: list[Any],
    closes: list[Any],
    target_ts: int,
) -> float | None:
    best: float | None = None
    for ts, close in zip(timestamps, closes, strict=False):
        try:
            numeric_ts = int(ts)
            numeric_close = float(close)
        except (TypeError, ValueError):
            continue
        if numeric_ts <= target_ts:
            best = numeric_close
        elif best is not None:
            break
    return best


def parse_yahoo_chart(payload: dict[str, Any]) -> dict[str, Any]:
    result = ((payload.get("chart") or {}).get("result") or [{}])[0]
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    closes = quote.get("close") or []
    latest_price = meta.get("regularMarketPrice")
    if latest_price is None:
        latest_price = close_at_or_before(timestamps, closes, int(datetime.now(UTC).timestamp()))
    latest_ts = int(meta.get("regularMarketTime") or (timestamps[-1] if timestamps else 0) or 0)
    price = float(latest_price) if latest_price is not None else None
    return {
        "price": price,
        "currency": meta.get("currency"),
        "as_of": datetime.fromtimestamp(latest_ts, UTC).isoformat() if latest_ts else None,
        "change_1d_pct": pct_change(price, close_at_or_before(timestamps, closes, latest_ts - 86_400)),
        "change_7d_pct": pct_change(price, close_at_or_before(timestamps, closes, latest_ts - 7 * 86_400)),
        "change_30d_pct": pct_change(price, close_at_or_before(timestamps, closes, latest_ts - 30 * 86_400)),
    }


def parse_nasdaq_market_cap(payload: dict[str, Any]) -> int | None:
    summary = ((payload.get("data") or {}).get("summaryData") or {})
    raw = ((summary.get("MarketCap") or {}).get("value") or "").replace(",", "")
    if not raw or raw.upper() == "N/A":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


class MarketDataProvider:
    def __init__(self, *, timeout_seconds: float = 2.5, max_workers: int = 6):
        self.timeout_seconds = timeout_seconds
        self.max_workers = max_workers

    def watchlist_market_data(self, config: WatchConfig) -> list[dict[str, Any]]:
        companies = list(config.companies)
        if not companies:
            return []
        workers = max(1, min(self.max_workers, len(companies)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._company_market_data, companies))

    def _company_market_data(self, company: CompanyConfig) -> dict[str, Any]:
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            return self.company_market_data(company, client)

    def company_market_data(
        self,
        company: CompanyConfig,
        client: httpx.Client,
    ) -> dict[str, Any]:
        symbol = provider_symbol(company.ticker)
        row: dict[str, Any] = {
            "company_id": company.id,
            "name": company.name,
            "ticker": company.ticker,
            "symbol": symbol,
            "exchange": company.exchange,
            "status": "unavailable",
            "provider": "yahoo_chart+nasdaq_summary",
            "price": None,
            "currency": None,
            "market_cap": None,
            "change_1d_pct": None,
            "change_7d_pct": None,
            "change_30d_pct": None,
            "as_of": None,
            "error": None,
        }
        if not symbol:
            row["error"] = "no provider symbol configured"
            return row

        errors: list[str] = []
        try:
            chart = client.get(
                YAHOO_CHART_URL.format(symbol=symbol),
                params={"range": "1mo", "interval": "1d"},
            )
            chart.raise_for_status()
            row.update(parse_yahoo_chart(chart.json()))
            row["status"] = "ok" if row["price"] is not None else "partial"
        except Exception as exc:  # noqa: BLE001 - provider failures stay row-local
            errors.append(f"yahoo_chart: {type(exc).__name__}")

        try:
            summary = client.get(NASDAQ_SUMMARY_URL.format(symbol=symbol))
            summary.raise_for_status()
            row["market_cap"] = parse_nasdaq_market_cap(summary.json())
            if row["market_cap"] is not None and row["status"] == "unavailable":
                row["status"] = "partial"
        except Exception as exc:  # noqa: BLE001 - provider failures stay row-local
            errors.append(f"nasdaq_summary: {type(exc).__name__}")

        row["error"] = "; ".join(errors) or None
        return row


def watchlist_market_data(config: WatchConfig) -> list[dict[str, Any]]:
    return MarketDataProvider().watchlist_market_data(config)
