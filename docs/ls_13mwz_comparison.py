"""
ls_13mwz_comparison.py
======================
Phase 1 of the Corrinne-approved 13MWZ delete-and-rebuild workflow.

Fetches current Lightspeed data for all 13MWZ products and compares
against the authoritative Wrangler spreadsheet (docs/Wrangler 13MWZ.xlsx).

Outputs:
  docs/ls_13mwz_comparison.csv     — side-by-side comparison per variant
  docs/ls_13mwz_retail_prices.json — retail prices extracted from LS (not in spreadsheet)
  docs/ls_13mwz_audit_log.csv      — audit log for all changes with timestamps

Usage:
  python3 docs/ls_13mwz_comparison.py [--dry-run]

Notes:
  - v2.0 for all reads (v2.1 has no GET)
  - Retail prices from LS are preserved for the rebuild phase
  - UPCs normalized: 11-digit starting with 5 or 8 → prepend leading 0
  - Spreadsheet is the authoritative source for: UPC, supplier price, variant structure
  - LS is the authoritative source for: retail price, current product IDs
"""

import sys
import csv
import json
import time
import datetime
import urllib.request
import urllib.error
import urllib.parse
import warnings
warnings.filterwarnings('ignore')

try:
    import pandas as pd
    import openpyxl
except ImportError:
    print("ERROR: pip3 install pandas openpyxl")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
SPREADSHEET = "docs/Wrangler 13MWZ.xlsx"
CATALOG_FILE = "docs/ls_fresh_catalog.json"

# Known 13MWZ family IDs in LS
KNOWN_FAMILIES = {
    "aa01454d-24f9-48e0-a1ad-74366fb12cbb": "0013M (Cowboy Cut® Original Fit - Navy)",
    "c3c968b4-b9b1-11f0-a200-020b2c2a4661": "Big Navy family (13MWZ catch-all)",
}

DRY_RUN = "--dry-run" in sys.argv

HEADERS = {
    "User-Agent": "curl/7.81.0",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_token() -> str:
    with open(".env.local") as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found")


def ls_get(token: str, path: str, params: dict = None) -> dict:
    url = f"{LS_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEADERS, "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} for {url}: {body[:200]}")


def normalize_upc(raw) -> str:
    """Normalize UPC per Corrinne's rule: 11-digit starting 5 or 8 → prepend 0."""
    if raw is None:
        return ""
    s = str(raw).strip().split(".")[0]  # strip .0 from Excel numerics
    if len(s) == 11 and s[0] in ("5", "8"):
        s = "0" + s
    return s


def extract_variant_options(product: dict) -> dict:
    """Extract Color, Size, Length from variant_options array."""
    opts = {}
    for o in product.get("variant_options", []) or []:
        name = (o.get("name") or o.get("option_name") or "").lower()
        val = o.get("value", "")
        if name in ("color", "colour"):
            opts["color"] = val
        elif name == "size":
            opts["size"] = val
        elif name in ("length", "fit/collar/length", "length/fit"):
            opts["length"] = val
    return opts


def extract_upc_and_custom(product: dict) -> tuple[str, str]:
    """Return (upc, custom_sku) from product_codes array."""
    upc = ""
    custom = ""
    for code in product.get("product_codes", []) or []:
        t = (code.get("type") or "").lower()
        c = code.get("code", "")
        if t == "upc":
            upc = c
        elif t == "custom":
            custom = c
    return upc, custom


def fetch_products_in_family(token: str, family_id: str) -> list[dict]:
    """Fetch all active products in a family using version-based pagination."""
    products = []
    version = 0
    page = 0
    while True:
        data = ls_get(token, "products", {"family_id": family_id, "after": version, "limit": 200})
        items = data.get("data", [])
        if not items:
            break
        products.extend(items)
        page += 1
        # version-based pagination
        pag = data.get("pagination", {})
        if not pag.get("has_next_page"):
            break
        version = pag.get("next_version", version + 1)
        time.sleep(0.3)
    return products


def fetch_products_by_ids(token: str, product_ids: list[str]) -> list[dict]:
    """Fetch individual products by ID (for families not queryable by filter)."""
    products = []
    for pid in product_ids:
        try:
            data = ls_get(token, f"products/{pid}")
            item = data.get("data", data)
            if isinstance(item, dict):
                products.append(item)
        except Exception as e:
            print(f"  WARN: failed to fetch {pid[:8]}: {e}")
        time.sleep(0.15)
    return products


# ──────────────────────────────────────────────────────────────────────────────
# Load spreadsheet
# ──────────────────────────────────────────────────────────────────────────────

def load_spreadsheet() -> pd.DataFrame:
    df = pd.read_excel(SPREADSHEET)
    df["upc_raw"] = df["UPC"].astype(str).str.strip().str.split(".").str[0]
    df["upc_normalized"] = df["upc_raw"].apply(normalize_upc)
    df["size_str"] = df["Size"].astype(str).str.strip()
    df["length_str"] = df["Fit/Collar/Length"].astype(str).str.strip()
    df["color_code"] = df["Color Code"].astype(str).str.strip()
    df["wholesale_price"] = pd.to_numeric(df["WHOLESALE"], errors="coerce")
    return df


def build_spreadsheet_index(df: pd.DataFrame) -> dict:
    """Build lookup: (color_code, size, length) → spreadsheet row."""
    idx = {}
    for _, row in df.iterrows():
        key = (row["color_code"], row["size_str"], row["length_str"])
        idx[key] = row
    return idx


# ──────────────────────────────────────────────────────────────────────────────
# Load LS catalog for product IDs
# ──────────────────────────────────────────────────────────────────────────────

def load_catalog_ids() -> dict[str, list[str]]:
    """Return {family_id: [product_id, ...]} for all known 13MWZ families."""
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)

    family_map: dict[str, list[str]] = {}
    for p in catalog:
        fid = p.get("family_id")
        pid = p.get("id")
        name = p.get("name", "")
        if fid and pid:
            if fid in KNOWN_FAMILIES:
                family_map.setdefault(fid, []).append(pid)
            # Also capture orphaned 13MWZ standalones
            elif "13MWZ" in name or "0013M" in name:
                family_map.setdefault(f"ORPHAN_{fid}", []).append(pid)
    return family_map


# ──────────────────────────────────────────────────────────────────────────────
# Main comparison
# ──────────────────────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("13MWZ LS vs Spreadsheet Comparison")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print("=" * 70)

    token = get_token()
    df_ss = load_spreadsheet()
    ss_idx = build_spreadsheet_index(df_ss)
    catalog_ids = load_catalog_ids()

    print(f"\nSpreadsheet: {len(df_ss)} variants across {df_ss['NEW Name'].nunique()} families")
    print(f"Known LS families to fetch: {len([k for k in catalog_ids if not k.startswith('ORPHAN')])}")

    all_ls_products = []
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    # Fetch known families
    for fid, label in KNOWN_FAMILIES.items():
        if fid not in catalog_ids:
            print(f"\nWARN: {label} — no products in catalog, skipping")
            continue
        pids = catalog_ids[fid]
        print(f"\nFetching {label}: {len(pids)} products...")
        prods = fetch_products_by_ids(token, pids)
        print(f"  → Fetched {len(prods)} products")
        for p in prods:
            p["_family_label"] = label
        all_ls_products.extend(prods)

    print(f"\nTotal LS products fetched: {len(all_ls_products)}")

    # Build comparison
    comparison_rows = []
    retail_prices = {}  # product_id → retail_price (preserve for rebuild)
    audit_log = []

    matched = 0
    unmatched_ls = []
    unmatched_ss_keys = set(ss_idx.keys())

    for prod in all_ls_products:
        opts = extract_variant_options(prod)
        color = opts.get("color", "")
        size = opts.get("size", "")
        length = opts.get("length", "")
        upc_ls, custom_ls = extract_upc_and_custom(prod)
        supply_ls = prod.get("supply_price") or 0
        retail_ls = prod.get("price_excluding_tax") or prod.get("price_including_tax") or 0
        pid = prod.get("id", "")
        name_ls = prod.get("name", "")
        active = prod.get("is_active", True)
        deleted = prod.get("deleted_at")

        # Preserve retail price
        if retail_ls:
            retail_prices[pid] = retail_ls

        # Find matching spreadsheet entry by color+size+length
        # Try direct color match first, then via color_code mapping
        color_code_map = {
            "ANTIQUE_WS": "AWS", "AWS": "AWS",
            "BLK_CHOCLT": "BCH", "BCH": "BCH",
            "CHARGREY": "CHA", "CHA": "CHA",
            "DK_STONE": "DST", "DST": "DST",
            "GB_BLEACH": "GBB", "GBB": "GBB",
            "PREWASHED_INDIGO": "PWI", "PWI": "PWI",
            "RIGID": "RIG", "RIG": "RIG",
            "SHADOW_BLK": "SHB", "SHB": "SHB",
            "SW_GLD_BKL": "SGB", "SGB": "SGB",
            "TAN": "TAN",
            "WHITE": "WHI", "WHI": "WHI",
        }
        color_code = color_code_map.get(color.upper(), color.upper()[:3])

        key = (color_code, size, length)
        ss_row = ss_idx.get(key)

        if ss_row is not None:
            matched += 1
            unmatched_ss_keys.discard(key)

            upc_ss = ss_row["upc_normalized"]
            supply_ss = ss_row["wholesale_price"]
            new_name_ss = ss_row["NEW Name"]
            new_sku_ss = ss_row["NEW SKU"]

            upc_match = (upc_ls == upc_ss) or (upc_ls == upc_ss.lstrip("0"))
            supply_match = abs(float(supply_ls) - float(supply_ss)) < 0.01

            row = {
                "ls_product_id": pid,
                "ls_name": name_ls,
                "ls_family_label": prod.get("_family_label", ""),
                "color": color,
                "size": size,
                "length": length,
                "ls_upc": upc_ls,
                "ss_upc": upc_ss,
                "upc_match": upc_match,
                "ls_supply_price": supply_ls,
                "ss_supply_price": supply_ss,
                "supply_match": supply_match,
                "ls_retail_price": retail_ls,
                "ls_custom_sku": custom_ls,
                "ss_new_sku": new_sku_ss,
                "ss_new_name": new_name_ss,
                "ls_is_active": active,
                "ls_deleted_at": deleted or "",
                "status": "MATCH" if (upc_match and supply_match) else "DISCREPANCY",
            }
            comparison_rows.append(row)

            if not upc_match or not supply_match:
                audit_log.append({
                    "timestamp": timestamp,
                    "ls_product_id": pid,
                    "item": f"{new_name_ss} | {size}x{length}",
                    "action": "DISCREPANCY_FOUND",
                    "field": "UPC" if not upc_match else "SUPPLY_PRICE",
                    "previous_value": upc_ls if not upc_match else str(supply_ls),
                    "new_value": upc_ss if not upc_match else str(supply_ss),
                    "notes": f"color={color}, size={size}, length={length}",
                })
        else:
            unmatched_ls.append({
                "ls_product_id": pid,
                "ls_name": name_ls,
                "color": color,
                "size": size,
                "length": length,
                "ls_upc": upc_ls,
                "ls_supply_price": supply_ls,
                "ls_retail_price": retail_ls,
                "ls_custom_sku": custom_ls,
                "ls_is_active": active,
                "note": "No match in spreadsheet — candidate for deletion",
            })

    # Unmatched spreadsheet entries (variants in spreadsheet not found in LS)
    unmatched_ss = []
    for key in unmatched_ss_keys:
        ss_row = ss_idx[key]
        unmatched_ss.append({
            "color_code": key[0],
            "size": key[1],
            "length": key[2],
            "ss_new_name": ss_row["NEW Name"],
            "ss_new_sku": ss_row["NEW SKU"],
            "ss_upc": ss_row["upc_normalized"],
            "ss_supply_price": ss_row["wholesale_price"],
            "note": "In spreadsheet but not found in LS — needs CREATE",
        })

    # Summary
    discrepancies = [r for r in comparison_rows if r["status"] == "DISCREPANCY"]
    print(f"\n{'='*70}")
    print(f"COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"  Matched (LS ↔ spreadsheet): {matched}")
    print(f"    - Clean (no discrepancies): {matched - len(discrepancies)}")
    print(f"    - Discrepancies: {len(discrepancies)}")
    print(f"  LS variants NOT in spreadsheet: {len(unmatched_ls)}")
    print(f"  Spreadsheet variants NOT in LS: {len(unmatched_ss)}")

    if discrepancies:
        print(f"\nDISCREPANCIES:")
        for d in discrepancies[:10]:
            print(f"  {d['color']} {d['size']}x{d['length']}: UPC {d['ls_upc']} → {d['ss_upc']}, "
                  f"Price ${d['ls_supply_price']} → ${d['ss_supply_price']}")

    # Write outputs
    print(f"\nWriting outputs...")

    # Comparison CSV
    cmp_path = "docs/ls_13mwz_comparison.csv"
    with open(cmp_path, "w", newline="") as f:
        if comparison_rows:
            w = csv.DictWriter(f, fieldnames=list(comparison_rows[0].keys()))
            w.writeheader()
            w.writerows(comparison_rows)
    print(f"  ✓ {cmp_path} ({len(comparison_rows)} rows)")

    # Unmatched LS
    unmatched_ls_path = "docs/ls_13mwz_unmatched_ls.csv"
    with open(unmatched_ls_path, "w", newline="") as f:
        if unmatched_ls:
            w = csv.DictWriter(f, fieldnames=list(unmatched_ls[0].keys()))
            w.writeheader()
            w.writerows(unmatched_ls)
    print(f"  ✓ {unmatched_ls_path} ({len(unmatched_ls)} rows)")

    # Unmatched SS
    unmatched_ss_path = "docs/ls_13mwz_unmatched_ss.csv"
    with open(unmatched_ss_path, "w", newline="") as f:
        if unmatched_ss:
            w = csv.DictWriter(f, fieldnames=list(unmatched_ss[0].keys()))
            w.writeheader()
            w.writerows(unmatched_ss)
    print(f"  ✓ {unmatched_ss_path} ({len(unmatched_ss)} rows)")

    # Retail prices JSON
    rp_path = "docs/ls_13mwz_retail_prices.json"
    with open(rp_path, "w") as f:
        json.dump(retail_prices, f, indent=2)
    print(f"  ✓ {rp_path} ({len(retail_prices)} price entries)")

    # Audit log
    audit_path = "docs/ls_13mwz_audit_log.csv"
    with open(audit_path, "w", newline="") as f:
        if audit_log:
            w = csv.DictWriter(f, fieldnames=list(audit_log[0].keys()))
            w.writeheader()
            w.writerows(audit_log)
        else:
            f.write("timestamp,ls_product_id,item,action,field,previous_value,new_value,notes\n")
    print(f"  ✓ {audit_path} ({len(audit_log)} entries)")

    print(f"\nDone. Next: review discrepancies, then proceed with delete-rebuild.")
    return comparison_rows, unmatched_ls, unmatched_ss, retail_prices, audit_log


if __name__ == "__main__":
    run()
