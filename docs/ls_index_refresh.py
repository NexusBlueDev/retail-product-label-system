"""
ls_index_refresh.py — Rebuild lightspeed_index from live LS catalog.

1. Fetches all active + deleted products from LS API (version-based pagination)
2. Adds family_id + variant_parent_id columns if missing
3. Truncates and reloads lightspeed_index via Supabase Management API
4. Cross-validates against our products table: reports mismatches in price,
   supplier, and missing LS links (products in our DB not yet in LS)

Usage:
    python3 docs/ls_index_refresh.py [--validate-only] [--dry-run]

Flags:
    --validate-only  Skip the index reload; just run cross-validation report
    --dry-run        Fetch from LS and report, but do not write to Supabase
"""

import json, os, sys, time, subprocess, requests
from datetime import datetime, timezone

DOCS        = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DOCS)
ENV_FILE    = os.path.join(PROJECT_ROOT, ".env.local")
CACHE_FILE  = os.path.join(DOCS, "ls_index_refresh_cache.json")
LOG_FILE    = os.path.join(DOCS, "ls_index_refresh.log")

LS_BASE     = "https://therodeoshop.retail.lightspeed.app/api/2.0"
SUPABASE_API = "https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query"
SUPABASE_REST = "https://ayfwyvripnetwrkimxka.supabase.co/rest/v1"

DRY_RUN       = "--dry-run" in sys.argv
VALIDATE_ONLY = "--validate-only" in sys.argv

# ── Credentials ──────────────────────────────────────────────────────────────

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
LS_TOKEN       = ENV.get("LIGHTSPEED_TOKEN", "")
ACCESS_TOKEN   = ENV.get("SUPABASE_ACCESS_TOKEN", "")
SUPABASE_KEY   = "sb_publishable_54gmrrTrRQFdHNshMr8aMw_CeH9r02k"

if not LS_TOKEN:
    print("ERROR: LIGHTSPEED_TOKEN not found in .env.local"); sys.exit(1)
if not ACCESS_TOKEN:
    print("ERROR: SUPABASE_ACCESS_TOKEN not found in .env.local"); sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def ls_get(path, params=None):
    """GET from LS API with 429 back-off."""
    url = f"{LS_BASE}/{path}"
    headers = {"Authorization": f"Bearer {LS_TOKEN}", "Accept": "application/json"}
    for attempt in range(3):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 429:
            log(f"  429 rate limit — sleeping 20s"); time.sleep(20); continue
        if r.status_code != 200:
            log(f"  LS GET {path} → {r.status_code}"); return [], None
        body = r.json()
        data = body.get("data", [])
        # version_info for cursor pagination
        version_info = body.get("version", None)
        return data, version_info
    return [], None

def sql(query):
    """Run a SQL query via Supabase Management API with 429 back-off."""
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
    log("  SQL error: 429 after 4 retries")
    return None

def pg_val(v):
    """Serialize a Python value to a safe SQL literal."""
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"
    # String — escape single quotes
    return "'" + str(v).replace("'", "''") + "'"

COLS = [
    'lightspeed_id', 'barcode', 'sku', 'name', 'variant_name',
    'brand', 'brand_id', 'supplier', 'supplier_id', 'category',
    'product_type_id', 'supply_price', 'retail_price', 'variant_options',
    'family_id', 'variant_parent_id', 'active', 'refreshed_at',
]

def supabase_insert_batch(rows):
    """Batch upsert into lightspeed_index via Management API SQL."""
    if not rows:
        return True
    values_parts = []
    for row in rows:
        vals = ', '.join(pg_val(row.get(c)) for c in COLS)
        values_parts.append(f'({vals})')
    update_set = ', '.join(
        f'{c} = EXCLUDED.{c}' for c in COLS if c != 'lightspeed_id'
    )
    query = (
        f"INSERT INTO lightspeed_index ({', '.join(COLS)}) VALUES "
        + ', '.join(values_parts)
    )
    return sql(query) is not None

# ── Schema migration ──────────────────────────────────────────────────────────

def ensure_columns():
    log("Checking lightspeed_index schema for new columns...")
    result = sql("""
        ALTER TABLE lightspeed_index
            ADD COLUMN IF NOT EXISTS family_id TEXT,
            ADD COLUMN IF NOT EXISTS variant_parent_id TEXT,
            ADD COLUMN IF NOT EXISTS supplier_id TEXT,
            ADD COLUMN IF NOT EXISTS brand_id TEXT,
            ADD COLUMN IF NOT EXISTS product_type_id TEXT,
            ADD COLUMN IF NOT EXISTS refreshed_at TIMESTAMPTZ DEFAULT now()
    """)
    if result is not None:
        log("  Schema OK — new columns added/verified.")
    else:
        log("  WARNING: Schema migration may have failed — check manually.")

# ── Fetch from LS ─────────────────────────────────────────────────────────────

def fetch_all_products():
    """Fetch all products from LS using version-based cursor pagination."""
    if os.path.exists(CACHE_FILE) and not DRY_RUN:
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < 3600:
            log(f"Using cached LS catalog ({age/60:.0f}min old) — delete {CACHE_FILE} to force refresh")
            with open(CACHE_FILE) as f:
                return json.load(f)

    log("Fetching all products from Lightspeed (version-based pagination)...")
    all_products = []
    after = 0
    page = 0
    page_size = 250

    while True:
        page += 1
        params = {"page_size": str(page_size)}
        if after > 0:
            params["after"] = str(after)

        if page % 10 == 1:
            log(f"  Page {page} (after={after}, total so far: {len(all_products)})")

        data, version_info = ls_get("products", params)

        if not data:
            break

        all_products.extend(data)
        time.sleep(1.1)  # stay under 55 req/min

        # Advance cursor via max version
        if isinstance(version_info, dict) and "max" in version_info:
            after = version_info["max"]
        elif data:
            after = data[-1].get("version", 0)

        if len(data) < page_size:
            break

    log(f"Fetched {len(all_products)} products from LS.")

    with open(CACHE_FILE, "w") as f:
        json.dump(all_products, f)
    log(f"Saved to cache: {CACHE_FILE}")

    return all_products

# ── Transform to index rows ───────────────────────────────────────────────────

def extract_barcode(product):
    codes = product.get("product_codes") or []
    if isinstance(codes, list):
        for c in codes:
            if isinstance(c, dict):
                code = c.get("code", "")
                if code and len(code) in (12, 13) and code.isdigit():
                    return code
    return None

def extract_supplier(product):
    # Prefer product_suppliers array, fall back to supplier string
    suppliers = product.get("product_suppliers") or []
    if isinstance(suppliers, list) and suppliers:
        s = suppliers[0]
        if isinstance(s, dict):
            return s.get("supplier_name") or s.get("name") or product.get("supplier")
    return product.get("supplier")

def to_index_row(p):
    barcode = extract_barcode(p)
    variant_opts = p.get("variant_options") or []
    # Normalise to dict
    if isinstance(variant_opts, list):
        opts = {}
        for v in variant_opts:
            if isinstance(v, dict):
                opts[v.get("attribute_name", "?")] = v.get("value", "")
        variant_opts = opts if opts else None
    elif not isinstance(variant_opts, dict):
        variant_opts = None

    return {
        "lightspeed_id":      p.get("id"),
        "barcode":            barcode,
        "sku":                p.get("sku"),
        "name":               p.get("name"),
        "variant_name":       p.get("variant_name"),
        "brand":              (p.get("brand") or {}).get("name") if isinstance(p.get("brand"), dict) else p.get("brand"),
        "brand_id":           p.get("brand_id"),
        "supplier":           extract_supplier(p),
        "supplier_id":        p.get("supplier_id"),
        "category":           p.get("product_category"),
        "product_type_id":    p.get("product_type_id"),
        "supply_price":       p.get("supply_price"),
        "retail_price":       p.get("price_excluding_tax"),
        "variant_options":    variant_opts,
        "family_id":          p.get("family_id"),
        "variant_parent_id":  p.get("variant_parent_id"),
        "active":             p.get("active", True) and not p.get("deleted_at"),
        "refreshed_at":       datetime.now(timezone.utc).isoformat(),
    }

# ── Load into Supabase ────────────────────────────────────────────────────────

def reload_index(products):
    log(f"Preparing {len(products)} rows for lightspeed_index...")
    batch_size = 200

    # Filter to meaningful rows only
    rows = [to_index_row(p) for p in products if p.get("id")]
    log(f"  {len(rows)} rows after transform. Inserting in batches of {batch_size}...")

    # Truncate and reload (faster than upsert for full refresh)
    if not DRY_RUN:
        result = sql("TRUNCATE TABLE lightspeed_index RESTART IDENTITY")
        if result is None:
            log("ERROR: Truncate failed — aborting index reload"); return False
        log("  Truncated lightspeed_index.")
    success = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        if DRY_RUN:
            success += len(batch)
            continue
        if supabase_insert_batch(batch):
            success += len(batch)
            time.sleep(0.4)  # stay under Management API rate limit (~2.5 req/s)
        else:
            log(f"  WARNING: Batch {i//batch_size + 1} insert failed")
        if i % 5000 == 0 and i > 0:
            log(f"  Inserted {success} rows so far...")

    log(f"Index reload complete. {success}/{len(rows)} rows written.")
    return True

# ── Cross-validation ──────────────────────────────────────────────────────────

def cross_validate(ls_products):
    """
    Compare our products table against live LS data.
    Finds:
    - Products in our DB that have a barcode but no LS match (not in LS yet)
    - Products in our DB with lightspeed_product_id but no match in live LS (stale ID)
    - Price mismatches > $1 between our DB and LS
    """
    log("\n=== CROSS-VALIDATION: Our DB vs Live LS ===")

    # Build LS lookup maps
    ls_by_barcode = {}
    ls_by_id      = {}
    for p in ls_products:
        uid = p.get("id")
        if uid:
            ls_by_id[uid] = p
        bc = extract_barcode(p)
        if bc and not p.get("deleted_at"):
            ls_by_barcode[bc] = p

    log(f"LS live products: {len(ls_by_id)} total, {len(ls_by_barcode)} with barcode")

    # Fetch our enhanced_complete products
    result = sql("""
        SELECT id, name, sku, barcode, retail_price, supply_price,
               lightspeed_product_id, supplier_name, brand_name, status
        FROM products
        WHERE status = 'enhanced_complete'
        ORDER BY name
    """)
    if not result:
        log("Could not fetch our products"); return

    our_products = result
    log(f"Our enhanced_complete products: {len(our_products)}")

    missing_from_ls   = []  # in our DB, not found in LS
    stale_ls_id       = []  # lightspeed_product_id points to deleted/missing product
    price_mismatches  = []  # retail_price differs by > $1
    supplier_gaps     = []  # our product has supplier_name but LS product has none

    for p in our_products:
        our_bc    = p.get("barcode")
        our_ls_id = p.get("lightspeed_product_id")
        our_price = float(p.get("retail_price") or 0)

        # Find the matching LS product
        ls_match = None
        if our_ls_id and our_ls_id in ls_by_id:
            ls_match = ls_by_id[our_ls_id]
        elif our_bc and our_bc in ls_by_barcode:
            ls_match = ls_by_barcode[our_bc]

        if not ls_match:
            missing_from_ls.append({
                "name": p.get("name"),
                "sku": p.get("sku"),
                "barcode": our_bc,
                "our_ls_id": our_ls_id,
            })
            continue

        # Check for stale ID
        if our_ls_id and our_ls_id not in ls_by_id:
            stale_ls_id.append({
                "name": p.get("name"),
                "sku": p.get("sku"),
                "stale_id": our_ls_id,
                "barcode_match_id": ls_match.get("id"),
            })

        # Check price mismatch
        ls_price = float(ls_match.get("price_excluding_tax") or 0)
        if our_price and ls_price and abs(our_price - ls_price) > 1.00:
            price_mismatches.append({
                "name": p.get("name"),
                "sku": p.get("sku"),
                "our_price": our_price,
                "ls_price": ls_price,
                "diff": round(our_price - ls_price, 2),
            })

        # Check supplier gap
        our_sup = p.get("supplier_name") or ""
        ls_sup  = extract_supplier(ls_match) or ""
        if our_sup and not ls_sup:
            supplier_gaps.append({
                "name": p.get("name"),
                "sku": p.get("sku"),
                "our_supplier": our_sup,
                "ls_id": ls_match.get("id"),
            })

    log(f"\n--- Results ---")
    log(f"Not found in LS:     {len(missing_from_ls)}")
    log(f"Stale LS IDs:        {len(stale_ls_id)}")
    log(f"Price mismatches:    {len(price_mismatches)} (diff > $1)")
    log(f"Supplier gaps in LS: {len(supplier_gaps)}")

    if missing_from_ls:
        log(f"\n[NOT IN LS] First 10:")
        for p in missing_from_ls[:10]:
            log(f"  {p['name']} | sku={p['sku']} | barcode={p['barcode']}")

    if stale_ls_id:
        log(f"\n[STALE LS ID] First 5:")
        for p in stale_ls_id[:5]:
            log(f"  {p['name']} | stale={p['stale_id']} → should be {p['barcode_match_id']}")

    if price_mismatches:
        log(f"\n[PRICE MISMATCH] First 10 (our price vs LS price):")
        for p in sorted(price_mismatches, key=lambda x: abs(x['diff']), reverse=True)[:10]:
            log(f"  {p['name']} | ours=${p['our_price']} LS=${p['ls_price']} diff=${p['diff']}")

    if supplier_gaps:
        log(f"\n[SUPPLIER GAP] First 10 (we have supplier, LS doesn't):")
        for p in supplier_gaps[:10]:
            log(f"  {p['name']} | {p['our_supplier']} | ls_id={p['ls_id']}")

    # Save detailed report
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "ls_total": len(ls_by_id),
        "our_enhanced_complete": len(our_products),
        "missing_from_ls": missing_from_ls,
        "stale_ls_ids": stale_ls_id,
        "price_mismatches": price_mismatches,
        "supplier_gaps": supplier_gaps,
    }
    report_file = os.path.join(DOCS, "ls_validation_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    log(f"\nFull report saved: {report_file}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log(f"=== ls_index_refresh.py {'(DRY RUN) ' if DRY_RUN else ''}{'(VALIDATE ONLY) ' if VALIDATE_ONLY else ''}===")

    if not VALIDATE_ONLY:
        ensure_columns()

    products = fetch_all_products()

    if not products:
        log("ERROR: No products fetched — aborting"); sys.exit(1)

    if VALIDATE_ONLY:
        cross_validate(products)
    else:
        if reload_index(products):
            log("\nIndex reload complete. Running cross-validation...")
            cross_validate(products)
        else:
            log("ERROR: Index reload failed"); sys.exit(1)

    log("=== Done ===")

if __name__ == "__main__":
    main()
