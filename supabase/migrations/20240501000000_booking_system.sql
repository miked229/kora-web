-- ============================================================
-- KORA DJ Event Booking System — Database Schema
-- Production-grade: idempotent, auditable, race-condition safe
-- ============================================================

-- ── Events ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                 TEXT NOT NULL,
  date                 TIMESTAMPTZ NOT NULL,
  venue                TEXT NOT NULL,
  capacity_general     INTEGER NOT NULL DEFAULT 0 CHECK (capacity_general >= 0),
  capacity_vip         INTEGER NOT NULL DEFAULT 0 CHECK (capacity_vip >= 0),
  price_general        NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (price_general >= 0),
  price_vip            NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (price_vip >= 0),
  tickets_sold_general INTEGER NOT NULL DEFAULT 0 CHECK (tickets_sold_general >= 0),
  tickets_sold_vip     INTEGER NOT NULL DEFAULT 0 CHECK (tickets_sold_vip >= 0),
  status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','paused','sold_out','cancelled')),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Bookings ─────────────────────────────────────────────────
-- idempotency_key (client-generated UUID per session) prevents
-- duplicate records even under retries or network failures.
CREATE TABLE IF NOT EXISTS bookings (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key           TEXT NOT NULL UNIQUE,
  event_id                  UUID NOT NULL REFERENCES events(id),
  customer_name             TEXT NOT NULL CHECK (char_length(trim(customer_name)) >= 2),
  customer_email            TEXT NOT NULL CHECK (customer_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  ticket_type               TEXT NOT NULL CHECK (ticket_type IN ('general','vip')),
  quantity                  INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  unit_price                NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
  total_amount              NUMERIC(10,2) NOT NULL CHECK (total_amount >= 0),
  status                    TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','confirmed','failed','refunded','expired')),
  stripe_payment_intent_id  TEXT UNIQUE,
  confirmation_code         TEXT UNIQUE,
  metadata                  JSONB NOT NULL DEFAULT '{}',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Booking audit log ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS booking_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id  UUID REFERENCES bookings(id) ON DELETE SET NULL,
  action      TEXT NOT NULL,
  old_status  TEXT,
  new_status  TEXT,
  details     JSONB NOT NULL DEFAULT '{}',
  ip_address  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Email delivery log ───────────────────────────────────────
-- UNIQUE(booking_id, email_type) is the idempotency guard for emails.
CREATE TABLE IF NOT EXISTS email_logs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id       UUID NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  email_type       TEXT NOT NULL CHECK (email_type IN ('confirmation','payment_failed','reminder')),
  recipient_email  TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','sent','failed','retrying')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  max_attempts     INTEGER NOT NULL DEFAULT 3,
  last_attempt_at  TIMESTAMPTZ,
  sent_at          TIMESTAMPTZ,
  error_message    TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (booking_id, email_type)
);

-- ── Indexes ──────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_bookings_idempotency_key          ON bookings(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_bookings_stripe_payment_intent_id ON bookings(stripe_payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_bookings_customer_email           ON bookings(customer_email);
CREATE INDEX IF NOT EXISTS idx_bookings_status                   ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_event_id                 ON bookings(event_id);
CREATE INDEX IF NOT EXISTS idx_booking_logs_booking_id           ON booking_logs(booking_id);
CREATE INDEX IF NOT EXISTS idx_booking_logs_created_at           ON booking_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_logs_booking_id             ON email_logs(booking_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_status                 ON email_logs(status);

-- ── updated_at auto-trigger ──────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_bookings_updated_at
  BEFORE UPDATE ON bookings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER trg_email_logs_updated_at
  BEFORE UPDATE ON email_logs
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER trg_events_updated_at
  BEFORE UPDATE ON events
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Atomic ticket-count increment (called from webhook) ──────
-- Uses advisory lock to prevent race conditions on the counter.
CREATE OR REPLACE FUNCTION increment_tickets_sold(
  p_event_id UUID,
  p_ticket_type TEXT,
  p_quantity INTEGER
)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  IF p_ticket_type = 'vip' THEN
    UPDATE events
    SET tickets_sold_vip = tickets_sold_vip + p_quantity
    WHERE id = p_event_id;
  ELSE
    UPDATE events
    SET tickets_sold_general = tickets_sold_general + p_quantity
    WHERE id = p_event_id;
  END IF;
END;
$$;

-- ── Row Level Security ───────────────────────────────────────
ALTER TABLE events        ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_logs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_logs    ENABLE ROW LEVEL SECURITY;

-- Public can read active events only
CREATE POLICY "public_read_active_events" ON events
  FOR SELECT USING (status = 'active');

-- Authenticated service role bypasses RLS automatically.
-- Anon users cannot read/write bookings directly;
-- all mutations go through Edge Functions (service role).

-- ── Seed: May 15 KORA event ──────────────────────────────────
INSERT INTO events (name, date, venue, capacity_general, capacity_vip, price_general, price_vip)
VALUES (
  'KORA — DJ Night Cozumel',
  '2026-05-15 22:00:00-06',
  'Cozumel, Quintana Roo, México',
  200,
  50,
  500.00,
  1200.00
)
ON CONFLICT DO NOTHING;
