-- Add supplier_name column to products table
-- Applied: 2026-04-15 via Management API

ALTER TABLE public.products ADD COLUMN IF NOT EXISTS supplier_name TEXT;
