# TODO — Retail Product Label System

> Last updated: 2026-04-13
> These are actions required from the client or NexusBlue team — NOT Claude tasks.

## Blocking
- [ ] **NexusBlue** Analyze `docs/For Import products-2026-04-03.xlsx` — study Corrinne's normalization patterns on "Working Copy" tab
- [ ] **NexusBlue** Create new database table with all datafields from the spreadsheet
- [ ] **NexusBlue** Normalize raw data following Corrinne's patterns (see `docs/DATA_ANALYSIS_INSTRUCTIONS.md`)
- [ ] **Client** Review normalized data before any Lightspeed push

## High Priority (do soon)
- [ ] **NexusBlue** Build SKUs using formula: `CONCAT(Y, "-", J, "-", E, "-", V, "-", Q)` after normalization
- [ ] **NexusBlue** Match style numbers against Lightspeed catalog (70,091 products) — apply pricing/data rules
- [ ] **NexusBlue** Push approved normalized data to Lightspeed via API (after client review)
- [ ] **Client** Test full workflow: Quick Capture photos on mobile → Process Photos from desktop
- [ ] **Client** Verify images are appearing in Supabase Storage dashboard (product-images bucket)
- [ ] **Client** Verify Vercel deployment at `retail-scanner-nii.nexusblue.ai`
- [ ] **Client** Test PWA install on mobile (Add to Home Screen)

## Infrastructure & Services
- [ ] **NexusBlue** Lightspeed X-Series API connected and verified (token vaulted in Setup Copilot)

## Nice to Have
- [ ] **NexusBlue** User PINs stored in plaintext — consider hashing (low priority, internal tool)

## Completed
- [x] **NexusBlue** Set up Vercel hosting + custom domain — done 2026-03-03
- [x] **NexusBlue** PWA support (manifest, service worker, icons) — done 2026-03-03
- [x] **NexusBlue** Command Center registration + project library populated — done 2026-03-03
- [x] **NexusBlue** Three-mode workflow (menu, quick capture, desktop processor) — done 2026-03-03
- [x] **NexusBlue** Supabase Storage bucket + image persistence — done 2026-03-03
- [x] **NexusBlue** Archive backend repo — done 2026-03-03
- [x] **NexusBlue** Verify OPENAI_API_KEY is still valid in Supabase Edge Function secrets — done 2026-03-03
- [x] **NexusBlue** Set up pg_cron for rate_limits table cleanup — done 2026-03-03
- [x] **NexusBlue** Standardize ai-extraction.js auth tokens — done 2026-03-03
- [x] **NexusBlue** Remove duplicate prompt and quantity field — done 2026-03-03
- [x] **NexusBlue** Extract inline styles into CSS classes — done 2026-03-03
