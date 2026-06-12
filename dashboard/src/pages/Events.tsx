import { ExternalLink, Keyboard } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { relativeTime, titleCase } from "../lib/format";
import type { EventsPage } from "../lib/types";
import { useFetch } from "../hooks/useFetch";
import { useSeen } from "../hooks/useSeen";
import { ComplianceFooter } from "../components/ComplianceFooter";
import { useEventDrawer } from "../components/eventDrawer";
import { Panel, SeverityBadge, Tag } from "../components/ui";

const SEVERITIES = ["", "critical", "high", "medium", "low"];

export function Events() {
  const [params, setParams] = useSearchParams();
  const severity = params.get("severity") || "";
  const peptide = params.get("peptide") || "";
  const source_type = params.get("source_type") || "";
  const review = params.get("review_status") || "";

  const { data, live } = useFetch<EventsPage>(
    () => api.events({ severity, peptide, source_type, review_status: review, limit: 100 }),
    [severity, peptide, source_type, review],
  );
  const { isNew, markAllSeen } = useSeen();
  const { openEvent } = useEventDrawer();

  const [cursor, setCursor] = useState(0);
  const items = data?.items || [];
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  // keyboard triage: j/k move, Enter opens, on the feed
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) return;
      if (e.key === "j") {
        setCursor((c) => Math.min(items.length - 1, c + 1));
      } else if (e.key === "k") {
        setCursor((c) => Math.max(0, c - 1));
      } else if (e.key === "Enter" && items[cursor]) {
        openEvent(items[cursor]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, cursor, openEvent]);

  useEffect(() => {
    rowRefs.current[cursor]?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setCursor(0);
  };

  return (
    <div className="animate-fade-up space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select label="Severity" value={severity} onChange={(v) => setFilter("severity", v)} options={SEVERITIES} />
        <input
          placeholder="peptide id…"
          defaultValue={peptide}
          onKeyDown={(e) => e.key === "Enter" && setFilter("peptide", (e.target as HTMLInputElement).value)}
          className="focusable rounded-md border border-line bg-panel px-2.5 py-1.5 font-mono text-xs text-ink placeholder:text-ink-3"
        />
        <input
          placeholder="source id…"
          defaultValue={source_type}
          onKeyDown={(e) => e.key === "Enter" && setFilter("source_type", (e.target as HTMLInputElement).value)}
          className="focusable rounded-md border border-line bg-panel px-2.5 py-1.5 font-mono text-xs text-ink placeholder:text-ink-3"
        />
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-1 font-mono text-[10px] text-ink-3 sm:flex">
            <Keyboard size={12} /> j/k move · ↵ open
          </span>
          <button
            onClick={markAllSeen}
            className="focusable rounded-md border border-line bg-panel px-2.5 py-1.5 font-mono text-[11px] text-ink-2 transition hover:border-line-strong hover:text-ink"
          >
            mark all seen
          </button>
        </div>
      </div>

      <Panel title={`Events · ${data?.total ?? 0}${live ? "" : " (sample)"}`}>
        <div className="row-divide">
          {items.length === 0 && (
            <div className="px-4 py-8 text-center font-mono text-xs text-ink-3">No events match.</div>
          )}
          {items.map((e, i) => {
            const fresh = isNew(e.created_at);
            const active = i === cursor;
            return (
              <div
                key={e.id}
                ref={(el) => (rowRefs.current[i] = el)}
                onMouseEnter={() => setCursor(i)}
                onClick={() => openEvent(e)}
                className={`relative grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-2.5 transition ${
                  active ? "bg-panel-2" : "hover:bg-panel-2/60"
                } ${fresh ? "before:absolute before:left-0 before:top-0 before:h-full before:w-[2px] before:bg-accent" : ""}`}
              >
                <SeverityBadge severity={e.severity} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13px] text-ink">{e.title}</span>
                    {fresh && <span className="font-mono text-[9px] uppercase text-accent">new</span>}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-ink-3">
                    <span className="text-accent/80">{titleCase(e.event_type)}</span>
                    <span>·</span>
                    <span>{e.source_id}</span>
                    {e.peptide_id && <Tag>{e.peptide_id}</Tag>}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[10px] text-ink-3">{relativeTime(e.created_at)}</span>
                  {e.source_url && (
                    <a
                      href={e.source_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(ev) => ev.stopPropagation()}
                      className="focusable rounded p-1 text-ink-3 transition hover:bg-panel-3 hover:text-accent"
                      title="Open source"
                    >
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
      <ComplianceFooter disclaimers={data?.disclaimers} />
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="focusable rounded-md border border-line bg-panel px-2.5 py-1.5 font-mono text-xs text-ink"
    >
      {options.map((o) => (
        <option key={o} value={o} className="bg-panel">
          {o || label.toLowerCase()}
        </option>
      ))}
    </select>
  );
}
