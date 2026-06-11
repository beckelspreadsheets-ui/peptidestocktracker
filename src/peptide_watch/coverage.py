"""Map every configured source to the scanner family that claims it.

The point: a source in ``sources.yaml`` that no family claims contributes
zero events silently. ``config check`` prints this map and fails on any
UNCLAIMED source so that bug class cannot come back.
"""

from __future__ import annotations

from peptide_watch.config import WatchConfig

UNCLAIMED = "UNCLAIMED"

# API-type sources are claimed by their dedicated families by exact id.
API_FAMILIES = {
    "clinicaltrials": "clinicaltrials",
    "federal_register": "federal_register",
    "sec_edgar": "sec_edgar",
    "pubmed": "pubmed",
    "sec_fulltext": "sec_fulltext",
}


def source_coverage(config: WatchConfig) -> dict[str, str]:
    from peptide_watch.sources.company_pages import _is_company_page_source
    from peptide_watch.sources.watched_pages import is_watched_source

    coverage: dict[str, str] = {}
    for source_id, source in config.sources.items():
        if source_id in API_FAMILIES:
            coverage[source_id] = API_FAMILIES[source_id]
        elif source_id.startswith("fda_"):
            coverage[source_id] = "fda"
        elif source_id.startswith("clinicaltrials"):
            # Page entries for specific studies feed known-NCT extraction.
            coverage[source_id] = "clinicaltrials (known-NCT extraction)"
        elif _is_company_page_source(source_id, source):
            coverage[source_id] = "company_pages"
        elif is_watched_source(source_id, source):
            coverage[source_id] = "watched_pages"
        else:
            coverage[source_id] = UNCLAIMED
    return coverage


def unclaimed_sources(config: WatchConfig) -> list[str]:
    return sorted(
        source_id for source_id, family in source_coverage(config).items() if family == UNCLAIMED
    )
