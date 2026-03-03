-- Migration: Scope products RLS policy to specific authenticated user UID
-- Replaces the overly-permissive USING (true) policy with a uid-specific one.
-- This eliminates the "unrestricted access" Supabase security advisory.
-- Auth user UID: 10cfa0fe-080e-4c8f-94f8-d763f20fb641

DROP POLICY IF EXISTS "authenticated_all_products" ON public.products;

CREATE POLICY "owner_all_products"
  ON public.products
  FOR ALL
  TO authenticated
  USING      (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid)
  WITH CHECK (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid);
