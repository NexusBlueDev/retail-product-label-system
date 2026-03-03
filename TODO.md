# TODO — Retail Product Label System

> Last updated: 2026-03-03
> These are actions required from the client or NexusBlue team — NOT Claude tasks.

## Blocking (nothing blocking — app is operational)

## High Priority (do soon)
- [ ] **Client** Test full workflow: Quick Capture photos on mobile → Process Photos from desktop
- [ ] **Client** Verify images are appearing in Supabase Storage dashboard (product-images bucket)

## Infrastructure & Services

## Nice to Have
- [ ] **NexusBlue** User PINs stored in plaintext — consider hashing (low priority, internal tool)

## Completed
- [x] **NexusBlue** Three-mode workflow (menu, quick capture, desktop processor) — done 2026-03-03
- [x] **NexusBlue** Supabase Storage bucket + image persistence — done 2026-03-03
- [x] **NexusBlue** Archive backend repo — done 2026-03-03
- [x] **NexusBlue** Verify OPENAI_API_KEY is still valid in Supabase Edge Function secrets — done 2026-03-03
- [x] **NexusBlue** Set up pg_cron for rate_limits table cleanup — done 2026-03-03
- [x] **NexusBlue** Standardize ai-extraction.js auth tokens — done 2026-03-03
- [x] **NexusBlue** Remove duplicate prompt and quantity field — done 2026-03-03
- [x] **NexusBlue** Extract inline styles into CSS classes — done 2026-03-03
