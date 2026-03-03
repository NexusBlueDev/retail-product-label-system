-- Migration: Add user tracking — app_users table + entered_by on products
-- Run in Supabase SQL Editor before pushing the frontend code.

-- 1. app_users table (name + PIN for front-end user gate)
CREATE TABLE IF NOT EXISTS public.app_users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT UNIQUE NOT NULL,
  pin        TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.app_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "owner_all_app_users"
  ON public.app_users FOR ALL TO authenticated
  USING      (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid)
  WITH CHECK (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid);

-- 2. Seed initial users (all PIN 1234)
INSERT INTO public.app_users (name, pin) VALUES
  ('Corrinne', '1234'),
  ('Emily',    '1234'),
  ('Roy',      '1234'),
  ('Bill',     '1234')
ON CONFLICT (name) DO NOTHING;

-- 3. Add entered_by to products (nullable; existing records get NULL)
ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS entered_by TEXT;
