#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 2 Final: Handle all remaining failures.

1. Supplier-mismatch add-to-existing (1,283): Create as standalone via v2.0
2. 1-variant "families" (22): Create as standalone
3. Duplicate barcode families (6): Strip barcodes, retry as family
4. Duplicate variant defs (2): Create each variant as standalone
5. SKU already exists (16): Skip — already in LS
"""

import json
import subprocess
import time
import sys
from datetime import datetime, timezone
from collections import defaultdict

LS_BASE_20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
PROGRESS_FILE = f"{DOCS}/ls_cleanup_phase2_progress.json"
REQ_DELAY = 1.1

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

def ls_api(method, endpoint, data=None):
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
               f"{LS_BASE_20}/{endpoint}",
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
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status

def load_metadata():
    global SUPPLIER_IDS, BRAND_IDS, CATEGORY_IDS
    with open(f"{DOCS}/ls_fresh_catalog.json") as f:
        catalog = json.load(f)
    for p in catalog:
        s = p.get("supplier")
        if s and isinstance(s, dict):
            SUPPLIER_IDS[s.get("name", "").upper()] = s.get("id")
        b = p.get("brand")
        if b and isinstance(b, dict):
            BRAND_IDS[b.get("name", "").upper()] = b.get("id")
        c = p.get("product_category")
        if c and isinstance(c, dict):
            CATEGORY_IDS[c.get("name", "").upper()] = c.get("id")

def create_standalone(product, name_idx):
    """Create a standalone product via v2.0 POST."""
    name = product.get("name", "")
    sku = product.get("sku", "")

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
    if barcode and barcode.isdigit() and len(barcode) >= 6:
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

    result, status = ls_api("POST", "products", payload)

    if status == 422:
        err = str(result)
        if "already exists" in err.lower():
            # Try with modified name and without barcode
            payload["name"] = f"{name} [{sku}]"
            payload.pop("product_codes", None)
            result, status = ls_api("POST", "products", payload)

    if status in (200, 201):
        data = result.get("data", [])
        pid = data[0] if isinstance(data, list) and data else ""
        name_idx[product["name"].upper()] = pid
        return True, pid
    return False, str(result)[:200]

def main():
    print(f"Lightspeed Cleanup — Phase 2 Final Fix")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    with open(PROGRESS_FILE) as f:
        progress = json.load(f)
    with open(f"{DOCS}/ls_reimport_plan.json") as f:
        plan = json.load(f)
    with open(f"{DOCS}/ls_fresh_name_idx.json") as f:
        name_idx = json.load(f)

    print("Loading metadata...")
    load_metadata()

    failures = progress.get("failed", [])
    print(f"Failures to process: {len(failures)}")

    # Categorize failures
    supplier_fails = []  # add-to-existing supplier mismatches → create as standalone
    single_variant_fails = []  # 1-variant families → create as standalone
    dup_barcode_fails = []  # duplicate barcodes → strip and retry
    dup_variant_fails = []  # duplicate variants → create standalone each
    skip_exists = []  # already exists → skip

    for f in failures:
        err = f.get("error", "")
        ftype = f.get("type", "")

        if "identical suppliers" in err:
            supplier_fails.append(f)
        elif "Array must have at least" in err:
            single_variant_fails.append(f)
        elif "Product codes must be unique" in err:
            dup_barcode_fails.append(f)
        elif "variant definition must be unique" in err:
            dup_variant_fails.append(f)
        elif "Already exists" in err:
            skip_exists.append(f)
        else:
            skip_exists.append(f)  # treat unknown as skip

    print(f"\n  Supplier mismatch → standalone: {len(supplier_fails)}")
    print(f"  1-variant families → standalone: {len(single_variant_fails)}")
    print(f"  Duplicate barcodes → strip & retry: {len(dup_barcode_fails)}")
    print(f"  Duplicate variants → standalone: {len(dup_variant_fails)}")
    print(f"  Already exists → skip: {len(skip_exists)}")

    # Clear all old failures
    progress["failed"] = []

    # === 1. Supplier mismatches: get products from plan and create as standalone ===
    print(f"\n{'='*70}")
    print(f"1. Creating {len(supplier_fails)} supplier-mismatch products as standalone")
    print(f"{'='*70}")

    # Build lookup: style → products from the plan
    plan_products = {}
    for fam in plan.get("add_to_existing", []):
        for p in fam["products"]:
            key = f"{fam['style_number']}|{p.get('sku', '')}"
            plan_products[key] = p

    created_standalone = set(progress.get("standalone_created", []))
    success = 0
    fail = 0

    for i, f in enumerate(supplier_fails):
        style = f.get("style", "")
        sku = f.get("sku", "")
        key = f"{style}|{sku}"

        product = plan_products.get(key)
        if not product:
            # Try finding by style in the plan
            for fam in plan.get("add_to_existing", []):
                if fam["style_number"] == style:
                    for p in fam["products"]:
                        if p.get("sku") == sku or not sku:
                            product = p
                            break
                    break

        if not product:
            progress["failed"].append({"type": "final_no_product", "style": style, "sku": sku})
            fail += 1
            continue

        if product.get("sku", "") in created_standalone:
            continue

        if (i + 1) % 100 == 0 or i == 0:
            print(f"  [{i+1}/{len(supplier_fails)}] {product.get('name','')[:40]}")

        ok, result = create_standalone(product, name_idx)
        if ok:
            progress["standalone_created"].append(product.get("sku", ""))
            created_standalone.add(product.get("sku", ""))
            success += 1
        else:
            fail += 1
            progress["failed"].append({
                "type": "final_standalone",
                "sku": product.get("sku", ""),
                "style": style,
                "error": result
            })

        if (i + 1) % 20 == 0:
            with open(PROGRESS_FILE, "w") as pf:
                json.dump(progress, pf, indent=2)

    print(f"  Done: {success} created, {fail} failed")

    # === 2. Single-variant families → standalone ===
    print(f"\n{'='*70}")
    print(f"2. Creating {len(single_variant_fails)} single-variant products as standalone")
    print(f"{'='*70}")

    # These are style numbers from new_families in the plan
    nf_by_style = {fam["style_number"]: fam for fam in plan.get("new_families", [])}

    for f in single_variant_fails:
        style = f.get("style", "")
        family = nf_by_style.get(style)
        if not family:
            continue

        for p in family["products"]:
            if p.get("sku", "") in created_standalone:
                continue
            ok, result = create_standalone(p, name_idx)
            if ok:
                progress["standalone_created"].append(p.get("sku", ""))
                created_standalone.add(p.get("sku", ""))
                success += 1
            else:
                progress["failed"].append({
                    "type": "final_single_variant",
                    "sku": p.get("sku", ""),
                    "error": result
                })

    print(f"  Done")

    # === 3. Duplicate barcode families → strip barcodes, retry as family ===
    print(f"\n{'='*70}")
    print(f"3. Retrying {len(dup_barcode_fails)} duplicate-barcode families (no barcodes)")
    print(f"{'='*70}")

    done_families = set(progress.get("created_families", []))

    for f in dup_barcode_fails:
        style = f.get("style", "")
        if style in done_families:
            continue

        family = nf_by_style.get(style)
        if not family:
            continue

        products = family["products"]
        # Determine variant options
        all_options = set()
        for p in products:
            if p.get("size_value"): all_options.add("Size")
            if p.get("width_length") == "Width" and p.get("width_length_value"): all_options.add("Width")
            if p.get("width_length") == "Length" and p.get("width_length_value"): all_options.add("Length")
            if p.get("color_value"): all_options.add("Color")

        option_names = sorted(all_options)

        variants = []
        seen_combos = set()
        for p in products:
            defs = []
            combo = []
            for name in option_names:
                attr_id = VARIANT_ATTRS.get(name)
                if not attr_id: continue
                if name == "Size": val = p.get("size_value", "NA")
                elif name in ("Width", "Shoe Width"): val = p.get("width_length_value", "NA") if p.get("width_length") == "Width" else "NA"
                elif name == "Length": val = p.get("width_length_value", "NA") if p.get("width_length") == "Length" else "NA"
                elif name == "Color": val = p.get("color_value", "NA")
                else: val = "NA"
                if not val: val = "NA"
                defs.append({"attribute_id": attr_id, "value": val})
                combo.append(f"{name}={val}")

            ck = "|".join(combo)
            if ck in seen_combos: continue
            seen_combos.add(ck)

            v = {
                "sku": p.get("sku", ""),
                "price_excluding_tax": float(p.get("retail_price", 0)) if p.get("retail_price") else 0,
                "supply_price": float(p.get("supply_price", 0)) if p.get("supply_price") else 0,
                "variant_definitions": defs,
                # NO product_codes — barcodes stripped
            }
            variants.append(v)

        if len(variants) < 2:
            # Create each as standalone
            for p in products:
                if p.get("sku", "") not in created_standalone:
                    ok, _ = create_standalone(p, name_idx)
                    if ok:
                        progress["standalone_created"].append(p.get("sku", ""))
                        created_standalone.add(p.get("sku", ""))
            continue

        family_name = products[0].get("name", style)
        if family_name.upper() in name_idx:
            family_name = f"{family_name} ({products[0].get('sku', '')})"

        payload = {"name": family_name, "active": True, "variants": variants}
        first = products[0]
        brand = first.get("brand", "")
        if brand and BRAND_IDS.get(brand.upper()):
            payload["brand_id"] = BRAND_IDS[brand.upper()]
        supplier = first.get("supplier", "")
        if supplier and SUPPLIER_IDS.get(supplier.upper()):
            payload["supplier_id"] = SUPPLIER_IDS[supplier.upper()]

        result, status = ls_api("POST", "products", payload)
        if status == 422 and "already exists" in str(result).lower():
            payload["name"] = f"{family_name} [{style}]"
            result, status = ls_api("POST", "products", payload)

        if status in (200, 201):
            progress["created_families"].append(style)
            done_families.add(style)
        else:
            progress["failed"].append({"type": "final_dup_barcode", "style": style, "error": str(result)[:200]})

    print(f"  Done")

    # === 4. Duplicate variant families → each variant as standalone ===
    print(f"\n{'='*70}")
    print(f"4. Creating {len(dup_variant_fails)} duplicate-variant products as standalone")
    print(f"{'='*70}")

    for f in dup_variant_fails:
        style = f.get("style", "")
        family = nf_by_style.get(style)
        if not family: continue
        for p in family["products"]:
            if p.get("sku", "") in created_standalone:
                continue
            ok, _ = create_standalone(p, name_idx)
            if ok:
                progress["standalone_created"].append(p.get("sku", ""))
                created_standalone.add(p.get("sku", ""))

    print(f"  Done")

    # === 5. Already exists → just count ===
    print(f"\n  Skipped {len(skip_exists)} products that already exist in LS")

    # Save final state
    with open(PROGRESS_FILE, "w") as pf:
        json.dump(progress, pf, indent=2)

    # === Summary ===
    fam = len(progress.get("created_families", []))
    exist = len(progress.get("added_to_existing", []))
    solo = len(progress.get("standalone_created", []))
    fails = len(progress.get("failed", []))

    print(f"\n{'='*70}")
    print("PHASE 2 FINAL — COMPLETE")
    print(f"{'='*70}")
    print(f"  Families created:    {fam}/635")
    print(f"  Added to existing:   {exist}/561")
    print(f"  Standalone created:  {solo}/1229+")
    print(f"  Remaining failures:  {fails}")
    print(f"  Finished:            {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
