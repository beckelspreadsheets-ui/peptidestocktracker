# Source Adapters

## V1 adapters

1. ClinicalTrials.gov API v2
   - Query by peptide aliases and known NCT IDs.
   - Normalize status, phase, sponsor, enrollment, primary completion date, locations, interventions, endpoints.
   - Store raw JSON snapshots and normalized `clinical_trials` rows.
   - Create reviewable events for new official records and changes in status, phase, enrollment, primary completion date, last update post date, and results availability.
   - Treat ClinicalTrials.gov records as primary-source registry facts, not proof of safety, efficacy, FDA approval, or investment merit.

2. FDA PCAC / advisory committee pages
   - Hash agenda pages, meeting-material pages, transcripts, briefing docs, recordings, minutes, and rosters.
   - Special watch: July 23–24, 2026 PCAC and future GHK-Cu/LL-37 PCAC before Feb. 2027.
   - Store normalized `regulatory_documents` rows and immutable snapshots.
   - Create reviewable events for new pages and content-hash changes.
   - Treat PCAC discussion/recommendations as advisory/regulatory-process facts, not FDA drug approval.

3. FDA 503A/503B bulk drug substance lists
   - Download PDFs/pages.
   - Parse peptide names, categories, route-specific notes, update dates.
   - Preserve GHK-Cu injectable vs non-injectable status.
   - Extract PDF text with `pypdf` and store route/status snippets for matched peptides.

4. FDA safety-risk page
   - Monitor for changed risk language and peptide additions/removals.
   - Preserve safety-risk language as official-source evidence, not clinical proof.

5. Federal Register
   - Use API/RSS with FDA agency filters and peptide keywords.
   - Search the official API with configured PCAC terms, fetch detailed JSON and raw text, and store notices by document number.
   - Create reviewable events for new notices and content-hash changes.

6. SEC EDGAR
   - Monitor target public companies and keyword search across filings.
   - Required user-agent and rate limiting.
   - Use the official SEC company ticker map to resolve configured public U.S. tickers to CIKs.
   - Fetch recent public submissions and primary filing documents for configured forms.
   - Store normalized `company_documents` rows and immutable snapshots.
   - Create reviewable events for SEC filing target mentions with high source confidence.
   - SEC filing mentions are public-source facts about filing text, not buy/sell recommendations or proof of clinical value.

7. SEDAR+/CSE/OTC
   - Monitor Precision Peptide and PharmaTher disclosures.
   - Store CSE/OTC public pages through the company page monitor when configured with `company_id`.
   - Treat OTC/CSE/microcap claims as reviewable and include liquidity, dilution, promotional, and regulatory risk language.

8. PubMed / NCBI E-utilities
   - Monitor peptide aliases and known asset names.

9. WIPO / USPTO / PatentsView
   - Monitor patent publications, assignments, legal status, and applications.

10. Company IR/news pages
   - Hims, LifeMD, RegeneRx, ReGenTree, HLB, PharmaTher, Precision Peptide, Harrow, Bachem, PolyPeptide.
   - Fetch only configured public pages with explicit rate limiting.
   - Match peptide aliases, configured company ids, tickers, and catalyst keyword buckets.
   - Create reviewable events for public-source mentions of compounding, 503A/503B, product launches, patents, licensing/acquisition, clinical-trial language, or peptide infrastructure.
   - Treat company press releases as company-source claims, not independently verified clinical evidence.

## Adapter design

Every adapter should return normalized `SourceDocument` and `SourceEvent` objects with source hash, retrieved_at, source URL, entity matches, peptide matches, extracted evidence, and confidence.
