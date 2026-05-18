"""
ls_verify_items1_2.py
=====================
Verifies Corrinne's S24/S25 manual work in Lightspeed:

  Item 1 -- 36 missing 13MWZ variants
    Source: docs/ls_13mwz_missing_variants_for_corrinne.csv
    Check : each custom_sku now exists as a CUSTOM product code in LS
    Expected groups: SW_GLD_BKL(26), SHADOW_BLK(5), DK_STONE(4), PREWASHED_INDIGO(1)

  Item 2 -- ANTIQUE_WS per-color family
    Expected family name: "COWBOY CUT JEAN* ORIGINAL FIT ANTIQUE_WS"
    Check : family exists and has at least 1 variant

Output:
  docs/ls_verify_items1_2_results.csv  -- per-SKU row for Item 1
  Prints summary to stdout.

Usage:
  python3 docs/ls_verify_items1_2.py
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, "..", ".env.local")
MISSING_CSV = os.path.join(BASE_DIR, "ls_13mwz_missing_variants_for_corrinne.csv")
OUT_CSV = os.path.join(BASE_DIR, "ls_verify_items1_2_results.csv")

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"

ANTIQUE_WS_FAMILY_NAME = "COWBOY CUT JEAN* ORIGINAL FIT ANTIQUE_WS"


def get_ls_token() -> str:
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


def ls_get(token: str, path: str, params: dict = None):
    url = f"{LS_BASE_V20}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "curl/7.81.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:200]}")


def search_by_custom_code(token: str, code: str):
    """Search for a product by its CUSTOM product code."""
    resp = ls_get(token, "/products", {"productCode": code})
    if resp is None:
        return None
    data = resp.get("data", [])
    if not data:
        return None
    return data[0] if isinstance(data, list) else data


def search_by_name(token: str, name: str):
    """Search for products by exact name (family name)."""
    resp = ls_get(token, "/products", {"name": name, "perPage": 200})
    if resp is None:
        return []
    data = resp.get("data", [])
    return data if isinstance(data, list) else []


def get_all_pages(token: str, path: str, params: dict = None) -> list:
    """Fetch all pages for paginated LS endpoints."""
    params = params or {}
    params["perPage"] = 200
    results = []
    page = 1
    while True:
        params["page"] = page
        resp = ls_get(token, path, params)
        if not resp:
            break
        data = resp.get("data", [])
        if not data:
            break
        results.extend(data if isinstance(data, list) else [data])
        meta = resp.get("meta", {})
        total_pages = meta.get("last_page", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.15)
    return results


def main():
    token = get_ls_token()

    # ---- ITEM 1: 36 missing variants ----
    print("=" * 60)
    print("ITEM 1 — 36 missing 13MWZ variants")
    print("=" * 60)

    missing_rows = list(csv.DictReader(open(MISSING_CSV)))
    print(f"Checking {len(missing_rows)} expected variants by CUSTOM SKU code ...\n")

    item1_results = []
    found = 0
    not_found = []

    color_groups = {}
    for row in missing_rows:
        family = row["ls_family_name"]
        color = family.split()[-1] if family else "UNKNOWN"
        color_groups.setdefault(color, []).append(row)

    for i, row in enumerate(missing_rows, 1):
        sku = row["custom_sku"]
        family = row["ls_family_name"]
        product = None
        status = "NOT_FOUND"
        ls_id = ""
        ls_name = ""

        try:
            product = search_by_custom_code(token, sku)
            if product:
                status = "FOUND"
                ls_id = product.get("id", "")
                ls_name = product.get("name", "")
                found += 1
            else:
                not_found.append(row)
        except Exception as e:
            status = f"ERROR: {str(e)[:60]}"
            not_found.append(row)

        item1_results.append({
            "custom_sku": sku,
            "family": family,
            "size": row.get("size", ""),
            "length": row.get("length", ""),
            "upc": row.get("upc_barcode", ""),
            "status": status,
            "ls_id": ls_id,
            "ls_name": ls_name,
        })

        sys.stdout.write(f"\r  {i}/{len(missing_rows)} — {status[:30]}          ")
        sys.stdout.flush()
        time.sleep(0.12)

    print()
    print()
    print(f"  FOUND     : {found}/{len(missing_rows)}")
    print(f"  NOT FOUND : {len(not_found)}/{len(missing_rows)}")

    if not_found:
        print()
        print("  Missing variants (still not in LS):")
        by_color = {}
        for r in not_found:
            color = r["ls_family_name"].split()[-1]
            by_color.setdefault(color, []).append(r)
        for color, group in sorted(by_color.items()):
            print(f"    {color} ({len(group)} missing):")
            for r in group:
                print(f"      Size {r['size']}-{r['length']}  SKU:{r['custom_sku']}  UPC:{r['upc_barcode']}")
    else:
        print()
        print("  All 36 missing variants are now present in Lightspeed.")

    # ---- ITEM 2: ANTIQUE_WS per-color family ----
    print()
    print("=" * 60)
    print("ITEM 2 — ANTIQUE_WS per-color family")
    print("=" * 60)
    print(f'Looking for family: "{ANTIQUE_WS_FAMILY_NAME}" ...')
    time.sleep(0.15)

    antique_products = []
    try:
        antique_products = get_all_pages(token, "/products", {"name": ANTIQUE_WS_FAMILY_NAME})
    except Exception as e:
        print(f"  ERROR: {e}")

    if antique_products:
        print(f"  FOUND: {len(antique_products)} variants in ANTIQUE_WS family")
        # Sample a few to show they look correct
        print()
        print("  Sample variants (first 5):")
        for p in antique_products[:5]:
            codes = p.get("product_codes", [])
            upc = next((c["code"] for c in codes if c.get("type") == "UPC"), "no-upc")
            custom = next((c["code"] for c in codes if c.get("type") == "CUSTOM"), "no-custom")
            print(f"    {p.get('name', '')[:50]}  custom={custom}  upc={upc}")
    else:
        # Try alternate name format
        alt_name = "COWBOY CUT JEAN ORIGINAL FIT ANTIQUE_WS"
        print(f'  Not found under exact name. Trying partial search ...')
        time.sleep(0.15)
        # Search products with ANTIQUE_WS in name
        try:
            resp = ls_get(token, "/products", {"name": "ANTIQUE_WS", "perPage": 50})
            alt_data = resp.get("data", []) if resp else []
        except Exception:
            alt_data = []
        if alt_data:
            print(f"  Found {len(alt_data)} products containing 'ANTIQUE_WS' in name:")
            for p in alt_data[:10]:
                print(f"    [{p.get('id','')}] {p.get('name',''[:60])}")
        else:
            print("  ANTIQUE_WS family NOT FOUND in Lightspeed.")
            print("  Action needed: Corrinne must create the ANTIQUE_WS per-color family via LS UI.")

    # ---- Write Item 1 results ----
    fieldnames = ["custom_sku", "family", "size", "length", "upc", "status", "ls_id", "ls_name"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item1_results)

    print()
    print(f"Item 1 detail results: {OUT_CSV}")
    print()

    # ---- Final summary ----
    print("=" * 60)
    print("OVERALL SUMMARY")
    print("=" * 60)
    item1_ok = found == len(missing_rows)
    item2_ok = len(antique_products) > 0
    print(f"  Item 1 (36 missing variants) : {'COMPLETE' if item1_ok else f'INCOMPLETE -- {len(not_found)} still missing'}")
    print(f"  Item 2 (ANTIQUE_WS family)   : {'COMPLETE -- ' + str(len(antique_products)) + ' variants found' if item2_ok else 'INCOMPLETE -- family not found'}")
    print()
    if item1_ok and item2_ok:
        print("Both items verified complete. Ready to proceed.")
    else:
        print("Some items need follow-up. See details above.")


if __name__ == "__main__":
    main()
