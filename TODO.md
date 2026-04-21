# TODO — Retail Product Label System

> Last updated: 2026-04-20 (Session 3)
> These are actions required from the client or NexusBlue team — NOT Claude tasks.

## Client — Pending Testing
- [ ] **Corrinne** Test Enhanced Processor ls-upsert integration — save a product that already exists in LS (confirm no duplicate created, `action: skipped` in browser console), then save a new product (confirm `action: created` and it appears in LS)
- [ ] **Corrinne** Test Enhanced Processor v2 features — copy buttons, dynamic SKU, category dropdown (24 categories), supplier cross-population (name ↔ code bidirectional)
- [ ] **Corrinne** Continue manual supplier/category edits for ~60 historic styles missing supplier in LS dashboard (new products going forward are correct automatically)
- [ ] **Corrinne** Spot-check `docs/ls_space_sku_review.csv` — 136 sibling-dupe cases remaining after 7 manual resolutions

## Client — LS Manual Fixes Required
- [ ] **Corrinne** Resolve 6 barcode-conflict products in Lightspeed: SE2801, 03-050-0522-1697-AS, HL4227, 100153-234, AR2341-002-M, 230992MUL-L
- [ ] **Corrinne** Fix swapped prices in LS (cross-validation found prices are inverted): **JACKIE SQUARE TOE** ours=$46.97 vs LS=$65.95 and **SILVERSMITH SQUARE TOE** ours=$65.95 vs LS=$46.97 — the two prices are literally exchanged
- [ ] **Corrinne** Review 36 price mismatches — `docs/ls_validation_report.json` has full list. Most are small ($1-2 rounding), but 4 products differ by >$10

## NexusBlue — Next Engineering
- [x] **NexusBlue** lightspeed_index refresh — done 2026-04-20. 75,379 rows loaded. Added family_id, variant_parent_id, supplier_id, brand_id, product_type_id. Script: `docs/ls_index_refresh.py`.
- [x] **NexusBlue** Variant grouping diagnostic — done 2026-04-20. `docs/variant_grouping_diagnostic.csv` (51 styles, 4+ variants each). Top: MB71934005/Cinch×54, MB92834019/Cinch×46.
- [x] **NexusBlue** LS backfill — complete 2026-04-21. 658 processed: 141 created, 355 skipped (ID written back), 156 no-key (no barcode/SKU). 10 errors cleaned up (6 indexing-lag dupes linked; 4 bad-SKU chars sanitized + created). Script: `docs/ls_backfill.py`.
- [x] **NexusBlue** P4 SKU normalization — complete 2026-04-21. 4,096 SKUs generated (collision-safe: 423 duplicate-scan skips, 564 no-style skips). complete: 5,351/6,201 now have SKU. enhanced_complete: 537/674.
- [ ] **NexusBlue** Price sync gap — confirmed: LS personal access token rejects ALL PUT fields (price, active, everything). Investigate OAuth or Retailer API.
- [x] **NexusBlue** Archive `docs/lightspeed_import.py` + `docs/lightspeed_import_v2.py` (contain hardcoded LS token from old pattern) — deleted 2026-04-20. Rotate the LS personal access token in the Lightspeed dashboard.

## Nice to Have
- [ ] **NexusBlue** User PINs stored in plaintext — consider hashing (low priority, internal tool)
- [ ] **NexusBlue** lightspeed_index weekly scheduled refresh (pg_cron)

## Completed
- [x] **NexusBlue** lightspeed_index refresh + cross-validation — 75,379 rows, family/supplier/brand IDs added, validation report generated — done 2026-04-20
- [x] **NexusBlue** ls-upsert Edge Function — lookup-first LS import, duplicate prevention live — done 2026-04-20
- [x] **NexusBlue** Enhanced Processor (v2) deployed — LS lookup, copy buttons, dynamic SKU, category dropdown, supplier fields — done 2026-04-20
- [x] **NexusBlue** Space-SKU remediation — 544 orphan standalones fixed, 60 variant families rebuilt — done 2026-04-17
- [x] **NexusBlue** style_number sanitization at all save paths — done 2026-04-17
- [x] **NexusBlue** Lightspeed X-Series API connected (token vaulted) — done 2026-04-13
- [x] **NexusBlue** Data normalization: 12-rule pipeline, SKU formula, lightspeed_index table (70K rows) — done 2026-04-13
- [x] **NexusBlue** Set up Vercel hosting + custom domain — done 2026-03-03
- [x] **NexusBlue** PWA support (manifest, service worker, icons) — done 2026-03-03
- [x] **NexusBlue** Three-mode workflow (menu, quick capture, desktop processor) — done 2026-03-03
- [x] **NexusBlue** Supabase Storage bucket + image persistence — done 2026-03-03
- [x] **NexusBlue** pg_cron for rate_limits cleanup — done 2026-03-03
