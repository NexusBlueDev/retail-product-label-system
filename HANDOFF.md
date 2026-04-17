# HANDOFF — Retail Product Label System

## Last Updated
2026-04-17 — Space-SKU remediation: 544 orphan standalones replaced with 60 variant families + 310 standalones

## Project State
Production app (v6.0) with four operational modes + Lightspeed POS integration. Post-login menu leads to:
1. **Product Scanner** — mobile flow (scan, AI extract, review, save)
2. **Quick Capture** — speed mode: stage photos, save, background AI extracts all fields into ai_cache
3. **Process Photos** — desktop view: queue sidebar, sticky photos, side-by-side AI vs form fields with copy buttons
4. **Enhanced Processor** — test mode: same queue but with Lightspeed lookup + expanded normalization + three-source display (AI blue | LS green | form white)

All images in Supabase Storage (`product-images` bucket). Products have `status` (`photo_only`/`complete`/`enhanced_complete`) and `ai_cache` (JSONB, pre-computed AI extraction). PWA installable on mobile home screens.

## Completed
- Per-user login overlay with PIN gate (v3.4) — commit 6ebc952
- Silent Supabase Auth with JWT refresh every 55 min — commit 8da7a2a
- Modular architecture: 13→18 ES6 modules — commit c5bea16 + v4.0 commits
- RLS scoped to single UID across all tables + storage bucket
- DB-backed rate limiting on Edge Function (10 req/min per IP)
- Barcode duplicate pre-check with debounced warning
- Image compression pipeline (WebP + JPEG fallback)
- CSV export with pagination + status/image count columns
- Merged backend repo into frontend monorepo (2026-03-03)
- All standard documentation files in place
- All previous tech debt items resolved
- **v4.0: Three-mode workflow** (2026-03-03):
  - Post-login menu view with navigation system (js/navigation.js)
  - Quick Capture mode (js/storage.js, js/quick-capture.js)
  - Desktop Processor mode (js/desktop-processor.js)
  - DB migrations: `image_urls` JSONB + `status` column + `product-images` storage bucket
  - Scanner now saves images to Supabase Storage on product save
  - Menu badge shows photo-only queue count

## In Progress
- **Enhanced Processor v2 deployed** — copy buttons, dynamic SKU, category dropdown, supplier cross-population, supplier name field. Awaiting Corrinne's testing.

## Next Up
1. **Corrinne spot-checks space-SKU remediation** — verify MSW9165087, MTW1725003, CTK8990004 now show as proper variant families (not standalones)
2. **Metadata follow-up for 60 rebuilt families** — supplier_id + product_type_id could not be set via API (LS v2.1 PUT rejects these fields, v2.0 has no PUT route). Options: (a) manual dashboard edits; (b) investigate alternate LS endpoint or CSV re-import. See `docs/ls_patch_metadata.py` (pre-built, awaits unblocked endpoint)
3. **44 sibling-dupe products couldn't be rebuilt** — see `docs/ls_space_sku_review.csv` (143 sibling-match cases flagged for review; 44 of those collided on POST)
4. **Corrinne tests Enhanced Processor v2** — verify copy buttons, dynamic SKU, category dropdown, supplier cross-population
5. **6 barcode-conflict products** need manual resolution in Lightspeed — see `docs/ls_cleanup_needs_review.csv` (styles: SE2801, 03-050-0522-1697-AS, HL4227, 100153-234, AR2341-002-M, 230992MUL-L)
6. **874 photo-only products** — 746 have AI cache, need Enhanced Processor review. 128 need AI extraction first.
7. **365 needs_review products** — incomplete data, many can be enriched from refreshed LS index
8. Consider hashing user PINs (low priority — internal tool, plaintext is accepted)

## Active Stack
- Frontend: HTML5 / CSS3 / ES6 modules (no build tools), 20 modules
- Backend: Supabase Edge Function (Deno/TypeScript) + PostgreSQL
- Storage: Supabase Storage (`product-images` bucket, private, UID-scoped RLS)
- AI: OpenAI GPT-4o Vision (via Edge Function)
- Barcode: QuaggaJS 2 v1.12.1 (CDN)
- Hosting: Vercel (primary, `retail-scanner-nii.nexusblue.ai`) + GitHub Pages (legacy)
- PWA: manifest.json + sw.js (cache-first app shell, network-only API)
- Supabase project ref: ayfwyvripnetwrkimxka

## Known Issues / Tech Debt
- User PINs stored in plaintext (accepted — internal tool)
- Hardcoded credentials in `js/config.js` in public repo (accepted — see CLAUDE.md Security Model)

## Session Log

### 2026-04-17 — Space-SKU Remediation (Corrinne's 3-style complaint → 544 orphans fixed)

**Trigger:** Corrinne reported MSW9165087, MTW1725003, CTK8990004 appearing as multiple standalone products instead of variant families, with missing Tag/Category/UPC/Supplier.

**Root cause:** Source `style_number` field contained embedded color codes with a space (e.g. "MSW9165087 LIM"). The generated SKU inherited the space. Lightspeed's SKU regex `^[a-zA-Z0-9_/()#\-\|\.]+$` rejected 1,129 SKUs during the Apr 13-14 import. The retry logic stripped the space and re-pushed each variant as a **standalone** (dropping variant-family grouping + most metadata). Scope: 1,129 rejections → 544 distinct products landed as orphan standalones across 383 styles.

**Recovery:**
- v1 attempt halted: `docs/ls_fresh_sku_idx.json` was captured Apr 15 19:08 before Phase 1 cleanup soft-deleted ~5k products, so our manifest UUIDs pointed at already-dead shadow records. DELETE calls were idempotent no-ops; Corrinne's live orphans were untouched.
- v2 successful: Rebuilt fresh sku→uuid mapping via live LS search for all 383 styles (`docs/ls_refresh_manifest_uuids.py`), then re-ran remediation (`docs/ls_space_sku_remediation.py`) with the correct live UUIDs.
- Script patched mid-flight to handle "Product codes must be unique" (strip barcodes and retry) and "Variant definitions do not match" (normalize variant attribute sets across family).

**Final outcome:**
- 544 orphans soft-deleted (all live UUIDs confirmed via search)
- 60 variant families created with brand_id set (vs 0 before)
- 310 standalones rebuilt with brand_id (single-variant fallbacks)
- 44 rebuild failures — 43 sibling-SKU collisions with Corrinne's pre-existing clean products (see `docs/ls_space_sku_review.csv` for the 143 cases to manually spot-check), 1 residual barcode conflict
- Corrinne's 3 flagged styles verified as proper variant families

**Known gap (follow-up):** supplier_id + product_type_id could NOT be set on the 60 new families — LS API update endpoints are locked down (v2.0 /products has no PUT/PATCH route; v2.1 PUT rejects all metadata fields with "Unknown field in payload"). `docs/ls_patch_metadata.py` is ready to run once we identify a working endpoint. Brand_id IS set correctly on all new families.

**Prevention:** Patched `js/sku-generator.js` to sanitize `style_number` in `generateSKU()` — drops anything after the first whitespace and strips characters outside LS's allowed SKU regex. Prevents this specific class of regression for any future Enhanced Processor entries.

**Artifacts:**
- `docs/ls_space_sku_remediation.csv` — 544-row manifest (post-UUID-refresh)
- `docs/ls_space_sku_remediation.v1.csv` — pre-refresh manifest (archived)
- `docs/ls_space_sku_remediation.py` — DELETE+REBUILD script (with barcode + variant-def fallbacks)
- `docs/ls_refresh_manifest_uuids.py` — live-search UUID refresh
- `docs/ls_space_sku_review.csv` — 143 sibling-dupe cases for Corrinne to spot-check
- `docs/ls_patch_metadata.py` — supplier/category patch script (blocked by API; kept for future)
- `docs/ls_space_sku_progress.json` — final progress snapshot
- `docs/ls_space_sku_progress.v1.json` — halted v1 run archive


### 2026-03-03 (Session 4) — Command Center Library Population
- Created `project_library` table in Supabase (portable schema from cross-project template)
- Populated 15 library entries: 9 features, 2 architecture, 2 integrations, 1 infrastructure, 1 tool
- Saved migration to `supabase/migrations/create_project_library.sql`
- Strengthened global CLAUDE.md Session End Protocol step 4 to enforce library updates (create table if missing, all 8 categories documented)

### 2026-03-03 (Session 3) — Vercel + PWA + Module Documentation
- Set up Vercel project (prj_TEL3Y3lwVVdYvUWkBl90Jug61ojk) linked to GitHub repo
- Added custom domain `retail-scanner-nii.nexusblue.ai` (wildcard CNAME on `*.nexusblue.ai`)
- Created PWA: `manifest.json`, `sw.js` (cache-first app shell, network-only Supabase), icons (192, 512, apple-touch)
- Added PWA meta tags to index.html, service worker registration script
- Moved Export CSV button from scanner bottom bar to menu view
- Made processor photos sticky at top when scrolling fields
- Added `ai_cache` JSONB column for pre-computed AI extraction
- Background AI extraction in Quick Capture (full extraction, not just name)
- Delete confirmation modal with Supabase Storage cleanup
- Side-by-side processor field grid (AI extract left, form right, arrow between)
- Created `scripts/deploy.sh` (manual Vercel fallback)
- Updated `.env.local` with Vercel credentials
- Updated ARCHITECTURE.md with module classification, PWA, Vercel, ai_cache
- Documented as NexusBlue Standalone App module

### 2026-03-03 (Session 2) — Three-Mode Workflow Implementation
- **Phase 1: Menu + Navigation Foundation**
  - DB migrations via Management API: `image_urls` JSONB column, `status` TEXT column on products, `product-images` storage bucket with UID-scoped RLS policy
  - Created `js/navigation.js` — view controller with `navigateTo()` + delegated `[data-nav]` click handler
  - Restructured `index.html` into 4 view containers: menuView, scannerView, quickCaptureView, processorView
  - Updated `js/state.js` with 5 new properties, `js/dom.js` with ~30 new element references
  - Added menu cards CSS, view nav CSS, quick capture styles to `styles/components.css`
  - Created `styles/desktop.css` for processor 3-column grid layout
  - Updated `js/app.js` startup flow: post-login → `navigateTo('menu')` instead of showing scanner
- **Phase 2: Quick Capture Mode**
  - Created `js/storage.js` — Supabase Storage REST API (upload, signed URLs, fetch as base64)
  - Created `js/quick-capture.js` — camera/gallery/drag-drop, parallel upload + AI name extraction, session counter, recent captures list
  - Updated scanner save (`js/database.js`) to upload images to Storage on save
  - Updated `js/image-handler.js` to store blobs alongside base64 for Storage upload
  - Updated `js/form-manager.js` to include `status: 'complete'` on scanner saves
  - CSV export now includes Status and Image Count columns
- **Phase 3: Desktop Processor Mode**
  - Created `js/desktop-processor.js` — 3-column workflow with queue sidebar, AI extraction, copy-field buttons, save/skip
  - Queue loads `photo_only` products, fetches signed URLs fresh per selection
  - AI extraction runs on all product images with same merge strategy as scanner
  - Copy All button + individual per-field copy buttons with green flash feedback
  - Save & Complete PATCHes product to `status='complete'`, removes from queue
  - Menu badge shows photo-only queue count, refreshes on capture/process events
- **Phase 4: Documentation**
  - Updated HANDOFF.md, TODO.md, ARCHITECTURE.md to reflect v4.0 architecture

### 2026-03-03 (Session 1) — Repo Merge, Standards Compliance, Tech Debt Cleanup
- Merged `retail-product-label-system-backend` into this repo (Edge Function, 6 migrations, config, concept doc)
- Removed dead files: legacy backup HTML (117KB), duplicate image-compression.js, logo_base64.txt
- Created .gitignore, package.json, .env.local, CLAUDE.md, ARCHITECTURE.md, HANDOFF.md, TODO.md
- Updated README.md for merged monorepo structure
- Verified OPENAI_API_KEY, set up pg_cron, fixed auth tokens, removed duplicates, extracted inline styles

### 2026-04-15 — Enhanced Processor UX Improvements (Corrinne's Feedback)
- **Per-field copy buttons** — `→` buttons between AI→Form and LS→Form columns (5-column grid), delegated click handler with green flash feedback
- **Dynamic SKU regeneration** — form field changes instantly rebuild SKU + all derived fields (supplier code, gender, color code, size value, width/length)
- **Category dropdown** — `<datalist>` with 24 standard Rodeo Shop categories, browser-native autocomplete + free text
- **Supplier/brand cross-population** — brand↔supplier name↔supplier code auto-fill bidirectionally using reference data maps
- **Supplier name field** — new row in 3-source grid (AI derived from brand, LS from catalog, Form editable). DB column `supplier_name TEXT` added. Supplier code now editable for override.
- **New module:** `js/reference-data.js` — 24 categories, 46 supplier code↔name mappings
- **Architect review: PASS** (2026-04-15) — all additive, no Edge Function changes, no RLS changes

### 2026-04-16 — Post-Cleanup Data Quality Improvements
- **Refreshed `lightspeed_index`** — 74,179 rows from post-cleanup catalog (was stale from Apr 14)
- **Normalized 650 missing products** — complete/enhanced_complete products that were never in normalized_products. 551 normalized, 99 to needs_review.
- **Barcode validation** — `checkBarcodeExists` in database.js now validates format (non-numeric, too-short warnings), checks both products table AND lightspeed_index in parallel, shows LS product info on match
- **Duplicate barcode block** — `saveProduct` now prompts confirmation when saving a product with a barcode that already exists in the database
- **Variant consistency check** — `saveProduct` checks siblings by style_number before saving. Warns if siblings have Size/Color but the new product doesn't (prevents LS import failures)
- **Enhanced Processor promoted** — reordered menu: Enhanced Processor now 3rd (before basic Process Photos), labeled "Recommended", photo-only badge moved to it
- **Edge Function color extraction** — added directive to describe product color from image when label doesn't specify (deployed, 35% of products were missing color)
- **Barcode input validation** — debounced check now fires on any input (not just 12-13 digits), catching bad barcodes immediately

### 2026-04-15/16 — Lightspeed Cleanup Execution (4-Phase)
- **Phase 0: Catalog refresh + manifest** — fetched 75,379 products, diffed against pre-import cache (70,093), identified 5,286 orphans via multi-layer safety filters (standalone + no metadata + SKU pattern match). Built re-import plan: 635 new families, 561 add-to-existing, 1,229 standalone.
- **Phase 1: Deleted 5,286 orphaned products** — 100% success, 0 failures. ~96 min runtime at 55 req/min.
- **Phase 2: Re-imported 5,746 products** (3 passes):
  - Pass 1: 448 new variant families created (v2.0 POST with `variant_definitions`), 154 added to existing families (v2.1 POST matching parent attributes), 170 standalone
  - Pass 2 (fix): Corrected attribute ID mismatches (Color/Size/Width UUIDs from `/variant_attributes` endpoint), fetched 561 parent products to match exact attribute structure, created remaining standalone. Resolved 1,329 failures → 0.
  - Pass 3 (final): Converted 1,283 supplier-mismatch products to standalone (v2.1 API doesn't support supplier in POST), resolved single-variant families, duplicate barcodes, duplicate variant defs.
  - **Final: 600 families + 154 added to existing + 2,516 standalone = ~5,270 products imported. 18 residual (12 already-exist + 6 barcode conflicts).**
- **Phase 3: Verification report** — post-cleanup catalog: 74,908 products. 0 remaining orphans. Report saved to `docs/ls_cleanup_report.txt`.
- **Key learnings:**
  - Lightspeed v2.0 POST `variant_options` is READ-ONLY. Use `variant_definitions` with `attribute_id` for family creation.
  - Variant attribute UUIDs from product `variant_options.id` differ from `/variant_attributes` endpoint IDs.
  - v2.1 POST doesn't accept supplier fields — inherits from family, but fails validation if mismatch.
  - Existing families use "Width" (e7261267) not "Shoe Width" (2add3700) — must fetch parent's actual attributes.
  - v2.0 POST response: `{"data": ["uuid1", "uuid2", ...]}` — list of IDs, not full objects.
- **Scripts:** `docs/ls_cleanup_phase0.py`, `phase1.py`, `phase2.py`, `phase2_fix.py`, `phase2_final.py`, `phase3.py`
- **Architect review: ISSUES FOUND → all resolved** (2026-04-15) — 6 issues addressed during execution

### 2026-04-14 — Enhanced Processor + Lightspeed Import Diagnosis
- **Diagnosed Corrinne's Lightspeed import issues** — all 5 concerns validated:
  - ~5,000 products created as standalone (0 as variants), 100% missing brand/supplier/category/tags
  - 3,452 had SKU appended to name (name collision fallback)
  - Existing LS families undamaged (Carter 2.4 = 60 variants, intact)
  - Root cause: v2.0 POST creates standalone; script used `variant_options` (read-only field, ignored)
- **Researched Lightspeed X-Series API** — variant creation model documented:
  - v2.0 POST = new standalone; v2.1 POST = add to existing family; v2.1 PUT = update family+variant
  - Variant attributes (Color, Size, Length, Width) have global UUIDs in LS
  - DELETE /products/{id} = single product removal (no bulk endpoint)
- **Analyzed scanner data quality** from 6,153 products:
  - 40.8% of scanned barcodes already exist in Lightspeed (could have pulled LS data)
  - 93.5% size correction rate, 44% tag correction, 28% name correction needed
  - 101 products had partial/invalid barcodes from AI
- **Built Enhanced Processor** (js/enhanced-processor.js, 430 lines):
  - 4th menu option: same photo_only queue, same AI extraction
  - Lightspeed lookup by barcode → style number (70,096-row lightspeed_index table)
  - Three-source display: AI (blue) | Lightspeed (green) | Editable Form (white)
  - Expanded normalization: size splitting, supplier codes, gender, color codes
  - 8 new DB columns: supplier_code, gender, size_value, width_length, width_length_value, color_code, lightspeed_product_id, data_source
  - Saves as `enhanced_complete` — zero impact on existing flows
- **Documented 4-phase Lightspeed cleanup plan** (Phase 0-3: refresh cache → delete orphans → re-import as variants → verify)

### 2026-04-13/14 — Data Normalization & Lightspeed Import
- **Recovered lost session** — extracted instructions from crashed session JSONL
- **Created `normalized_products` table** in Supabase — 6,129 products from scanner DB
- **Lightspeed API connected** — personal token, 70K+ product catalog cached locally
- **Full normalization pipeline built:**
  - 12 normalization rules reverse-engineered from Corrinne's 1,177 manually normalized products
  - Supplier codes mapped to Lightspeed vendor list (60+ brands)
  - Size parsing (footwear width, jeans length, apparel sizes)
  - Color codes, gender from tags, SKU formula (Corrinne's GENDER-SUPPLIER-STYLE-COLOR-SIZE-WIDTH)
  - Brand misspelling fixes, category standardization, style number digit error detection
  - Variant consistency enforcement, clearance auto-tagging (.00/.97 prices)
  - "..." / non-numeric barcode / no style+barcode → flagged for review
- **Lightspeed import completed:**
  - 4,947 products created via API (initial + retry with SKU format fixes)
  - 421 already existed (matched by SKU)
  - 375 name collisions exported as CSV for LS import → `docs/lightspeed_variants_import.csv`
  - 300 items need manual review → `docs/normalized_needs_review.csv`
- **Enhanced AI extraction deployed:**
  - Rewrote Edge Function prompt with exact brand spellings, standard tags/categories, full color names, no partial data
  - Rewrote SKU generator with Corrinne's formula and Lightspeed vendor codes
  - Added post-processing layer: brand normalization, tag standardization, barcode validation, clearance detection
- **Complete playbook documented:** `docs/DATA_ANALYSIS_INSTRUCTIONS.md` — all phases, rules, lessons learned, rerun instructions

## How to Resume
> Project: Retail Product Label System (NexusBlue Module — Standalone App)
> Live: https://retail-scanner-nii.nexusblue.ai (Vercel)
> Legacy: https://nexusbluedev.github.io/retail-product-label-system/ (GitHub Pages)
> Repo: https://github.com/NexusBlueDev/retail-product-label-system
> Vercel: https://vercel.com/nexus-blue-dev/retail-product-label-system
> State: v6.0 — four-mode workflow, PWA, Lightspeed integration, cleanup complete
> Playbook: docs/DATA_ANALYSIS_INSTRUCTIONS.md
> Cleanup report: docs/ls_cleanup_report.txt
> Next action: Corrinne tests Enhanced Processor v2, resolve 6 barcode conflicts, review 300 needs-review items
> Start by reading: HANDOFF.md → CLAUDE.md → docs/ls_cleanup_report.txt
