"""
ls_13mwz_missing_variants.py
=============================
Creates 36 variants that are in the Wrangler 13MWZ spreadsheet but missing from
their respective per-color families in Lightspeed.

Breakdown: SGB (26), DST (4), SHB (5), PWI (1)

Retail prices: carried from matching per-color family by size (Corrinne S21 direction).
  Size-to-price maps derived from existing per-color family variants via Supabase.

After each creation, sets track_inventory=true via PUT v2.1 (POST defaults to false).

Usage:
  python3 docs/ls_13mwz_missing_variants.py [--dry-run]

Audit log: docs/ls_13mwz_missing_variants_audit.csv
"""

import sys
import csv
import json
import time
import datetime
import urllib.request
import urllib.error

DRY_RUN = "--dry-run" in sys.argv

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
HEADERS = {"User-Agent": "curl/7.81.0"}
AUDIT_FILE = "docs/ls_13mwz_missing_variants_audit.csv"

# ── Per-color family metadata ──────────────────────────────────────────────────
# family_id, variant_parent_id, supplier_id, brand_id, product_type_id
FAMILY_META = {
    "DK_STONE": {
        "family_id": "6106225a-97c9-48f8-9938-1e1cc2a3869f",
        "name": "COWBOY CUT JEAN* ORIGINAL FIT DK_STONE",
        "supplier_id": "75ccecc6-073b-4b52-bef7-59862a3fc569",
        "brand_id": "5b823dcf-2f6c-4390-9399-c3b9f08a28d2",
        "product_type_id": "39d2c133-a413-49b1-93a2-afca9b7dcd73",
    },
    "PWI": {
        "family_id": "3f0c6ef2-e517-4aa0-99b6-0d3e5f85f7db",
        "name": "COWBOY CUT JEAN* ORIGINAL FIT PREWASHED_INDIGO",
        "supplier_id": "75ccecc6-073b-4b52-bef7-59862a3fc569",
        "brand_id": "5b823dcf-2f6c-4390-9399-c3b9f08a28d2",
        "product_type_id": "39d2c133-a413-49b1-93a2-afca9b7dcd73",
    },
    "SHB": {
        "family_id": "18bbd144-e7cb-4306-9247-ff936bc4d26a",
        "name": "COWBOY CUT JEAN* ORIGINAL FIT SHADOW_BLK",
        "supplier_id": "75ccecc6-073b-4b52-bef7-59862a3fc569",
        "brand_id": "5b823dcf-2f6c-4390-9399-c3b9f08a28d2",
        "product_type_id": "39d2c133-a413-49b1-93a2-afca9b7dcd73",
    },
    "SGB": {
        "family_id": "8720572b-de00-4710-883e-08dafeb8357f",
        "name": "COWBOY CUT JEAN* ORIGINAL FIT SW_GLD_BKL",
        "supplier_id": "75ccecc6-073b-4b52-bef7-59862a3fc569",
        "brand_id": "5b823dcf-2f6c-4390-9399-c3b9f08a28d2",
        "product_type_id": "39d2c133-a413-49b1-93a2-afca9b7dcd73",
    },
}

# ── Retail price maps by size (derived from existing per-color variants) ───────
# Source: Supabase lightspeed_index, queried 2026-05-12
# For sizes not in map: use max size price (big/tall tier)
RETAIL_PRICE_MAP = {
    "DK_STONE": {
        27: 63.95, 28: 63.95, 29: 63.95, 30: 66.95, 31: 66.95, 32: 66.95,
        33: 66.95, 34: 66.95, 35: 63.95, 36: 66.95, 38: 66.95, 40: 63.95, 42: 63.95,
    },
    "PWI": {
        27: 57.95, 28: 57.95, 29: 57.95, 30: 61.95, 31: 61.95, 32: 61.95,
        33: 61.95, 34: 61.95, 35: 57.95, 36: 61.95, 37: 57.95, 38: 61.95,
        40: 57.95, 42: 57.95, 44: 63.95, 46: 63.95, 48: 63.95, 50: 57.95,
        52: 57.95, 54: 57.95,
    },
    "SHB": {
        27: 59.95, 28: 59.95, 29: 59.95, 30: 63.95, 31: 63.95, 32: 63.95,
        33: 63.95, 34: 63.95, 35: 59.95, 36: 63.95, 37: 59.95, 38: 63.95,
        40: 59.95, 42: 59.95, 44: 65.95, 46: 65.95, 48: 65.95, 50: 59.95,
        52: 59.95, 54: 59.95,
    },
    "SGB": {
        27: 63.95, 28: 63.95, 29: 66.95, 30: 66.95, 31: 66.95, 32: 66.95,
        33: 63.95, 34: 66.95, 35: 63.95, 36: 66.95, 38: 66.95, 40: 63.95,
        42: 63.95, 44: 68.95, 46: 68.95,
    },
}

# ── LS variant attribute IDs ───────────────────────────────────────────────────
ATTR_SIZE_ID   = "8d72c173-2d55-4ef6-9813-d6bfbed613b2"
ATTR_LENGTH_ID = "6c510e74-8d1d-4a3f-b948-7c78ad96d3f1"

# ── The 36 missing variants ────────────────────────────────────────────────────
# Derived by comparing spreadsheet against Supabase lightspeed_index (2026-05-12)
MISSING_VARIANTS = [
    # SGB (SW_GLD_BKL) — 26 missing
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-48-32", "upc": "760609356259", "supply_price": 34.15, "size": "48", "length": "32"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-44-34", "upc": "760609356204", "supply_price": 34.15, "size": "44", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-33-38", "upc": "084084240026", "supply_price": 32.9,  "size": "33", "length": "38"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-52-34", "upc": "760609356327", "supply_price": 31.65, "size": "52", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-30-40", "upc": "672787249479", "supply_price": 31.65, "size": "30", "length": "40"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-54-32", "upc": "760609356341", "supply_price": 34.15, "size": "54", "length": "32"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-35-34", "upc": "084084240095", "supply_price": 31.65, "size": "35", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-48-34", "upc": "760609356266", "supply_price": 34.15, "size": "48", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-50-32", "upc": "760609356280", "supply_price": 34.15, "size": "50", "length": "32"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-38-36", "upc": "084084240194", "supply_price": 31.65, "size": "38", "length": "36"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-38-40", "upc": "672787249516", "supply_price": 32.9,  "size": "38", "length": "40"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-46-34", "upc": "760609356235", "supply_price": 34.15, "size": "46", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-54-34", "upc": "760609356358", "supply_price": 31.65, "size": "54", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-52-30", "upc": "760609356303", "supply_price": 34.15, "size": "52", "length": "30"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-50-34", "upc": "760609356297", "supply_price": 31.65, "size": "50", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-32-40", "upc": "672787249486", "supply_price": 31.65, "size": "32", "length": "40"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-42-30", "upc": "084084392152", "supply_price": 31.65, "size": "42", "length": "30"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-48-30", "upc": "760609356242", "supply_price": 34.15, "size": "48", "length": "30"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-44-32", "upc": "760609356198", "supply_price": 34.15, "size": "44", "length": "32"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-40-34", "upc": "084084240217", "supply_price": 31.65, "size": "40", "length": "34"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-52-32", "upc": "760609356310", "supply_price": 34.15, "size": "52", "length": "32"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-34-40", "upc": "672787249493", "supply_price": 32.9,  "size": "34", "length": "40"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-36-40", "upc": "672787249509", "supply_price": 32.9,  "size": "36", "length": "40"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-54-30", "upc": "760609356334", "supply_price": 34.15, "size": "54", "length": "30"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-33-36", "upc": "084084240019", "supply_price": 31.65, "size": "33", "length": "36"},
    {"color": "SGB", "sku": "M-Kon-1013MWZGK-50-30", "upc": "760609356273", "supply_price": 34.15, "size": "50", "length": "30"},
    # DST (DK_STONE) — 4 missing
    {"color": "DST", "sku": "M-Kon-1013MWZDD-36-32", "upc": "084084358622", "supply_price": 31.65, "size": "36", "length": "32"},
    {"color": "DST", "sku": "M-Kon-1013MWZDD-29-36", "upc": "084084358325", "supply_price": 31.65, "size": "29", "length": "36"},
    {"color": "DST", "sku": "M-Kon-1013MWZDD-29-38", "upc": "084084358332", "supply_price": 32.9,  "size": "29", "length": "38"},
    {"color": "DST", "sku": "M-Kon-1013MWZDD-40-30", "upc": "084084392220", "supply_price": 31.65, "size": "40", "length": "30"},
    # SHB (SHADOW_BLK) — 5 missing
    {"color": "SHB", "sku": "M-Kon-1013MWZWK-34-32", "upc": "084084494559", "supply_price": 30.0,  "size": "34", "length": "32"},
    {"color": "SHB", "sku": "M-Kon-1013MWZWK-36-32", "upc": "084084494634", "supply_price": 30.0,  "size": "36", "length": "32"},
    {"color": "SHB", "sku": "M-Kon-1013MWZWK-33-32", "upc": "084084494504", "supply_price": 30.0,  "size": "33", "length": "32"},
    {"color": "SHB", "sku": "M-Kon-1013MWZWK-42-30", "upc": "084084494764", "supply_price": 30.0,  "size": "42", "length": "30"},
    {"color": "SHB", "sku": "M-Kon-1013MWZWK-36-30", "upc": "084084494627", "supply_price": 30.0,  "size": "36", "length": "30"},
    # PWI (PREWASHED_INDIGO) — 1 missing
    {"color": "PWI", "sku": "M-Kon-1013MWZPW-38-36", "upc": "051071352307", "supply_price": 29.0,  "size": "38", "length": "36"},
]

# Color code → family key mapping
COLOR_TO_FAMILY = {"SGB": "SGB", "DST": "DK_STONE", "SHB": "SHB", "PWI": "PWI"}


def get_retail_price(color_code: str, size_str: str) -> float:
    """Look up retail price from per-color family size map.
    Falls back to max size price in that family for unknown sizes."""
    family_key = COLOR_TO_FAMILY.get(color_code)
    if not family_key:
        return 0.0
    price_map = RETAIL_PRICE_MAP.get(family_key, {})
    try:
        size_int = int(size_str)
    except ValueError:
        return max(price_map.values()) if price_map else 0.0
    if size_int in price_map:
        return price_map[size_int]
    # For sizes above the known max (big/tall sizes), use the max-size price
    max_known = max(price_map.keys())
    if size_int > max_known:
        return price_map[max_known]
    # For sizes below min (unlikely), use min price
    return price_map[min(price_map.keys())]


def get_token() -> str:
    with open(".env.local") as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found")


def ls_post(token: str, payload: dict) -> tuple[dict, int]:
    url = f"{LS_BASE_V20}/products"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        **HEADERS,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, e.code


def ls_put(token: str, pid: str, payload: dict) -> tuple[dict, int]:
    url = f"{LS_BASE_V21}/products/{pid}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        **HEADERS,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            return (json.loads(body) if body else {}), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, e.code


def build_payload(v: dict, meta: dict, retail_price: float) -> dict:
    """Build v2.0 POST payload for one missing variant."""
    return {
        "name": meta["name"],
        "active": True,
        "family_id": meta["family_id"],
        "price_excluding_tax": retail_price,
        "supply_price": float(v["supply_price"]),
        "brand_id": meta["brand_id"],
        "supplier_id": meta["supplier_id"],
        "product_type_id": meta["product_type_id"],
        "variants": [{
            "price_excluding_tax": retail_price,
            "supply_price": float(v["supply_price"]),
            "product_codes": [
                {"type": "CUSTOM", "code": v["sku"]},
                {"type": "UPC",    "code": v["upc"]},
            ],
            "variant_definitions": [
                {"attribute_id": ATTR_SIZE_ID,   "value": v["size"]},
                {"attribute_id": ATTR_LENGTH_ID, "value": v["length"]},
            ],
        }],
    }


def run():
    print("=" * 65)
    print("13MWZ Missing Variants — Create 36")
    print(f"Mode: {'DRY RUN — no writes' if DRY_RUN else 'LIVE'}")
    print("=" * 65)

    token = get_token()
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    audit_rows = []

    stats = {"created": 0, "error": 0, "dry_run": 0}

    for i, v in enumerate(MISSING_VARIANTS, 1):
        family_key = COLOR_TO_FAMILY[v["color"]]
        meta = FAMILY_META[family_key]
        retail_price = get_retail_price(v["color"], v["size"])

        print(f"  [{i:2d}] {v['sku']} | retail={retail_price} | supply={v['supply_price']}")

        if DRY_RUN:
            stats["dry_run"] += 1
            audit_rows.append({
                "timestamp": timestamp, "sku": v["sku"], "upc": v["upc"],
                "family_key": family_key, "size": v["size"], "length": v["length"],
                "retail_price": retail_price, "supply_price": v["supply_price"],
                "action": "DRY_RUN", "created_id": "", "notes": "",
            })
            continue

        payload = build_payload(v, meta, retail_price)
        result, http_status = ls_post(token, payload)

        if http_status in (200, 201):
            # POST returns {"data": ["new-product-uuid"]}
            uuids = (result.get("data") or [])
            created_id = uuids[0] if isinstance(uuids, list) and uuids else None

            print(f"      ✓ Created: {created_id}")
            stats["created"] += 1
            audit_rows.append({
                "timestamp": timestamp, "sku": v["sku"], "upc": v["upc"],
                "family_key": family_key, "size": v["size"], "length": v["length"],
                "retail_price": retail_price, "supply_price": v["supply_price"],
                "action": "CREATED", "created_id": created_id or "", "notes": "",
            })

            # Set track_inventory=true
            if created_id:
                _, put_status = ls_put(token, created_id, {"common": {"track_inventory": True}})
                if put_status not in (200, 204):
                    print(f"      WARN: track_inventory PUT returned {put_status}")
        else:
            err_str = str(result)[:200]
            print(f"      ERROR {http_status}: {err_str}")
            stats["error"] += 1
            audit_rows.append({
                "timestamp": timestamp, "sku": v["sku"], "upc": v["upc"],
                "family_key": family_key, "size": v["size"], "length": v["length"],
                "retail_price": retail_price, "supply_price": v["supply_price"],
                "action": "ERROR", "created_id": "",
                "notes": f"HTTP {http_status}: {err_str}",
            })

        time.sleep(0.5)

    # Write audit
    with open(AUDIT_FILE, "w", newline="") as f:
        if audit_rows:
            w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
            w.writeheader()
            w.writerows(audit_rows)

    print(f"\n{'='*65}")
    print("RESULTS")
    print(f"  Created:  {stats['created']}")
    print(f"  Dry-run:  {stats['dry_run']}")
    print(f"  Errors:   {stats['error']}")
    print(f"  Audit:    {AUDIT_FILE}")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
