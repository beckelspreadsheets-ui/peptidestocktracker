import { ShieldCheck } from "lucide-react";
import type { Disclaimers } from "../lib/types";
import { DISCLAIMERS } from "../lib/mock";

export function ComplianceFooter({ disclaimers }: { disclaimers?: Disclaimers }) {
  const d = disclaimers || DISCLAIMERS;
  return (
    <footer className="mt-8 border-t border-line px-1 py-4">
      <div className="flex items-start gap-2 text-[11px] leading-relaxed text-ink-3">
        <ShieldCheck size={13} className="mt-0.5 shrink-0 text-ink-3" />
        <div className="space-y-0.5">
          <p>{d.global}</p>
          <p>{d.regulatory}</p>
          <p>{d.microcap}</p>
        </div>
      </div>
    </footer>
  );
}
