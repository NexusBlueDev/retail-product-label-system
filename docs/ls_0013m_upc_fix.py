"""
ls_0013m_upc_fix.py
===================
Fixes UPC codes on all 106 variants in the "Cowboy Cut® Original Fit - Navy - 0013M"
family (aa01454d-24f9-48e0-a1ad-74366fb12cbb).

Rule per Corrinne (S20): If a UPC is 11 digits and begins with 5 or 8, prepend a leading 0.

What this script does:
  For each 0013M variant:
    1. GET current product data (v2.0)
    2. If UPC is 11 digits starting with 5 or 8: build corrected 12-digit UPC
    3. PUT updated product_codes array (CUSTOM + corrected UPC) via v2.1
    4. Log every change to docs/ls_0013m_upc_fix_audit.csv

Usage:
  python3 docs/ls_0013m_upc_fix.py [--dry-run]

Does NOT change product names (awaiting Corrinne confirmation on naming).
"""

import sys
import csv
import json
import time
import datetime
import urllib.request
import urllib.error

FAMILY_ID = "aa01454d-24f9-48e0-a1ad-74366fb12cbb"
CATALOG_FILE = "docs/ls_fresh_catalog.json"
AUDIT_FILE = "docs/ls_0013m_upc_fix_audit.csv"

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
HEADERS = {"User-Agent": "curl/7.81.0"}

DRY_RUN = "--dry-run" in sys.argv


def get_token() -> str:
    with open(".env.local") as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found")


def ls_get(token: str, pid: str) -> dict:
    url = f"{LS_BASE_V20}/products/{pid}"
    req = urllib.request.Request(url, headers={**HEADERS, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return data.get("data", data)


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
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": body}, e.code


def normalize_upc(raw: str) -> tuple[str, bool]:
    """Returns (normalized_upc, was_changed)."""
    s = str(raw).strip().split(".")[0]
    if len(s) == 11 and s[0] in ("5", "8"):
        return "0" + s, True
    return s, False


def get_catalog_ids() -> list[str]:
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)
    return [p["id"] for p in catalog if p.get("family_id") == FAMILY_ID]


def run():
    print("=" * 65)
    print("0013M UPC Leading-Zero Fix")
    print(f"Mode: {'DRY RUN — no writes' if DRY_RUN else 'LIVE'}")
    print("=" * 65)

    token = get_token()
    product_ids = get_catalog_ids()
    print(f"Products to process: {len(product_ids)}")

    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    audit_rows = []
    stats = {"fixed": 0, "already_correct": 0, "no_upc": 0, "error": 0}

    for i, pid in enumerate(product_ids, 1):
        try:
            prod = ls_get(token, pid)
        except Exception as e:
            print(f"  [{i:3d}] GET error {pid[:8]}: {e}")
            stats["error"] += 1
            continue

        opts = {o["name"]: o["value"] for o in (prod.get("variant_options") or [])}
        size = opts.get("Size", "?")
        length = opts.get("Length", "?")
        name = prod.get("name", "")

        codes = prod.get("product_codes") or []
        upc_entry = next((c for c in codes if c.get("type", "").upper() == "UPC"), None)
        custom_entry = next((c for c in codes if c.get("type", "").upper() == "CUSTOM"), None)

        if not upc_entry:
            print(f"  [{i:3d}] {size}x{length} — no UPC, skipping")
            stats["no_upc"] += 1
            audit_rows.append({
                "timestamp": timestamp, "ls_product_id": pid,
                "item": f"{name} / {size}x{length}",
                "action": "SKIPPED_NO_UPC",
                "previous_value": "", "new_value": "", "notes": "No UPC code present",
            })
            continue

        raw_upc = upc_entry.get("code", "")
        corrected_upc, changed = normalize_upc(raw_upc)

        if not changed:
            stats["already_correct"] += 1
            audit_rows.append({
                "timestamp": timestamp, "ls_product_id": pid,
                "item": f"{name} / {size}x{length}",
                "action": "NO_CHANGE_NEEDED",
                "previous_value": raw_upc, "new_value": raw_upc,
                "notes": f"UPC already correct ({len(raw_upc)} digits)",
            })
            continue

        # Build new product_codes array — preserve CUSTOM + corrected UPC
        new_codes = []
        if custom_entry:
            new_codes.append({"type": "CUSTOM", "code": custom_entry["code"]})
        new_codes.append({"type": "UPC", "code": corrected_upc})

        payload = {"details": {"product_codes": new_codes}}

        status_char = "~" if DRY_RUN else "✓"
        if not DRY_RUN:
            result, http_status = ls_put(token, pid, payload)
            if http_status not in (200, 204):
                print(f"  [{i:3d}] {size}x{length} — ERROR {http_status}: {str(result)[:100]}")
                stats["error"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "ls_product_id": pid,
                    "item": f"{name} / {size}x{length}",
                    "action": "ERROR",
                    "previous_value": raw_upc, "new_value": corrected_upc,
                    "notes": f"HTTP {http_status}: {str(result)[:150]}",
                })
                time.sleep(0.5)
                continue
            time.sleep(0.4)

        stats["fixed"] += 1
        print(f"  [{i:3d}] {status_char} {size}x{length}  {raw_upc} → {corrected_upc}  (custom: {custom_entry['code'] if custom_entry else 'none'})")
        audit_rows.append({
            "timestamp": timestamp, "ls_product_id": pid,
            "item": f"{name} / {size}x{length}",
            "action": "DRY_RUN_UPC_FIX" if DRY_RUN else "UPC_FIXED",
            "previous_value": raw_upc, "new_value": corrected_upc,
            "notes": f"Prepended leading 0 (11-digit starting {raw_upc[0]})",
        })

    # Write audit log
    with open(AUDIT_FILE, "w", newline="") as f:
        if audit_rows:
            w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
            w.writeheader()
            w.writerows(audit_rows)

    print(f"\n{'='*65}")
    print("RESULTS")
    print(f"  Fixed (UPC updated):    {stats['fixed']}")
    print(f"  Already correct:        {stats['already_correct']}")
    print(f"  No UPC present:         {stats['no_upc']}")
    print(f"  Errors:                 {stats['error']}")
    print(f"  Audit log:              {AUDIT_FILE}")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
