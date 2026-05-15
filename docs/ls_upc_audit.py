"""
ls_upc_audit.py
===============
Audits all Lightspeed variants for UPC codes that are not 12 or 13 digits.

Per Corrinne (S23): Leading zeros were dropped during import for many Wrangler
products, producing 11-digit UPCs. This script finds ALL variants where the
UPC code (under SKU Codes in LS) is not exactly 12 or 13 digits.

Outputs:
  docs/ls_upc_audit.csv   — one row per variant with bad UPC

Columns:
  ID, Name, UPC, Auto-Generated, Custom 1, Custom 2,
  Product Category, Variant_option_one_name, Variant_option_one_value,
  Variant_option_two_name, Variant_option_two_value,
  Variant_option_three_name, Variant_option_three_value,
  Tags, Supply price, Retail price, Brand, Supplier, Supplier Code,
  Active, Track Inventory

Usage:
  python3 docs/ls_upc_audit.py             # fresh live fetch
  python3 docs/ls_upc_audit.py --use-cache # use cached catalog if <6h old
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOCS = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DOCS)

ENV_FILE = os.path.join(PROJECT_ROOT, ".env.local")
CACHE_FILE = os.path.join(DOCS, "ls_upc_audit_cache.json")
TAG_MAP_FILE = os.path.join(DOCS, "ls_tag_map.json")
OUTPUT_FILE = os.path.join(DOCS, "ls_upc_audit.csv")

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
HEADERS = {"User-Agent": "curl/7.81.0"}
PAGE_SIZE = 250
SLEEP_BETWEEN_PAGES = 1.1  # stay under 55 req/min

USE_CACHE = "--use-cache" in sys.argv
CACHE_MAX_AGE_SECS = 6 * 3600  # 6 hours


# ── Credentials ───────────────────────────────────────────────────────────────

def get_token() -> str:
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


# ── LS API ────────────────────────────────────────────────────────────────────

def ls_get(token: str, path: str, params: dict = None):
    url = f"{LS_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEADERS, "Authorization": f"Bearer {token}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                return body.get("data", []), body.get("version")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 20 * (attempt + 1)
                print(f"  429 rate limit — sleeping {wait}s")
                time.sleep(wait)
                continue
            raise
    return [], None


def fetch_all_products(token: str) -> list:
    if USE_CACHE and os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_MAX_AGE_SECS:
            print(f"Using cached catalog ({age/3600:.1f}h old). Pass without --use-cache to force refresh.")
            with open(CACHE_FILE) as f:
                return json.load(f)

    print("Fetching all products from Lightspeed (this takes ~6-8 minutes)...")
    all_products = []
    after = 0
    page = 0

    while True:
        page += 1
        params = {"page_size": str(PAGE_SIZE)}
        if after > 0:
            params["after"] = str(after)

        if page % 25 == 1:
            print(f"  Page {page} (after={after}, fetched so far: {len(all_products):,})")

        data, version_info = ls_get(token, "products", params)

        if not data:
            break

        all_products.extend(data)
        time.sleep(SLEEP_BETWEEN_PAGES)

        if isinstance(version_info, dict) and "max" in version_info:
            after = version_info["max"]
        elif data:
            after = data[-1].get("version", 0)

        if len(data) < PAGE_SIZE:
            break

    print(f"Fetched {len(all_products):,} total products.")

    with open(CACHE_FILE, "w") as f:
        json.dump(all_products, f)
    print(f"Saved to cache: {CACHE_FILE}")

    return all_products


# ── Tag lookup ────────────────────────────────────────────────────────────────

def load_tag_map() -> dict:
    if not os.path.exists(TAG_MAP_FILE):
        return {}
    with open(TAG_MAP_FILE) as f:
        data = json.load(f)
    return data.get("uuid_to_name", {})


# ── Field extractors ──────────────────────────────────────────────────────────

def extract_upc(product: dict) -> str:
    for c in (product.get("product_codes") or []):
        if c.get("type") == "UPC":
            return str(c.get("code", "")).strip()
    return ""


def extract_auto_generated(product: dict) -> str:
    return str(product.get("sku") or "").strip()


def extract_customs(product: dict) -> list:
    return [
        str(c.get("code", "")).strip()
        for c in (product.get("product_codes") or [])
        if c.get("type") in ("CUSTOM", "custom")
    ]


def extract_category(product: dict) -> str:
    cat = product.get("product_category")
    if not cat:
        return ""
    if isinstance(cat, dict):
        return cat.get("name", "")
    if isinstance(cat, str):
        try:
            obj = json.loads(cat)
            return obj.get("name", cat)
        except (json.JSONDecodeError, TypeError):
            return cat
    return ""


def extract_variant_options(product: dict) -> list:
    opts = product.get("variant_options") or []
    result = []
    if isinstance(opts, list):
        for o in opts:
            if isinstance(o, dict):
                result.append((o.get("name", ""), o.get("value", "")))
    elif isinstance(opts, dict):
        for name, val in opts.items():
            result.append((name, val))
    return result


def extract_tags(product: dict, tag_map: dict) -> str:
    tag_ids = product.get("tag_ids") or []
    names = [tag_map.get(tid, tid) for tid in tag_ids]
    return ", ".join(names)


def extract_brand(product: dict) -> str:
    brand = product.get("brand")
    if isinstance(brand, dict):
        return brand.get("name", "")
    return str(brand or "")


def extract_supplier(product: dict) -> str:
    suppliers = product.get("product_suppliers") or []
    if isinstance(suppliers, list) and suppliers:
        s = suppliers[0]
        if isinstance(s, dict):
            return s.get("supplier_name") or s.get("name") or ""
    return str(product.get("supplier") or "")


def extract_supplier_code(product: dict) -> str:
    sc = product.get("supplier_code")
    if sc:
        return str(sc).strip()
    suppliers = product.get("product_suppliers") or []
    if isinstance(suppliers, list) and suppliers:
        s = suppliers[0]
        if isinstance(s, dict) and s.get("code"):
            return str(s["code"]).strip()
    return ""


def is_bad_upc(upc: str) -> bool:
    if not upc:
        return False
    digits_only = upc.replace(" ", "")
    if not digits_only.isdigit():
        return True
    return len(digits_only) not in (12, 13)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = get_token()
    tag_map = load_tag_map()
    products = fetch_all_products(token)

    print("Scanning for bad UPC codes...")

    bad_rows = []
    for p in products:
        upc = extract_upc(p)
        if not upc or not is_bad_upc(upc):
            continue

        customs = extract_customs(p)
        variant_opts = extract_variant_options(p)

        def opt_name(i):
            return variant_opts[i][0] if i < len(variant_opts) else ""

        def opt_val(i):
            return variant_opts[i][1] if i < len(variant_opts) else ""

        active_val = p.get("is_active")
        if active_val is None:
            active_val = p.get("active")

        track_inv = p.get("track_inventory")
        if track_inv is None:
            track_inv = p.get("has_inventory")

        bad_rows.append({
            "ID":                        p.get("id", ""),
            "Name":                      p.get("name", ""),
            "UPC":                       upc,
            "Auto-Generated":            extract_auto_generated(p),
            "Custom 1":                  customs[0] if len(customs) > 0 else "",
            "Custom 2":                  customs[1] if len(customs) > 1 else "",
            "Product Category":          extract_category(p),
            "Variant_option_one_name":   opt_name(0),
            "Variant_option_one_value":  opt_val(0),
            "Variant_option_two_name":   opt_name(1),
            "Variant_option_two_value":  opt_val(1),
            "Variant_option_three_name": opt_name(2),
            "Variant_option_three_value": opt_val(2),
            "Tags":                      extract_tags(p, tag_map),
            "Supply price":              p.get("supply_price", ""),
            "Retail price":              p.get("price_excluding_tax", ""),
            "Brand":                     extract_brand(p),
            "Supplier":                  extract_supplier(p),
            "Supplier Code":             extract_supplier_code(p),
            "Active":                    active_val,
            "Track Inventory":           track_inv,
        })

    print(f"Found {len(bad_rows):,} variants with non-12/13-digit UPC codes.")

    fieldnames = [
        "ID", "Name", "UPC", "Auto-Generated", "Custom 1", "Custom 2",
        "Product Category",
        "Variant_option_one_name", "Variant_option_one_value",
        "Variant_option_two_name", "Variant_option_two_value",
        "Variant_option_three_name", "Variant_option_three_value",
        "Tags", "Supply price", "Retail price",
        "Brand", "Supplier", "Supplier Code",
        "Active", "Track Inventory",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bad_rows)

    print(f"Output saved: {OUTPUT_FILE}")

    # Summary breakdown by UPC digit length
    from collections import Counter
    lengths = Counter(len(row["UPC"]) for row in bad_rows if row["UPC"])
    print("\nUPC digit-length breakdown:")
    for length, count in sorted(lengths.items()):
        print(f"  {length} digits: {count:,} variants")


if __name__ == "__main__":
    main()
