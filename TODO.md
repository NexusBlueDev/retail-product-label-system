# TODO — Retail Product Label System

> Last updated: 2026-03-03
> These are actions required from the client or NexusBlue team — NOT Claude tasks.

## Blocking (nothing blocking — app is operational)

## High Priority (do soon)
- [ ] **NexusBlue** Archive backend repo: `gh repo archive NexusBlueDev/retail-product-label-system-backend --yes`

## Infrastructure & Services
- [ ] **NexusBlue** Verify OPENAI_API_KEY is still valid in Supabase Edge Function secrets
- [ ] **NexusBlue** Consider setting up pg_cron for rate_limits table cleanup (currently lazy cleanup per-request)

## Nice to Have
- [ ] **NexusBlue** Standardize ai-extraction.js to use `state.accessToken` instead of `SUPABASE_KEY` for Edge Function calls
- [ ] **NexusBlue** Remove duplicate prompt (prompt-optimized.txt vs inline in index.ts — keep one, delete the other)
- [ ] **NexusBlue** Extract inline styles from index.html into CSS classes

## Completed
