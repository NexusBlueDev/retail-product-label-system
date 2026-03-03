-- Migration: Create Supabase Storage bucket for product images
-- RLS policy scoped to same UID as products table
-- Applied: 2026-03-03

INSERT INTO storage.buckets (id, name, public)
VALUES ('product-images', 'product-images', false)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated user (UID-scoped) full access to product-images bucket
DO $$ BEGIN
IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE policyname = 'owner_all_product_images'
    AND tablename = 'objects'
    AND schemaname = 'storage'
) THEN
    CREATE POLICY owner_all_product_images
      ON storage.objects FOR ALL TO authenticated
      USING (
        bucket_id = 'product-images'
        AND auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid
      )
      WITH CHECK (
        bucket_id = 'product-images'
        AND auth.uid() = '10cfa0fe-080e-4c8f-94f8-d763f20fb641'::uuid
      );
END IF;
END $$;
