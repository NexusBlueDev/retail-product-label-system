-- Migration: Enable Row Level Security (RLS) on public tables
-- Resolves Supabase security advisories for products and rate_limits tables.

-- ============================================================
-- products table
-- ============================================================
-- The frontend accesses this table using the anon/publishable key.
-- This is a single-user internal tool (no auth), so we allow all
-- operations for the anon role.

ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

-- Allow anon (frontend) to read all products
CREATE POLICY "anon_select_products"
  ON public.products
  FOR SELECT
  TO anon
  USING (true);

-- Allow anon (frontend) to insert new products
CREATE POLICY "anon_insert_products"
  ON public.products
  FOR INSERT
  TO anon
  WITH CHECK (true);

-- Allow anon (frontend) to update existing products
CREATE POLICY "anon_update_products"
  ON public.products
  FOR UPDATE
  TO anon
  USING (true)
  WITH CHECK (true);

-- Allow anon (frontend) to delete products (e.g. future cleanup features)
CREATE POLICY "anon_delete_products"
  ON public.products
  FOR DELETE
  TO anon
  USING (true);


-- ============================================================
-- rate_limits table
-- ============================================================
-- Only accessed by the Edge Function via the service role key.
-- The service role bypasses RLS automatically, so no policies
-- are needed here — enabling RLS alone blocks all anon access.

ALTER TABLE public.rate_limits ENABLE ROW LEVEL SECURITY;

-- No public policies: service role (Edge Function) bypasses RLS;
-- anon access is blocked entirely.
