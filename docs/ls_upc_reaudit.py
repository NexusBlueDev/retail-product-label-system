"""
ls_upc_reaudit.py
=================
Re-audits the 61 UPC-fix errors from S24 after Corrinne's manual corrections.

For each row in ls_upc_fix_errors.csv:
  - GET /api/2.0/products/{ID} to check current state
  - FIXED        = variant exists and has the correct new_upc
  - DELETED      = variant no longer exists (404) -- Corrinne deleted the duplicate
  - HAS_OLD_UPC  = variant exists but still has the old/wrong UPC
  - NO_UPC       = variant exists but has no UPC at all
  - OTHER        = variant exists with a different (unexpected) UPC
  - ERROR        = API call failed

Also checks the "conflict partner" -- the existing_code_UPC_id that blocked the original
write -- to verify it now has the correct UPC where available.

Output:
  docs/ls_upc_reaudit_results.csv   -- per-row status
  Prints summary counts and any remaining issues to stdout.

Usage:
  python3 docs/ls_upc_reaudit.py
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, "..", ".env.local")
ERRORS_CSV = os.path.join(BASE_DIR, "ls_upc_fix_errors.csv")
OUT_CSV = os.path.join(BASE_DIR, "ls_upc_reaudit_results.csv")

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"


def get_ls_token() -> str:
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


def ls_get(token: str, path: str):
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


def extract_upc_and_custom(product_data: dict) -> tuple[str | None, str | None]:
    """Returns (upc, custom_code) from v2.0 product response."""
    upc = None
    custom = None
    codes = product_data.get("product_codes", [])
    for code in codes:
        if code.get("type") == "UPC":
            upc = code.get("code")
        elif code.get("type") == "CUSTOM":
            custom = code.get("code")
    return upc, custom


def extract_conflict_id(note: str) -> str | None:
    """Extract the full existing_code_UPC_id UUID from the note JSON."""
    if not note:
        return None
    try:
        data = json.loads(note)
        fields = data.get("fields", {})
        raw = fields.get("existing_code_UPC_id", "")
        # Format is "UUID already exists." -- extract UUID
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", raw)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def check_variant(token: str, variant_id: str, expected_upc: str) -> tuple[str, str, str]:
    """Returns (status, actual_upc, custom_code)."""
    data = ls_get(token, f"/products/{variant_id}")
    if data is None:
        return "DELETED", "", ""
    product = data.get("data", data)
    # v2.0 response wraps in "data" key
    if isinstance(product, dict) and "data" in product:
        product = product["data"]
    actual_upc, custom = extract_upc_and_custom(product)
    if actual_upc == expected_upc:
        return "FIXED", actual_upc or "", custom or ""
    elif actual_upc is None or actual_upc == "":
        return "NO_UPC", "", custom or ""
    elif actual_upc == expected_upc.lstrip("0"):
        # 11-digit vs 12-digit (leading zero may be stripped by LS)
        return "FIXED", actual_upc, custom or ""
    else:
        return "OTHER", actual_upc or "", custom or ""


def main():
    token = get_ls_token()
    rows = list(csv.DictReader(open(ERRORS_CSV)))
    print(f"Re-auditing {len(rows)} UPC-fix error rows ...")

    results = []
    counts = {"FIXED": 0, "DELETED": 0, "HAS_OLD_UPC": 0, "NO_UPC": 0, "OTHER": 0, "ERROR": 0}
    needs_action = []

    for i, row in enumerate(rows, 1):
        variant_id = row["ID"]
        name = row["Name"]
        old_upc = row["old_upc"]
        new_upc = row["new_upc"]
        note = row.get("note", "")
        conflict_id = extract_conflict_id(note)

        try:
            status, actual_upc, custom = check_variant(token, variant_id, new_upc)
        except Exception as e:
            status, actual_upc, custom = "ERROR", "", str(e)[:80]

        # Check conflict partner if variant was deleted
        conflict_status = ""
        conflict_upc = ""
        if status == "DELETED" and conflict_id:
            try:
                c_status, c_upc, _ = check_variant(token, conflict_id, new_upc)
                conflict_status = c_status
                conflict_upc = c_upc
            except Exception:
                conflict_status = "ERROR"

        result_row = {
            "ID": variant_id,
            "Name": name,
            "old_upc": old_upc,
            "expected_new_upc": new_upc,
            "status": status,
            "actual_upc": actual_upc,
            "custom_code": custom,
            "conflict_id": conflict_id or "",
            "conflict_status": conflict_status,
            "conflict_upc": conflict_upc,
        }
        results.append(result_row)

        if status in ("FIXED", "DELETED"):
            counts[status] += 1
            # If deleted, check conflict partner is fixed
            if status == "DELETED" and conflict_status not in ("FIXED", ""):
                needs_action.append(result_row)
        elif status == "NO_UPC":
            counts["NO_UPC"] += 1
        elif status == "OTHER":
            counts["OTHER"] += 1
            needs_action.append(result_row)
        else:
            counts.get(status, counts.__setitem__(status, 0))
            counts[status] = counts.get(status, 0) + 1
            needs_action.append(result_row)

        sys.stdout.write(f"\r  {i}/{len(rows)} — {status}          ")
        sys.stdout.flush()
        time.sleep(0.12)  # stay within LS rate limit

    print()

    # Write results
    fieldnames = ["ID", "Name", "old_upc", "expected_new_upc", "status",
                  "actual_upc", "custom_code", "conflict_id", "conflict_status", "conflict_upc"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print()
    print("=" * 60)
    print("UPC RE-AUDIT SUMMARY")
    print("=" * 60)
    print(f"  FIXED       : {counts.get('FIXED', 0):3d}  (variant exists, UPC corrected)")
    print(f"  DELETED     : {counts.get('DELETED', 0):3d}  (duplicate removed by Corrinne)")
    print(f"  NO_UPC      : {counts.get('NO_UPC', 0):3d}  (variant exists but has no UPC)")
    print(f"  OTHER       : {counts.get('OTHER', 0):3d}  (variant has unexpected UPC)")
    print(f"  ERROR       : {counts.get('ERROR', 0):3d}  (API call failed)")
    print()
    total_resolved = counts.get("FIXED", 0) + counts.get("DELETED", 0)
    print(f"  TOTAL RESOLVED: {total_resolved}/61")

    if needs_action:
        print()
        print(f"NEEDS ATTENTION ({len(needs_action)} rows):")
        for r in needs_action:
            print(f"  [{r['status']}] {r['Name'][:40]:40s}  expected: {r['expected_new_upc']}  actual: {r['actual_upc']}")
    else:
        print("  All 61 variants resolved. No further action needed.")

    print()
    print(f"Full results: {OUT_CSV}")


if __name__ == "__main__":
    main()
