# Source Adapters

## V1 adapters

1. ClinicalTrials.gov API v2
   - Query by peptide aliases and known NCT IDs.
   - Normalize status, phase, sponsor, enrollment, primary completion date, locations, interventions, endpoints.

2. FDA PCAC / advisory committee pages
   - Hash agenda pages, meeting-material pages, transcripts, briefing docs, recordings, minutes, and rosters.
   - Special watch: July 23–24, 2026 PCAC and future GHK-Cu/LL-37 PCAC before Feb. 2027.

3. FDA 503A/503B bulk drug substance lists
   - Download PDFs/pages.
   - Parse peptide names, categories, route-specific notes, update dates.
   - Preserve GHK-Cu injectable vs non-injectable status.

4. FDA safety-risk page
   - Monitor for changed risk language and peptide additions/removals.

5. Federal Register
   - Use API/RSS with FDA agency filters and peptide keywords.

6. SEC EDGAR
   - Monitor target public companies and keyword search across filings.
   - Required user-agent and rate limiting.

7. SEDAR+/CSE/OTC
   - Monitor Precision Peptide and PharmaTher disclosures.

8. PubMed / NCBI E-utilities
   - Monitor peptide aliases and known asset names.

9. WIPO / USPTO / PatentsView
   - Monitor patent publications, assignments, legal status, and applications.

10. Company IR/news pages
   - Hims, LifeMD, RegeneRx, ReGenTree, HLB, PharmaTher, Precision Peptide, Harrow, Bachem, PolyPeptide.

## Adapter design

Every adapter should return normalized `SourceDocument` and `SourceEvent` objects with source hash, retrieved_at, source URL, entity matches, peptide matches, extracted evidence, and confidence.
