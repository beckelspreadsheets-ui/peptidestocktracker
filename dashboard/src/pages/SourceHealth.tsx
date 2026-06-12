import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { SourceHealth as SH } from "../lib/types";
import { useFetch } from "../hooks/useFetch";
import { ComplianceFooter } from "../components/ComplianceFooter";
import { Panel, StatusDot } from "../components/ui";

export function SourceHealth() {
  const { data } = useFetch<SH[]>(() => api.sourceHealth(), []);
  const rows = data || [];
  const errors = rows.filter((r) => r.status === "error").length;

  return (
    <div className="animate-fade-up space-y-4">
      <Panel title={`Source health · ${rows.length} families · ${errors} blocked`}>
        <div className="row-divide">
          {rows.map((r) => (
            <div key={r.source_id} className="flex items-center gap-3 px-4 py-3">
              <StatusDot status={r.status} />
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[13px] text-ink">{r.source_id}</div>
                {r.last_error && (
                  <div className="mt-0.5 truncate font-mono text-[11px] text-crit">{r.last_error}</div>
                )}
              </div>
              <div className="text-right">
                <div className={`font-mono text-[11px] ${statusColor(r.status)}`}>{r.status}</div>
                <div className="font-mono text-[10px] text-ink-3">
                  {r.attempt > 0 ? `attempt ${r.attempt} · ` : ""}
                  {relativeTime(r.finished_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
      <p className="px-1 font-mono text-[11px] leading-relaxed text-ink-3">
        A blocked source (e.g. a datacenter-IP block on fda.gov) is isolated and does not fail the
        run; its signal is redundantly covered by other families.
      </p>
      <ComplianceFooter />
    </div>
  );
}

function statusColor(status: string): string {
  if (status === "error" || status === "failed") return "text-crit";
  if (status === "done" || status === "completed") return "text-ok";
  if (status === "skipped") return "text-low";
  return "text-ink-2";
}
