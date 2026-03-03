# CLAUDE.md — Retail Product Label System

## Project Type
Website / Standalone (NOT Platform Product)

## What This Is
Mobile-first AI-powered product scanner for retail inventory (Rodeo Shop).
Static HTML5/CSS3/ES6 app hosted on GitHub Pages with Supabase backend.
Staff scan barcodes and photograph product labels; GPT-4o extracts structured data;
products are saved to PostgreSQL and exported as CSV for Lightspeed POS import.

## Tech Stack
- **Frontend:** Pure HTML/CSS/ES6 modules (13 modules, no build tools, no framework)
- **Backend:** Supabase Edge Function (Deno/TypeScript) calling OpenAI GPT-4o Vision
- **Database:** Supabase PostgreSQL with RLS (project ref: `ayfwyvripnetwrkimxka`)
- **Hosting:** GitHub Pages (auto-deploys on push to main)
- **Barcode:** QuaggaJS 2 v1.12.1 (CDN-loaded)

## Static App Exceptions (per global CLAUDE.md)
This is a static HTML5/ES5 PWA hosted on GitHub Pages. Per the global testing and CI standards:
- No CI/CD pipeline (GitHub Pages auto-deploys on push)
- No Vitest tests (static PWA exception)
- No Vercel deployment
- No Next.js patterns, no Tailwind
- No deploy.sh script
- No .docs-verified gate enforcement

## Security Model — ACCEPTED AND DOCUMENTED
`js/config.js` contains hardcoded credentials visible in the public repo:
- `SUPABASE_URL` — public by design
- `SUPABASE_KEY` (anon/publishable key) — public by design
- `AUTH_EMAIL`: `support@nexusblue.io`
- `AUTH_PASSWORD`: `rodeoshop!1`

**Why this is accepted:**
1. Static HTML app — there is no server to hide secrets behind
2. RLS policies scope ALL data access to UID `10cfa0fe-080e-4c8f-94f8-d763f20fb641`
3. This is an internal-use tool (retail staff only)
4. The anon key is designed to be publicly exposed (publishable)
5. The auth password grants access to one Supabase auth account whose data is protected by RLS
6. The `OPENAI_API_KEY` lives in Supabase Edge Function secrets — never in client code

## Auth Architecture
- **Supabase Auth:** Single account (`support@nexusblue.io`) — silent auto-login in `auth.js`
- **Per-person gate:** `app_users` table (name + 4-digit PIN) — identification, not security
- **PINs are not hashed** — accepted for internal tool
- **All DB operations** use the shared auth JWT via `state.accessToken`
- **JWT refreshes** every 55 minutes (tokens expire after 1 hour)
- **Session persistence:** JWT cached in `localStorage('nb_session')`, user name in `localStorage('nb_current_user')`

## Edge Function Deployment
```bash
# Via npm script (uses supabase CLI from devDependencies)
npm run deploy:function

# Or directly
npx supabase functions deploy extract-product --no-verify-jwt --project-ref ayfwyvripnetwrkimxka
```
The `OPENAI_API_KEY` must be set in Supabase secrets:
```bash
npx supabase secrets set OPENAI_API_KEY=sk-...
```

## Database Access (SQL via Management API)
The Droplet cannot connect directly to Supabase PostgreSQL (IPv6-only). All SQL runs via the Supabase Management API using `SUPABASE_ACCESS_TOKEN` from `.env.local`. This runs as the `postgres` superuser (bypasses RLS).

```bash
ACCESS_TOKEN=$(grep '^SUPABASE_ACCESS_TOKEN=' .env.local | cut -d= -f2-)
curl -s -X POST "https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "YOUR SQL HERE"}'
```

Full CRUD verified: SELECT, INSERT, UPDATE, DELETE, DDL (CREATE/ALTER), and pg_cron scheduling all work.

**Tables:** `products` (1,514 rows), `app_users` (6 rows), `rate_limits` (transient)

## Database Migrations
Migrations in `supabase/migrations/` are reference SQL — they have already been applied to the production database. New migrations use the same Management API pattern above.

## Key Files
| File | Purpose |
|------|---------|
| `js/config.js` | Supabase URL, keys, auth credentials |
| `js/app.js` | Entry point, module wiring, startup sequence |
| `js/auth.js` | Silent Supabase Auth login + JWT refresh |
| `js/user-auth.js` | Per-person PIN login overlay |
| `js/ai-extraction.js` | GPT-4o Vision API calls via Edge Function |
| `js/database.js` | Supabase REST API CRUD + CSV export |
| `js/barcode-scanner.js` | QuaggaJS barcode detection |
| `js/form-manager.js` | Form population + SKU auto-generation wiring |
| `js/sku-generator.js` | SKU generation (STYLE-BRAND-COLOR-SIZE, max 15 chars) |
| `supabase/functions/extract-product/index.ts` | Edge Function (384 lines) |
| `supabase/migrations/` | 6 SQL migration files (reference) |
