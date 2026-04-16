#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 0: Catalog Refresh + Manifest Builder
Read-only: fetches LS catalog, diffs against pre-import cache, identifies orphans.

Outputs:
  - docs/ls_fresh_catalog.json       — full fresh catalog
  - docs/ls_fresh_barcode_idx.json   — barcode → product_id index
  - docs/ls_fresh_sku_idx.json       — SKU → product_id index
  - docs/ls_fresh_name_idx.json      — name → product_id index
  - docs/ls_cleanup_manifest.json    — products to delete (with safety filters)
  - docs/ls_cleanup_manifest.csv     — same, human-readable for Corrinne
  - docs/ls_reimport_plan.json       — grouped by style, v2.0 vs v2.1 routing
"""

import json
import csv
import time
import subprocess
import sys
from datetime import datetime, timezone
from collections import defaultdict

# === Config ===
LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
SUPABASE_ACCESS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^SUPABASE_ACCESS_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
SUPABASE_PROJECT = "ayfwyvripnetwrkimxka"

# Rate limiting: 55 req/min
REQ_DELAY = 1.1  # seconds between requests

def ls_api(method, endpoint, data=None):
    """Call Lightspeed API via curl (reliable on this Droplet)."""
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
               f"{LS_BASE}/{endpoint}",
               "-H", f"Authorization: Bearer {LS_TOKEN}",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json"]
        if data:
            cmd.extend(["-d", json.dumps(data)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        parts = r.stdout.rsplit('\n', 1)
        body = parts[0] if parts else ''
        status = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        try:
            parsed = json.loads(body)
        except:
            parsed = {"raw": body[:500]}
        if status == 429:
            print(f"  Rate limited (attempt {attempt+1}), waiting 15s...")
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status

def ls_get(path, params=None):
    """GET from Lightspeed API. Returns the 'data' array from the response."""
    endpoint = path.lstrip("/")
    if params:
        endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    parsed, status = ls_api("GET", endpoint)
    if status >= 400:
        print(f"  API error {status}: {parsed}")
        return [], None
    # LS API wraps results in {"data": [...], "version": {...}}
    if isinstance(parsed, dict) and "data" in parsed:
        version_info = parsed.get("version", {})
        return parsed["data"], version_info
    return parsed if isinstance(parsed, list) else [], None

def supabase_sql(query):
    """Run SQL via Supabase Management API (curl-based)."""
    r = subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT}/database/query",
         "-H", f"Authorization: Bearer {SUPABASE_ACCESS_TOKEN}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"query": query})],
        capture_output=True, text=True, timeout=120
    )
    return json.loads(r.stdout)

# =========================================================
# STEP 1: Fetch full fresh Lightspeed catalog
# =========================================================
def fetch_fresh_catalog():
    print("=" * 60)
    print("STEP 1: Fetching fresh Lightspeed catalog...")
    print("=" * 60)

    all_products = []
    after = 0
    page = 0
    page_size = 250

    while True:
        page += 1
        params = {"page_size": str(page_size)}
        if after > 0:
            params["after"] = str(after)

        if page % 20 == 1:
            print(f"  Page {page} (after={after}, total so far: {len(all_products)})...")

        data, version_info = ls_get("/products", params)

        if not data or len(data) == 0:
            break

        all_products.extend(data)

        # Use the max version from the response for cursor pagination
        if version_info and "max" in version_info:
            after = version_info["max"]
        elif data:
            after = data[-1].get("version", 0)

        if len(data) < page_size:
            break

    print(f"  Total products fetched: {len(all_products)}")

    # Save fresh catalog
    with open(f"{DOCS}/ls_fresh_catalog.json", "w") as f:
        json.dump(all_products, f)

    return all_products

# =========================================================
# STEP 2: Build indexes from fresh catalog
# =========================================================
def build_indexes(products):
    print("\n" + "=" * 60)
    print("STEP 2: Building indexes...")
    print("=" * 60)

    barcode_idx = {}
    sku_idx = {}
    name_idx = {}

    for p in products:
        pid = p.get("id", "")
        name = p.get("name", "")
        sku = p.get("sku", "")

        # Name index
        if name:
            name_idx[name.upper()] = pid

        # SKU index
        if sku:
            sku_idx[sku] = pid

        # Barcode index — check product_codes array
        codes = p.get("product_codes", [])
        if codes:
            for code in codes:
                bc = code.get("code", "")
                if bc:
                    barcode_idx[bc] = pid

    print(f"  Barcode index: {len(barcode_idx)} entries")
    print(f"  SKU index: {len(sku_idx)} entries")
    print(f"  Name index: {len(name_idx)} entries")

    with open(f"{DOCS}/ls_fresh_barcode_idx.json", "w") as f:
        json.dump(barcode_idx, f, indent=2)
    with open(f"{DOCS}/ls_fresh_sku_idx.json", "w") as f:
        json.dump(sku_idx, f, indent=2)
    with open(f"{DOCS}/ls_fresh_name_idx.json", "w") as f:
        json.dump(name_idx, f, indent=2)

    return barcode_idx, sku_idx, name_idx

# =========================================================
# STEP 3: Load pre-import cache and diff to find orphans
# =========================================================
def identify_orphans(fresh_products):
    print("\n" + "=" * 60)
    print("STEP 3: Identifying orphan products from April 13-14 import...")
    print("=" * 60)

    # Load pre-import cache (built before the April 13-14 import)
    # Cache format: dict keyed by product UUID → {id, name, variant_name, sku, ...}
    pre_import_path = f"{DOCS}/lightspeed_cache.json"
    try:
        with open(pre_import_path) as f:
            pre_import = json.load(f)
        # Cache is a dict keyed by product ID
        if isinstance(pre_import, dict):
            pre_import_ids = set(pre_import.keys())
        else:
            pre_import_ids = set(p.get("id", "") for p in pre_import)
        print(f"  Pre-import cache: {len(pre_import_ids)} products")
    except FileNotFoundError:
        print("  ERROR: Pre-import cache not found! Cannot diff.")
        sys.exit(1)

    # Fresh catalog IDs
    fresh_ids = set(p.get("id", "") for p in fresh_products)
    fresh_by_id = {p.get("id", ""): p for p in fresh_products}

    # New products = in fresh but NOT in pre-import
    new_ids = fresh_ids - pre_import_ids
    print(f"  New products since pre-import cache: {len(new_ids)}")

    # Apply multi-layer safety filters to identify import orphans
    orphans = []
    not_orphans = []

    for pid in new_ids:
        p = fresh_by_id[pid]
        name = p.get("name", "")
        sku = p.get("sku", "")
        brand = p.get("brand", "")
        supplier = p.get("supplier", "")
        category = p.get("category", "")
        tags = p.get("tags", [])
        variants = p.get("variants", [])

        # Safety filters — our import created products with these characteristics:
        # 1. Standalone (0 or 1 variants, not part of a family)
        # 2. Missing brand/supplier/category (we didn't set these in the import)
        # 3. SKU matches our pattern (GENDER-SUPPLIER-STYLE-...)

        is_standalone = len(variants) <= 1
        has_no_brand = not brand or brand.strip() == ""
        has_no_supplier = not supplier or supplier.strip() == ""
        has_no_category = not category or category.strip() == ""

        # Our SKUs follow pattern: X-XXX-... (gender-supplier-style...)
        # or special patterns like LT-XXXXX
        sku_looks_like_ours = False
        if sku:
            parts = sku.split("-")
            if len(parts) >= 3:
                sku_looks_like_ours = True
            elif sku.startswith("LT-"):
                sku_looks_like_ours = True

        # Multi-layer filter: must match at least 2 of 3 signals
        signals = [
            is_standalone,
            (has_no_brand and has_no_supplier and has_no_category),
            sku_looks_like_ours
        ]
        signal_count = sum(signals)

        if signal_count >= 2:
            orphans.append({
                "id": pid,
                "name": name,
                "sku": sku,
                "brand": brand,
                "supplier": supplier,
                "category": category,
                "tags": tags,
                "variant_count": len(variants),
                "signals": signal_count,
                "is_standalone": is_standalone,
                "has_no_metadata": (has_no_brand and has_no_supplier and has_no_category),
                "sku_matches_pattern": sku_looks_like_ours
            })
        else:
            not_orphans.append({
                "id": pid,
                "name": name,
                "sku": sku,
                "signals": signal_count,
                "reason": "Did not match enough safety filters"
            })

    print(f"  Orphans identified: {len(orphans)}")
    print(f"  New products NOT matching orphan pattern: {len(not_orphans)}")

    if not_orphans:
        print(f"\n  Non-orphan new products (for review):")
        for p in not_orphans[:10]:
            print(f"    - {p['name'][:60]} (SKU: {p['sku']}, signals: {p['signals']})")
        if len(not_orphans) > 10:
            print(f"    ... and {len(not_orphans) - 10} more")

    return orphans, not_orphans

# =========================================================
# STEP 4: Build re-import plan from normalized_products
# =========================================================
def build_reimport_plan(orphans, fresh_products, barcode_idx, sku_idx):
    print("\n" + "=" * 60)
    print("STEP 4: Building re-import plan from normalized_products...")
    print("=" * 60)

    # Fetch our normalized products
    result = supabase_sql("""
        SELECT id, product_id, item_name, style_number, sku, barcode,
               supplier_code, supplier, brand, category,
               retail_price, supply_price,
               size, size_value, width_length, width_length_value,
               color, color_value, color_code,
               tags, gender, description, notes,
               normalization_status, lightspeed_product_id
        FROM normalized_products
        WHERE normalization_status = 'normalized'
        ORDER BY style_number, id
    """)

    products = result if isinstance(result, list) else []
    print(f"  Normalized products loaded: {len(products)}")

    # Build existing family index from fresh catalog
    # A "family" is a product with variants > 1, keyed by style number
    existing_families = {}
    for p in fresh_products:
        variants = p.get("variants", [])
        if len(variants) > 1:
            # Try to extract style number from name or SKU
            sku = p.get("sku", "")
            name = p.get("name", "")
            # Store by product ID for v2.1 matching
            existing_families[p["id"]] = {
                "id": p["id"],
                "name": name,
                "sku": sku,
                "variant_count": len(variants),
                "variant_options": _extract_variant_options(variants)
            }

    print(f"  Existing LS families (multi-variant): {len(existing_families)}")

    # Group our products by style_number
    style_groups = defaultdict(list)
    no_style = []

    for p in products:
        style = p.get("style_number", "")
        if style and style != "..." and style.strip():
            style_groups[style].append(p)
        else:
            no_style.append(p)

    print(f"  Style groups: {len(style_groups)}")
    print(f"  Products without style number: {len(no_style)}")

    # Determine v2.0 (new family) vs v2.1 (add to existing)
    # Check which style numbers match existing LS families by barcode or SKU
    plan = {
        "new_families": [],      # v2.0 POST — create new family
        "add_to_existing": [],   # v2.1 POST — add to existing family
        "standalone": [],        # single products, no family needed
        "stats": {}
    }

    orphan_ids = set(o["id"] for o in orphans)

    for style, group in style_groups.items():
        # Check if any product in this group has a barcode matching an existing LS family
        existing_family_id = None
        existing_family_options = None

        for p in group:
            bc = p.get("barcode", "")
            if bc and bc in barcode_idx:
                ls_pid = barcode_idx[bc]
                # Check if this LS product is NOT one of our orphans (i.e., it's a real existing family)
                if ls_pid not in orphan_ids and ls_pid in existing_families:
                    existing_family_id = ls_pid
                    existing_family_options = existing_families[ls_pid]["variant_options"]
                    break

        if existing_family_id:
            plan["add_to_existing"].append({
                "style_number": style,
                "existing_family_id": existing_family_id,
                "existing_variant_options": existing_family_options,
                "products": [_product_summary(p) for p in group]
            })
        elif len(group) == 1:
            plan["standalone"].append(_product_summary(group[0]))
        else:
            plan["new_families"].append({
                "style_number": style,
                "products": [_product_summary(p) for p in group]
            })

    # Add no-style products as standalone
    for p in no_style:
        plan["standalone"].append(_product_summary(p))

    plan["stats"] = {
        "total_products": len(products),
        "new_families": len(plan["new_families"]),
        "new_family_products": sum(len(f["products"]) for f in plan["new_families"]),
        "add_to_existing": len(plan["add_to_existing"]),
        "add_to_existing_products": sum(len(f["products"]) for f in plan["add_to_existing"]),
        "standalone": len(plan["standalone"]),
        "orphans_to_delete": len(orphans)
    }

    print(f"\n  Re-import plan:")
    print(f"    New families (v2.0):     {plan['stats']['new_families']} families, {plan['stats']['new_family_products']} products")
    print(f"    Add to existing (v2.1):  {plan['stats']['add_to_existing']} families, {plan['stats']['add_to_existing_products']} products")
    print(f"    Standalone:              {plan['stats']['standalone']} products")
    print(f"    Orphans to delete:       {plan['stats']['orphans_to_delete']}")

    return plan

def _extract_variant_options(variants):
    """Extract unique variant option names from a product's variants."""
    options = set()
    for v in variants:
        for opt in v.get("variant_options", []):
            options.add(opt.get("name", ""))
    return sorted(options)

def _product_summary(p):
    """Create a slim summary of a normalized product for the plan."""
    return {
        "id": p.get("id"),
        "product_id": p.get("product_id"),
        "name": p.get("item_name", ""),
        "style_number": p.get("style_number", ""),
        "sku": p.get("sku", ""),
        "barcode": p.get("barcode", ""),
        "brand": p.get("brand", ""),
        "category": p.get("category", ""),
        "supplier_code": p.get("supplier_code", ""),
        "supplier": p.get("supplier", ""),
        "retail_price": float(p["retail_price"]) if p.get("retail_price") else None,
        "supply_price": float(p["supply_price"]) if p.get("supply_price") else None,
        "gender": p.get("gender", ""),
        "size_value": p.get("size_value", ""),
        "width_length": p.get("width_length", ""),
        "width_length_value": p.get("width_length_value", ""),
        "color_value": p.get("color_value", ""),
        "color_code": p.get("color_code", ""),
        "tags": p.get("tags", ""),
        "description": p.get("description", ""),
    }

# =========================================================
# STEP 5: Check variant consistency within style groups
# =========================================================
def check_variant_consistency(plan):
    print("\n" + "=" * 60)
    print("STEP 5: Checking variant consistency within style groups...")
    print("=" * 60)

    inconsistent = []

    for family in plan["new_families"]:
        options_per_product = []
        for p in family["products"]:
            options = set()
            if p.get("size_value"):
                options.add("Size")
            if p.get("width_length") and p.get("width_length_value"):
                wl = p["width_length"]
                options.add(wl)  # "Width" or "Length"
            if p.get("color_value"):
                options.add("Color")
            options_per_product.append((p["sku"], options))

        # Check all products have the same option set
        if options_per_product:
            reference = options_per_product[0][1]
            all_same = all(opts == reference for _, opts in options_per_product)
            if not all_same:
                inconsistent.append({
                    "style_number": family["style_number"],
                    "products": [(sku, sorted(opts)) for sku, opts in options_per_product]
                })

    print(f"  Total new families: {len(plan['new_families'])}")
    print(f"  Inconsistent families: {len(inconsistent)}")

    if inconsistent:
        print(f"\n  Will fix by backfilling NA for missing variant options.")

    return inconsistent

# =========================================================
# STEP 6: Save manifest and plan
# =========================================================
def save_outputs(orphans, not_orphans, plan, inconsistent):
    print("\n" + "=" * 60)
    print("STEP 6: Saving outputs...")
    print("=" * 60)

    # Save manifest JSON
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "orphan_count": len(orphans),
        "non_orphan_new_count": len(not_orphans),
        "orphans": orphans,
        "non_orphans": not_orphans
    }
    with open(f"{DOCS}/ls_cleanup_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Saved: ls_cleanup_manifest.json ({len(orphans)} orphans)")

    # Save manifest CSV for Corrinne
    with open(f"{DOCS}/ls_cleanup_manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["Product ID", "Name", "SKU", "Brand", "Supplier", "Category",
                         "Variant Count", "Safety Signals", "Is Standalone",
                         "No Metadata", "SKU Matches Pattern"])
        for o in orphans:
            writer.writerow([
                o["id"], o["name"], o["sku"], o["brand"], o["supplier"], o["category"],
                o["variant_count"], o["signals"], o["is_standalone"],
                o["has_no_metadata"], o["sku_matches_pattern"]
            ])
    print(f"  Saved: ls_cleanup_manifest.csv")

    # Save re-import plan
    plan["inconsistent_families"] = inconsistent
    plan["generated_at"] = datetime.now(timezone.utc).isoformat()
    with open(f"{DOCS}/ls_reimport_plan.json", "w") as f:
        json.dump(plan, f, indent=2)
    print(f"  Saved: ls_reimport_plan.json")

    # Summary
    print("\n" + "=" * 60)
    print("PHASE 0 COMPLETE — Summary")
    print("=" * 60)
    print(f"  Fresh catalog size:        {plan['stats'].get('total_products', 'N/A')} (our normalized)")
    print(f"  Orphans to delete:         {len(orphans)}")
    print(f"  Non-orphan new products:   {len(not_orphans)}")
    print(f"  New families (v2.0):       {plan['stats']['new_families']} ({plan['stats']['new_family_products']} products)")
    print(f"  Add to existing (v2.1):    {plan['stats']['add_to_existing']} ({plan['stats']['add_to_existing_products']} products)")
    print(f"  Standalone:                {plan['stats']['standalone']}")
    print(f"  Inconsistent families:     {len(inconsistent)} (will be fixed)")
    print(f"\n  NEXT: Review ls_cleanup_manifest.csv, then run Phase 1")

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    print(f"Lightspeed Cleanup — Phase 0")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    fresh = fetch_fresh_catalog()
    barcode_idx, sku_idx, name_idx = build_indexes(fresh)
    orphans, not_orphans = identify_orphans(fresh)
    plan = build_reimport_plan(orphans, fresh, barcode_idx, sku_idx)
    inconsistent = check_variant_consistency(plan)
    save_outputs(orphans, not_orphans, plan, inconsistent)
