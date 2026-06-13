export type Severity = "critical" | "high" | "medium" | "low";

export interface EventItem {
  id: number;
  event_type: string;
  peptide_id: string | null;
  title: string;
  what_changed: string | null;
  why_it_matters: string | null;
  confidence: string | null;
  severity: Severity | string | null;
  directness: string | null;
  stock_market_relevance?: string | null;
  needs_review?: number;
  source_id: string | null;
  external_id?: string | null;
  created_at: string | null;
  source_url?: string | null;
  source_title?: string | null;
  evidence_tier?: string | null;
  // briefing-only:
  score?: number;
  score_components?: Record<string, number>;
  score_reasons?: string[];
}

export interface Disclaimers {
  global: string;
  microcap: string;
  regulatory: string;
  company_source: string;
}

export interface Briefing {
  schema_version: string;
  generated_at: string;
  disclaimers: Disclaimers;
  counts: {
    events_window: number;
    events_immediate: number;
    events_digest: number;
    discoveries: number;
    active_comment_periods: number;
    active_shortages: number;
  };
  top_events: EventItem[];
  discoveries: Discovery[];
  active_comment_periods: CommentPeriod[];
  active_shortages: Shortage[];
  source_health: {
    latest_run: {
      run_id: string;
      status: string;
      started_at: string;
      finished_at: string | null;
      tasks_by_status: Record<string, number>;
    } | null;
    errors: Record<string, string>;
    skipped: Record<string, string>;
  };
}

export interface Discovery {
  company_name: string;
  filings: number;
  latest: string | null;
  forms: string | null;
  peptide_sets?: number;
}

export interface CommentPeriod {
  title: string;
  url: string | null;
  docket_id: string | null;
  document_type: string | null;
  comment_end_date: string | null;
  publication_date: string | null;
}

export interface Shortage {
  title: string;
  url: string | null;
  generic_name: string | null;
  status: string | null;
  update_type: string | null;
  company_name: string | null;
}

export interface WatchlistCompany {
  id: string;
  name: string;
  ticker: string | null;
  exchange: string | null;
  tier: number;
  public_private: string;
  liquidity_risk: string | null;
  relationship: string;
  confidence: string;
  peptides: string[];
}

export interface SourceHealth {
  source_id: string;
  status: string;
  attempt: number;
  last_error: string | null;
  finished_at: string | null;
}

export interface EventsPage {
  items: EventItem[];
  total: number;
  limit: number;
  offset: number;
  disclaimers?: Disclaimers;
}

export type OperatorStatus = "watch" | "promoted" | "ignore" | "archived";
export type OperatorPriority = "low" | "normal" | "high";

export interface OperatorEntity {
  entity_key: string;
  display_name: string;
  entity_type: string | null;
  status: OperatorStatus;
  priority: OperatorPriority;
  first_seen_at: string;
  last_seen_at: string;
  appearance_count: number;
  source_url_count: number;
  has_notes: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  memory_event_count: number;
  latest_memory_event_at: string | null;
}

export interface OperatorEntitiesPage {
  items: OperatorEntity[];
  counts: Record<OperatorStatus, number>;
  disclaimers?: Disclaimers;
}

export interface OperatorSourceFact {
  id: number;
  run_id: string | null;
  event_type: string | null;
  source_family: string | null;
  source_url: string | null;
  observed_at: string;
  fact_summary: string;
}

export interface OperatorEntityDetail {
  entity: OperatorEntity;
  source_facts: OperatorSourceFact[];
  disclaimers?: Disclaimers;
}

export interface OperatorDeadlinesPage {
  items: CommentPeriod[];
  disclaimers?: Disclaimers;
}
