import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { EventItem } from "../lib/types";
import { Drawer } from "./Drawer";
import { EventDetail } from "./EventDetail";

interface Ctx {
  openEvent: (e: EventItem) => void;
}
const EventDrawerCtx = createContext<Ctx>({ openEvent: () => {} });

export function useEventDrawer() {
  return useContext(EventDrawerCtx);
}

export function EventDrawerProvider({ children }: { children: ReactNode }) {
  const [event, setEvent] = useState<EventItem | null>(null);
  const openEvent = useCallback((e: EventItem) => setEvent(e), []);
  return (
    <EventDrawerCtx.Provider value={{ openEvent }}>
      {children}
      <Drawer open={!!event} onClose={() => setEvent(null)} title={`Event #${event?.id ?? ""}`}>
        {event && <EventDetail event={event} />}
      </Drawer>
    </EventDrawerCtx.Provider>
  );
}
