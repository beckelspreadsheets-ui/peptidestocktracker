import { Archive, Ban, Clock, ExternalLink, Eye, Filter, Lock, Star } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { relativeTime, shortDate, titleCase } from "../lib/format";
import type {
  CommentPeriod,
  OperatorDeadlinesPage,
  OperatorEntitiesPage,
  OperatorEntity,
  OperatorEntityDetail,
  OperatorStatus,
} from "../lib/types";
import { useFetch } from "../hooks/useFetch";
import { ComplianceFooter } from "../components/ComplianceFooter";
import { CountdownChip, Empty, Panel, Tag } from "../components/ui";

const STATUS_META: Record<OperatorStatus, { label: string; icon: typeof Eye; cls: string }> = {
  watch: { label: "Watching", icon: Eye, cls: "border-accent/40 bg-accent/10 text-accent" },
  promoted: { label: "Promoted", icon: Star, cls: "border-high/40 bg-high/10 text-high" },
  ignore: { label: "Ignored", icon: Ban, cls: "border-low/30 bg-low/10 text-low" },
  archived: { label: "Archived", icon: Archive, cls: "border-line bg-panel-2 text-ink-3" },
};

const FILTERS: Array<{ label: string; value: "all" | OperatorStatus }> = [
  { label: "All", value: "all" },
  { label: "Watching", value: "watch" },
  { label: "Promoted", value: "promoted" },
  { label: "Ignored", value: "ignore" },
  { label: "Archived", value: "archived" },
];

export function OperatorMemory() {
  const { data } = useFetch<OperatorEntitiesPage>(() => api.operatorEntities(), []);
  const { data: deadlines } = useFetch<OperatorDeadlinesPage>(() => api.operatorDeadlines(), []);
  const navigate = useNavigate();
  const { entityKey } = useParams();
  const [filter, setFilter] = useState<"all" | OperatorStatus>("all");
  const [selected, setSelected] = useState<string | null>(entityKey || null);

  const rows = useMemo(() => {
    const all = data?.items || [];
    return filter === "all" ? all : all.filter((item) => item.status === filter);
  }, [data, filter]);

  useEffect(() => {
    setSelected(entityKey || null);
  }, [entityKey]);

  useEffect(() => {
    if (!data) return;
    if (!rows.length) {
      setSelected(null);
      return;
    }
    if (!selected || !rows.some((row) => row.entity_key === selected)) {
      setSelected(rows[0].entity_key);
    }
  }, [data, rows, selected]);

  const selectEntity = (key: string) => {
    setSelected(key);
    navigate(`/operator/${key}`);
  };

  const counts = data?.counts || { archived: 0, ignore: 0, promoted: 0, watch: 0 };
  return (
    <div className="animate-fade-up space-y-5">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-4">
        {(["watch", "promoted", "ignore", "archived"] as OperatorStatus[]).map((status) => (
          <StatCell key={status} status={status} value={counts[status] || 0} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[420px_1fr]">
        <Panel
          title={
            <span className="flex items-center gap-2">
              <Filter size={12} className="text-accent" /> Operator state
            </span>
          }
          action={<ReadOnlyBadge />}
        >
          <div className="border-b border-line px-4 py-3">
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  onClick={() => setFilter(item.value)}
                  className={
                    "focusable rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition " +
                    (filter === item.value
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : "border-line bg-panel-2 text-ink-3 hover:text-ink-2")
                  }
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className="row-divide">
            {rows.length === 0 && <Empty>No operator entities for this filter.</Empty>}
            {rows.map((entity) => (
              <EntityButton
                key={entity.entity_key}
                entity={entity}
                selected={selected === entity.entity_key}
                onSelect={() => selectEntity(entity.entity_key)}
              />
            ))}
          </div>
        </Panel>

        <div className="space-y-5">
          {selected ? <EntityDetail entityKey={selected} /> : <EmptyDetail />}
          <DeadlinesPanel items={deadlines?.items || []} />
        </div>
      </div>
      <ComplianceFooter disclaimers={data?.disclaimers || deadlines?.disclaimers} />
    </div>
  );
}

function StatCell({ status, value }: { status: OperatorStatus; value: number }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <div className="bg-panel px-4 py-3">
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-accent" />
        <span className="font-mono text-2xl font-semibold tabular-nums text-ink">{value}</span>
      </div>
      <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-3">{meta.label}</div>
    </div>
  );
}

function ReadOnlyBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
      <Lock size={10} /> read-only
    </span>
  );
}

function EntityButton({
  entity,
  selected,
  onSelect,
}: {
  entity: OperatorEntity;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={"block w-full px-4 py-3 text-left transition " + (selected ? "bg-accent/10" : "hover:bg-panel-2")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusChip status={entity.status} />
            <PriorityChip priority={entity.priority} />
            {entity.has_notes && <Tag>note</Tag>}
          </div>
          <div className="mt-1 truncate text-[13px] font-medium text-ink">{entity.display_name}</div>
          <div className="mt-0.5 font-mono text-[10px] text-ink-3">
            {entity.appearance_count} appearance{entity.appearance_count === 1 ? "" : "s"} ·{" "}
            {entity.source_url_count} source link{entity.source_url_count === 1 ? "" : "s"}
          </div>
        </div>
        <span className="shrink-0 font-mono text-[10px] text-ink-3">{relativeTime(entity.updated_at)}</span>
      </div>
    </button>
  );
}

function EntityDetail({ entityKey }: { entityKey: string }) {
  const { data, loading } = useFetch<OperatorEntityDetail>(() => api.operatorEntity(entityKey), [entityKey]);
  if (loading || !data) {
    return (
      <Panel title="Entity detail" action={<ReadOnlyBadge />}>
        <Empty>Loading operator detail.</Empty>
      </Panel>
    );
  }
  const { entity, source_facts } = data;
  return (
    <Panel title={entity.display_name} action={<ReadOnlyBadge />}>
      <div className="grid gap-px border-b border-line bg-line sm:grid-cols-4">
        <MiniStat label="Status" value={<StatusChip status={entity.status} />} />
        <MiniStat label="Priority" value={<PriorityChip priority={entity.priority} />} />
        <MiniStat label="First seen" value={shortDate(entity.first_seen_at)} />
        <MiniStat label="Updated" value={relativeTime(entity.updated_at)} />
      </div>
      <div className="px-4 py-3">
        <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-3">Why surfaced</h3>
        <div className="mt-2 row-divide overflow-hidden rounded-md border border-line">
          {source_facts.length === 0 && <Empty>No stored source facts yet.</Empty>}
          {source_facts.map((fact) => (
            <div key={fact.id} className="px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                {fact.event_type && <Tag tone="accent">{titleCase(fact.event_type)}</Tag>}
                {fact.source_family && <Tag>{fact.source_family}</Tag>}
                {fact.run_id && <span className="font-mono text-[10px] text-ink-3">run {fact.run_id}</span>}
              </div>
              <div className="mt-1 text-[12px] leading-snug text-ink-2">{fact.fact_summary}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10px] text-ink-3">
                <span>{relativeTime(fact.observed_at)}</span>
                {fact.source_url && (
                  <a
                    href={fact.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-accent hover:text-accent-bright"
                  >
                    <ExternalLink size={10} /> source
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function EmptyDetail() {
  return (
    <Panel title="Entity detail" action={<ReadOnlyBadge />}>
      <Empty>Select an operator entity.</Empty>
    </Panel>
  );
}

function DeadlinesPanel({ items }: { items: CommentPeriod[] }) {
  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <Clock size={12} className="text-accent" /> Deadlines
        </span>
      }
    >
      <div className="row-divide">
        {items.length === 0 && <Empty>No open comment periods.</Empty>}
        {items.map((item) => (
          <a
            key={item.docket_id || item.title}
            href={item.url || "#"}
            target="_blank"
            rel="noreferrer"
            className="block px-4 py-2.5 transition hover:bg-panel-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] text-ink-3">{item.docket_id || "public docket"}</span>
              <CountdownChip date={item.comment_end_date} />
            </div>
            <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-ink-2">{item.title}</div>
          </a>
        ))}
      </div>
    </Panel>
  );
}

function MiniStat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="bg-panel px-4 py-3">
      <div className="text-[12px] text-ink">{value}</div>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink-3">{label}</div>
    </div>
  );
}

function StatusChip({ status }: { status: OperatorStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span className={"inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] " + meta.cls}>
      <Icon size={10} /> {meta.label}
    </span>
  );
}

function PriorityChip({ priority }: { priority: OperatorEntity["priority"] }) {
  const cls =
    priority === "high"
      ? "border-high/40 bg-high/10 text-high"
      : priority === "low"
        ? "border-low/30 bg-low/10 text-low"
        : "border-line bg-panel-2 text-ink-3";
  return <span className={"inline-flex rounded border px-1.5 py-0.5 font-mono text-[10px] " + cls}>{priority}</span>;
}
