"""
ls_issue_b_supplier_backfill.py
================================
Issue B -- Supplier backfill for our LS products missing a supplier assignment.

Target: products in our Supabase DB with lightspeed_product_id but no supplier_id
        in lightspeed_index, where we have a mappable supplier_name.

Source: products table JOIN lightspeed_index (deduped by lightspeed_product_id).

Action: PUT v2.1 /products/{id} with {"common": {"product_suppliers": [{"supplier_id": ..., "price": ...}]}}

Output:
  docs/ls_issue_b_supplier_backfill_log.csv
  Prints summary to stdout.

Usage:
  python3 docs/ls_issue_b_supplier_backfill.py [--dry-run]
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

DRY_RUN = "--dry-run" in sys.argv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, "..", ".env.local")
OUT_CSV = os.path.join(BASE_DIR, "ls_issue_b_supplier_backfill_log.csv")

LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
SUPABASE_API = "https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query"

# Supplier name → LS supplier UUID (canonical mapping, verified 2026-05-18)
SUPPLIER_MAP = {
    "Kontoor Brands":                "75ccecc6-073b-4b52-bef7-59862a3fc569",  # Kontoor Brands, Inc.
    "Ariat International":           "378f1b1b-418a-45f2-968b-de8565fc4d1b",  # Ariat
    "M&F Western Products":          "e42bc561-321d-4abf-9328-57ec8822162b",  # M&F Western Products LLC (most common)
    "M&F Western":                   "e42bc561-321d-4abf-9328-57ec8822162b",  # M&F Western Products LLC
    "Miller International":          "611e9fd9-54a4-45dc-9e4c-237166497ced",  # Miller International, Inc.
    "Trenditions":                   "0be95f96-4454-41e9-90ce-7e10402f9329",  # Trenditions LLC
    "Scully":                        "ce0244cd-198c-4c2c-8970-13f76965bd91",  # Scully Leather
    "Saddle Barn Inc":               "dccbc35d-b22e-45b7-b840-82f3b2d55fea",  # Saddle Barn Inc.
    "Hooey Brands":                  "b26f645d-7278-45c0-98b1-3c6a51f30f3f",  # Hooey LLC
    "BH Shoe Holdings":              "dd0210cd-1d1d-4ec4-8fd7-bdbd68f8739b",  # BH Shoe Holdings, Inc
    "Jacks Manufacturing, Inc.":     "f623fa81-4acf-4860-bfcd-d76c8ae9f48f",  # Jacks Manufacturing, Inc
    "JT International":              "5e1318de-9180-43da-8b25-3cdb5de4dc99",  # JT International Distributors, Inc.
    "Sidran":                        "9614c98a-52c9-4194-ae33-d42ec45cbab8",  # Sidran
    "Karman Inc":                    "2050de2f-466d-48db-8aa4-8773085b6ad6",  # Karman, Inc.
    "American West":                 "cefa0390-1a4d-46a3-9542-6735975015b6",  # American West
    "Cactus Ropes":                  "f30292cc-4b01-4a46-b1ce-360066680bd3",  # Cactus Ropes
    "Western Fashion Accessories":   "84fae64e-063c-4f86-9897-5a79f2513bef",  # Western Fashion
    "AWST Int'l":                    "f21b05af-ea69-46a9-b5e7-8034f385620c",  # AWST International
    "JPC":                           "01227dd7-8817-40be-aa24-0263269fa5a8",  # JPC Equestrian
    "HATCO. RHE Hatco, Inc.":        "de60e400-7584-48f2-a7ba-cf3033ad0085",  # HATCO. RHE Hatco, Inc
}

# These supplier names have no confident LS mapping -- will be logged as SKIP
SKIP_SUPPLIERS = {"Generic", "Cripple Creek", "Tucker", "M",
                  "Horse/Rodeo - Feed, Water & Stable Supplies"}


def load_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


def get_ls_token(env):
    t = env.get("LIGHTSPEED_TOKEN", "")
    if not t:
        raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")
    return t


def db_query(token, query):
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(SUPABASE_API, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "curl/7.81.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def ls_put_v21(ls_token, variant_id, payload):
    if DRY_RUN:
        return True, f"DRY_RUN: {json.dumps(payload)}"
    url = f"{LS_BASE_V21}/products/{variant_id}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {ls_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "curl/7.81.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            return True, "OK"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, f"HTTP {e.code}: {body[:200]}"


def main():
    env = load_env()
    ls_token = get_ls_token(env)
    access_token = env.get("SUPABASE_ACCESS_TOKEN", "")
    if not access_token:
        print("ERROR: SUPABASE_ACCESS_TOKEN not found"); sys.exit(1)

    if DRY_RUN:
        print("DRY RUN mode -- no changes will be made\n")

    # Fetch target products (unique by lightspeed_product_id, no supplier in LS, have supplier_name)
    print("Fetching target products from Supabase ...")
    rows = db_query(access_token, """
        SELECT DISTINCT ON (p.lightspeed_product_id)
          p.lightspeed_product_id,
          p.supplier_name,
          p.supply_price,
          p.name as product_name
        FROM products p
        JOIN lightspeed_index li ON li.lightspeed_id = p.lightspeed_product_id
        WHERE p.lightspeed_product_id IS NOT NULL AND length(p.lightspeed_product_id) > 0
          AND (li.supplier_id IS NULL OR li.supplier_id = '')
          AND p.supplier_name IS NOT NULL AND p.supplier_name != ''
        ORDER BY p.lightspeed_product_id, p.id
    """)
    print(f"Found {len(rows)} unique products with no supplier and a supplier_name\n")

    results = []
    counts = {"FIXED": 0, "SKIP_NO_MAP": 0, "SKIP_SUPPLIER": 0, "FAILED": 0}

    print("=" * 60)
    print("Processing supplier backfill")
    print("=" * 60)

    for i, row in enumerate(rows, 1):
        ls_id = row["lightspeed_product_id"]
        supplier_name = row["supplier_name"] or ""
        supply_price = float(row["supply_price"]) if row.get("supply_price") else 0.0
        product_name = row.get("product_name", "")[:50]

        if supplier_name in SKIP_SUPPLIERS:
            counts["SKIP_SUPPLIER"] += 1
            results.append({"ls_id": ls_id, "product_name": product_name,
                             "supplier_name": supplier_name, "status": "SKIP_SUPPLIER",
                             "supplier_id": "", "note": "No LS mapping for this supplier"})
            print(f"  {i:3d} SKIP_SUPPLIER  {supplier_name:30s}  {product_name}")
            continue

        supplier_id = SUPPLIER_MAP.get(supplier_name)
        if not supplier_id:
            counts["SKIP_NO_MAP"] += 1
            results.append({"ls_id": ls_id, "product_name": product_name,
                             "supplier_name": supplier_name, "status": "SKIP_NO_MAP",
                             "supplier_id": "", "note": "supplier_name not in SUPPLIER_MAP"})
            print(f"  {i:3d} SKIP_NO_MAP    {supplier_name:30s}  {product_name}")
            continue

        payload = {"common": {"product_suppliers": [
            {"supplier_id": supplier_id, "price": supply_price}
        ]}}

        ok, msg = ls_put_v21(ls_token, ls_id, payload)
        status = "FIXED" if ok else "FAILED"
        counts[status] += 1
        results.append({"ls_id": ls_id, "product_name": product_name,
                         "supplier_name": supplier_name, "status": status,
                         "supplier_id": supplier_id, "note": msg})
        print(f"  {i:3d} {status:8s}  {supplier_name:30s}  {product_name}  ({msg[:40]})")
        time.sleep(0.15)

    # Write log
    fieldnames = ["ls_id", "product_name", "supplier_name", "status", "supplier_id", "note"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  FIXED          : {counts['FIXED']}")
    print(f"  FAILED         : {counts['FAILED']}")
    print(f"  SKIP_SUPPLIER  : {counts['SKIP_SUPPLIER']}  (no LS supplier equivalent)")
    print(f"  SKIP_NO_MAP    : {counts['SKIP_NO_MAP']}  (supplier_name not in map)")
    print(f"  Total          : {len(rows)}")
    print()
    print(f"Log: {OUT_CSV}")

    if counts["FAILED"] > 0:
        print()
        print("FAILURES:")
        for r in results:
            if r["status"] == "FAILED":
                print(f"  {r['ls_id']}  {r['supplier_name']}  {r['note'][:80]}")


if __name__ == "__main__":
    main()
