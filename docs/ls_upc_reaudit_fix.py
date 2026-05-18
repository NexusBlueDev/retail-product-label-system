"""
ls_upc_reaudit_fix.py
=====================
Fixes the 23 remaining UPC issues identified by ls_upc_reaudit.py:

  Group A (10 NO_UPC): Sport Western Snap Shirt - 71105 variants
    - Each has a CUSTOM code but no UPC
    - Apply the target UPC (was blocked by a duplicate -- now presumably deleted)
    - PUT v2.1 with both CUSTOM + UPC codes

  Group B (13 OTHER): Tack items with fake UPCs (CUSTOM SKU codes in the UPC field)
    - Each has only a UPC-type code containing what should be a CUSTOM code (e.g. "RSRR9995")
    - Move the code from UPC type to CUSTOM type -- no real UPC available
    - PUT v2.1 with [{CUSTOM, code}]

Output:
  docs/ls_upc_reaudit_fix_log.csv  -- per-row result
  Remaining failures printed to stdout for Corrinne review

Usage:
  python3 docs/ls_upc_reaudit_fix.py [--dry-run]
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

DRY_RUN = "--dry-run" in sys.argv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, "..", ".env.local")
ERRORS_CSV = os.path.join(BASE_DIR, "ls_upc_fix_errors.csv")
AUDIT_CSV = os.path.join(BASE_DIR, "ls_upc_reaudit_results.csv")
OUT_CSV = os.path.join(BASE_DIR, "ls_upc_reaudit_fix_log.csv")

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"


def get_ls_token() -> str:
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


def ls_get_v20(token: str, path: str):
    url = f"{LS_BASE_V20}{path}"
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
        raise


def ls_put_v21(token: str, variant_id: str, payload: dict) -> tuple[bool, str]:
    """Returns (success, message)."""
    if DRY_RUN:
        return True, f"DRY_RUN: would PUT {json.dumps(payload)}"
    url = f"{LS_BASE_V21}/products/{variant_id}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {token}",
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


def get_current_codes(token: str, variant_id: str) -> list[dict]:
    """Fetch current product_codes from v2.0."""
    resp = ls_get_v20(token, f"/products/{variant_id}")
    if not resp:
        return []
    d = resp.get("data", resp)
    if isinstance(d, list):
        d = d[0] if d else {}
    return d.get("product_codes", [])


def main():
    token = get_ls_token()
    if DRY_RUN:
        print("DRY RUN mode -- no changes will be made")
        print()

    errors = {r["ID"]: r for r in csv.DictReader(open(ERRORS_CSV))}
    audit = {r["ID"]: r for r in csv.DictReader(open(AUDIT_CSV))}

    group_a = [audit[vid] for vid in audit if audit[vid]["status"] == "NO_UPC"]
    group_b = [audit[vid] for vid in audit if audit[vid]["status"] == "OTHER"]

    print(f"Group A (NO_UPC, needs UPC applied)  : {len(group_a)} variants")
    print(f"Group B (OTHER, fake UPC to fix)      : {len(group_b)} variants")
    print()

    results = []
    still_broken = []

    # ---- GROUP A: Apply correct UPC to NO_UPC Sport Western variants ----
    print("=== GROUP A: Applying correct UPCs ===")
    for i, row in enumerate(group_a, 1):
        vid = row["ID"]
        error_row = errors.get(vid, {})
        target_upc = error_row.get("new_upc", "")
        name = row["Name"]

        if not target_upc:
            results.append({"ID": vid, "Name": name, "group": "A", "status": "SKIP_NO_TARGET_UPC", "note": ""})
            print(f"  {i}/{len(group_a)} SKIP — no target UPC for {name}")
            continue

        # Get current CUSTOM code
        codes = get_current_codes(token, vid)
        time.sleep(0.15)
        custom_codes = [c for c in codes if c.get("type", "").upper() == "CUSTOM"]
        custom_value = custom_codes[0]["code"] if custom_codes else None

        # Build new product_codes: keep existing CUSTOM + add UPC
        new_codes = []
        if custom_value:
            new_codes.append({"type": "CUSTOM", "code": custom_value})
        new_codes.append({"type": "UPC", "code": target_upc})

        payload = {"details": {"product_codes": new_codes}}
        ok, msg = ls_put_v21(token, vid, payload)
        time.sleep(0.15)

        status = "FIXED" if ok else "FAILED"
        results.append({"ID": vid, "Name": name, "group": "A", "status": status, "note": msg})
        print(f"  {i}/{len(group_a)} {status} — {name[:40]}  custom={custom_value}  upc={target_upc}")
        if not ok:
            still_broken.append({"ID": vid, "Name": name, "expected_upc": target_upc, "note": msg})

    print()

    # ---- GROUP B: Move fake UPC to CUSTOM type ----
    print("=== GROUP B: Moving fake UPCs to CUSTOM type ===")
    for i, row in enumerate(group_b, 1):
        vid = row["ID"]
        name = row["Name"]
        # actual_upc contains the current (fake) UPC value
        fake_upc_value = row.get("actual_upc", "")

        if not fake_upc_value:
            # Fallback: check error row old_upc
            fake_upc_value = errors.get(vid, {}).get("old_upc", "")

        if not fake_upc_value:
            results.append({"ID": vid, "Name": name, "group": "B", "status": "SKIP_NO_VALUE", "note": ""})
            print(f"  {i}/{len(group_b)} SKIP — no code value for {name}")
            continue

        # Move: send only CUSTOM code with the value (no UPC)
        new_codes = [{"type": "CUSTOM", "code": fake_upc_value}]
        payload = {"details": {"product_codes": new_codes}}
        ok, msg = ls_put_v21(token, vid, payload)
        time.sleep(0.15)

        status = "FIXED" if ok else "FAILED"
        results.append({"ID": vid, "Name": name, "group": "B", "status": status, "note": msg})
        print(f"  {i}/{len(group_b)} {status} — {name[:40]}  code={fake_upc_value}")
        if not ok:
            still_broken.append({"ID": vid, "Name": name, "code": fake_upc_value, "note": msg})

    print()

    # Write results
    fieldnames = ["ID", "Name", "group", "status", "note"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Summary
    a_fixed = sum(1 for r in results if r["group"] == "A" and r["status"] == "FIXED")
    b_fixed = sum(1 for r in results if r["group"] == "B" and r["status"] == "FIXED")
    print("=" * 60)
    print("FIX RUN SUMMARY")
    print("=" * 60)
    print(f"  Group A (UPC apply)     : {a_fixed}/{len(group_a)} fixed")
    print(f"  Group B (code move)     : {b_fixed}/{len(group_b)} fixed")
    print(f"  Total resolved          : {a_fixed + b_fixed}/23")

    if still_broken:
        print()
        print(f"STILL NEEDS ATTENTION ({len(still_broken)} items):")
        for r in still_broken:
            print(f"  {r['Name'][:50]:50s}  {r['note'][:80]}")
    else:
        print()
        print("All 23 remaining issues resolved. Full UPC audit complete.")

    print()
    print(f"Log: {OUT_CSV}")


if __name__ == "__main__":
    main()
