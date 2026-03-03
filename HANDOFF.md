# HANDOFF — Retail Product Label System

## Last Updated
2026-03-03 — Vercel hosting + PWA + module documentation

## Project State
Production app (v4.6) with three operational modes, now PWA-enabled and hosted on Vercel. Post-login menu leads to:
1. **Product Scanner** — mobile flow (scan, AI extract, review, save)
2. **Quick Capture** — speed mode: stage photos, save, background AI extracts all fields into ai_cache
3. **Process Photos** — desktop view: queue sidebar, sticky photos, side-by-side AI vs form fields with copy buttons

All images in Supabase Storage (`product-images` bucket). Products have `status` (`photo_only`/`complete`) and `ai_cache` (JSONB, pre-computed AI extraction). PWA installable on mobile home screens.

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
- Nothing currently in progress

## Next Up
1. Verify Vercel deployment at `retail-scanner-nii.nexusblue.ai` (DNS propagation may take a few minutes)
2. Test PWA install on mobile (Add to Home Screen)
3. Test full workflow: Quick Capture on mobile → Process Photos on desktop
4. Consider hashing user PINs (low priority — internal tool, plaintext is accepted)
5. Monitor pg_cron job is running correctly

## Active Stack
- Frontend: HTML5 / CSS3 / ES6 modules (no build tools), 18 modules
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

## How to Resume
> Project: Retail Product Label System (NexusBlue Module — Standalone App)
> Live: https://retail-scanner-nii.nexusblue.ai (Vercel)
> Legacy: https://nexusbluedev.github.io/retail-product-label-system/ (GitHub Pages)
> Repo: https://github.com/NexusBlueDev/retail-product-label-system
> Vercel: https://vercel.com/nexus-blue-dev/retail-product-label-system
> State: v4.6 — three-mode workflow, PWA, Vercel hosted, ai_cache
> Next action: Verify Vercel deployment + test PWA install on mobile
> Start by reading: HANDOFF.md → CLAUDE.md → ARCHITECTURE.md
