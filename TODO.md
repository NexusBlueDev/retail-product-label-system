# TODO — Retail Product Label System

> Last updated: 2026-03-03
> These are actions required from the client or NexusBlue team — NOT Claude tasks.

## Blocking (nothing blocking — app is operational)

## High Priority (do soon)

## Infrastructure & Services

## Nice to Have
- [ ] **NexusBlue** User PINs stored in plaintext — consider hashing (low priority, internal tool)

## Completed
- [x] **NexusBlue** Archive backend repo — done 2026-03-03
- [x] **NexusBlue** Verify OPENAI_API_KEY is still valid in Supabase Edge Function secrets — done 2026-03-03 (tested with live request)
- [x] **NexusBlue** Set up pg_cron for rate_limits table cleanup (every 5 min, deletes records > 10 min old) — done 2026-03-03
- [x] **NexusBlue** Standardize ai-extraction.js to use `state.accessToken` instead of `SUPABASE_KEY` — done 2026-03-03
- [x] **NexusBlue** Remove duplicate prompt (deleted prompt-optimized.txt, kept inline in index.ts) — done 2026-03-03
- [x] **NexusBlue** Remove duplicate quantity field (id="qty" was orphaned) — done 2026-03-03
- [x] **NexusBlue** Extract inline styles from index.html into CSS classes — done 2026-03-03
