# Kimi Findings Review

This file converts the Kimi research output into a structured review. It does not treat Kimi's conclusions as facts unless supported by public sources.

## Summary judgment

Kimi surfaced useful watchlist candidates that were not in the initial report, especially Precision Peptide / PNGAF, PharmaTher / PHRRF, and MMA.INC / MMA. These should be added to the tracker, but their status should be lower-confidence commercial/microcap exposure until independently verified with filings, patents, trials, or regulatory records.

## Add to watchlist immediately

### Precision Peptide Company Inc. — CSE:BPC / OTCQB:PNGAF

Claim category: direct commercial BPC-157 patch exposure.  
Evidence status: partially verified through public company/OTC/CSE/press-release sources.  
Confidence: medium for commercial claim; low for regulated-drug-development claim.  
Primary next checks:
- CSE filings
- SEDAR+ filings
- OTC Markets profile/news
- Product launch status
- Any FDA/warning-letter risk
- Patent applications
- Actual ingredient/testing documentation if public

### PharmaTher Holdings — CSE:PHRM / OTCQB:PHRRF

Claim category: peptide microneedle patch platform exposure.  
Evidence status: partially verified through company press releases and OTC/CSE identity.  
Confidence: medium for platform-strategy claim; low for active target-peptide clinical asset.  
Primary next checks:
- Patent application publication
- CSE/SEDAR filings
- Any named peptide development candidates
- Any trial records
- Financing/cash runway/dilution risk

### MMA.INC — NYSE American:MMA

Claim category: Precision Peptide marketing/revenue-share partner.  
Evidence status: partially verified through company press release.  
Confidence: medium for partnership claim; low for drug-development relevance.  
Primary next checks:
- NYSE/SEC filings confirming agreement
- Revenue materiality
- Product-launch timing
- Regulatory/compliance disclosures

## Keep but verify current relevance

### TuHURA Biosciences / HURA, CohBar legacy

Claim category: MOTS-c analog CB4211 legacy.  
Evidence status: verified historical connection; current relevance uncertain.  
Confidence: high historical, low/medium current.  
Primary next checks:
- Current HURA SEC filings for CB4211/MOTS-c references
- Pipeline page
- Asset status/discontinuation language

### Hims & Hers / HIMS

Claim category: broad telehealth/compounding narrative.  
Evidence status: not target-peptide-specific based on Kimi excerpt.  
Confidence: low.  
Action: keep as Tier 3 only if direct target-peptide mentions appear in filings/IR.

## Kimi claims that must not be promoted without more evidence

- Any claim that all four primary peptides are under FDA PCAC review: FDA July 2026 agenda includes BPC-157 and TB-500 but GHK-Cu is on a separate later review track, and full Tβ4/timbetasin is distinct from TB-500.
- Any implication that PCAC review means legalization, FDA approval, or clinical validation.
- Any microcap market caps from the Kimi report without timestamped market-data source.
- Any claim that a commercial peptide patch is a regulated drug unless evidence supports it.
- Any claim that Precision Peptide, PharmaTher, or MMA are Tier 1 regulated-drug plays.

## Tracker implementation impact

Add a `claim_registry` table and make AI-sourced and press-release-only claims reviewable objects. Alerts from these claims should default to `needs_review=true` and not exceed `medium` severity unless independently verified by Tier A/B sources.
