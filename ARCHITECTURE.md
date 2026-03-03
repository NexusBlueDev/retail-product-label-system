# ARCHITECTURE — Retail Product Label System

## System Overview

**Project Type:** Website / Standalone
**NexusBlue Module Classification:** Standalone App (internal tool for NII retail)
**Component Type:** Module — self-contained feature domain with DB tables, UI views, AI integration

```
Mobile/Desktop Browser → Vercel (static HTML/ES6) + GitHub Pages (legacy)
    │                     Domain: retail-scanner-nii.nexusblue.ai
    ├── Supabase REST API (products, app_users tables)
    │   └── PostgreSQL with RLS (scoped to UID 10cfa0fe-...)
    ├── Supabase Storage (product-images bucket, UID-scoped RLS)
    └── Supabase Edge Function (extract-product)
        └── OpenAI GPT-4o Vision API
```

All code runs client-side in the browser. No server-side rendering, no build tools, no bundler. The only server-side component is the Supabase Edge Function that proxies calls to OpenAI.

PWA-enabled: installable on mobile home screens, offline app shell caching, full-screen standalone mode.

## Three-Mode Workflow

```
Login → PIN → Menu
  ├── Product Scanner  → Camera/Gallery → AI Extract All → Review Form → Save (status='complete')
  ├── Quick Capture    → Camera/Gallery/Drag → Upload Storage → AI Extract Name → Save (status='photo_only')
  └── Process Photos   → Queue → Load Photos → AI Extract All → Copy to Form → Save (status='complete')
```

## Frontend Architecture

18 ES6 native modules loaded via `<script type="module" src="js/app.js">` from `index.html`.

### Module Layers

| Layer | Modules | Responsibility |
|-------|---------|----------------|
| **Foundation** | config.js, state.js, events.js, dom.js | Config constants, shared state object, event bus, DOM element cache |
| **Auth** | auth.js, user-auth.js | Silent Supabase JWT login + per-person PIN gate overlay |
| **Navigation** | navigation.js | View controller — shows/hides 4 top-level views (menu, scanner, quickCapture, processor) |
| **Features** | barcode-scanner.js, image-handler.js, image-compression.js, ai-extraction.js | Camera/barcode scanning, image capture/compression, AI extraction |
| **Storage** | storage.js | Supabase Storage REST API — upload, signed URLs, fetch as base64 |
| **Capture** | quick-capture.js | Quick Capture mode — parallel upload + name extraction, session counter |
| **Processor** | desktop-processor.js | Desktop 3-column processor — queue, AI panel, copy-field form |
| **Data** | form-manager.js, sku-generator.js, database.js | Form I/O, SKU generation logic, Supabase REST CRUD + CSV export |
| **UI** | ui-utils.js | Status messages, modal helpers |
| **Entry** | app.js | Init sequence, event wiring, orchestration, menu badge updates |

### View Navigation

Four top-level views, controlled by `navigation.js`:
- **menuView** — Post-login landing with three cards (Product Scanner, Quick Capture, Process Photos)
- **scannerView** — Original product scanner (wraps all existing scanner UI + fixed bottom bar)
- **quickCaptureView** — Speed capture with camera/gallery/drag-drop, session counter, recent captures
- **processorView** — 2-column desktop layout (240px queue | 1fr main with sticky photos + side-by-side field grid)

Navigation uses `display:none/block` toggling. The fixed bottom bar (Save/Export/Rescan) only shows on scanner view. Body padding class (`no-bottom-bar`) toggles accordingly.

### Startup Sequence
1. `ensureAuthenticated()` — get Supabase JWT (or refresh from localStorage)
2. `getCurrentUser()` — check localStorage for saved front-end user
3. If no saved user → `showUserLoginOverlay()` (blocks until PIN validated)
4. `initApp()` — wire DOM events, init navigation, init Quick Capture, init Desktop Processor
5. `navigateTo('menu')` — show menu as first view
6. `updateMenuBadge()` — fetch photo-only count for Process Photos badge

### Cross-Module Communication
- **state.js** — single mutable state object shared by all modules (17 properties)
- **events.js** — pub/sub event bus: `barcode:scanned`, `images:selected`, `extraction:complete`, `product:saved`, `view:changed`, `capture:saved`, `processor:saved`
- No framework, no reactive bindings — modules import what they need directly

## Backend Architecture

### Edge Function: extract-product
- **Runtime:** Deno (Supabase Edge Functions)
- **Entry:** `supabase/functions/extract-product/index.ts` (384 lines)
- **Model:** GPT-4o (temperature 0.1, max_tokens 800)
- **Rate limiting:** DB-backed via `rate_limits` table, 10 req/min per IP, lazy purge of old records
- **Image validation:** Format check (png/jpeg/jpg/webp), size cap (20MB base64), base64 encoding check
- **Barcode validation:** Post-extraction cleanup — must be exactly 12 or 13 digits
- **Retry:** Exponential backoff (1s, 2s), 2 max retries, 30s timeout per OpenAI call
- **Logging:** Structured JSON (timestamp, duration, fields extracted, barcode presence, token usage)

### Supabase Storage: product-images
- **Bucket:** `product-images` (private, not public)
- **RLS:** UID-scoped — same `auth.uid() = 10cfa0fe-...` pattern as products table
- **Path convention:** `products/{productId}/{index}.webp`
- **Access:** Signed URLs (1-hour expiry), fetched fresh per queue item selection

### Database Tables

| Table | Purpose | RLS Policy |
|-------|---------|------------|
| `products` | Product records (22 fields incl. ai_cache) | Owner-scoped: `auth.uid() = 10cfa0fe-...` |
| `app_users` | Front-end user names + PINs | Owner-scoped: `auth.uid() = 10cfa0fe-...` |
| `rate_limits` | Edge Function per-IP rate limiting | Deny anon; service_role bypasses |

### Products Schema
```
id (UUID), created_at, updated_at, name (required), style_number, sku (unique),
barcode (unique), brand_name, product_category, retail_price, supply_price,
size_or_dimensions, color, quantity (default 1), tags, description, notes,
verified, entered_by, image_urls (JSONB, default []), status (TEXT, 'photo_only'|'complete'),
ai_cache (JSONB, default null — pre-computed AI extraction, cleared on Save & Complete)
```

### RLS Evolution
The migrations tell the security hardening story:
1. `enable_rls.sql` — Initial RLS with permissive anon policies
2. `rls_products_authenticated.sql` — Replaced anon with authenticated-only
3. `rls_products_scoped_to_uid.sql` — Scoped to specific UID (current state)
4. `rls_rate_limits_deny_anon.sql` — Explicit deny for anon on rate_limits
5. `add_user_tracking.sql` — app_users table + entered_by column on products
6. `add_image_storage_columns.sql` — image_urls JSONB + status column + partial index
7. `create_storage_bucket.sql` — product-images bucket + owner RLS policy

## Data Flow: Product Scanner (Mode 1)

```
1. User takes photo(s) → camera/gallery file input
2. image-compression.js → WebP blob (max 1920px, 0.85 quality, JPEG fallback)
3. ai-extraction.js → parallel POST to Edge Function (one per image)
4. Edge Function → validate → rate limit → GPT-4o Vision
5. Client merges multi-image results → populate form → auto-generate SKU
6. User reviews/edits → clicks Save
7. database.js → upload blobs to Storage → POST /rest/v1/products (with image_urls + status='complete')
8. Success modal → "Scan Next" or "Edit Product"
```

## Data Flow: Quick Capture (Mode 2)

```
1. User stages photo(s) via camera/gallery/drag → WebP blobs in stagedBlobs[]
2. User clicks "Save Product" → generate UUID → upload all blobs to Storage
3. POST /rest/v1/products → { name: 'Processing...', image_urls, status: 'photo_only', entered_by }
4. Session counter increments → recent captures list updates → ready for next
5. BACKGROUND (fire-and-forget): full AI extraction on ALL photos
   → merge results → PATCH ai_cache + name on product record
   → update recent captures list with extracted name
```

## Data Flow: Desktop Processor (Mode 3)

```
1. View entered → GET products?status=eq.photo_only (incl. ai_cache) → render queue sidebar
2. User clicks queue item → getSignedUrls() → display photos (sticky at top)
3. If ai_cache exists → instant populate AI fields (no network call)
   Else → fetchImageAsBase64() for each → POST to Edge Function → merge results
4. AI results displayed as read-only side-by-side with editable form fields
5. User clicks → buttons to copy individual fields (or Copy All)
6. User edits/verifies → clicks Save & Complete
7. PATCH /rest/v1/products?id=eq.{id} → { ...formData, status: 'complete', ai_cache: null }
8. Removed from queue → next item selected
9. Delete: confirm modal → DELETE DB record → DELETE storage images → update queue
```

### Multi-Image Merge Strategy
- Image 1 (vendor label): primary source for ALL fields
- Image 2+ (handwritten notes): only overrides `retail_price`, appends to `notes`
- Scanned barcodes (`data-source="scanned"`) are never overwritten by AI extraction

## CSS Architecture

| Stylesheet | Purpose |
|-----------|---------|
| `styles/main.css` | Base reset, body layout, container, typography |
| `styles/components.css` | Forms, buttons, camera, status, modals, menu cards, quick capture, view nav |
| `styles/modals.css` | Success and duplicate warning modals |
| `styles/desktop.css` | Processor 2-column grid, queue sidebar, sticky photos, side-by-side field grid, responsive stacking |

## Integrations

| Service | Purpose | Classification |
|---------|---------|----------------|
| OpenAI GPT-4o | Product data extraction from images | Integration (via Edge Function) |
| Supabase Auth | Single-account silent authentication | Infrastructure |
| Supabase PostgreSQL | Product and user data storage | Infrastructure |
| Supabase Storage | Product image persistence | Infrastructure |
| QuaggaJS 2 | Browser-based barcode scanning | Library (CDN) |
| Vercel | Primary static hosting (auto-deploy from GitHub) | Infrastructure |
| GitHub Pages | Legacy static hosting (still active) | Infrastructure |

## Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Static app with hardcoded credentials | RLS scopes all data to one UID; internal tool; no server to hide secrets |
| Single Supabase auth account for all users | Per-person PIN is identification, not authentication; simplifies auth |
| No build tools | ES6 modules natively supported in all target browsers; trivial deploy |
| Edge Function for AI, REST API for CRUD | Edge Function handles expensive OpenAI call with rate limiting and retry |
| 15-char SKU limit | Matches Lightspeed POS field constraint |
| WebP compression with JPEG fallback | ~60% image size reduction; Safari fallback for older iOS |
| Supabase Storage over base64 in DB | Scalable image persistence; private bucket with signed URLs |
| Client-side UUID for product ID | Storage path known before DB insert; enables parallel upload + name extraction |
| `p_` prefix on processor form IDs | Avoids DOM ID collisions with scanner form (same field names) |
| CSS Grid for processor layout | Native 2-column responsive layout; stacks vertically below 1024px |
| ai_cache JSONB column | Pre-compute AI during Quick Capture, instant load in Processor, clear on save |
| PWA with service worker | Installable on mobile, offline app shell, full-screen standalone mode |
| Vercel + custom domain | Auto-deploy from GitHub, `retail-scanner-nii.nexusblue.ai` |

## PWA Configuration

| File | Purpose |
|------|---------|
| `manifest.json` | App name, icons, theme color, standalone display mode |
| `sw.js` | Service worker — cache-first for app shell, network-only for Supabase API |
| `icons/icon-192.png` | Home screen icon (192x192) |
| `icons/icon-512.png` | Splash screen icon (512x512) |
| `icons/apple-touch-icon.png` | iOS home screen icon (180x180) |

**Cache strategy:** App shell (HTML, CSS, JS, icons) is pre-cached on install and served cache-first with stale-while-revalidate. All Supabase API/auth/storage calls are network-only (never cached). Cache name includes version for clean upgrades.

## Hosting & Deployment

| Target | Domain | Method |
|--------|--------|--------|
| **Vercel (primary)** | `retail-scanner-nii.nexusblue.ai` | Auto-deploy on push to `main` |
| **GitHub Pages (legacy)** | `nexusbluedev.github.io/retail-product-label-system` | Auto-deploy on push to `main` |

Both remain active during transition. Staff can use either URL — they hit the same code.

## Known Tech Debt

- User PINs stored in plaintext (accepted — internal tool, identification not security)
