"""
ls_backfill.py — Bulk push enhanced_complete products to Lightspeed via ls-upsert.

For each enhanced_complete product with no lightspeed_product_id:
  - POST to ls-upsert Edge Function (lookup-first: barcode → SKU → create)
  - On success: UPDATE products table with returned lightspeed_product_id
  - Rate: 3.5s between calls (~17 products/min), stays under LS 55 req/min limit

Usage:
    python3 docs/ls_backfill.py [--dry-run] [--limit N]

Flags:
    --dry-run   Fetch products and show what would be pushed; no API calls
    --limit N   Process at most N products (default: all)
"""

import json, os, sys, time, requests
from datetime import datetime, timezone

DOCS         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DOCS)
ENV_FILE     = os.path.join(PROJECT_ROOT, ".env.local")
LOG_FILE     = os.path.join(DOCS, "ls_backfill.log")

SUPABASE_URL  = "https://ayfwyvripnetwrkimxka.supabase.co"
LS_UPSERT_URL = f"{SUPABASE_URL}/functions/v1/ls-upsert"
SUPABASE_API  = f"https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query"

DRY_RUN = "--dry-run" in sys.argv
LIMIT   = None
for i, a in enumerate(sys.argv):
    if a == "--limit" and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

# ── Credentials ───────────────────────────────────────────────────────────────

def load_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
ACCESS_TOKEN = ENV.get("SUPABASE_ACCESS_TOKEN", "")
SUPABASE_KEY = "sb_publishable_54gmrrTrRQFdHNshMr8aMw_CeH9r02k"
AUTH_EMAIL   = "support@nexusblue.io"
AUTH_PASSWORD = "rodeoshop!1"

if not ACCESS_TOKEN:
    print("ERROR: SUPABASE_ACCESS_TOKEN not found in .env.local"); sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── Supabase Management API SQL ───────────────────────────────────────────────

def sql(query):
    """Run SQL via Management API with 429 back-off."""
    for attempt in range(4):
        r = requests.post(
            SUPABASE_API,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={"query": query},
            timeout=60,
        )
        if r.status_code == 429:
            wait = 10 * (attempt + 1)
            log(f"  Management API 429 — sleeping {wait}s")
            time.sleep(wait)
            continue
        if r.status_code not in (200, 201):
            log(f"  SQL error {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    return None

# ── Supabase Auth ─────────────────────────────────────────────────────────────

def get_auth_jwt() -> str:
    """Sign in with email/password and return the session access_token."""
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
        json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD},
        timeout=30,
    )
    if r.status_code == 200:
        return r.json().get("access_token", "")
    log(f"  Auth error {r.status_code}: {r.text[:200]}")
    return ""

# ── LS Upsert ─────────────────────────────────────────────────────────────────

def ls_upsert(product: dict, auth_jwt: str) -> dict | None:
    """Call the ls-upsert Edge Function for a single product."""
    payload = {
        "name":             product.get("name"),
        "sku":              product.get("sku"),
        "barcode":          product.get("barcode"),
        "style_number":     product.get("style_number"),
        "brand_name":       product.get("brand_name"),
        "supplier_name":    product.get("supplier_name"),
        "product_category": product.get("product_category"),
        "retail_price":     float(product["retail_price"]) if product.get("retail_price") else None,
        "supply_price":     float(product["supply_price"]) if product.get("supply_price") else None,
        "description":      product.get("description"),
        "gender":           product.get("gender"),
    }
    try:
        r = requests.post(
            LS_UPSERT_URL,
            headers={
                "apikey":        SUPABASE_KEY,
                "Authorization": f"Bearer {auth_jwt}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
        log(f"  HTTP {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        log(f"  Request error: {e}")
        return None

# ── DB update ─────────────────────────────────────────────────────────────────

def update_ls_id(product_id: int, ls_id: str):
    """Write lightspeed_product_id back to the products table."""
    escaped = ls_id.replace("'", "''")
    sql(f"UPDATE products SET lightspeed_product_id = '{escaped}' WHERE id = {product_id}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log(f"=== ls_backfill.py {'(DRY RUN) ' if DRY_RUN else ''}===")

    # Auth
    if not DRY_RUN:
        log("Authenticating...")
        auth_jwt = get_auth_jwt()
        if not auth_jwt:
            log("ERROR: Could not get auth JWT — aborting")
            sys.exit(1)
        log("  Auth OK.")
    else:
        auth_jwt = ""

    # Fetch all enhanced_complete products with no LS ID
    log("Fetching products to backfill...")
    result = sql("""
        SELECT id, name, sku, barcode, style_number, brand_name, supplier_name,
               product_category, retail_price, supply_price, description, gender
        FROM products
        WHERE status = 'enhanced_complete'
          AND (lightspeed_product_id IS NULL
               OR lightspeed_product_id = '0'
               OR lightspeed_product_id = '')
        ORDER BY id
    """)

    if not result:
        log("ERROR: Could not fetch products"); sys.exit(1)

    products = result
    if LIMIT:
        products = products[:LIMIT]

    has_barcode = sum(1 for p in products if p.get("barcode"))
    has_sku     = sum(1 for p in products if p.get("sku") and not p.get("barcode"))
    no_key      = sum(1 for p in products if not p.get("barcode") and not p.get("sku"))
    log(f"Found {len(products)} products to push (barcode={has_barcode}, sku-only={has_sku}, no-key={no_key})")

    if DRY_RUN:
        log("DRY RUN — showing first 10:")
        for p in products[:10]:
            log(f"  [{p['id']}] {p['name']} | barcode={p['barcode']} | sku={p['sku']}")
        log("=== Done (dry run) ===")
        return

    # Push each product
    counts = {"created": 0, "updated": 0, "skipped": 0, "error": 0, "no_key": 0}
    for i, product in enumerate(products, 1):
        name = product.get("name", "?")[:50]

        # Skip products with no lookup key — ls-upsert can't match or create them properly
        if not product.get("barcode") and not product.get("sku"):
            log(f"  [{i}/{len(products)}] SKIP (no barcode/sku): {name}")
            counts["no_key"] += 1
            continue

        result = ls_upsert(product, auth_jwt)

        if not result:
            log(f"  [{i}/{len(products)}] ERROR: {name}")
            counts["error"] += 1
        else:
            action    = result.get("action", "error")
            ls_id     = result.get("lightspeed_id")
            msg       = result.get("message", "")[:80]
            log(f"  [{i}/{len(products)}] {action.upper()}: {name} | ls_id={ls_id} | {msg}")
            counts[action] = counts.get(action, 0) + 1

            if ls_id and action != "error":
                update_ls_id(product["id"], ls_id)

        # Rate limiting: 3.5s between calls = ~17 products/min, well under LS 55 req/min
        if i < len(products):
            time.sleep(3.5)

        # Progress summary every 25 products
        if i % 25 == 0:
            log(f"  Progress: {i}/{len(products)} — {counts}")

    log(f"\n=== BACKFILL COMPLETE ===")
    log(f"  Created:  {counts['created']}")
    log(f"  Updated:  {counts.get('updated', 0)}")
    log(f"  Skipped:  {counts['skipped']} (already in LS, ID written back)")
    log(f"  No key:   {counts['no_key']} (no barcode or SKU — cannot match)")
    log(f"  Errors:   {counts['error']}")
    log(f"  Total:    {len(products)}")

if __name__ == "__main__":
    main()
