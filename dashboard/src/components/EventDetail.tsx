import { ExternalLink } from "lucide-react";
import type { EventItem } from "../lib/types";
import { relativeTime, shortDate, titleCase } from "../lib/format";
import { ScoreMeter, SeverityBadge, Tag } from "./ui";

export function EventDetail({ event }: { event: EventItem }) {
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={event.severity} />
            <Tag tone="accent">{titleCase(event.event_type)}</Tag>
            {event.peptide_id && <Tag>{event.peptide_id}</Tag>}
          </div>
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{event.title}</h3>
        </div>
        {event.score != null && (
          <ScoreMeter score={event.score} components={event.score_components} />
        )}
      </div>

      <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-line bg-line text-xs">
        {[
          ["Source", event.source_id || "—"],
          ["Confidence", event.confidence || "—"],
          ["Directness", event.directness || "—"],
          ["Detected", relativeTime(event.created_at)],
          ["Evidence tier", event.evidence_tier || "—"],
          ["External ID", event.external_id || "—"],
        ].map(([k, v]) => (
          <div key={k} className="bg-panel-2 px-3 py-2">
            <dt className="font-mono text-[10px] uppercase tracking-wide text-ink-3">{k}</dt>
            <dd className="mt-0.5 truncate font-mono text-ink-2">{v}</dd>
          </div>
        ))}
      </dl>

      {event.what_changed && (
        <Section label="What changed">{event.what_changed}</Section>
      )}
      {event.why_it_matters && (
        <Section label="Framing">{event.why_it_matters}</Section>
      )}

      {event.score_reasons && event.score_reasons.length > 0 && (
        <div>
          <SectionLabel>Why it ranks</SectionLabel>
          <ul className="mt-1.5 space-y-1">
            {event.score_reasons.map((r, i) => (
              <li key={i} className="flex gap-2 text-xs text-ink-2">
                <span className="text-accent">›</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {event.source_url && (
        <a
          href={event.source_url}
          target="_blank"
          rel="noreferrer"
          className="focusable inline-flex items-center gap-1.5 rounded-md border border-accent/30 bg-accent/10 px-3 py-1.5 font-mono text-xs text-accent transition hover:bg-accent/20"
        >
          <ExternalLink size={13} /> Open source document
        </a>
      )}
      {event.created_at && (
        <p className="font-mono text-[10px] text-ink-3">Recorded {shortDate(event.created_at)}</p>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-3">{children}</h4>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{children}</p>
    </div>
  );
}
