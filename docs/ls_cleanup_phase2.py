#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 2: Re-import as Proper Variant Families

API approach (validated by testing):
  - New families: v2.0 POST with variants[].variant_definitions (all variants in one call)
  - Add to existing: v2.1 POST {common: {name}, details: {variant_attribute_values}}
    then v2.1 PUT {details: {product_codes, price_including_tax}} for SKU/price/barcode
  - Standalone: v2.0 POST (simple product, no variants array)

Saves progress per-family for resumability.
Prerequisite: docs/ls_reimport_plan.json from Phase 0.
"""

import json
import subprocess
import time
import sys
from datetime import datetime, timezone

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

# Correct variant attribute UUIDs (from GET /variant_attributes)
VARIANT_ATTRS = {
    "Color":      "c67f4856-9113-4447-aea0-6a4d9cafb176",
    "Size":       "8d72c173-2d55-4ef6-9813-d6bfbed613b2",
    "Length":     "6c510e74-8d1d-4a3f-b948-7c78ad96d3f1",
    "Width":      "e7261267-9196-4701-88dd-1df8ffc374ec",
    "Shoe Width": "2add3700-e4bc-4292-96ed-f10a5568197b",
}

SUPPLIER_IDS = {}
BRAND_IDS = {}
CATEGORY_IDS = {}

def ls_api(method, base_url, endpoint, data=None):
    """Call Lightspeed API via curl."""
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
            print(f"    Rate limited (attempt {attempt+1}), waiting 15s...")
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status

def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"created_families": [], "added_to_existing": [],
                "standalone_created": [], "failed": [], "skipped": []}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

def load_metadata_ids():
    """Load supplier/brand/category IDs from fresh catalog."""
    global SUPPLIER_IDS, BRAND_IDS, CATEGORY_IDS
    try:
        with open(f"{DOCS}/ls_fresh_catalog.json") as f:
            catalog = json.load(f)
    except FileNotFoundError:
        print("WARNING: No fresh catalog found.")
        return

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

    print(f"  Loaded: {len(SUPPLIER_IDS)} suppliers, {len(BRAND_IDS)} brands, {len(CATEGORY_IDS)} categories")

def enforce_variant_consistency(products):
    """Ensure all products in a family have identical variant option sets. Backfill NA."""
    all_options = set()
    for p in products:
        if p.get("size_value"):
            all_options.add("Size")
        if p.get("width_length") == "Width" and p.get("width_length_value"):
            all_options.add("Shoe Width")
        if p.get("width_length") == "Length" and p.get("width_length_value"):
            all_options.add("Length")
        if p.get("color_value"):
            all_options.add("Color")

    for p in products:
        if "Size" in all_options and not p.get("size_value"):
            p["size_value"] = "NA"
        if "Shoe Width" in all_options and not (p.get("width_length") == "Width" and p.get("width_length_value")):
            p["width_length"] = "Width"
            p["width_length_value"] = "NA"
        if "Length" in all_options and not (p.get("width_length") == "Length" and p.get("width_length_value")):
            p["width_length"] = "Length"
            p["width_length_value"] = "NA"
        if "Color" in all_options and not p.get("color_value"):
            p["color_value"] = "NA"
            p["color_code"] = "NA"

    return products, sorted(all_options)

def build_variant_definitions(product, option_names):
    """Build variant_definitions array for v2.0 POST (uses attribute_id + value)."""
    defs = []
    for name in option_names:
        attr_id = VARIANT_ATTRS.get(name)
        if not attr_id:
            continue
        if name == "Size":
            defs.append({"attribute_id": attr_id, "value": product.get("size_value", "NA")})
        elif name == "Shoe Width":
            defs.append({"attribute_id": attr_id, "value": product.get("width_length_value", "NA")})
        elif name == "Length":
            defs.append({"attribute_id": attr_id, "value": product.get("width_length_value", "NA")})
        elif name == "Color":
            defs.append({"attribute_id": attr_id, "value": product.get("color_value", "NA")})
    return defs

def build_variant_attribute_values(product, option_names):
    """Build variant_attribute_values for v2.1 POST (uses attribute_id + attribute_value)."""
    vals = []
    for name in option_names:
        attr_id = VARIANT_ATTRS.get(name)
        if not attr_id:
            continue
        if name == "Size":
            vals.append({"attribute_id": attr_id, "attribute_value": product.get("size_value", "NA")})
        elif name == "Shoe Width":
            vals.append({"attribute_id": attr_id, "attribute_value": product.get("width_length_value", "NA")})
        elif name == "Length":
            vals.append({"attribute_id": attr_id, "attribute_value": product.get("width_length_value", "NA")})
        elif name == "Color":
            vals.append({"attribute_id": attr_id, "attribute_value": product.get("color_value", "NA")})
    return vals

def build_product_codes(product, barcode_idx=None):
    """Build product_codes for barcode. Skip if already in LS."""
    barcode = product.get("barcode", "")
    if not barcode or not barcode.strip() or not barcode.isdigit() or len(barcode) < 6:
        return []
    if barcode_idx and barcode in barcode_idx:
        return []
    return [{"type": "UPC", "code": barcode}]

# =========================================================
# NEW FAMILIES: v2.0 POST with variants array
# =========================================================
def create_new_family(style_number, products, barcode_idx, name_idx, progress):
    """Create a new variant family via v2.0 POST with variants[].variant_definitions."""
    products, option_names = enforce_variant_consistency(products)

    family_name = products[0].get("name", style_number)
    if family_name.upper() in name_idx:
        family_name = f"{family_name} ({products[0].get('sku', '')})"

    # Build variants array
    variants = []
    for p in products:
        v = {
            "sku": p.get("sku", ""),
            "price_excluding_tax": float(p.get("retail_price", 0)) if p.get("retail_price") else 0,
            "supply_price": float(p.get("supply_price", 0)) if p.get("supply_price") else 0,
            "variant_definitions": build_variant_definitions(p, option_names),
        }
        codes = build_product_codes(p, barcode_idx)
        if codes:
            v["product_codes"] = codes
        variants.append(v)

    payload = {
        "name": family_name,
        "active": True,
        "variants": variants,
    }

    # Metadata from first product
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
        error_msg = str(result)
        if "already exists" in error_msg.lower():
            payload["name"] = f"{family_name} [{style_number}]"
            result, status = ls_api("POST", LS_BASE_20, "products", payload)

    if status not in (200, 201):
        return False, str(result)[:200], status

    # v2.0 POST returns {"data": ["id1", "id2", ...]}
    data = result.get("data", [])
    family_id = data[0] if isinstance(data, list) and data else ""
    return True, family_id, status

# =========================================================
# ADD TO EXISTING: v2.1 POST + v2.1 PUT
# =========================================================
def add_to_existing_family(family_name, products, existing_options, barcode_idx, progress, style_number):
    """Add variants to existing family. v2.1 POST creates, then v2.1 PUT sets SKU/price/barcode."""
    products, our_options = enforce_variant_consistency(products)

    results = []
    for p in products:
        # Step 1: v2.1 POST to add variant (matches family by name)
        post_payload = {
            "common": {"name": family_name},
            "details": {
                "variant_attribute_values": build_variant_attribute_values(p, our_options)
            }
        }

        result, status = ls_api("POST", LS_BASE_21, "products", post_payload)

        if status not in (200, 201):
            results.append((p.get("sku", ""), status, result))
            progress["failed"].append({
                "type": "add_to_existing",
                "style": style_number,
                "sku": p.get("sku", ""),
                "status": status,
                "error": str(result)[:200]
            })
            continue

        # Extract new variant ID
        new_id = result.get("data", "")
        if isinstance(new_id, list):
            new_id = new_id[0] if new_id else ""

        if not new_id:
            results.append((p.get("sku", ""), status, "no ID returned"))
            continue

        # Step 2: v2.1 PUT to set SKU, price, barcode
        put_details = {}
        sku = p.get("sku", "")
        if sku:
            put_details["product_codes"] = [{"type": "CUSTOM", "code": sku}]
        codes = build_product_codes(p, barcode_idx)
        if codes:
            existing_codes = put_details.get("product_codes", [])
            existing_codes.extend(codes)
            put_details["product_codes"] = existing_codes

        price = float(p.get("retail_price", 0)) if p.get("retail_price") else 0
        if price > 0:
            put_details["price_including_tax"] = price

        if put_details:
            put_payload = {"details": put_details}
            put_result, put_status = ls_api("PUT", LS_BASE_21, f"products/{new_id}", put_payload)
            if put_status not in (200, 201):
                progress["failed"].append({
                    "type": "update_variant",
                    "style": style_number,
                    "sku": sku,
                    "variant_id": new_id,
                    "status": put_status,
                    "error": str(put_result)[:200]
                })

        results.append((p.get("sku", ""), 200, new_id))

    return results

# =========================================================
# STANDALONE: v2.0 POST (simple product)
# =========================================================
def create_standalone(product, barcode_idx, name_idx):
    """Create a standalone product via v2.0 POST."""
    name = product.get("name", "")
    if name.upper() in name_idx:
        name = f"{name} ({product.get('sku', '')})"

    payload = {
        "name": name,
        "sku": product.get("sku", ""),
        "active": True,
        "price_excluding_tax": float(product.get("retail_price", 0)) if product.get("retail_price") else 0,
        "supply_price": float(product.get("supply_price", 0)) if product.get("supply_price") else 0,
    }

    if product.get("description"):
        payload["description"] = product["description"]

    codes = build_product_codes(product, barcode_idx)
    if codes:
        payload["product_codes"] = codes

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
        error_msg = str(result)
        if "already exists" in error_msg.lower():
            payload["name"] = f"{name} [{product.get('sku', '')}]"
            result, status = ls_api("POST", LS_BASE_20, "products", payload)

    if status in (200, 201):
        data = result.get("data", [])
        pid = data[0] if isinstance(data, list) and data else ""
        return True, pid, status
    return False, str(result)[:200], status

# =========================================================
# MAIN
# =========================================================
def main():
    print(f"Lightspeed Cleanup — Phase 2: Re-import as Variant Families")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    plan_path = f"{DOCS}/ls_reimport_plan.json"
    try:
        with open(plan_path) as f:
            plan = json.load(f)
    except FileNotFoundError:
        print("ERROR: ls_reimport_plan.json not found. Run Phase 0 first.")
        sys.exit(1)

    with open(f"{DOCS}/ls_fresh_barcode_idx.json") as f:
        barcode_idx = json.load(f)
    with open(f"{DOCS}/ls_fresh_name_idx.json") as f:
        name_idx = json.load(f)

    print("Loading metadata IDs from fresh catalog...")
    load_metadata_ids()

    progress = load_progress()
    done_families = set(progress["created_families"])
    done_existing = set(progress["added_to_existing"])
    done_standalone = set(progress["standalone_created"])

    stats = plan.get("stats", {})
    print(f"\nRe-import plan:")
    print(f"  New families (v2.0):    {stats.get('new_families', 0)} ({stats.get('new_family_products', 0)} products)")
    print(f"  Add to existing (v2.1): {stats.get('add_to_existing', 0)} ({stats.get('add_to_existing_products', 0)} products)")
    print(f"  Standalone:             {stats.get('standalone', 0)}")
    print(f"\nPrevious progress: {len(done_families)} families, {len(done_existing)} existing, {len(done_standalone)} standalone")
    print()

    # === Phase 2a: New families (v2.0) ===
    print("=" * 60)
    print("Phase 2a: Creating new variant families (v2.0 POST)")
    print("=" * 60)

    new_families = plan.get("new_families", [])
    count = 0
    total = len(new_families)

    for family in new_families:
        style = family["style_number"]
        if style in done_families:
            continue
        count += 1
        products = family["products"]

        if count % 25 == 1 or count <= 3:
            print(f"\n  [{count}/{total}] {style} ({len(products)} variants)")

        success, result_id, status = create_new_family(style, products, barcode_idx, name_idx, progress)

        if success:
            progress["created_families"].append(style)
            done_families.add(style)
            for p in products:
                name_idx[p["name"].upper()] = result_id
        else:
            progress["failed"].append({
                "type": "new_family", "style": style, "status": status,
                "error": str(result_id)[:200], "product_count": len(products)
            })
            print(f"  FAILED: {style} — HTTP {status}: {str(result_id)[:100]}")

        if count % 10 == 0:
            save_progress(progress)

    save_progress(progress)
    print(f"\n  Families created: {len(progress['created_families'])}")

    # === Phase 2b: Add to existing (v2.1) ===
    print("\n" + "=" * 60)
    print("Phase 2b: Adding to existing families (v2.1 POST + PUT)")
    print("=" * 60)

    existing_families = plan.get("add_to_existing", [])
    count = 0
    total = len(existing_families)

    for family in existing_families:
        style = family["style_number"]
        if style in done_existing:
            continue
        count += 1
        products = family["products"]
        family_id = family["existing_family_id"]
        existing_options = family.get("existing_variant_options", [])

        # Use pre-fetched family name (saved in plan by Phase 0)
        family_name = family.get("existing_family_name", "")
        if not family_name:
            # Fallback: fetch from LS
            parent_result, parent_status = ls_api("GET", LS_BASE_20, f"products/{family_id}")
            if parent_status == 200:
                pdata = parent_result.get("data", parent_result)
                if isinstance(pdata, list):
                    pdata = pdata[0]
                family_name = pdata.get("name", products[0].get("name", ""))

        if count % 25 == 1 or count <= 3:
            print(f"\n  [{count}/{total}] {style} → \"{family_name[:30]}\" ({len(products)} variants)")

        results = add_to_existing_family(family_name, products, existing_options, barcode_idx, progress, style)

        ok_count = sum(1 for _, s, _ in results if s in (200, 201))
        if ok_count == len(products):
            progress["added_to_existing"].append(style)
            done_existing.add(style)

        if count % 10 == 0:
            save_progress(progress)

    save_progress(progress)
    print(f"\n  Added to existing: {len(progress['added_to_existing'])}")

    # === Phase 2c: Standalone ===
    print("\n" + "=" * 60)
    print("Phase 2c: Creating standalone products")
    print("=" * 60)

    standalone = plan.get("standalone", [])
    count = 0
    total = len(standalone)

    for product in standalone:
        sku = product.get("sku", "")
        if sku in done_standalone:
            continue
        count += 1

        if count % 50 == 1 or count <= 3:
            print(f"\n  [{count}/{total}] {product.get('name', '')[:50]}")

        success, result_id, status = create_standalone(product, barcode_idx, name_idx)

        if success:
            progress["standalone_created"].append(sku)
            done_standalone.add(sku)
            name_idx[product["name"].upper()] = result_id
        else:
            progress["failed"].append({
                "type": "standalone", "sku": sku,
                "name": product.get("name", "")[:50],
                "status": status, "error": str(result_id)[:200]
            })

        if count % 10 == 0:
            save_progress(progress)

    save_progress(progress)

    # === Summary ===
    print("\n" + "=" * 60)
    print("PHASE 2 COMPLETE")
    print(f"  New families:    {len(progress['created_families'])}")
    print(f"  Added existing:  {len(progress['added_to_existing'])}")
    print(f"  Standalone:      {len(progress['standalone_created'])}")
    print(f"  Failed:          {len(progress['failed'])}")
    print(f"  Progress:        {PROGRESS_FILE}")
    print(f"  Finished:        {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

if __name__ == "__main__":
    main()
