-- Add ai_cache column for pre-computed AI extraction results
-- Quick Capture runs full AI extraction in the background after save,
-- storing results here so Desktop Processor can load them instantly.
-- Cleared when product is saved as 'complete'.
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS ai_cache JSONB DEFAULT NULL;
