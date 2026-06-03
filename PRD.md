# PRD — Peptide Stock Tracker

## 1. Objective

Build a private, compliance-safe public-source monitoring system that tracks peptide-related regulatory, clinical, patent, commercial, and capital-market catalysts.

The product should help identify early public signals around peptides that may become legally compoundable, prescribable, clinically validated, commercially developed, or FDA-approved in the United States.

The tool must not make buy/sell recommendations. It should surface evidence, classify confidence, and help prioritize follow-up research.

## 2. User and use case

Primary user: a long-term public-market investor/researcher seeking to find companies ahead of major peptide development or commercialization curves.

Investment horizon: months to years, focused on early positioning before legal access, clinical validation, licensing, major commercialization, or drug launch events.

Primary market preference: U.S.-accessible securities first. Non-U.S. names may be tracked as context but should be clearly labeled as indirect or less accessible.

## 3. Peptide universe

Primary targets:
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
- Other FDA 503A/503B PCAC substances

## 4. Key current thesis from reconciled research

### 4.1 Highest regulatory catalyst

FDA has scheduled a July 23–24, 2026 Pharmacy Compounding Advisory Committee meeting to discuss BPC-157-related substances, KPV-related substances, TB-500-related substances, MOTs-C-related substances, Emideltide/DSIP-related substances, Semax-related substances, and Epitalon-related substances for potential inclusion on the 503A Bulks List.

Important: a PCAC discussion or recommendation is not FDA approval, and a positive committee recommendation may still require further FDA process or rulemaking.

### 4.2 Primary direct clinical axis

RGN-259 / thymosin beta-4 / timbetasin remains the clearest traditional drug-development axis via ReGenTree, HLB Therapeutics, and RegeneRx. The tracker should monitor trial records, company letters, investor updates, orphan/NDA-related language, and patent developments.

### 4.3 Emerging BPC-157 axis

Hudson Biotech is a high-priority private-company clinical sponsor to monitor for BPC-157 and possibly related peptide trials. Diagen d.o.o. remains a high-priority private IP holder around stable BPC salts. Precision Peptide Company is a public microcap commercial/wellness BPC-157 transdermal patch watch item, but should not be treated as regulated-drug proof without more evidence.

### 4.4 Commercial distribution axis

Hims & Hers and LifeMD should be monitored as indirect public-market beneficiaries because of peptide, personalized medicine, telehealth, and compounding infrastructure claims. These are not direct target-peptide drug developers based on current evidence.

### 4.5 Delivery-platform axis

PharmaTher should be monitored as a speculative microcap delivery-platform/patent watch item due to its PharmaPatch/PatchPrint peptide microneedle/transdermal claims covering BPC-157, GHK-Cu, TB-500, and KPV.

### 4.6 CDMO/API axis

Bachem and PolyPeptide are indirect peptide API/CDMO proxies. They are likely too diversified to be pure plays, but should be monitored for peptide manufacturing capacity, GLP-1 demand spillover, and any explicit target-peptide API supply disclosures.

## 5. Core product features

### 5.1 Claim registry

The system must store every relevant claim with:
- claim text
- source URL
- source type
- claim category
- company
- peptide
- confidence level
- verification status
- first seen date
- last checked date
- evidence excerpt
- reviewer notes

Claim statuses:
- `confirmed_primary_source`
- `confirmed_secondary_source`
- `needs_verification`
- `contradicted`
- `stale`
- `excluded`

### 5.2 Source adapters

V1 source adapters:
- ClinicalTrials.gov API v2
- FDA PCAC page monitor
- FDA 503A bulk substance PDF/page monitor
- FDA safety-risk page monitor
- Federal Register API/search/RSS
- SEC EDGAR company and keyword monitor
- PubMed/NCBI E-utilities
- WIPO PATENTSCOPE saved-query RSS
- Company IR/news page monitors
- SEDAR+/CSE/OTC page monitors for Canadian/OTC microcaps

### 5.3 Event detection

Detect changes in:
- clinical trial creation
- trial status
- trial phase
- enrollment
- primary completion date
- results posting
- FDA agenda, briefing docs, transcripts, minutes, and PCAC recommendations
- 503A/503B bulk drug substance category/status
- patent publication/grant/assignment
- company press release/product launch
- SEC filing mention
- investor presentation mention
- licensing/acquisition/partnership
- ticker/listing/name changes

### 5.4 Alert system

Alerts must include:
- peptide
- company
- ticker/exchange if public
- event type
- severity
- what changed
- why it matters
- source link
- confidence level
- possible market relevance
- suggested follow-up research steps
- no buy/sell recommendation

Severity:
- Critical: FDA decision, pivotal trial readout, phase advancement, licensing/acquisition, patent assignment to public company.
- High: new clinical trial, recruiting status, patent publication, investor presentation adds target peptide.
- Medium: briefing document, conference abstract, PubMed paper, company PR with plausible connection.
- Low: cosmetic/RUO/commercial mentions, weak blog/news mentions, repeated PR language.

### 5.5 Manual review queue

Any high-impact but non-primary claim must enter manual review before being promoted into the main watchlist.

Examples:
- “commercial launch as early as June 2026” from a microcap press release
- “stock rose due to peptide news” from financial media
- “company will dominate peptide compounding” from commentary
- “trial is active” from non-official trial mirror

## 6. Ranking framework

Do not rank as buy/sell. Rank by watchlist relevance and catalyst sensitivity.

Tier 1:
- direct clinical asset sponsor
- direct asset owner or licensee
- major patent holder
- clearly regulated peptide product

Tier 2:
- delivery platform
- API/CDMO
- compounding infrastructure
- licensing/CVR exposure
- commercial product with plausible regulatory sensitivity

Tier 3:
- speculative narrative beneficiary
- cosmetic brand
- wellness/RUO vendor
- weak/unclear connection
- indirect diversified company

## 7. Initial priority watchlist

Tier 1 / highest directness:
- ReGenTree LLC
- HLB Therapeutics
- RegeneRx
- Hudson Biotech
- Diagen d.o.o.

Tier 2 / high-interest indirect or emerging:
- Hims & Hers
- LifeMD
- Precision Peptide Company
- PharmaTher Holdings
- Bachem
- PolyPeptide Group
- Harrow
- TuHURA / CohBar legacy / Morphogenesis CVRs

Tier 3 / speculative/context:
- Pharma Cosmetics / NEOVA / Skin Biology / ProCyte legacy
- PMD / Promore / LL-37 legacy
- SciClone / thymalfasin legacy
- Red Mountain Med Spa
- MMA.INC partnership claims
- Superpower/Noom and other private telehealth/longevity platforms

## 8. Out of scope for v1

- Automated buy/sell recommendations
- Automated trade execution
- Scraping private dashboards or paywalled data without permission
- CAPTCHAs, login scraping, or ToS circumvention
- Medical advice or patient-treatment recommendations
- Promotional content for unapproved peptides

## 9. Success criteria

Milestone 1:
- repo initializes
- config loads
- SQLite schema creates successfully
- tests pass

Milestone 2:
- claim registry works and stores external report claims as `needs_verification`

Milestone 3:
- ClinicalTrials.gov adapter detects records and changes

Milestone 4:
- FDA/Federal Register adapters detect PCAC and 503A status updates

Milestone 5:
- company/news/filing monitors create reviewable events

Milestone 6:
- Telegram alerting and weekly digest produce clear, compliance-safe outputs
