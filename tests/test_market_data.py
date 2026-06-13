from __future__ import annotations

from peptide_watch.market_data import (
    parse_nasdaq_market_cap,
    parse_yahoo_chart,
    provider_symbol,
)


def test_provider_symbol_uses_primary_configured_ticker() -> None:
    assert provider_symbol("PNGAF / BPC") == "PNGAF"
    assert provider_symbol("PHRRF / PHRM") == "PHRRF"
    assert provider_symbol("HIMS") == "HIMS"
    assert provider_symbol(None) is None


def test_parse_yahoo_chart_computes_change_windows() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "regularMarketPrice": 20.0,
                        "regularMarketTime": 30 * 86_400,
                    },
                    "timestamp": [0, 23 * 86_400, 29 * 86_400, 30 * 86_400],
                    "indicators": {
                        "quote": [
                            {
                                "close": [10.0, 12.0, 16.0, 20.0],
                            }
                        ]
                    },
                }
            ]
        }
    }

    parsed = parse_yahoo_chart(payload)

    assert parsed["price"] == 20.0
    assert parsed["currency"] == "USD"
    assert round(parsed["change_1d_pct"], 2) == 25.0
    assert round(parsed["change_7d_pct"], 2) == 66.67
    assert round(parsed["change_30d_pct"], 2) == 100.0


def test_parse_nasdaq_market_cap() -> None:
    payload = {
        "data": {
            "summaryData": {
                "MarketCap": {
                    "label": "Market Cap",
                    "value": "6,207,695,380",
                }
            }
        }
    }

    assert parse_nasdaq_market_cap(payload) == 6_207_695_380
    assert parse_nasdaq_market_cap({"data": {"summaryData": {"MarketCap": {"value": "N/A"}}}}) is None
