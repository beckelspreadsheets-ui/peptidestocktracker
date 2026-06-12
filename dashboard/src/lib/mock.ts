import type {
  Briefing,
  EventItem,
  EventsPage,
  SourceHealth,
  WatchlistCompany,
} from "./types";

const now = Date.now();
const iso = (offsetH: number) => new Date(now - offsetH * 3600000).toISOString();
const future = (days: number) =>
  new Date(now + days * 86400000).toISOString().slice(0, 10);

export const DISCLAIMERS = {
  global:
    "This is public-source research, not financial advice. This is not a buy/sell recommendation. Verify independently.",
  microcap:
    "OTC/CSE/microcap names may carry liquidity, dilution, promotional, and regulatory risk.",
  regulatory: "PCAC review and 503A/503B list movement are not FDA drug approval.",
  company_source:
    "Company press releases and commercial claims are company-source claims, not independently verified clinical evidence.",
};

const ev = (o: Partial<EventItem> & { id: number }): EventItem => ({
  event_type: "sec_filing_target_mention",
  peptide_id: "bpc_157",
  title: "Event",
  what_changed: null,
  why_it_matters: null,
  confidence: "high",
  severity: "medium",
  directness: "direct",
  source_id: "sec_fulltext",
  created_at: iso(6),
  source_url: "https://www.sec.gov/",
  ...o,
});

const TOP: EventItem[] = [
  ev({
    id: 101,
    event_type: "new_company_peptide_disclosure",
    severity: "high",
    title: "10-K detected: KALA BIO, Inc. (KALA)",
    what_changed:
      "Confirmed fact: a public company filing disclosed a target peptide; peptide matches thymosin_beta_4.",
    peptide_id: "thymosin_beta_4",
    created_at: iso(2),
    score: 84.4,
    score_components: { severity: 22.5, event_type: 35, proximity: 12, recency: 14.9 },
    score_reasons: [
      "Severity: high (curated tier).",
      "Event type: new_company_peptide_disclosure (novelty weight 1.00).",
      "Watchlist proximity: new non-watchlist public filer (fresh lead).",
      "Recency: 0 day(s) old.",
    ],
  }),
  ev({
    id: 102,
    event_type: "regulatory_comment_period_open",
    severity: "high",
    title: "Pharmacy Compounding Advisory Committee — public docket",
    what_changed:
      "Confirmed fact: a notice is open for comment on a peptide-compounding docket.",
    source_id: "regulations_gov",
    peptide_id: null,
    created_at: iso(14),
    score: 71.2,
    score_components: { severity: 22.5, event_type: 24.5, proximity: 12, recency: 12.2 },
    score_reasons: [
      "Severity: high (curated tier).",
      "Event type: regulatory_comment_period_open (novelty weight 0.70).",
      "Watchlist proximity: tracked regulatory thread.",
      "Recency: 1 day(s) old.",
    ],
  }),
  ev({
    id: 103,
    event_type: "drug_shortage",
    severity: "high",
    title: "Semaglutide injection — Currently in Shortage",
    what_changed:
      "Confirmed fact: a peptide-class drug entered shortage status (compounding-demand signal).",
    source_id: "openfda_shortages",
    peptide_id: null,
    created_at: iso(20),
    score: 66.8,
    score_components: { severity: 22.5, event_type: 24.5, proximity: 8, recency: 11.8 },
    score_reasons: [
      "Severity: high (curated tier).",
      "Event type: drug_shortage (novelty weight 0.70).",
      "Watchlist proximity: tracked peptide.",
      "Recency: 1 day(s) old.",
    ],
  }),
  ev({
    id: 104,
    event_type: "new_recruiting_trial",
    severity: "critical",
    title: "ClinicalTrials.gov record detected: NCT07437547",
    what_changed: "Confirmed fact: a trial for a target peptide is recruiting.",
    source_id: "clinicaltrials",
    created_at: iso(30),
    score: 64.1,
  }),
  ev({
    id: 105,
    event_type: "sec_filing_target_mention",
    severity: "medium",
    title: "8-K mentioning RGN-259: RegeneRx (RGRX)",
    what_changed: "Confirmed fact: a watchlist company filing mentioned a target peptide.",
    source_id: "sec_edgar",
    peptide_id: "thymosin_beta_4",
    created_at: iso(48),
    score: 41.0,
  }),
];

export const mockBriefing: Briefing = {
  schema_version: "1.0",
  generated_at: iso(1),
  disclaimers: DISCLAIMERS,
  counts: {
    events_window: 812,
    events_immediate: 471,
    events_digest: 341,
    discoveries: 26,
    active_comment_periods: 6,
    active_shortages: 13,
  },
  top_events: TOP,
  discoveries: [
    { company_name: "KALA BIO, Inc. (KALA)", filings: 3, latest: future(-2), forms: "10-K,10-Q,ARS" },
    { company_name: "BioScience Health Innovations (BHIC)", filings: 2, latest: future(-32), forms: "10-Q,10-K" },
    { company_name: "Carnyx Therapeutics, Ltd", filings: 1, latest: future(-11), forms: "EX-99" },
    { company_name: "Regenerative Medical Technology (RMTG)", filings: 2, latest: future(-40), forms: "10-Q" },
    { company_name: "Rallybio Corp (RLYB)", filings: 4, latest: future(-90), forms: "10-K" },
  ],
  active_comment_periods: [
    {
      title: "Pharmacy Compounding Advisory Committee; Notice of Meeting; Public Docket",
      url: "https://www.regulations.gov/document/FDA-2025-N-6895-0001",
      docket_id: "FDA-2025-N-6895",
      document_type: "Notice",
      comment_end_date: future(41),
      publication_date: future(-3),
    },
    {
      title: "503A Bulk Drug Substances; Proposed Rule",
      url: "https://www.regulations.gov/",
      docket_id: "FDA-2026-N-0008",
      document_type: "Proposed Rule",
      comment_end_date: future(9),
      publication_date: future(-20),
    },
  ],
  active_shortages: [
    {
      title: "Semaglutide injection",
      url: "https://www.accessdata.fda.gov/scripts/drugshortages/",
      generic_name: "Semaglutide Injection",
      status: "Currently in Shortage",
      update_type: "New",
      company_name: "Novo Nordisk",
    },
    {
      title: "Liraglutide injection",
      url: "https://www.accessdata.fda.gov/scripts/drugshortages/",
      generic_name: "Liraglutide Injection",
      status: "To Be Discontinued",
      update_type: "New",
      company_name: "Teva",
    },
  ],
  source_health: {
    latest_run: {
      run_id: "20260612T035910-a6d40b6a",
      status: "completed",
      started_at: iso(3),
      finished_at: iso(2.9),
      tasks_by_status: { done: 11, error: 1 },
    },
    errors: { fda: "Client error '403 Forbidden' for url 'https://www.fda.gov/...'" },
    skipped: { uspto_patents: "no key" },
  },
};

export function mockEvents(params: Record<string, string | number | undefined>): EventsPage {
  let items = [...TOP, ...moreEvents()];
  if (params.q) {
    const needle = String(params.q).toLowerCase();
    items = items.filter((e) => e.title.toLowerCase().includes(needle));
  }
  if (params.severity) items = items.filter((e) => e.severity === params.severity);
  if (params.peptide) items = items.filter((e) => e.peptide_id === params.peptide);
  if (params.source_type) items = items.filter((e) => e.source_id === params.source_type);
  if (params.event_type) items = items.filter((e) => e.event_type === params.event_type);
  return { items, total: items.length, limit: 50, offset: 0, disclaimers: DISCLAIMERS };
}

function moreEvents(): EventItem[] {
  return [
    ev({ id: 201, event_type: "grant_award", severity: "medium", title: "NIH grant: thymosin beta-4 wound healing", source_id: "nih_reporter", created_at: iso(60), why_it_matters: "Inference: federal research funding signal." }),
    ev({ id: 202, event_type: "pubmed_publication", severity: "medium", title: "BPC-157 accelerates tendon healing (PubMed)", source_id: "pubmed", created_at: iso(72) }),
    ev({ id: 203, event_type: "fda_enforcement_report", severity: "high", title: "FDA enforcement: GHK-Cu injectable recall", source_id: "openfda_enforcement", peptide_id: "ghk_cu", created_at: iso(96) }),
    ev({ id: 204, event_type: "company_press_release_target_mention", severity: "medium", title: "PharmaTher news: microneedle peptide platform", source_id: "pharmather_news", created_at: iso(120) }),
  ];
}

export const mockWatchlist: WatchlistCompany[] = [
  { id: "regenerx", name: "RegeneRx Biopharmaceuticals", ticker: "RGRX", exchange: "OTC", tier: 1, public_private: "public_us_otc", liquidity_risk: "extreme", relationship: "Tβ4/RGN IP and economics", confidence: "high", peptides: ["Thymosin beta-4 / timbetasin"] },
  { id: "hims", name: "Hims & Hers Health", ticker: "HIMS", exchange: "NYSE", tier: 2, public_private: "public_us", liquidity_risk: null, relationship: "Peptide facility; telehealth/compounding", confidence: "medium", peptides: ["BPC-157", "TB-500", "GHK-Cu"] },
  { id: "pharmather", name: "PharmaTher Holdings", ticker: "PHRRF", exchange: "OTCQB / CSE", tier: 2, public_private: "public_otc_canada", liquidity_risk: "extreme", relationship: "Microneedle/transdermal delivery", confidence: "medium", peptides: ["BPC-157", "GHK-Cu", "TB-500"] },
  { id: "harrow", name: "Harrow", ticker: "HROW", exchange: "NASDAQ", tier: 2, public_private: "public_us", liquidity_risk: null, relationship: "Ophthalmology/compounding infrastructure", confidence: "low_medium", peptides: ["Thymosin beta-4 / timbetasin"] },
  { id: "lifemd", name: "LifeMD", ticker: "LFMD", exchange: "NASDAQ", tier: 2, public_private: "public_us", liquidity_risk: null, relationship: "Telehealth + 503A/compounding", confidence: "medium_low", peptides: ["BPC-157", "TB-500"] },
];

export const mockSourceHealth: SourceHealth[] = [
  { source_id: "clinicaltrials", status: "done", attempt: 1, last_error: null, finished_at: iso(3) },
  { source_id: "fda", status: "error", attempt: 3, last_error: "Client error '403 Forbidden'", finished_at: iso(3) },
  { source_id: "sec_fulltext", status: "done", attempt: 1, last_error: null, finished_at: iso(3) },
  { source_id: "regulations_gov", status: "done", attempt: 1, last_error: null, finished_at: iso(3) },
  { source_id: "openfda_shortages", status: "done", attempt: 1, last_error: null, finished_at: iso(3) },
  { source_id: "uspto_patents", status: "skipped", attempt: 0, last_error: "no key", finished_at: iso(3) },
];
