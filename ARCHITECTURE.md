# ARCHITECTURE — Retail Product Label System

## System Overview

```
Mobile Browser → GitHub Pages (static HTML/ES6)
    ├── Supabase REST API (products, app_users tables)
    │   └── PostgreSQL with RLS (scoped to UID 10cfa0fe-...)
    └── Supabase Edge Function (extract-product)
        └── OpenAI GPT-4o Vision API
```

All code runs client-side in the browser. No server-side rendering, no build tools, no bundler. The only server-side component is the Supabase Edge Function that proxies calls to OpenAI.

## Frontend Architecture

13 ES6 native modules loaded via `<script type="module" src="js/app.js">` from `index.html`.

### Module Layers

| Layer | Modules | Responsibility |
|-------|---------|----------------|
| **Foundation** | config.js, state.js, events.js, dom.js | Config constants, shared state object, event bus, DOM element cache |
| **Auth** | auth.js, user-auth.js | Silent Supabase JWT login + per-person PIN gate overlay |
| **Features** | barcode-scanner.js, image-handler.js, image-compression.js, ai-extraction.js | Camera/barcode scanning, image capture/compression, AI extraction |
| **Data** | form-manager.js, sku-generator.js, database.js | Form I/O, SKU generation logic, Supabase REST CRUD + CSV export |
| **UI** | ui-utils.js | Status messages, modal helpers |
| **Entry** | app.js | Init sequence, event wiring, orchestration |

### Startup Sequence
1. `ensureAuthenticated()` — get Supabase JWT (or refresh from localStorage)
2. `getCurrentUser()` — check localStorage for saved front-end user
3. If no saved user → `showUserLoginOverlay()` (blocks until PIN validated)
4. `initApp()` — wire DOM events, load product count, start 55-min JWT refresh interval

### Cross-Module Communication
- **state.js** — single mutable state object shared by all modules
- **events.js** — simple pub/sub event bus (`barcode:scanned`, `images:selected`, `extraction:complete`, `product:saved`)
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

### Database Tables

| Table | Purpose | RLS Policy |
|-------|---------|------------|
| `products` | Product records (19 fields) | Owner-scoped: `auth.uid() = 10cfa0fe-...` |
| `app_users` | Front-end user names + PINs | Owner-scoped: `auth.uid() = 10cfa0fe-...` |
| `rate_limits` | Edge Function per-IP rate limiting | Deny anon; service_role bypasses |

### Products Schema
```
id, created_at, updated_at, name (required), style_number, sku (unique),
barcode (unique), brand_name, product_category, retail_price, supply_price,
size_or_dimensions, color, quantity (default 1), tags, description, notes,
verified, entered_by
```

### RLS Evolution
The migrations tell the security hardening story:
1. `enable_rls.sql` — Initial RLS with permissive anon policies
2. `rls_products_authenticated.sql` — Replaced anon with authenticated-only
3. `rls_products_scoped_to_uid.sql` — Scoped to specific UID (current state)
4. `rls_rate_limits_deny_anon.sql` — Explicit deny for anon on rate_limits
5. `add_user_tracking.sql` — app_users table + entered_by column on products

## Data Flow: Product Scan

```
1. User takes photo(s) → camera/gallery file input
2. image-compression.js → WebP blob (max 1920px, 0.85 quality, JPEG fallback)
3. ai-extraction.js → parallel POST to Edge Function (one per image)
4. Edge Function → validate image → check rate limit → call GPT-4o Vision
5. GPT-4o returns structured JSON → Edge Function validates barcode → returns to client
6. Client merges multi-image results (Image 1 = primary, Image 2+ = price override only)
7. form-manager.js → populate form fields → auto-generate SKU
8. User reviews/edits → clicks Save
9. database.js → POST /rest/v1/products (with Bearer JWT)
10. Supabase RLS check → INSERT → return saved row
11. Success modal → "Scan Next" or "Edit Product"
```

### Multi-Image Merge Strategy
- Image 1 (vendor label): primary source for ALL fields
- Image 2+ (handwritten notes): only overrides `retail_price`, appends to `notes`
- Scanned barcodes (`data-source="scanned"`) are never overwritten by AI extraction

## Integrations

| Service | Purpose | Classification |
|---------|---------|----------------|
| OpenAI GPT-4o | Product data extraction from images | Integration (via Edge Function) |
| Supabase Auth | Single-account silent authentication | Infrastructure |
| Supabase PostgreSQL | Product and user data storage | Infrastructure |
| QuaggaJS 2 | Browser-based barcode scanning | Library (CDN) |
| GitHub Pages | Static hosting | Infrastructure |

## Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Static app with hardcoded credentials | RLS scopes all data to one UID; internal tool; no server to hide secrets (see CLAUDE.md) |
| Single Supabase auth account for all users | Per-person PIN is identification, not authentication; simplifies auth for internal tool |
| No build tools | ES6 modules natively supported in all target browsers; trivial deploy (push = live) |
| Edge Function for AI, REST API for CRUD | Edge Function handles expensive OpenAI call with rate limiting and retry; CRUD uses Supabase's auto-generated REST |
| 15-char SKU limit | Matches Lightspeed POS field constraint |
| WebP compression with JPEG fallback | ~60% image size reduction; Safari fallback for older iOS |

## Known Tech Debt

- User PINs stored in plaintext (accepted — internal tool, identification not security)
