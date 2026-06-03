# AGENTS.md — Peptide Stock Tracker

You are working on Peptide Stock Tracker, a compliance-safe public-source biotech catalyst monitoring system.

Before coding, read these files in order:

1. `PRD.md`
2. `docs/RESEARCH_CONTEXT.md`
3. `docs/KIMI_FINDINGS_REVIEW.md`
4. `docs/GEMINI_FINDINGS_REVIEW.md`
5. `docs/CLAIMS_TO_VERIFY.md`
6. `docs/VERIFIED_SOURCE_MAP.md`
7. `docs/COMPLIANCE.md`
8. `docs/ARCHITECTURE.md`
9. `docs/SOURCE_ADAPTERS.md`
10. `docs/ALERT_TAXONOMY.md`
11. `docs/DATA_MODEL.md`
12. `config/peptides.yaml`
13. `config/companies.yaml`
14. `config/sources.yaml`
15. `config/queries.yaml`
16. `config/alert_rules.yaml`

## Product goal

Build a private automated intelligence system that monitors public signals around peptide regulatory changes, clinical development, patents, public-company filings, commercial launches, and market-relevant events.

Primary peptide targets:
- BPC-157
- TB-500
- Thymosin beta-4 / timbetasin
- GHK-Cu / copper peptide / copper tripeptide-1

Secondary targets:
- KPV
- MOTS-c
- Semax
- Epitalon
- LL-37
- Thymosin alpha-1
- Emideltide / DSIP-related substances

## Non-negotiable compliance rules

Use only public, legal, compliant sources.

Do not use material nonpublic information.

Do not recommend insider trading, rumor trading, hacking, bypassing paywalls, bypassing CAPTCHAs, credentialed scraping, or violating website terms.

Do not make buy/sell recommendations.

Do not treat FDA compounding review as FDA approval.

Do not treat company press releases as verified clinical evidence.

Do not treat wellness/RUO/commercial peptide products as regulated drug assets unless supported by primary evidence.

Every event and alert must distinguish:
- confirmed fact
- inference
- speculation
- confidence level
- possible market relevance
- source URL

## Important research posture

Kimi and Gemini reports are useful but are not authoritative. They have been integrated into the repo through `KIMI_FINDINGS_REVIEW.md`, `GEMINI_FINDINGS_REVIEW.md`, and `CLAIMS_TO_VERIFY.md`.

When an external report makes a high-value claim, implement the tracker so the claim is stored as `needs_verification` until confirmed from primary sources such as FDA, ClinicalTrials.gov, SEC, company IR, USPTO, WIPO, or peer-reviewed literature.

## Highest-priority watch items

1. FDA July 23–24, 2026 PCAC meeting for BPC-157, KPV, TB-500, MOTs-C, Emideltide/DSIP, Semax, and Epitalon.
2. FDA 503A status of GHK-Cu, especially non-injectable vs injectable route distinctions.
3. RGN-259 / thymosin beta-4 / timbetasin via ReGenTree, HLB Therapeutics, and RegeneRx.
4. Hudson Biotech trials for BPC-157, TB-500, and MOTS-c, pending direct registry verification.
5. Precision Peptide Company commercial BPC-157 transdermal patch claims.
6. PharmaTher peptide microneedle/transdermal patent and platform claims.
7. Hims & Hers peptide facility and possible future peptide category expansion.
8. LifeMD 503A/telehealth/compounding infrastructure as an indirect beneficiary.
9. Bachem and PolyPeptide as indirect peptide API/CDMO proxies.
10. CohBar/TuHURA/Morphogenesis legacy MOTS-c analog/CVR exposure.

## Engineering style

Use Python 3.12, SQLite for v1, Typer CLI, Pydantic models, YAML config, pytest, deterministic source adapters, explicit rate limiting, source hashing, durable event records, and reviewable alerts.

Never hardcode secrets. Use environment variables or GitHub Actions secrets.

## Definition of done for each task

Each task must include:
- working code
- tests
- updated docs if behavior changes
- a summary of files changed
- a next-step recommendation
