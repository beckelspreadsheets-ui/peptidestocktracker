# Alert Taxonomy

## Delivery philosophy — the funnel

Two delivery tiers, each with one job:

- **Immediate (critical + high)** → pushed the moment a scan finds it. Reserved for genuine
  *early movers*: a new company disclosing a target peptide, a patent assigned to a public
  company, a comment period opening on a peptide-compounding rule, a newly recruiting or
  advancing trial, a new peptide-drug shortage. Low volume, high signal.
- **Digest (medium + low)** → swept into a daily summary. This is the "review 10 to find 1"
  pile: routine mentions of companies already on the watchlist, first capture of existing
  trials, PubMed, grants, docket activity.

Guiding rule: **existence is not news; change and novelty are.** A trial *existing* or a
tracked company *mentioning* a peptide again is digest-tier; a *new* filer, a *status change*,
or a *regulatory door opening* is immediate. Fund/passive-holder SEC filings (NPORT, N-CSR,
13F, 497, SC 13G/D) are dropped entirely — a fund holding a ticker is not a peptide company.

The highest-value early signal is **`new_company_peptide_disclosure`**: a filer not on the
watchlist disclosing a target peptide for the first time, surfaced by SEC full-text search.
Review these in `peptide-watch discoveries` and promote the promising ones to the watchlist.

## Severity

### Critical
- New trial goes recruiting for target peptide.
- Phase advancement or pivotal top-line data.
- FDA PCAC decision/category change materially improves/worsens compounding path.
- Patent assignment/license/acquisition moves target-peptide IP into a public company.
- Public company files material target-peptide disclosure.

### High
- **New company peptide disclosure** — a non-watchlist filer mentions a target peptide for
  the first time (`new_company_peptide_disclosure`). The gem-discovery signal.
- New patent publication; patent assigned to a *private* watchlist company.
- Trial status / phase / results update.
- Regulatory comment period opens on a peptide-compounding notice.
- New peptide-drug shortage; SBIR/STTR (small-company) grant award.
- FDA briefing document appears.

### Medium
- Routine SEC mention by a company already on the watchlist (digest — not news).
- First capture of an already-existing trial (backfill, not a new catalyst).
- Conference abstract; PubMed/preprint publication.
- Commercial launch claim from a microcap press release (often promotional).
- NIH grant award (non-SBIR); routine regulatory docket activity.
- Patent application filing claim not yet published.

### Low
- Cosmetic mention.
- RUO vendor mention.
- Blog/news repeat.
- AI report claim.

## Confidence

- High: primary source.
- Medium: company PR or reputable secondary source.
- Low: blog, third-party finance site, AI report, social media.

## Directness

- Direct: asset, patent, trial, FDA item, or named product.
- Indirect: supplier, CDMO, partner, platform.
- Speculative: narrative read-through only.
