#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 3: Verification Report
Re-fetches catalog post-import and compares against expected state.
Generates a human-readable report for Corrinne.
"""

import json
import subprocess
import time
import csv
import sys
from datetime import datetime, timezone

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
REQ_DELAY = 1.1

def ls_api(method, endpoint, data=None):
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
            time.sleep(15)
            continue
        return parsed, status
    return parsed, status

def fetch_catalog():
    """Fetch full catalog for verification."""
    all_products = []
    after = 0
    page = 0

    while True:
        page += 1
        endpoint = f"products?page_size=250"
        if after > 0:
            endpoint += f"&after={after}"

        if page % 20 == 1:
            print(f"  Page {page} (total: {len(all_products)})...")

        parsed, status = ls_api("GET", endpoint)
        if status >= 400 or not isinstance(parsed, dict):
            break

        data = parsed.get("data", [])
        if not data:
            break

        all_products.extend(data)

        version_info = parsed.get("version", {})
        if version_info and "max" in version_info:
            after = version_info["max"]
        elif data:
            after = data[-1].get("version", 0)

        if len(data) < 250:
            break

    return all_products

def main():
    print(f"Lightspeed Cleanup — Phase 3: Verification Report")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Load Phase 0 manifest
    try:
        with open(f"{DOCS}/ls_cleanup_manifest.json") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print("ERROR: No manifest found.")
        sys.exit(1)

    # Load Phase 1 progress
    try:
        with open(f"{DOCS}/ls_cleanup_phase1_progress.json") as f:
            phase1 = json.load(f)
    except FileNotFoundError:
        phase1 = {"deleted": [], "failed": []}

    # Load Phase 2 progress
    try:
        with open(f"{DOCS}/ls_cleanup_phase2_progress.json") as f:
            phase2 = json.load(f)
    except FileNotFoundError:
        phase2 = {"created_families": [], "added_to_existing": [], "standalone_created": [], "failed": []}

    # Load pre-import cache for baseline
    try:
        with open(f"{DOCS}/lightspeed_cache.json") as f:
            pre_import_cache = json.load(f)
        pre_import_count = len(pre_import_cache)
    except:
        pre_import_count = "unknown"

    orphan_count = len(manifest.get("orphans", []))

    print("Fetching post-cleanup catalog...")
    post_catalog = fetch_catalog()
    post_count = len(post_catalog)

    # Analyze post-cleanup state
    standalone_count = 0
    family_count = 0
    with_brand = 0
    with_supplier = 0
    with_category = 0
    variant_families = {}

    for p in post_catalog:
        variants = p.get("variants", [])
        has_variants = p.get("has_variants", False)

        if has_variants:
            fid = p.get("family_id", "")
            if fid not in variant_families:
                variant_families[fid] = {"name": p.get("name", ""), "count": 0}
            variant_families[fid]["count"] += 1
        else:
            standalone_count += 1

        if p.get("brand"):
            with_brand += 1
        if p.get("supplier"):
            with_supplier += 1
        if p.get("product_category"):
            with_category += 1

    # Check if orphans are actually gone
    orphan_ids = set(o["id"] for o in manifest.get("orphans", []))
    post_ids = set(p["id"] for p in post_catalog)
    remaining_orphans = orphan_ids & post_ids

    # Generate report
    report = []
    report.append("=" * 60)
    report.append("LIGHTSPEED CLEANUP — VERIFICATION REPORT")
    report.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    report.append("=" * 60)
    report.append("")
    report.append("CATALOG OVERVIEW:")
    report.append(f"  Pre-import baseline:     {pre_import_count}")
    report.append(f"  Orphans targeted:        {orphan_count}")
    report.append(f"  Post-cleanup total:      {post_count}")
    report.append(f"  Standalone products:     {standalone_count}")
    report.append(f"  Variant families:        {len(variant_families)}")
    report.append(f"  Products with brand:     {with_brand} ({100*with_brand/post_count:.1f}%)")
    report.append(f"  Products with supplier:  {with_supplier} ({100*with_supplier/post_count:.1f}%)")
    report.append(f"  Products with category:  {with_category} ({100*with_category/post_count:.1f}%)")
    report.append("")
    report.append("DELETION RESULTS (Phase 1):")
    report.append(f"  Deleted:                 {len(phase1.get('deleted', []))}")
    report.append(f"  Failed:                  {len(phase1.get('failed', []))}")
    report.append(f"  Remaining orphans:       {len(remaining_orphans)}")
    if remaining_orphans:
        report.append(f"  WARNING: {len(remaining_orphans)} orphans still exist in catalog!")
    report.append("")
    report.append("RE-IMPORT RESULTS (Phase 2):")
    report.append(f"  New families created:    {len(phase2.get('created_families', []))}")
    report.append(f"  Added to existing:       {len(phase2.get('added_to_existing', []))}")
    report.append(f"  Standalone created:      {len(phase2.get('standalone_created', []))}")
    report.append(f"  Failed:                  {len(phase2.get('failed', []))}")
    report.append("")

    if phase2.get("failed"):
        report.append("FAILED IMPORTS (needs attention):")
        for f in phase2["failed"][:20]:
            report.append(f"  - [{f.get('type', '')}] {f.get('style', f.get('sku', ''))} — HTTP {f.get('status', '')}: {f.get('error', '')[:80]}")
        if len(phase2["failed"]) > 20:
            report.append(f"  ... and {len(phase2['failed']) - 20} more")
        report.append("")

    verdict = "PASS" if len(remaining_orphans) == 0 and len(phase2.get("failed", [])) == 0 else "NEEDS ATTENTION"
    report.append(f"VERDICT: {verdict}")
    report.append("=" * 60)

    report_text = "\n".join(report)
    print(report_text)

    # Save report
    with open(f"{DOCS}/ls_cleanup_report.txt", "w") as f:
        f.write(report_text)
    print(f"\nSaved: {DOCS}/ls_cleanup_report.txt")

if __name__ == "__main__":
    main()
