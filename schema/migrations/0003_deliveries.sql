-- Transactional outbox: the scan writes events; a separate deliver phase
-- reads undelivered events and sends them. An event is delivered at most
-- once per channel; a channel outage just leaves pending rows behind.
CREATE TABLE IF NOT EXISTS deliveries (
  event_id   INTEGER NOT NULL REFERENCES events(id),
  channel    TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN ('pending','sent','suppressed','failed')),
  attempts   INTEGER NOT NULL DEFAULT 0,
  sent_at    TEXT,
  last_error TEXT,
  PRIMARY KEY (event_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(channel, status);
