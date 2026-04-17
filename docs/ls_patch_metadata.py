#!/usr/bin/env python3
"""
Patch newly-created families with missing supplier_id / product_type_id.

The space-SKU remediation rebuild set brand_id correctly but missed
supplier_id and product_type_id because our source data uses shorter
informal names that didn't match LS's full taxonomy.

This script:
  1. Resolves supplier_id and product_type_id per-family using an alias map
  2. PUTs each variant to apply supplier_id + product_type_id
  3. Logs unresolved (style, source_supplier, source_category) to
     docs/ls_patch_unresolved.csv for Corrinne's review

Usage: python3 docs/ls_patch_metadata.py [--dry-run]
"""
import csv, json, subprocess, sys, time
from collections import defaultdict
from datetime import datetime, timezone

DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
REQ_DELAY = 1.1
DRY_RUN = "--dry-run" in sys.argv

TOKEN = subprocess.run(
    ["bash","-c","grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()

# Supplier source → LS canonical name alias map (built from diagnostic run)
SUPPLIER_ALIASES = {
    "Miller International": "Miller International, Inc. - Cinch",
    "HATCO (RHE Hatco, Inc.)": "HATCO",
    "M&F Western Products": "M&F Western",
    "M&F Western Products LLC": "M&F Western",
    "Kontoor Brands": "Kontoor Brands, Inc.",
    "Ariat International": "Ariat",
    "JT International": "JT International Distributors, Inc.",
    "Rocky Brands US": "Rocky Brands",
    "Dan Post": "Dan Post Boot Company",
}

# Category source → LS canonical name alias map
CATEGORY_ALIASES = {
    "Apparel - Western Shirt": "Apparel - Western Woven Shirts",
    "Apparel - Western  Shirt": "Apparel - Western Woven Shirts",
    "Apparel - Woven Shirt": "Apparel - Western Woven Shirts",
    "Apparel - w Shirt": "Apparel - Western Woven Shirts",
    "Apparel - woven Shirt": "Apparel - Western Woven Shirts",
    "Hats - Straw": "Hats - Straw Cowboy Hats",
    "Hat - Straw": "Hats - Straw Cowboy Hats",
    "Hats - Felt": "Hats - Felt Cowboy Hats",
    "Hat - Felt": "Hats - Felt Cowboy Hats",
    "Apparel - T-Shirt": "Apparel - T-Shirts & Tanks",
    "Apparel - T-shirt": "Apparel - T-Shirts & Tanks",
    "Apparel - Tank": "Apparel - T-Shirts & Tanks",
    "Apparel - Mid Layer": "Apparel - Mid-Layer",
    "Apparel - Hoodie": "Apparel - Hoodies & Sweatshirts",
    "Apparel - Sweatshirt": "Apparel - Hoodies & Sweatshirts",
    "Apparel - Top": "Apparel - Tops/Blouses",
    "Apparel - Sport Jacket": "Apparel - Suits & Sport Coats",
    "Apparel - Show Coat": "Apparel - Suits & Sport Coats",
    "Footwear - Accessories": "Footwear - Footwear Accessories & Care",
    "Home - Decor": "Gifts & Novelties-Gift Items/Small Goods/HomeDecor",
    "Decor": "Gifts & Novelties-Gift Items/Small Goods/HomeDecor",
    "Horse Feed": "Horse/Rodeo - Feed, Water & Stable Supplies",
    "Fragrance - Cologne": "Accessories - Fragrance",
}


def ls_api(method, endpoint, data=None):
    if DRY_RUN:
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
        body = parts[0] if parts else ''
        status = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body[:500]}
        if status == 429:
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status


def build_indexes():
    print("Loading LS catalog indexes...")
    with open(f"{DOCS}/ls_fresh_catalog.json") as f:
        catalog = json.load(f)
    suppliers, categories = {}, {}
    for p in catalog:
        s = p.get("supplier")
        if isinstance(s, dict) and s.get("name"):
            suppliers[s["name"]] = s["id"]
        c = p.get("product_category")
        if isinstance(c, dict) and c.get("name"):
            categories[c["name"]] = c["id"]
    print(f"  Suppliers: {len(suppliers)}  Categories: {len(categories)}")
    return suppliers, categories


def resolve_supplier(source_name, supplier_ids):
    if not source_name:
        return None, None
    canonical = SUPPLIER_ALIASES.get(source_name, source_name)
    return supplier_ids.get(canonical), canonical


def resolve_category(source_name, category_ids):
    if not source_name:
        return None, None
    canonical = CATEGORY_ALIASES.get(source_name, source_name)
    return category_ids.get(canonical), canonical


def search_family(style, orphan_sku):
    """Find the family we just created for this style via the first variant SKU."""
    r, status = ls_api("GET", f"search?type=products&q={orphan_sku}")
    if status != 200:
        return None
    results = r.get("data", [])
    # Our families are named "... [STYLE]" — find one with that pattern
    for p in results:
        name = p.get("name") or ""
        if f"[{style}]" in name and not p.get("deleted_at"):
            return p
    # Fallback: just an exact-SKU match that is active
    for p in results:
        if p.get("sku") == orphan_sku and not p.get("deleted_at"):
            return p
    return None


def main():
    print("=" * 70)
    print(f"LS Metadata Patch {'[DRY RUN]' if DRY_RUN else '[LIVE]'}")
    print("=" * 70)

    with open(f"{DOCS}/ls_space_sku_progress.json") as f:
        progress = json.load(f)
    created_families = progress.get("created_families", [])
    print(f"Newly-created families: {len(created_families)}")

    # Load source-row data per style (first row per style for metadata)
    source_rows = {}
    for path in ["normalized_ready.csv", "normalized_needs_review.csv"]:
        with open(f"{DOCS}/{path}") as f:
            reader = csv.DictReader(f)
            id_key = '\ufeff"product_id"'
            for row in reader:
                raw_style = (row.get("style_number") or "").strip()
                clean = raw_style.split()[0] if raw_style else ""
                if clean and clean not in source_rows:
                    source_rows[clean] = row

    supplier_ids, category_ids = build_indexes()

    unresolved = []
    stats = {"patched_variants": 0, "families_ok": 0, "families_no_change": 0, "errors": 0}

    # Load manifest to find the first orphan_sku per created-family style
    style_to_sku = {}
    with open(f"{DOCS}/ls_space_sku_remediation.csv") as f:
        for r in csv.DictReader(f):
            s = r["style_number_clean"]
            if s not in style_to_sku:
                style_to_sku[s] = r["orphan_sku"]

    for i, style in enumerate(created_families):
        src = source_rows.get(style)
        if not src:
            unresolved.append({"style": style, "reason": "no_source_row"})
            continue

        src_sup = src.get("supplier") or ""
        src_cat = src.get("category") or ""
        sup_id, sup_canon = resolve_supplier(src_sup, supplier_ids)
        cat_id, cat_canon = resolve_category(src_cat, category_ids)

        if not sup_id and not cat_id:
            unresolved.append({"style": style, "src_supplier": src_sup, "src_category": src_cat,
                              "reason": "no_mapping_for_either"})
            continue

        # Find the family via search by an orphan SKU
        orphan_sku = style_to_sku.get(style)
        if not orphan_sku:
            unresolved.append({"style": style, "reason": "no_orphan_sku_in_manifest"})
            continue

        r, status = ls_api("GET", f"search?type=products&q={orphan_sku}")
        if status != 200:
            stats["errors"] += 1
            unresolved.append({"style": style, "reason": f"search_failed_{status}"})
            continue

        candidates = [p for p in r.get("data", []) if not p.get("deleted_at")
                       and p.get("active") and p.get("sku") == orphan_sku]

        if not candidates:
            unresolved.append({"style": style, "orphan_sku": orphan_sku,
                              "reason": "variant_not_found_active"})
            continue

        # Get the variant_parent_id from the first candidate — that's the family ID
        v = candidates[0]
        family_id = v.get("variant_parent_id") or v.get("id")
        if not family_id:
            unresolved.append({"style": style, "reason": "no_family_id_found"})
            continue

        # PUT update to the family parent
        patch_payload = {}
        if sup_id:
            patch_payload["supplier_id"] = sup_id
        if cat_id:
            patch_payload["product_type_id"] = cat_id

        if not patch_payload:
            stats["families_no_change"] += 1
            continue

        result, status = ls_api("PUT", f"products/{family_id}", patch_payload)
        if status in (200, 201):
            stats["families_ok"] += 1
            stats["patched_variants"] += len(candidates)
        else:
            stats["errors"] += 1
            unresolved.append({
                "style": style, "family_id": family_id,
                "supplier_mapped": sup_canon, "category_mapped": cat_canon,
                "reason": f"PUT_failed_{status}",
                "error": str(result)[:200]
            })

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(created_families)}] patched: {stats['families_ok']} | errors: {stats['errors']} | unresolved: {len(unresolved)}")

    # Write unresolved report
    if unresolved:
        keys = set()
        for u in unresolved:
            keys.update(u.keys())
        keys = sorted(keys)
        with open(f"{DOCS}/ls_patch_unresolved.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(unresolved)
        print(f"\nUnresolved: {len(unresolved)} → {DOCS}/ls_patch_unresolved.csv")

    print(f"\n{'='*70}\nPATCH COMPLETE\n{'='*70}")
    print(f"  Families patched:   {stats['families_ok']}")
    print(f"  Families no change: {stats['families_no_change']}")
    print(f"  Errors:             {stats['errors']}")
    print(f"  Finished:           {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
