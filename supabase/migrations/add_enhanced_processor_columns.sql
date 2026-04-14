-- Enhanced Processor: new columns on products + lightspeed_index table
-- Applied: 2026-04-14 via Management API

-- 1. New columns on products for enhanced processor output
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS supplier_code TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS size_value TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS width_length TEXT;         -- "Width" or "Length"
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS width_length_value TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS color_code TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS lightspeed_product_id TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS data_source JSONB;         -- tracks field provenance

-- 2. Update status CHECK to allow 'enhanced_complete'
ALTER TABLE public.products DROP CONSTRAINT products_status_check;
ALTER TABLE public.products ADD CONSTRAINT products_status_check
  CHECK (status IN ('photo_only', 'complete', 'enhanced_complete'));

-- 3. Lightspeed index table for barcode/style lookups from the browser
CREATE TABLE IF NOT EXISTS public.lightspeed_index (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lightspeed_id TEXT NOT NULL,
  barcode TEXT,
  sku TEXT,
  name TEXT,
  variant_name TEXT,
  brand TEXT,
  supplier TEXT,
  category TEXT,
  supply_price NUMERIC,
  retail_price NUMERIC,
  variant_options JSONB,
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ls_index_barcode ON public.lightspeed_index (barcode) WHERE barcode IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ls_index_sku ON public.lightspeed_index (sku) WHERE sku IS NOT NULL;

-- 4. RLS (same UID-scoped pattern as products)
ALTER TABLE public.lightspeed_index ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'lightspeed_index' AND policyname = 'owner_all_lightspeed_index') THEN
    CREATE POLICY owner_all_lightspeed_index ON public.lightspeed_index
      FOR ALL TO authenticated
      USING (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid)
      WITH CHECK (auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid);
  END IF;
END $$;
