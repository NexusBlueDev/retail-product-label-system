#!/usr/bin/env python3
"""
Lightspeed Space-SKU Remediation

Fixes 544 orphaned standalone products that were created during the April 13-16
cleanup because their source `style_number` contained an embedded color code
separated by a space (e.g. "MSW9165087 LIM"). The space propagated into the
generated SKU, which Lightspeed rejected via regex. The retry logic then pushed
each variant as a standalone product, losing variant grouping + most metadata.

This script:
  1. Loads docs/ls_space_sku_remediation.csv (manifest built from the import log)
  2. Joins with docs/normalized_ready.csv for full source fields
  3. Groups by cleaned style_number (embedded color code stripped)
  4. DELETEs each orphan via DELETE /api/2.0/products/{uuid}
  5. Rebuilds: variant families (>=2 variants) via POST with variant_definitions,
              standalones (1 variant) via plain POST
  6. Applies brand_id, supplier_id, product_type_id from ls_fresh_catalog.json

Usage:
  python3 docs/ls_space_sku_remediation.py --dry-run   # plan only, no API calls
  python3 docs/ls_space_sku_remediation.py             # live execution

Progress saved to docs/ls_space_sku_progress.json — resumable on interrupt.
"""

import csv
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
MANIFEST = f"{DOCS}/ls_space_sku_remediation.csv"
NORMALIZED = f"{DOCS}/normalized_ready.csv"
NORMALIZED_NR = f"{DOCS}/normalized_needs_review.csv"
CATALOG = f"{DOCS}/ls_fresh_catalog.json"
PROGRESS_FILE = f"{DOCS}/ls_space_sku_progress.json"
REQ_DELAY = 1.1

VARIANT_ATTRS = {
    "Color":  "c67f4856-9113-4447-aea0-6a4d9cafb176",
    "Size":   "8d72c173-2d55-4ef6-9813-d6bfbed613b2",
    "Length": "6c510e74-8d1d-4a3f-b948-7c78ad96d3f1",
    "Width":  "e7261267-9196-4701-88dd-1df8ffc374ec",
}

DRY_RUN = "--dry-run" in sys.argv

LS_TOKEN = subprocess.run(
    ["bash", "-c", f"grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()


def ls_api(method, endpoint, data=None):
    if DRY_RUN:
        return {"data": [{"id": "dry-run-id"}]}, 200
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method,
               f"{LS_BASE}/{endpoint}",
               "-H", f"Authorization: Bearer {LS_TOKEN}",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json"]
        if data is not None:
            cmd.extend(["-d", json.dumps(data)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        parts = r.stdout.rsplit('\n', 1)
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


def load_source_rows():
    """Load normalized_ready.csv + normalized_needs_review.csv keyed by product_id."""
    rows = {}
    for path in (NORMALIZED, NORMALIZED_NR):
        with open(path) as f:
            reader = csv.DictReader(f)
            id_key = '\ufeff"product_id"'
            for row in reader:
                pid = (row.get(id_key) or row.get('product_id') or '').strip('"')
                if pid.isdigit() and int(pid) not in rows:
                    rows[int(pid)] = row
    return rows


def load_catalog_indexes():
    """Build SUPPLIER/BRAND/CATEGORY id lookups from ls_fresh_catalog.json."""
    print("Loading LS catalog for metadata IDs...")
    with open(CATALOG) as f:
        catalog = json.load(f)
    suppliers, brands, categories = {}, {}, {}
    for p in catalog:
        s = p.get("supplier")
        if isinstance(s, dict) and s.get("name"):
            suppliers[s["name"].upper()] = s.get("id")
        b = p.get("brand")
        if isinstance(b, dict) and b.get("name"):
            brands[b["name"].upper()] = b.get("id")
        c = p.get("product_category")
        if isinstance(c, dict) and c.get("name"):
            categories[c["name"].upper()] = c.get("id")
    print(f"  Suppliers: {len(suppliers)}  Brands: {len(brands)}  Categories: {len(categories)}")
    return suppliers, brands, categories


def build_plan(manifest_rows, source_rows):
    """Group manifest by clean style_number; classify as family vs standalone."""
    groups = defaultdict(list)
    for m in manifest_rows:
        style_clean = m['style_number_clean']
        if not style_clean:
            continue
        pid = int(m['source_pid'])
        src = source_rows.get(pid)
        if not src:
            continue
        groups[style_clean].append({
            'pid': pid,
            'ls_product_id': m['ls_product_id'],
            'orphan_sku': m['orphan_sku'],
            'src': src,
            'embedded_color_code': m['embedded_color_code'],
        })

    families = {k: v for k, v in groups.items() if len(v) >= 2}
    standalones = {k: v for k, v in groups.items() if len(v) == 1}
    return families, standalones


def build_variant_options(src):
    """Build variant_definitions list from a source row."""
    defs = []
    size = (src.get('size_value') or '').strip()
    if size and size not in ('NA',):
        defs.append({"attribute_id": VARIANT_ATTRS["Size"], "value": size})
    wl_kind = (src.get('width_length') or '').strip()
    wl_val = (src.get('width_length_value') or '').strip()
    if wl_val and wl_val not in ('NA', ''):
        if wl_kind == 'Length':
            defs.append({"attribute_id": VARIANT_ATTRS["Length"], "value": wl_val})
        else:
            defs.append({"attribute_id": VARIANT_ATTRS["Width"], "value": wl_val})
    color = (src.get('color_value') or '').strip()
    if color and color not in ('NA',):
        defs.append({"attribute_id": VARIANT_ATTRS["Color"], "value": color})
    return defs


def build_standalone_payload(group_item, brand_ids, supplier_ids, category_ids):
    src = group_item['src']
    sku = group_item['orphan_sku']
    name = (src.get('item_name') or '').strip() or sku
    price = float(src.get('retail_price') or 0)
    supply = float(src.get('supply_price') or 0)
    barcode = (src.get('barcode') or '').strip()
    payload = {
        "name": name,
        "sku": sku,
        "active": True,
        "price_excluding_tax": price,
    }
    if supply > 0:
        payload["supply_price"] = supply
    desc = (src.get('description') or '').strip()
    if desc:
        payload["description"] = desc
    if barcode.isdigit() and len(barcode) >= 6:
        payload["product_codes"] = [{"type": "UPC", "code": barcode}]
    brand = (src.get('brand') or '').upper()
    if brand and brand_ids.get(brand):
        payload["brand_id"] = brand_ids[brand]
    supplier = (src.get('supplier') or '').upper()
    if supplier and supplier_ids.get(supplier):
        payload["supplier_id"] = supplier_ids[supplier]
    category = (src.get('category') or '').upper()
    if category and category_ids.get(category):
        payload["product_type_id"] = category_ids[category]
    return payload


def build_family_payload(style, items, brand_ids, supplier_ids, category_ids):
    """Build variant family POST payload. Ensures all variants share the same attribute set."""
    first = items[0]['src']
    family_name = (first.get('item_name') or '').strip() or style

    per_item_defs = [(it, build_variant_options(it['src'])) for it in items]
    all_attr_ids = []
    seen_attrs = set()
    for _, defs in per_item_defs:
        for d in defs:
            if d['attribute_id'] not in seen_attrs:
                seen_attrs.add(d['attribute_id'])
                all_attr_ids.append(d['attribute_id'])

    variants = []
    seen_combos = set()
    seen_barcodes = set()
    for it, defs in per_item_defs:
        if not defs:
            continue
        def_map = {d['attribute_id']: d['value'] for d in defs}
        normalized_defs = [{"attribute_id": a, "value": def_map.get(a, 'NA')} for a in all_attr_ids]
        combo_key = "|".join(f"{d['attribute_id']}={d['value']}" for d in normalized_defs)
        if combo_key in seen_combos:
            continue
        seen_combos.add(combo_key)

        src = it['src']
        price = float(src.get('retail_price') or 0)
        supply = float(src.get('supply_price') or 0)
        v = {
            "sku": it['orphan_sku'],
            "price_excluding_tax": price,
            "variant_definitions": normalized_defs,
        }
        if supply > 0:
            v["supply_price"] = supply
        barcode = (src.get('barcode') or '').strip()
        if barcode.isdigit() and len(barcode) >= 6 and barcode not in seen_barcodes:
            v["product_codes"] = [{"type": "UPC", "code": barcode}]
            seen_barcodes.add(barcode)
        variants.append(v)

    if len(variants) < 2:
        return None  # caller will handle fallback

    payload = {
        "name": family_name,
        "active": True,
        "variants": variants,
    }
    brand = (first.get('brand') or '').upper()
    if brand and brand_ids.get(brand):
        payload["brand_id"] = brand_ids[brand]
    supplier = (first.get('supplier') or '').upper()
    if supplier and supplier_ids.get(supplier):
        payload["supplier_id"] = supplier_ids[supplier]
    category = (first.get('category') or '').upper()
    if category and category_ids.get(category):
        payload["product_type_id"] = category_ids[category]
    return payload


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "started": datetime.now(timezone.utc).isoformat(),
            "deleted": [],
            "delete_failed": [],
            "created_families": [],
            "standalones_created": [],
            "rebuild_failed": [],
        }


def save_progress(p):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(p, f, indent=2)


def main():
    print("=" * 70)
    print(f"Lightspeed Space-SKU Remediation {'[DRY RUN]' if DRY_RUN else '[LIVE]'}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    if not LS_TOKEN and not DRY_RUN:
        print("ERROR: LIGHTSPEED_TOKEN not found in .env.local")
        sys.exit(1)

    # Load inputs
    with open(MANIFEST) as f:
        manifest_rows = list(csv.DictReader(f))
    print(f"Manifest: {len(manifest_rows)} orphan rows")

    source_rows = load_source_rows()
    print(f"Source rows: {len(source_rows)}")

    brand_ids, supplier_ids, category_ids = {}, {}, {}
    if not DRY_RUN:
        supplier_ids, brand_ids, category_ids = load_catalog_indexes()
    else:
        print("(dry-run: skipping catalog load for speed)")

    families, standalones = build_plan(manifest_rows, source_rows)
    family_count = sum(len(v) for v in families.values())
    print(f"\nPlan:")
    print(f"  Variant families: {len(families)} styles / {family_count} variants")
    print(f"  Standalones:      {len(standalones)} items")
    print(f"  Total:            {family_count + len(standalones)} products")

    if DRY_RUN:
        print("\nTop 10 family plans:")
        for style, items in sorted(families.items(), key=lambda x: -len(x[1]))[:10]:
            src = items[0]['src']
            print(f"  {style}: {len(items)} variants | {src.get('item_name','')[:40]} | brand={src.get('brand','')}")
        print("\nSample standalone plans:")
        for style, items in list(standalones.items())[:5]:
            src = items[0]['src']
            print(f"  {style}: sku={items[0]['orphan_sku']} | {src.get('item_name','')[:40]}")
        print("\nMetadata coverage check (UPPERCASE lookups needed):")
        brands_needed = set((i['src'].get('brand') or '').upper() for g in list(families.values()) + list(standalones.values()) for i in g)
        cats_needed = set((i['src'].get('category') or '').upper() for g in list(families.values()) + list(standalones.values()) for i in g)
        supps_needed = set((i['src'].get('supplier') or '').upper() for g in list(families.values()) + list(standalones.values()) for i in g)
        print(f"  Distinct brands needed: {len([b for b in brands_needed if b])}")
        print(f"  Distinct categories needed: {len([c for c in cats_needed if c])}")
        print(f"  Distinct suppliers needed: {len([s for s in supps_needed if s])}")
        print("\nDRY RUN complete. No API calls made.")
        return

    progress = load_progress()
    deleted_ids = set(progress.get("deleted", []))
    failed_deletes = {f['ls_product_id'] for f in progress.get("delete_failed", [])}
    done_families = set(progress.get("created_families", []))
    done_standalones = set(progress.get("standalones_created", []))

    # === Phase A: DELETE orphans ===
    all_orphan_ids = [m['ls_product_id'] for m in manifest_rows if m['ls_product_id']]
    to_delete = [uid for uid in all_orphan_ids if uid not in deleted_ids and uid not in failed_deletes]
    print(f"\n{'='*70}\nPhase A: DELETE {len(to_delete)} orphans (skipping {len(deleted_ids)} already done)\n{'='*70}")

    for i, uid in enumerate(to_delete):
        result, status = ls_api("DELETE", f"products/{uid}")
        if status in (200, 204):
            progress["deleted"].append(uid)
            deleted_ids.add(uid)
        elif status == 404:
            # Already gone — treat as deleted
            progress["deleted"].append(uid)
            deleted_ids.add(uid)
        else:
            progress["delete_failed"].append({"id": uid, "status": status, "error": str(result)[:200]})

        if (i + 1) % 25 == 0:
            save_progress(progress)
            pct = (i + 1) / len(to_delete) * 100
            print(f"  [{pct:.1f}%] deleted {len(deleted_ids)}/{len(all_orphan_ids)} | fails {len(progress['delete_failed'])}")

    save_progress(progress)
    print(f"Phase A done. Deleted: {len(deleted_ids)} | Failed: {len(progress['delete_failed'])}")

    # === Phase B: Rebuild as variant families ===
    print(f"\n{'='*70}\nPhase B: Create {len(families)} variant families\n{'='*70}")
    fam_success, fam_fail = 0, 0
    for i, (style, items) in enumerate(families.items()):
        if style in done_families:
            continue
        payload = build_family_payload(style, items, brand_ids, supplier_ids, category_ids)
        if payload is None:
            # Fallback to per-item standalone
            for it in items:
                sp = build_standalone_payload(it, brand_ids, supplier_ids, category_ids)
                r, s = ls_api("POST", "products", sp)
                if s in (200, 201):
                    progress["standalones_created"].append(it['orphan_sku'])
                else:
                    progress["rebuild_failed"].append({"style": style, "sku": it['orphan_sku'], "status": s, "error": str(r)[:200]})
            continue

        result, status = ls_api("POST", "products", payload)
        if status == 422 and "already exists" in str(result).lower():
            payload["name"] = f"{payload['name']} [{style}]"
            result, status = ls_api("POST", "products", payload)
        if status == 422 and "Product codes must be unique" in str(result):
            for v in payload.get("variants", []):
                v.pop("product_codes", None)
            result, status = ls_api("POST", "products", payload)

        if status in (200, 201):
            progress["created_families"].append(style)
            done_families.add(style)
            fam_success += 1
        else:
            fam_fail += 1
            progress["rebuild_failed"].append({"type": "family", "style": style, "status": status, "error": str(result)[:300]})

        if (i + 1) % 25 == 0:
            save_progress(progress)
            print(f"  [{i+1}/{len(families)}] families created: {fam_success} | failed: {fam_fail}")

    save_progress(progress)
    print(f"Phase B done. Families: {fam_success} created, {fam_fail} failed")

    # === Phase C: Rebuild standalones ===
    print(f"\n{'='*70}\nPhase C: Create {len(standalones)} standalones\n{'='*70}")
    sa_success, sa_fail = 0, 0
    for i, (style, items) in enumerate(standalones.items()):
        it = items[0]
        if it['orphan_sku'] in done_standalones:
            continue
        payload = build_standalone_payload(it, brand_ids, supplier_ids, category_ids)
        result, status = ls_api("POST", "products", payload)
        if status == 422 and "already exists" in str(result).lower():
            payload["name"] = f"{payload['name']} [{it['orphan_sku']}]"
            payload.pop("product_codes", None)
            result, status = ls_api("POST", "products", payload)
        if status == 422 and "Product codes must be unique" in str(result):
            payload.pop("product_codes", None)
            result, status = ls_api("POST", "products", payload)

        if status in (200, 201):
            progress["standalones_created"].append(it['orphan_sku'])
            done_standalones.add(it['orphan_sku'])
            sa_success += 1
        else:
            sa_fail += 1
            progress["rebuild_failed"].append({"type": "standalone", "sku": it['orphan_sku'], "status": status, "error": str(result)[:300]})

        if (i + 1) % 25 == 0:
            save_progress(progress)
            print(f"  [{i+1}/{len(standalones)}] standalones: {sa_success} ok, {sa_fail} failed")

    progress["finished"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    print(f"\n{'='*70}\nCOMPLETE\n{'='*70}")
    print(f"  Deleted orphans:    {len(progress['deleted'])}")
    print(f"  Delete failures:    {len(progress['delete_failed'])}")
    print(f"  Families created:   {len(progress['created_families'])}")
    print(f"  Standalones built:  {len(progress['standalones_created'])}")
    print(f"  Rebuild failures:   {len(progress['rebuild_failed'])}")
    print(f"  Finished:           {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
