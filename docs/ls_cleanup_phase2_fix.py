#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 2 Fix: Record-by-record correction and retry.

Fixes:
1. add_to_existing (1,899 records): Fetch each parent's actual variant attributes,
   map our data to match parent structure, match supplier, deduplicate
2. new_family (187 records): Deduplicate product_codes and variant definitions
3. standalone (1,059 remaining): Complete from progress file

Approach:
- Fetches parent product details to get exact attribute IDs + supplier
- Maps our Size/Width/Length/Color to the parent's actual attributes
- Deduplicates barcodes and variant combos before sending
- Resumes from progress file
"""

import json
import subprocess
import time
import sys
import re
from datetime import datetime, timezone
from collections import defaultdict

# === Config ===
LS_BASE_20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
LS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
PROGRESS_FILE = f"{DOCS}/ls_cleanup_phase2_progress.json"
REQ_DELAY = 1.1

# Correct variant attribute UUIDs
VARIANT_ATTRS = {
    "Color":      "c67f4856-9113-4447-aea0-6a4d9cafb176",
    "Size":       "8d72c173-2d55-4ef6-9813-d6bfbed613b2",
    "Length":     "6c510e74-8d1d-4a3f-b948-7c78ad96d3f1",
    "Width":      "e7261267-9196-4701-88dd-1df8ffc374ec",
    "Shoe Width": "2add3700-e4bc-4292-96ed-f10a5568197b",
}

# Reverse lookup: attribute ID → name
ATTR_ID_TO_NAME = {v: k for k, v in VARIANT_ATTRS.items()}

SUPPLIER_IDS = {}
BRAND_IDS = {}
CATEGORY_IDS = {}

def ls_api(method, base_url, endpoint, data=None):
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
               f"{base_url}/{endpoint}",
               "-H", f"Authorization: Bearer {LS_TOKEN}",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json"]
        if data:
            cmd.extend(["-d", json.dumps(data)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        parts = r.stdout.rsplit('\n', 1)
        body = parts[0] if parts else ''
        status = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        try:
            parsed = json.loads(body)
        except:
            parsed = {"raw": body[:500]}
        if status == 429:
            print(f"    Rate limited, waiting 15s...")
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status

def load_progress():
    with open(PROGRESS_FILE) as f:
        return json.load(f)

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

def load_metadata_ids():
    global SUPPLIER_IDS, BRAND_IDS, CATEGORY_IDS
    with open(f"{DOCS}/ls_fresh_catalog.json") as f:
        catalog = json.load(f)
    for p in catalog:
        supplier = p.get("supplier")
        if supplier and isinstance(supplier, dict):
            name = supplier.get("name", "").upper()
            if name and name not in SUPPLIER_IDS:
                SUPPLIER_IDS[name] = supplier.get("id")
        brand = p.get("brand")
        if brand and isinstance(brand, dict):
            name = brand.get("name", "").upper()
            if name and name not in BRAND_IDS:
                BRAND_IDS[name] = brand.get("id")
        cat = p.get("product_category")
        if cat and isinstance(cat, dict):
            name = cat.get("name", "").upper()
            if name and name not in CATEGORY_IDS:
                CATEGORY_IDS[name] = cat.get("id")
    print(f"  Metadata: {len(SUPPLIER_IDS)} suppliers, {len(BRAND_IDS)} brands, {len(CATEGORY_IDS)} categories")

def get_product_value(product, attr_name):
    """Get the value from our product data for a given LS attribute name."""
    if attr_name == "Size":
        return product.get("size_value", "")
    elif attr_name in ("Width", "Shoe Width"):
        return product.get("width_length_value", "") if product.get("width_length") == "Width" else ""
    elif attr_name == "Length":
        return product.get("width_length_value", "") if product.get("width_length") == "Length" else ""
    elif attr_name == "Color":
        return product.get("color_value", "")
    return ""

# =========================================================
# FIX 1: Fetch all parent product details for add-to-existing
# =========================================================
def fetch_parent_details(existing_families):
    """Fetch variant attributes and supplier for each parent product."""
    print(f"\n  Fetching {len(existing_families)} parent product details...")
    parent_cache = {}

    for i, fam in enumerate(existing_families):
        parent_id = fam["existing_family_id"]
        if parent_id in parent_cache:
            continue

        result, status = ls_api("GET", LS_BASE_20, f"products/{parent_id}")
        if status != 200:
            print(f"    [{i+1}] WARN: Could not fetch parent {parent_id[:8]}... (HTTP {status})")
            continue

        data = result.get("data", result)
        if isinstance(data, list):
            data = data[0]

        vopts = data.get("variant_options", [])
        parent_attrs = []
        for vo in vopts:
            parent_attrs.append({
                "id": vo.get("id", ""),
                "name": vo.get("name", ""),
            })

        supplier = data.get("supplier")
        supplier_id = supplier.get("id", "") if isinstance(supplier, dict) else ""
        supplier_name = supplier.get("name", "") if isinstance(supplier, dict) else ""

        parent_cache[parent_id] = {
            "name": data.get("name", ""),
            "attrs": parent_attrs,
            "attr_names": [a["name"] for a in parent_attrs],
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
        }

        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{len(existing_families)}] fetched...")

    print(f"  Cached {len(parent_cache)} parent product details")
    return parent_cache

# =========================================================
# FIX 2: Add to existing families with correct attributes
# =========================================================
def fix_add_to_existing(existing_families, parent_cache, progress):
    """Re-attempt add-to-existing with parent-matched attributes."""
    print(f"\n{'='*70}")
    print("FIX: Add to existing families (matching parent attributes)")
    print(f"{'='*70}")

    # Clear old add_to_existing failures
    old_fails = [f for f in progress["failed"] if f.get("type") not in ("add_to_existing",)]
    progress["failed"] = old_fails
    done = set(progress.get("added_to_existing", []))

    total = len(existing_families)
    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, fam in enumerate(existing_families):
        style = fam["style_number"]
        if style in done:
            skip_count += 1
            continue

        parent_id = fam["existing_family_id"]
        parent = parent_cache.get(parent_id)

        if not parent:
            progress["failed"].append({
                "type": "add_to_existing_fix",
                "style": style,
                "status": 0,
                "error": f"Parent {parent_id} not in cache"
            })
            fail_count += 1
            continue

        parent_name = parent["name"]
        parent_attrs = parent["attrs"]
        parent_attr_names = parent["attr_names"]

        products = fam["products"]

        if (i + 1) % 25 == 0 or i == 0:
            print(f"\n  [{i+1}/{total}] {style} → \"{parent_name[:30]}\" (parent attrs: {parent_attr_names})")

        # Track seen variant combos to avoid duplicates
        seen_combos = set()
        family_success = 0
        family_fail = 0

        for p in products:
            # Build variant_attribute_values matching the parent's EXACT attributes
            variant_vals = []
            combo_parts = []

            for attr in parent_attrs:
                attr_id = attr["id"]
                attr_name = attr["name"]
                value = get_product_value(p, attr_name)

                if not value:
                    value = "NA"

                variant_vals.append({
                    "attribute_id": attr_id,
                    "attribute_value": value
                })
                combo_parts.append(f"{attr_name}={value}")

            # Skip duplicate combos
            combo_key = "|".join(combo_parts)
            if combo_key in seen_combos:
                continue
            seen_combos.add(combo_key)

            # v2.1 POST to add variant
            post_payload = {
                "common": {"name": parent_name},
                "details": {
                    "variant_attribute_values": variant_vals
                }
            }

            result, status = ls_api("POST", LS_BASE_21, "products", post_payload)

            if status in (200, 201):
                new_id = result.get("data", "")
                if isinstance(new_id, list):
                    new_id = new_id[0] if new_id else ""

                # v2.1 PUT to set SKU, price, barcode
                if new_id:
                    put_details = {}
                    sku = p.get("sku", "")
                    if sku:
                        put_details["product_codes"] = [{"type": "CUSTOM", "code": sku}]

                    barcode = p.get("barcode", "")
                    if barcode and barcode.isdigit() and len(barcode) >= 6:
                        existing_codes = put_details.get("product_codes", [])
                        existing_codes.append({"type": "UPC", "code": barcode})
                        put_details["product_codes"] = existing_codes

                    price = float(p.get("retail_price", 0)) if p.get("retail_price") else 0
                    if price > 0:
                        put_details["price_including_tax"] = price

                    if put_details:
                        ls_api("PUT", LS_BASE_21, f"products/{new_id}", {"details": put_details})

                family_success += 1
            else:
                err_str = str(result)[:200]
                # Don't fail the whole family for one variant
                if "same attributes" in err_str.lower():
                    # Variant already exists in this family — skip
                    family_success += 1
                else:
                    family_fail += 1
                    progress["failed"].append({
                        "type": "add_to_existing_fix",
                        "style": style,
                        "sku": p.get("sku", ""),
                        "status": status,
                        "error": err_str
                    })

        if family_success > 0:
            progress["added_to_existing"].append(style)
            done.add(style)
            success_count += 1
        elif family_fail > 0:
            fail_count += 1

        if (i + 1) % 10 == 0:
            save_progress(progress)

    save_progress(progress)
    print(f"\n  Results: {success_count} families added, {fail_count} failed, {skip_count} skipped (already done)")
    return success_count, fail_count

# =========================================================
# FIX 3: Retry new families with deduplication
# =========================================================
def fix_new_families(plan, barcode_idx, name_idx, progress):
    """Re-attempt failed new families with deduplicated product codes and variant definitions."""
    print(f"\n{'='*70}")
    print("FIX: Retry failed new families (deduplication)")
    print(f"{'='*70}")

    # Find which styles failed in Phase 2a
    failed_styles = set()
    for f in progress.get("failed", []):
        if f.get("type") == "new_family":
            failed_styles.add(f.get("style", ""))

    # Also remove these from the old failed list
    progress["failed"] = [f for f in progress["failed"] if f.get("type") != "new_family"]

    done = set(progress.get("created_families", []))
    retry_families = [f for f in plan.get("new_families", []) if f["style_number"] in failed_styles and f["style_number"] not in done]

    print(f"  {len(retry_families)} families to retry")

    success_count = 0
    fail_count = 0

    for i, family in enumerate(retry_families):
        style = family["style_number"]
        products = family["products"]

        if (i + 1) % 25 == 0 or i == 0:
            print(f"\n  [{i+1}/{len(retry_families)}] {style} ({len(products)} variants)")

        # Determine which variant options this family needs
        all_options = set()
        for p in products:
            if p.get("size_value"): all_options.add("Size")
            if p.get("width_length") == "Width" and p.get("width_length_value"): all_options.add("Width")
            if p.get("width_length") == "Length" and p.get("width_length_value"): all_options.add("Length")
            if p.get("color_value"): all_options.add("Color")

        option_names = sorted(all_options)

        # Build variants with deduplication
        family_name = products[0].get("name", style)
        if family_name.upper() in name_idx:
            family_name = f"{family_name} ({products[0].get('sku', '')})"

        variants = []
        seen_combos = set()
        seen_barcodes = set()

        for p in products:
            # Build variant definitions
            defs = []
            combo_parts = []
            for name in option_names:
                attr_id = VARIANT_ATTRS.get(name)
                if not attr_id:
                    continue
                value = get_product_value(p, name)
                if not value:
                    value = "NA"
                defs.append({"attribute_id": attr_id, "value": value})
                combo_parts.append(f"{name}={value}")

            # Skip duplicate variant combos
            combo_key = "|".join(combo_parts)
            if combo_key in seen_combos:
                continue
            seen_combos.add(combo_key)

            v = {
                "sku": p.get("sku", ""),
                "price_excluding_tax": float(p.get("retail_price", 0)) if p.get("retail_price") else 0,
                "supply_price": float(p.get("supply_price", 0)) if p.get("supply_price") else 0,
                "variant_definitions": defs,
            }

            # Deduplicate barcodes — only include if not already used
            barcode = p.get("barcode", "")
            if barcode and barcode.isdigit() and len(barcode) >= 6:
                if barcode not in seen_barcodes and barcode not in barcode_idx:
                    v["product_codes"] = [{"type": "UPC", "code": barcode}]
                    seen_barcodes.add(barcode)

            variants.append(v)

        if not variants:
            continue

        payload = {
            "name": family_name,
            "active": True,
            "variants": variants,
        }

        # Metadata
        first = products[0]
        if first.get("description"):
            payload["description"] = first["description"]
        brand = first.get("brand", "")
        if brand and BRAND_IDS.get(brand.upper()):
            payload["brand_id"] = BRAND_IDS[brand.upper()]
        supplier = first.get("supplier", "")
        if supplier and SUPPLIER_IDS.get(supplier.upper()):
            payload["supplier_id"] = SUPPLIER_IDS[supplier.upper()]
        category = first.get("category", "")
        if category and CATEGORY_IDS.get(category.upper()):
            payload["product_type_id"] = CATEGORY_IDS[category.upper()]

        result, status = ls_api("POST", LS_BASE_20, "products", payload)

        if status == 422:
            err = str(result)
            if "already exists" in err.lower():
                payload["name"] = f"{family_name} [{style}]"
                result, status = ls_api("POST", LS_BASE_20, "products", payload)

        if status in (200, 201):
            progress["created_families"].append(style)
            done.add(style)
            success_count += 1
        else:
            fail_count += 1
            progress["failed"].append({
                "type": "new_family_fix",
                "style": style,
                "status": status,
                "error": str(result)[:200],
                "variant_count": len(variants),
                "deduped_from": len(products)
            })
            if fail_count <= 5:
                print(f"    STILL FAILED: {style} — HTTP {status}: {str(result)[:80]}")

        if (i + 1) % 10 == 0:
            save_progress(progress)

    save_progress(progress)
    print(f"\n  Results: {success_count} families created, {fail_count} still failed")
    return success_count, fail_count

# =========================================================
# FIX 4: Complete remaining standalone imports
# =========================================================
def complete_standalone(plan, barcode_idx, name_idx, progress):
    """Complete remaining standalone product imports."""
    print(f"\n{'='*70}")
    print("FIX: Complete remaining standalone imports")
    print(f"{'='*70}")

    done = set(progress.get("standalone_created", []))
    standalone = plan.get("standalone", [])
    remaining = [p for p in standalone if p.get("sku", "") not in done]

    print(f"  {len(remaining)} standalone products remaining (of {len(standalone)} total)")

    success_count = 0
    fail_count = 0

    for i, product in enumerate(remaining):
        sku = product.get("sku", "")
        name = product.get("name", "")

        if (i + 1) % 50 == 0 or i == 0:
            print(f"\n  [{i+1}/{len(remaining)}] {name[:50]}")

        if name.upper() in name_idx:
            name = f"{name} ({sku})"

        payload = {
            "name": name,
            "sku": sku,
            "active": True,
            "price_excluding_tax": float(product.get("retail_price", 0)) if product.get("retail_price") else 0,
            "supply_price": float(product.get("supply_price", 0)) if product.get("supply_price") else 0,
        }

        if product.get("description"):
            payload["description"] = product["description"]

        barcode = product.get("barcode", "")
        if barcode and barcode.isdigit() and len(barcode) >= 6 and barcode not in barcode_idx:
            payload["product_codes"] = [{"type": "UPC", "code": barcode}]

        brand = product.get("brand", "")
        if brand and BRAND_IDS.get(brand.upper()):
            payload["brand_id"] = BRAND_IDS[brand.upper()]
        supplier = product.get("supplier", "")
        if supplier and SUPPLIER_IDS.get(supplier.upper()):
            payload["supplier_id"] = SUPPLIER_IDS[supplier.upper()]
        category = product.get("category", "")
        if category and CATEGORY_IDS.get(category.upper()):
            payload["product_type_id"] = CATEGORY_IDS[category.upper()]

        result, status = ls_api("POST", LS_BASE_20, "products", payload)

        if status == 422:
            err = str(result)
            if "already exists" in err.lower():
                payload["name"] = f"{name} [{sku}]"
                result, status = ls_api("POST", LS_BASE_20, "products", payload)

        if status in (200, 201):
            data = result.get("data", [])
            pid = data[0] if isinstance(data, list) and data else ""
            progress["standalone_created"].append(sku)
            done.add(sku)
            name_idx[product["name"].upper()] = pid
            success_count += 1
        else:
            fail_count += 1
            progress["failed"].append({
                "type": "standalone_fix",
                "sku": sku,
                "name": product.get("name", "")[:50],
                "status": status,
                "error": str(result)[:200]
            })

        if (i + 1) % 10 == 0:
            save_progress(progress)

    save_progress(progress)
    print(f"\n  Results: {success_count} created, {fail_count} failed")
    return success_count, fail_count

# =========================================================
# MAIN
# =========================================================
def main():
    print(f"Lightspeed Cleanup — Phase 2 Fix (Record-by-Record)")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    with open(f"{DOCS}/ls_reimport_plan.json") as f:
        plan = json.load(f)
    with open(f"{DOCS}/ls_fresh_barcode_idx.json") as f:
        barcode_idx = json.load(f)
    with open(f"{DOCS}/ls_fresh_name_idx.json") as f:
        name_idx = json.load(f)

    print("Loading metadata...")
    load_metadata_ids()

    progress = load_progress()
    print(f"\nCurrent state:")
    print(f"  Families created:    {len(progress.get('created_families', []))}")
    print(f"  Added to existing:   {len(progress.get('added_to_existing', []))}")
    print(f"  Standalone created:  {len(progress.get('standalone_created', []))}")
    print(f"  Failed:              {len(progress.get('failed', []))}")

    # Step 1: Fetch parent product details for add-to-existing
    existing_families = plan.get("add_to_existing", [])
    parent_cache = fetch_parent_details(existing_families)

    # Step 2: Fix add-to-existing (biggest failure category)
    ae_success, ae_fail = fix_add_to_existing(existing_families, parent_cache, progress)

    # Step 3: Fix failed new families
    nf_success, nf_fail = fix_new_families(plan, barcode_idx, name_idx, progress)

    # Step 4: Complete remaining standalone
    solo_success, solo_fail = complete_standalone(plan, barcode_idx, name_idx, progress)

    # Final summary
    progress = load_progress()
    print(f"\n{'='*70}")
    print("PHASE 2 FIX COMPLETE")
    print(f"{'='*70}")
    print(f"  Families created:    {len(progress.get('created_families', []))}/635")
    print(f"  Added to existing:   {len(progress.get('added_to_existing', []))}/561")
    print(f"  Standalone created:  {len(progress.get('standalone_created', []))}/1229")
    print(f"  Remaining failures:  {len(progress.get('failed', []))}")
    print(f"  Finished:            {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
