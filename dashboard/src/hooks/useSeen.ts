import { useCallback, useState } from "react";
import { parseDate } from "../lib/format";

const KEY = "pw.lastSeen";

/** "New since last visit": a persisted last-seen timestamp + a marker test. */
export function useSeen() {
  // On first ever visit, seed the baseline to "now" so the feed isn't a sea of
  // "new" badges; thereafter "new" means added since the last "mark all seen".
  const [pending] = useState<number>(() => {
    const v = localStorage.getItem(KEY);
    if (v) return Number(v);
    const ts = Date.now();
    localStorage.setItem(KEY, String(ts));
    return ts;
  });
  const [lastSeen, setLastSeen] = useState<number>(pending);

  const isNew = useCallback(
    (createdAt: string | null | undefined) => {
      const d = parseDate(createdAt);
      return d ? d.getTime() > pending : false;
    },
    [pending],
  );

  const markAllSeen = useCallback(() => {
    const ts = Date.now();
    localStorage.setItem(KEY, String(ts));
    setLastSeen(ts);
  }, []);

  return { lastSeen, isNew, markAllSeen };
}
