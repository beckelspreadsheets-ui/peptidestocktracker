# Claims to Verify

The tracker should seed these claims as `needs_verification` unless already confirmed by a primary source. This file exists to prevent external research reports from poisoning the watchlist with unsupported conclusions.

## Critical/high priority

| Claim | Target status | Priority | Verification path | Notes |
|---|---|---:|---|---|
| FDA July 23–24, 2026 PCAC will discuss BPC-157, KPV, TB-500, MOTs-C, Emideltide/DSIP, Semax, and Epitalon for 503A Bulks List inclusion | confirmed_primary_source | Critical | FDA PCAC page + Federal Register | Do not call this FDA approval. |
| Non-injectable GHK-Cu added back to 503A Category 1; GHK-Cu PCAC before Feb. 2027 | confirmed_primary_source | Critical | FDA 503A PDF | Preserve route distinction. |
| Hims & Hers acquired a U.S.-based peptide facility in California | confirmed_primary_source | High | HIMS investor relations PR | Indirect infrastructure exposure only. |
| Hims & Hers will launch specific target peptides | needs_verification | High | HIMS filings, presentations, product pages | Do not infer product launch from facility. |
| LifeMD has national 503A/compounding pharmacy infrastructure | needs_verification | High | LifeMD SEC filings + IR presentations | Track as indirect only until peptide names appear. |
| Precision Peptide has ordered 20,000 BPC-157 patches for planned launch | confirmed_secondary_or_company_source | High | Newsfile/CSE/SEDAR+ | Company claim; not regulated-drug proof. |
| Precision Peptide signed with U.S. 503A sterile compounding pharmacy | needs_verification | High | CSE release + pharmacy disclosure + SEDAR+ | Verify legal/regulatory wording carefully. |
| PharmaTher filed U.S. provisional patent 64/034,315 covering peptide microneedle/transdermal compositions | confirmed_company_source | High | Company PR; later USPTO publication | Provisional filings are not public patent publications by default. |
| PharmaTher embodiments include BPC-157, GHK-Cu, TB-500, and KPV | confirmed_company_source | High | PharmaTher PR | Do not treat as clinical proof. |
| Hudson Biotech sponsors NCT07487363 TB-500 trial | needs_official_api_verification | Critical | ClinicalTrials.gov API v2 | Official page search found record, but adapter should verify. |
| Hudson Biotech sponsors NCT07505745 MOTS-c trial | needs_official_api_verification | Critical | ClinicalTrials.gov API v2 | Current lead came from trial mirror. |
| CohBar CVR holders may benefit from CB4211 disposition/licensing | needs_verification | Medium | SEC merger documents | Financial instrument, not normal stock exposure. |
| PMD/Promore ropocamptide asset remains divestable/licensable | needs_verification | Medium | Swedish filings/company releases | Dormant asset risk. |
| SciClone was taken private/delisted and is not clean public proxy | needs_verification | Low | HKEX/company releases | Context only. |

## Exclusion rules

Exclude or downgrade claims when:
- source is a promotional landing page without filings or primary evidence
- trial ID does not resolve through official registry/API
- company page uses “research use only” language
- a claim says or implies PCAC review equals FDA approval
- route/formulation is ambiguous, especially for GHK-Cu and TB-500/Tβ4
