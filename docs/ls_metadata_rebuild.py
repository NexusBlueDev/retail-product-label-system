#!/usr/bin/env python3
"""
Metadata rebuild for 60 LS variant families.

Since LS API PUT rejects all metadata fields (supplier_id, product_type_id —
confirmed Apr 17), the only way to set them is at POST (create) time.
This script: GET all variants → DELETE family → POST fresh with correct metadata.

Corrinne's corrected CSV (ls_60_families_metadata_todo Update 4_20.csv) is
the source of truth for supplier names and category names. She has verified
both against live Lightspeed and added any missing suppliers.

Usage:
  python3 docs/ls_metadata_rebuild.py [--dry-run] [--style STYLE_NUMBER]

  --dry-run    Show what would happen, make no changes to Lightspeed.
  --style X    Process only the row with style_number = X (for testing).
"""

import csv, json, subprocess, sys, time
from collections import defaultdict
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────────────────
DOCS     = "/home/nexusblue/dev/retail-product-label-system/docs"
LS_BASE  = "https://therodeoshop.retail.lightspeed.app/api/2.0"
REQ_DELAY = 1.1   # seconds between API calls (stay under 55 req/min)
POST_RETRY_DELAY = 3.0  # extra wait after DELETE before POST

DRY_RUN     = "--dry-run" in sys.argv
STYLE_FILTER = next((sys.argv[i+1] for i, a in enumerate(sys.argv)
                     if a == "--style" and i+1 < len(sys.argv)), None)

TOKEN = subprocess.run(
    ["bash", "-c",
     "grep '^LIGHTSPEED_TOKEN=' "
     "/home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()

PROGRESS_FILE = f"{DOCS}/ls_metadata_rebuild_progress.json"

# Known supplier name mismatches between Corrinne's CSV and live LS names.
# Key = CSV value (uppercase), Value = exact LS name.
# Confirmed Apr 20 by comparing live GET /suppliers against the CSV.
SUPPLIER_ALIASES = {
    "MILLER BRANDS LLC":  "Miller International, Inc.",  # Cinch brand parent
    "KONTOOR BRANDS":     "Kontoor Brands, Inc.",        # Wrangler parent
}

# LS variant attribute UUIDs (same as phase2 script — do not change)
VARIANT_ATTRS = {
    "Color":      "c67f4856-9113-4447-aea0-6a4d9cafb176",
    "Size":       "8d72c173-2d55-4ef6-9813-d6bfbed613b2",
    "Length":     "6c510e74-8d1d-4a3f-b948-7c78ad96d3f1",
    "Width":      "e7261267-9196-4701-88dd-1df8ffc374ec",
    "Shoe Width": "2add3700-e4bc-4292-96ed-f10a5568197b",
}

# ─── LS API helper ────────────────────────────────────────────────────────────
def ls_api(method, endpoint, data=None):
    if DRY_RUN and method in ("DELETE", "POST", "PUT"):
        return {"data": {}}, 200
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
               f"{LS_BASE}/{endpoint}",
               "-H", f"Authorization: Bearer {TOKEN}",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json"]
        if data is not None:
            cmd.extend(["-d", json.dumps(data)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        parts = r.stdout.rsplit("\n", 1)
        body   = parts[0] if parts else ""
        status = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body[:500]}
        if status == 429:
            print(f"  [rate-limit] sleeping 20s…")
            time.sleep(20)
            continue
        return parsed, status
    return parsed, status


# ─── Load live ID indexes ─────────────────────────────────────────────────────
def normalize(name):
    """Uppercase + strip trailing/leading punctuation for fuzzy name matching."""
    return name.upper().strip().rstrip(".,")


def resolve_name(csv_name, id_map, aliases=None):
    """
    Try to resolve csv_name to an ID in id_map.
    1. Exact match (case-insensitive)
    2. Known alias map
    3. Normalized match (strip trailing punctuation)
    Returns (id_or_None, canonical_name_or_None)
    """
    if not csv_name:
        return None, None
    upper = csv_name.upper()

    # Exact
    if upper in id_map:
        return id_map[upper], csv_name

    # Alias map
    if aliases and upper in aliases:
        canonical = aliases[upper]
        if canonical.upper() in id_map:
            return id_map[canonical.upper()], canonical

    # Normalized (strip trailing punctuation)
    norm = normalize(csv_name)
    for k, v in id_map.items():
        if normalize(k) == norm:
            return v, k

    return None, None


def load_live_ids():
    """
    Fetch current supplier and product_type lists from LS.
    Returns (supplier_map, category_map) — both keyed by UPPERCASE name.
    The catalog (Apr 15) is stale; Corrinne added new suppliers after that.
    """
    supplier_map  = {}
    category_map  = {}

    print("  Loading live supplier list from LS…")
    page = 1
    while True:
        r, status = ls_api("GET", f"suppliers?limit=200&page={page}")
        if status != 200:
            print(f"  WARNING: GET /suppliers page {page} → {status}")
            break
        items = r.get("data", [])
        if not items:
            break
        for s in items:
            if isinstance(s, dict) and s.get("name"):
                supplier_map[s["name"].upper()] = s["id"]
        if len(items) < 200:
            break
        page += 1
    print(f"  → {len(supplier_map)} suppliers")

    print("  Loading live product_type (category) list from LS…")
    page = 1
    while True:
        r, status = ls_api("GET", f"product_types?limit=200&page={page}")
        if status != 200:
            print(f"  WARNING: GET /product_types page {page} → {status}")
            break
        items = r.get("data", [])
        if not items:
            break
        for c in items:
            if isinstance(c, dict) and c.get("name"):
                category_map[c["name"].upper()] = c["id"]
        if len(items) < 200:
            break
        page += 1
    print(f"  → {len(category_map)} categories")

    return supplier_map, category_map


def load_brand_ids():
    """Build brand name → id from the stale catalog (brands change rarely)."""
    brand_map = {}
    with open(f"{DOCS}/ls_fresh_catalog.json") as f:
        catalog = json.load(f)
    for p in catalog:
        b = p.get("brand")
        if isinstance(b, dict) and b.get("name"):
            brand_map[b["name"].upper()] = b["id"]
    print(f"  → {len(brand_map)} brands (from catalog)")
    return brand_map


# ─── Variant helpers ──────────────────────────────────────────────────────────
def get_family_data(ls_family_id):
    """
    GET the family parent product.
    Returns (product_dict, error_str).
    """
    r, status = ls_api("GET", f"products/{ls_family_id}")
    if status != 200:
        return None, f"GET_family_failed_{status}"
    data = r.get("data", [])
    if isinstance(data, list) and data:
        return data[0], None
    if isinstance(data, dict):
        return data, None
    return None, "empty_response"


def get_variants_for_family(ls_family_id, style_number, first_variant_sku):
    """
    Find all active variants of a family.

    Strategy:
      1. Search by first_variant_sku (exact) → quick confirmation + variant_parent_id check
      2. Search by style_number → broader sweep for all siblings
      3. Merge and deduplicate by SKU
    """
    variants = {}

    # Pass 1: targeted search by first_variant_sku
    r, status = ls_api("GET", f"search?type=products&q={first_variant_sku}&limit=50")
    if status == 200:
        for p in r.get("data", []):
            if (p.get("variant_parent_id") == ls_family_id
                    and not p.get("deleted_at")
                    and p.get("active")):
                sku = p.get("sku", "")
                if sku:
                    variants[sku] = p

    # Pass 2: broader search by style number
    r, status = ls_api("GET", f"search?type=products&q={style_number}&limit=200")
    if status == 200:
        for p in r.get("data", []):
            if (p.get("variant_parent_id") == ls_family_id
                    and not p.get("deleted_at")
                    and p.get("active")):
                sku = p.get("sku", "")
                if sku:
                    variants[sku] = p

    # Pass 3: if still nothing found, check if the ls_family_id is itself a standalone
    # (product with no variant_parent_id — created as fallback on Apr 17)
    if not variants:
        r, status = ls_api("GET", f"products/{ls_family_id}")
        if status == 200:
            data = r.get("data", [])
            p = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
            if p and not p.get("deleted_at") and p.get("active") and not p.get("variant_parent_id"):
                sku = p.get("sku", "") or first_variant_sku
                if sku:
                    variants[sku] = p

    return list(variants.values())


def variant_options_to_definitions(variant_options):
    """
    Convert LS GET response variant_options to POST variant_definitions.

    GET response can be:
      - dict:  {"Size": "M", "Color": "Blue"}
      - list:  [{"attribute_name": "Size", "value": "M"}, ...]
    """
    defs = []
    if isinstance(variant_options, dict):
        items = [{"attribute_name": k, "value": v}
                 for k, v in variant_options.items()]
    elif isinstance(variant_options, list):
        items = variant_options
    else:
        return defs

    for item in items:
        attr_name = item.get("attribute_name") or item.get("name", "")
        val       = item.get("value", "NA")
        attr_id   = VARIANT_ATTRS.get(attr_name)
        if attr_id and val:
            defs.append({"attribute_id": attr_id, "value": val or "NA"})
    return defs


def build_variant_payload(v):
    """Build one variant dict for the POST variants[] array."""
    options = v.get("variant_options", {})
    defs = variant_options_to_definitions(options)

    vp = {
        "sku":                   v.get("sku", ""),
        "active":                True,
        "price_excluding_tax":   float(v.get("price_excluding_tax") or 0),
        "supply_price":          float(v.get("supply_price") or 0),
    }
    if defs:
        vp["variant_definitions"] = defs

    # Barcodes live under product_codes in the GET response
    codes = v.get("product_codes", [])
    valid = [c for c in codes
             if isinstance(c, dict)
             and str(c.get("code", "")).isdigit()
             and len(str(c.get("code", ""))) >= 6]
    if valid:
        vp["product_codes"] = [{"type": c.get("type", "UPC"), "code": c["code"]}
                                for c in valid]
    return vp


# ─── Progress persistence ─────────────────────────────────────────────────────
def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"done": [], "failed": [], "skipped": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print(f"LS Metadata Rebuild — 60 Families {'[DRY RUN]' if DRY_RUN else '[LIVE]'}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    if STYLE_FILTER:
        print(f"Style filter: {STYLE_FILTER}")
    print("=" * 70)

    if not TOKEN:
        print("ERROR: LIGHTSPEED_TOKEN not found in .env.local")
        sys.exit(1)

    # Load ID maps
    print("\nLoading ID maps…")
    brand_map = load_brand_ids()
    supplier_map, category_map = load_live_ids()

    # Read Corrinne's corrected CSV
    csv_path = f"{DOCS}/ls_60_families_metadata_todo Update 4_20.csv"
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    print(f"\nCSV rows: {len(rows)}")

    if STYLE_FILTER:
        rows = [r for r in rows if r["style_number"] == STYLE_FILTER]
        print(f"After filter: {len(rows)} rows")

    # ── Pre-flight: show all supplier/category resolutions before touching LS ──
    print("\n── Pre-flight resolution check ──")
    unresolved_sup = []
    unresolved_cat = []
    for row in rows:
        s = row["needs_supplier"].strip()
        c = row["needs_category"].strip()
        sid, _ = resolve_name(s, supplier_map, SUPPLIER_ALIASES)
        cid, _ = resolve_name(c, category_map)
        if not sid:
            unresolved_sup.append((row["style_number"], s))
        if not cid:
            unresolved_cat.append((row["style_number"], c))

    if unresolved_sup:
        print(f"  SUPPLIERS not matched ({len(unresolved_sup)}) — will import without supplier_id:")
        for style, s in unresolved_sup:
            print(f"    {style}: '{s}'")
    else:
        print(f"  All {len(rows)} supplier names resolved ✓")

    if unresolved_cat:
        print(f"  CATEGORIES not matched ({len(unresolved_cat)}) — will import without product_type_id:")
        for style, c in unresolved_cat:
            print(f"    {style}: '{c}'")
    else:
        print(f"  All {len(rows)} category names resolved ✓")

    if (unresolved_sup or unresolved_cat) and not DRY_RUN:
        print("\n  NOTE: unresolved names will be skipped for those fields.")
        print("  Run with --dry-run to preview without changes.\n")

    progress = load_progress()
    done_styles = set(progress["done"])
    stats = {"rebuilt": 0, "skipped_already_done": 0, "failed": 0,
             "no_variants": 0}

    print()
    for i, row in enumerate(rows):
        style         = row["style_number"].strip()
        family_id     = row["ls_family_id"].strip()
        family_name   = row["ls_family_name"].strip()
        brand_name    = row["brand_set"].strip()
        supplier_name = row["needs_supplier"].strip()
        category_name = row["needs_category"].strip()
        first_sku     = row["first_variant_sku"].strip()

        prefix = f"[{i+1}/{len(rows)}] {style}"

        if style in done_styles:
            print(f"{prefix} → already done, skipping")
            stats["skipped_already_done"] += 1
            continue

        print(f"\n{prefix} — {family_name[:50]}")
        print(f"  family_id: {family_id}")
        print(f"  supplier:  {supplier_name}")
        print(f"  category:  {category_name}")

        # Resolve IDs (alias-aware, normalized matching)
        supplier_id, sup_canon  = resolve_name(supplier_name, supplier_map, SUPPLIER_ALIASES)
        category_id, cat_canon  = resolve_name(category_name, category_map)
        brand_id,    _          = resolve_name(brand_name, brand_map)

        if not supplier_id:
            print(f"  WARNING: supplier '{supplier_name}' not found in LS — will rebuild without supplier_id")
        else:
            print(f"  supplier:  resolved → '{sup_canon}'")
        if not category_id:
            print(f"  WARNING: category '{category_name}' not found in LS — will rebuild without product_type_id")
        else:
            print(f"  category:  resolved → '{cat_canon}'")

        # Fetch family metadata (name, existing brand_id if we don't have one)
        family_data, err = get_family_data(family_id)
        if err:
            print(f"  ERROR: GET family → {err}")
            progress["failed"].append({"style": style, "family_id": family_id,
                                        "reason": f"get_family_failed: {err}"})
            save_progress(progress)
            stats["failed"] += 1
            continue

        # Use existing brand_id from LS if our lookup missed
        if not brand_id and isinstance(family_data, dict):
            existing_brand = family_data.get("brand")
            if isinstance(existing_brand, dict):
                brand_id = existing_brand.get("id")
                print(f"  brand_id sourced from existing LS product")

        # Get all variants
        print(f"  Fetching variants (style search + SKU search)…")
        variants = get_variants_for_family(family_id, style, first_sku)
        print(f"  → {len(variants)} variants found")

        if not variants:
            print(f"  ERROR: no active variants found for family — skipping")
            progress["failed"].append({"style": style, "family_id": family_id,
                                        "reason": "no_variants_found"})
            save_progress(progress)
            stats["no_variants"] += 1
            stats["failed"] += 1
            continue

        # Build variant payloads
        variant_payloads = [build_variant_payload(v) for v in variants]
        # Filter out empty SKUs just in case
        variant_payloads = [v for v in variant_payloads if v.get("sku")]

        if len(variant_payloads) < 2:
            print(f"  Only {len(variant_payloads)} variant(s) — will create as standalone(s) instead of family")

        # Build POST payload
        post_payload = {
            "name":   family_name,
            "active": True,
        }
        if brand_id:
            post_payload["brand_id"] = brand_id
        if supplier_id:
            post_payload["supplier_id"] = supplier_id
        if category_id:
            post_payload["product_type_id"] = category_id

        if len(variant_payloads) >= 2:
            post_payload["variants"] = variant_payloads
        # Single-variant or zero: handled below as standalone

        if DRY_RUN:
            print(f"  [DRY RUN] Would DELETE {family_id} then POST:")
            print(f"    name={family_name}")
            print(f"    supplier_id={supplier_id} ({supplier_name})")
            print(f"    product_type_id={category_id} ({category_name})")
            print(f"    brand_id={brand_id} ({brand_name})")
            print(f"    variants={len(variant_payloads)}")
            for v in variant_payloads[:3]:
                print(f"      {v.get('sku')} | defs={v.get('variant_definitions', [])}")
            if len(variant_payloads) > 3:
                print(f"      … +{len(variant_payloads)-3} more")
            stats["rebuilt"] += 1
            progress["done"].append(style)
            save_progress(progress)
            continue

        # ── LIVE: DELETE then POST ────────────────────────────────────────────
        print(f"  DELETE {family_id}…")
        del_result, del_status = ls_api("DELETE", f"products/{family_id}")
        if del_status not in (200, 204):
            print(f"  ERROR: DELETE → {del_status}: {str(del_result)[:150]}")
            progress["failed"].append({"style": style, "family_id": family_id,
                                        "reason": f"delete_failed_{del_status}",
                                        "error": str(del_result)[:200]})
            save_progress(progress)
            stats["failed"] += 1
            continue

        print(f"  DELETE OK. Waiting {POST_RETRY_DELAY}s before POST…")
        time.sleep(POST_RETRY_DELAY)

        if len(variant_payloads) >= 2:
            # POST as variant family
            print(f"  POST family ({len(variant_payloads)} variants)…")
            post_result, post_status = ls_api("POST", "products", post_payload)

            if post_status in (200, 201):
                new_ids = post_result.get("data", [])
                print(f"  POST OK → {len(new_ids)} product IDs created")
                stats["rebuilt"] += 1
                progress["done"].append(style)
                save_progress(progress)
                continue

            # Fallback: name collision → try with [style] suffix
            err_str = str(post_result)
            if "already exists" in err_str.lower():
                post_payload["name"] = f"{family_name} [{style}]"
                print(f"  Name collision — retrying with suffix…")
                post_result, post_status = ls_api("POST", "products", post_payload)

            if post_status in (200, 201):
                new_ids = post_result.get("data", [])
                print(f"  POST (retry) OK → {len(new_ids)} IDs")
                stats["rebuilt"] += 1
                progress["done"].append(style)
                save_progress(progress)
                continue

            # Final fallback: strip barcodes and retry (barcode conflict)
            if "product codes must be unique" in err_str.lower():
                print(f"  Barcode conflict — stripping barcodes and retrying…")
                for v in post_payload.get("variants", []):
                    v.pop("product_codes", None)
                post_result, post_status = ls_api("POST", "products", post_payload)

            if post_status in (200, 201):
                new_ids = post_result.get("data", [])
                print(f"  POST (no-barcode) OK → {len(new_ids)} IDs")
                stats["rebuilt"] += 1
                progress["done"].append(style)
                save_progress(progress)
                continue

            # POST failed — log with DELETED status so it's clearly flagged
            print(f"  ERROR: POST → {post_status}: {err_str[:200]}")
            progress["failed"].append({
                "style":      style,
                "family_id":  family_id,
                "reason":     f"post_failed_{post_status}_FAMILY_WAS_DELETED",
                "error":      err_str[:300],
                "variants":   [v.get("sku") for v in variant_payloads],
                "supplier":   supplier_name,
                "category":   category_name,
            })
            save_progress(progress)
            stats["failed"] += 1

        else:
            # Single variant → create as standalone(s)
            print(f"  Single-variant family — creating as standalone…")
            for v_data in variants:
                solo_payload = {
                    "name":   family_name,
                    "sku":    v_data.get("sku", ""),
                    "active": True,
                    "price_excluding_tax": float(v_data.get("price_excluding_tax") or 0),
                    "supply_price":        float(v_data.get("supply_price") or 0),
                }
                if brand_id:
                    solo_payload["brand_id"] = brand_id
                if supplier_id:
                    solo_payload["supplier_id"] = supplier_id
                if category_id:
                    solo_payload["product_type_id"] = category_id
                codes = v_data.get("product_codes", [])
                valid = [c for c in codes
                         if str(c.get("code", "")).isdigit()
                         and len(str(c.get("code", ""))) >= 6]
                if valid:
                    solo_payload["product_codes"] = [
                        {"type": c.get("type", "UPC"), "code": c["code"]} for c in valid
                    ]
                r, s = ls_api("POST", "products", solo_payload)
                if s in (200, 201):
                    print(f"  Standalone POST OK — {v_data.get('sku')}")
                    stats["rebuilt"] += 1
                    progress["done"].append(style)
                    save_progress(progress)
                else:
                    print(f"  Standalone POST failed {s} — {str(r)[:150]}")
                    progress["failed"].append({
                        "style":     style,
                        "family_id": family_id,
                        "reason":    f"standalone_post_failed_{s}_FAMILY_WAS_DELETED",
                        "error":     str(r)[:200],
                    })
                    save_progress(progress)
                    stats["failed"] += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    save_progress(progress)
    print()
    print("=" * 70)
    print(f"METADATA REBUILD {'[DRY RUN] ' if DRY_RUN else ''}COMPLETE")
    print("=" * 70)
    print(f"  Rebuilt:           {stats['rebuilt']}")
    print(f"  Already done:      {stats['skipped_already_done']}")
    print(f"  No variants found: {stats['no_variants']}")
    print(f"  Failed:            {stats['failed']}")
    print(f"  Finished:          {datetime.now(timezone.utc).isoformat()}")
    if progress["failed"]:
        print(f"\n  Failed styles:")
        for f in progress["failed"]:
            print(f"    {f.get('style')} — {f.get('reason')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
