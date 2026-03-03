-- Migration: Add explicit anon-deny policy to rate_limits
-- Resolves "RLS enabled but no policies exist" advisory.
-- The Edge Function uses the service role key, which bypasses RLS
-- automatically — this policy only affects the anon role.

CREATE POLICY "deny_anon_rate_limits"
  ON public.rate_limits
  FOR ALL
  TO anon
  USING (false)
  WITH CHECK (false);
