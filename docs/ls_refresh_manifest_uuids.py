#!/usr/bin/env python3
"""
Refresh the manifest's ls_product_id column with CURRENT live UUIDs.

The original manifest was built from docs/ls_fresh_sku_idx.json (Apr 15 19:08)
which was captured BEFORE the Phase 1 cleanup soft-deleted ~5k products. So our
manifest UUIDs point at soft-deleted shadow records — not the currently-live
orphans Corrinne actually sees.

This script:
  - For each distinct style_number in the manifest, search LS for matching SKUs
  - Updates docs/ls_space_sku_remediation.csv with fresh ls_product_id values
  - Flags any SKUs no longer findable in LS (already gone)

Writes to:
  - docs/ls_space_sku_remediation.csv (in-place update)
  - docs/ls_space_sku_remediation_v2.csv (backup-safe new file)
"""
import csv, json, subprocess, sys, time
from collections import defaultdict

DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
MANIFEST = f"{DOCS}/ls_space_sku_remediation.csv"
OUT = f"{DOCS}/ls_space_sku_remediation_v2.csv"
LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
REQ_DELAY = 1.1

TOKEN = subprocess.run(
    ["bash","-c",f"grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()

def search_by_style(style):
    """Return list of {id, sku, deleted_at, active, family_id, name} for matching products."""
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        r = subprocess.run(
            ["curl","-s","-G","-X","GET",
             f"{LS_BASE}/search",
             "--data-urlencode","type=products",
             "--data-urlencode",f"q={style}",
             "-H",f"Authorization: Bearer {TOKEN}","-H","Accept: application/json"],
            capture_output=True, text=True, timeout=30
        )
        try:
            d = json.loads(r.stdout)
            return d.get('data', [])
        except Exception:
            time.sleep(3)
    return []

def main():
    with open(MANIFEST) as f:
        rows = list(csv.DictReader(f))
    # Group by style to minimize API calls
    by_style = defaultdict(list)
    for r in rows:
        by_style[r['style_number_clean']].append(r)

    styles = sorted(by_style.keys())
    print(f"Refreshing UUIDs for {len(rows)} SKUs across {len(styles)} styles...")

    # Build fresh sku -> record lookup from live LS
    fresh = {}
    not_found_styles = []
    for i, style in enumerate(styles):
        results = search_by_style(style)
        live_active = [p for p in results if not p.get('deleted_at') and p.get('active')]
        for p in live_active:
            fresh[p.get('sku')] = p
        if not live_active:
            not_found_styles.append(style)
        if (i+1) % 25 == 0:
            print(f"  [{i+1}/{len(styles)}] styles processed | fresh mappings: {len(fresh)} | not-found: {len(not_found_styles)}")

    print(f"\nTotal: {len(fresh)} fresh SKU mappings from {len(styles)} styles")
    print(f"Styles with zero live matches: {len(not_found_styles)}")

    # Rewrite manifest
    updated = 0
    still_stale = 0
    gone = 0
    for r in rows:
        sku = r['orphan_sku']
        live = fresh.get(sku)
        if live:
            r['ls_product_id'] = live['id']
            r['ls_deleted_at'] = live.get('deleted_at') or ''
            r['ls_active'] = 'Y' if live.get('active') else 'N'
            r['ls_family_id'] = live.get('family_id') or ''
            r['ls_name'] = (live.get('name') or '')[:80]
            r['ls_uuid_found'] = 'Y'
            updated += 1
        else:
            r['ls_deleted_at'] = ''
            r['ls_active'] = ''
            r['ls_family_id'] = ''
            r['ls_name'] = ''
            r['ls_uuid_found'] = 'N'
            gone += 1

    fields = list(rows[0].keys())
    with open(OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {OUT}")
    print(f"  Updated with live UUID: {updated}")
    print(f"  Not found in LS (already gone): {gone}")

if __name__ == "__main__":
    main()
