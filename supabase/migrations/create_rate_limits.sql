-- Migration: Create rate_limits table for persistent, cross-instance rate limiting
-- Run this in Supabase SQL Editor before deploying the updated edge function.

CREATE TABLE IF NOT EXISTS rate_limits (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identifier  TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookups by identifier + time window
CREATE INDEX IF NOT EXISTS idx_rate_limits_identifier_created
  ON rate_limits (identifier, created_at DESC);

-- Auto-cleanup: delete records older than 10 minutes to prevent table bloat
-- Run this as a Supabase scheduled job (cron), or it will be cleaned up lazily per-request.
-- Alternatively, Supabase pg_cron:
-- SELECT cron.schedule('cleanup-rate-limits', '*/5 * * * *',
--   'DELETE FROM rate_limits WHERE created_at < NOW() - INTERVAL ''10 minutes''');

-- RLS: edge function uses service role key, no row-level security needed
-- (service role bypasses RLS by default)
