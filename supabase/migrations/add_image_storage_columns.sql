-- Migration: Add image storage columns to products table
-- Supports Quick Capture (photo_only) and Desktop Processing (complete) workflows
-- Applied: 2026-03-03

-- 1. Add image_urls column (JSONB array of Supabase Storage paths)
ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS image_urls JSONB DEFAULT '[]'::jsonb;

-- 2. Add status column to distinguish photo-only captures from complete records
ALTER TABLE public.products
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'complete'
  CHECK (status IN ('photo_only', 'complete'));

-- 3. Backfill existing records as 'complete'
UPDATE public.products SET status = 'complete' WHERE status IS NULL;

-- 4. Partial index for fast photo_only queue queries
CREATE INDEX IF NOT EXISTS idx_products_status ON public.products (status)
  WHERE status = 'photo_only';
