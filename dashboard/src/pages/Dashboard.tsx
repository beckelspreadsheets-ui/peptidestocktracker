import { ChevronRight, ExternalLink, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { cleanCompanyName, relativeTime, titleCase } from "../lib/format";
import type { Briefing, EventItem } from "../lib/types";
import { useFetch } from "../hooks/useFetch";
import { useSeen } from "../hooks/useSeen";
import { ComplianceFooter } from "../components/ComplianceFooter";
import { useEventDrawer } from "../components/eventDrawer";
import {
  CountdownChip,
  Empty,
  Panel,
  ScoreMeter,
  SeverityBadge,
  StatusDot,
  Tag,
} from "../components/ui";

export function Dashboard({ onLive }: { onLive: (b: Briefing, live: boolean) => void }) {
  const { data, live, loading } = useFetch<Briefing>(() => api.briefing(25), []);
  const { isNew } = useSeen();
  useEffect(() => {
    if (data) onLive(data, live);
  }, [data, live, onLive]);
  if (loading || !data) return <LoadingState />;

  const c = data.counts;
  return (
    <div className="animate-fade-up space-y-5">
      <CountsHeader counts={c} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_360px]">
        {/* Top signals */}
        <Panel
          title={
            <span className="flex items-center gap-2">
              <Sparkles size={12} className="text-accent" /> Top signals today
            </span>
          }
        >
          <div className="row-divide">
            {data.top_events.length === 0 && <Empty>No signals in the current window.</Empty>}
            {data.top_events.map((e, i) => (
              <SignalRow key={e.id} event={e} index={i} fresh={isNew(e.created_at)} />
            ))}
          </div>
        </Panel>

        {/* Right rail */}
        <div className="space-y-5">
          <Panel title={`Discovery queue · ${data.discoveries.length}`}>
            <div className="row-divide">
              {data.discoveries.length === 0 && <Empty>No new filers.</Empty>}
              {data.discoveries.slice(0, 6).map((d) => (
                <div key={d.company_name} className="flex items-center justify-between gap-2 px-4 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] text-ink">{cleanCompanyName(d.company_name)}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-ink-3">
                      {d.filings} filing{d.filings === 1 ? "" : "s"} · {d.forms}
                    </div>
                  </div>
                  <span className="shrink-0 font-mono text-[10px] text-accent">{relativeTime(d.latest)}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title={`Regulatory doors · ${data.active_comment_periods.length}`}>
            <div className="row-divide">
              {data.active_comment_periods.length === 0 && <Empty>No open comment periods.</Empty>}
              {data.active_comment_periods.map((cp) => (
                <a
                  key={cp.docket_id || cp.title}
                  href={cp.url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="block px-4 py-2.5 transition hover:bg-panel-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] text-ink-3">{cp.docket_id}</span>
                    <CountdownChip date={cp.comment_end_date} />
                  </div>
                  <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-ink-2">{cp.title}</div>
                </a>
              ))}
            </div>
          </Panel>

          <Panel title={`Active shortages · ${data.active_shortages.length}`}>
            <div className="row-divide">
              {data.active_shortages.length === 0 && <Empty>No active shortages.</Empty>}
              {data.active_shortages.slice(0, 5).map((s) => (
                <div key={s.title} className="flex items-center justify-between gap-2 px-4 py-2.5">
                  <span className="truncate text-[12px] text-ink-2">{s.generic_name || s.title}</span>
                  <Tag>{s.status || ""}</Tag>
                </div>
              ))}
            </div>
          </Panel>

          <SourceStrip health={data.source_health} />
        </div>
      </div>

      <ComplianceFooter disclaimers={data.disclaimers} />
    </div>
  );
}

function SignalRow({ event, index, fresh }: { event: EventItem; index: number; fresh: boolean }) {
  const { openEvent } = useEventDrawer();
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`group relative px-4 py-3 transition hover:bg-panel-2 ${
        fresh ? "before:absolute before:left-0 before:top-0 before:h-full before:w-[2px] before:bg-accent" : ""
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-xs text-ink-3">{index + 1}</span>
        <button onClick={() => openEvent(event)} className="min-w-0 flex-1 text-left">
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={event.severity} />
            <Tag tone="accent">{titleCase(event.event_type)}</Tag>
            {fresh && <span className="font-mono text-[9px] uppercase tracking-wider text-accent">new</span>}
          </div>
          <div className="mt-1 truncate text-[13px] font-medium text-ink group-hover:text-accent-bright">
            {event.title}
          </div>
          {event.what_changed && (
            <div className="mt-0.5 line-clamp-1 text-[12px] text-ink-3">{event.what_changed}</div>
          )}
        </button>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <ScoreMeter score={event.score} components={event.score_components} />
          <span className="font-mono text-[10px] text-ink-3">{relativeTime(event.created_at)}</span>
        </div>
      </div>
      {event.score_reasons && event.score_reasons.length > 0 && (
        <div className="ml-8 mt-1">
          <button
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 font-mono text-[10px] text-ink-3 transition hover:text-ink-2"
          >
            <ChevronRight size={11} className={`transition ${open ? "rotate-90" : ""}`} /> why it ranks
          </button>
          {open && (
            <ul className="mt-1 space-y-0.5">
              {event.score_reasons.map((r, i) => (
                <li key={i} className="flex gap-1.5 text-[11px] text-ink-2">
                  <span className="text-accent">›</span> {r}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function CountsHeader({ counts }: { counts: Briefing["counts"] }) {
  const cells = [
    { label: "Immediate", value: counts.events_immediate, accent: true },
    { label: "Digest", value: counts.events_digest },
    { label: "Discoveries", value: counts.discoveries, accent: true },
    { label: "Comment periods", value: counts.active_comment_periods },
    { label: "Shortages", value: counts.active_shortages },
  ];
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-5">
      {cells.map((c) => (
        <div key={c.label} className="bg-panel px-4 py-3">
          <div className={`font-mono text-2xl font-semibold tabular-nums ${c.accent ? "text-accent" : "text-ink"}`}>
            {c.value}
          </div>
          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-3">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function SourceStrip({ health }: { health: Briefing["source_health"] }) {
  const run = health.latest_run;
  const errs = Object.keys(health.errors || {});
  return (
    <Panel title="Source health">
      <div className="px-4 py-3">
        {run ? (
          <>
            <div className="flex items-center justify-between font-mono text-[11px]">
              <span className="flex items-center gap-1.5 text-ink-2">
                <StatusDot status={run.status} /> {run.status}
              </span>
              <span className="text-ink-3">{relativeTime(run.finished_at || run.started_at)}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(run.tasks_by_status).map(([k, v]) => (
                <Tag key={k} tone={k === "error" ? "neutral" : "neutral"}>
                  {v} {k}
                </Tag>
              ))}
            </div>
            {errs.length > 0 && (
              <div className="mt-2 font-mono text-[10px] text-crit">
                {errs.join(", ")} blocked
              </div>
            )}
          </>
        ) : (
          <Empty>No runs yet.</Empty>
        )}
      </div>
    </Panel>
  );
}

function LoadingState() {
  return (
    <div className="flex h-[60vh] items-center justify-center">
      <div className="flex items-center gap-2 font-mono text-xs text-ink-3">
        <ExternalLink size={14} className="animate-pulse text-accent" /> loading briefing…
      </div>
    </div>
  );
}
