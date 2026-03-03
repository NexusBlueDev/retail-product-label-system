-- Migration: Replace anon RLS policies on products with authenticated-only policy
-- Resolves Supabase security advisories for overly permissive anon write access.
-- Auth user UID: 10cfa0fe-080e-4c8f-94f8-d763f20fb641

-- Drop all existing anon policies
DROP POLICY IF EXISTS "anon_select_products" ON public.products;
DROP POLICY IF EXISTS "anon_insert_products" ON public.products;
DROP POLICY IF EXISTS "anon_update_products" ON public.products;
DROP POLICY IF EXISTS "anon_delete_products" ON public.products;

-- Single policy: authenticated users (logged-in via Supabase Auth) have full access.
-- The anon role has no policies, so unauthenticated requests are blocked entirely.
CREATE POLICY "authenticated_all_products"
  ON public.products
  FOR ALL
  TO authenticated
  USING (true)
  WITH CHECK (true);
