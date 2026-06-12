import { useCallback, useState } from "react";
import { parseDate } from "../lib/format";

const KEY = "pw.lastSeen";

/** "New since last visit": a persisted last-seen timestamp + a marker test. */
export function useSeen() {
  const [lastSeen, setLastSeen] = useState<number>(() => {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : 0;
  });
  // a pending value captured at mount so newly-marked items stay highlighted
  // until the user explicitly clears them
  const [pending] = useState<number>(() => {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : 0;
  });

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
