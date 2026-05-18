"""
ls_rigid_cleanup.py
===================
Cleans up the RIGID family in Lightspeed:

  Phase 1 -- Delete 44 old-format catch-all residuals
    SKUs: 12085-12131 (no UPCs, old numeric CUSTOM codes)
    These are pre-normalization duplicates of the correct M-Kon format variants.

  Phase 2 -- Fix 2 M-Kon RIGID variants with wrong CUSTOM codes
    - M-Kon-1013MWZXS-42-40: CUSTOM was set to UPC value 051071611879
    - M-Kon-1013MWZXS-44-38: CUSTOM was set to UPC value 051071611886
    Fix: PUT correct CUSTOM code + correct UPC in product_codes

  Report -- 3 missing RIGID variants (cannot add via API)
    - 48-32, 50-32, 52-32 -- must be added manually by Corrinne via LS UI

Output:
  docs/ls_rigid_cleanup_log.csv
  Prints summary to stdout.

Usage:
  python3 docs/ls_rigid_cleanup.py [--dry-run]
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
OUT_CSV = os.path.join(BASE_DIR, "ls_rigid_cleanup_log.csv")

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"

# 44 old-format variants to delete (id, sku, size, length) -- verified live IDs 2026-05-18
OLD_FORMAT_VARIANTS = [
    ("b4116494-9a3e-4bd8-abd4-d307ed880224", "12085", 40, 32),
    ("10b170e6-35bc-4bb0-b98f-4e7e2844a230", "12086", 40, 34),
    ("64b7063e-0d01-447a-aba9-01b0076bba6d", "12087", 40, 44),
    ("b2835dd1-e814-489a-b809-f290d1dfa1c8", "12089", 42, 32),
    ("0c5c6a7a-7de7-42da-9cbe-f0c8146a35a4", "12090", 42, 34),
    ("c6ab022a-da0f-470f-bfc4-d3bbb87621ce", "12091", 42, 44),
    ("c80f8503-54b9-4cc9-b035-a246629ce5bf", "12093", 44, 32),
    ("bbd9c896-ac90-4465-9cff-32f5f57e39af", "12094", 44, 34),
    ("1b0b6e21-658e-4c28-8fa0-5bb6c2ede118", "12095", 44, 44),
    ("a94ba190-15be-461e-b749-3d983319b2c7", "12096", 44, 40),
    ("b65e6173-92b3-4d0d-9cfa-f1625c0785f9", "12097", 46, 32),
    ("1fb4439c-7bf1-4bc8-9172-7a1e2111d7a9", "12098", 46, 34),
    ("611ca568-6371-4623-9b1f-002128b8660d", "12099", 46, 44),
    ("7eefec6e-a9d4-4463-822a-77bc04f4ef0d", "12100", 46, 40),
    ("74e6e750-8391-427e-9e05-a89e4f66e0e2", "12101", 29, 36),
    ("de973e05-5291-4135-a13f-d3ba2c7ffc2f", "12102", 29, 38),
    ("7e493aa9-909c-4ab2-bb32-58c13587fa5a", "12103", 30, 36),
    ("5ce601d4-e0a4-4a9a-976a-ba292c67dda6", "12104", 30, 38),
    ("b8fb7614-2c85-4298-8045-3d4955dbe0d3", "12105", 31, 36),
    ("65e0b842-ec72-4d92-919b-c251fa1c6c54", "12106", 31, 38),
    ("091f7ed0-9523-4625-b1f0-b8034ba7873f", "12107", 32, 36),
    ("5a2628e9-60f2-48f2-ae5d-5ec80f320d36", "12108", 32, 38),
    ("be81136b-12a3-4379-bd2b-6ef1b647041e", "12109", 33, 36),
    ("07db5bfc-56b1-4e16-a620-a8143bf8b259", "12110", 33, 38),
    ("9250b29f-b5fc-4364-97b6-185b9ad38c71", "12111", 34, 36),
    ("f62f33b7-5d62-4f39-a032-dce3be3af577", "12112", 34, 38),
    ("7e4682de-2d38-42aa-bd8d-3813d8b1eedc", "12113", 36, 36),
    ("a48c841f-9c19-409c-a373-b9a2381cf0a8", "12114", 36, 38),
    ("7f254e82-cbb1-4f24-851d-8f3846503b5e", "12115", 38, 36),
    ("13207728-2526-408f-9457-b00b63d21439", "12116", 38, 38),
    ("16fcb693-e73f-4e19-9757-167f7eb6966e", "12117", 40, 36),
    ("4cda887e-8d94-4189-9524-331200da37ca", "12118", 40, 38),
    ("7d38302a-6e86-42a7-9b2e-4147ba955d9b", "12119", 48, 36),
    ("a434e9eb-d5f3-439a-8cbf-0ce900b25edf", "12120", 48, 38),
    ("3437e545-7ce6-4a20-9b78-4a071dea94aa", "12121", 50, 36),
    ("7e002e32-48c0-461f-a671-b2b7b95955cc", "12122", 50, 38),
    ("39677b61-3ca3-4924-9083-d9e412feee59", "12123", 52, 36),
    ("867a81aa-86a3-4fa3-8ce9-d682f83b6974", "12124", 52, 38),
    ("f636f558-0b20-492f-a24a-add7e7b873bb", "12125", 54, 36),
    ("6e98b215-51fc-4710-baf4-76bbb84f3aa6", "12126", 54, 38),
    ("dd04805e-1a91-4907-95a5-9889b05cb112", "12127", 42, 36),
    ("967fbb9e-4c34-4052-84e6-a07cff5a73e6", "12128", 42, 38),
    ("e2f68bff-87c9-4447-b563-885c67fb8568", "12129", 44, 36),
    ("5a0bbbba-1f7d-47e2-9da9-2c2a89288456", "12131", 46, 36),
]

# 2 M-Kon variants with wrong CUSTOM codes (UPC value in CUSTOM field)
CUSTOM_CODE_FIXES = [
    # (id, correct_custom_sku, correct_upc)
    ("ed0fb6bf-256f-40db-8581-7259657f24bc", "M-Kon-1013MWZXS-42-40", "051071611879"),
    ("58c04a66-0b76-46ea-9467-3eb72ab74bc8", "M-Kon-1013MWZXS-44-38", "051071611886"),
]

MISSING_RIGID = [
    ("M-Kon-1013MWZXS-48-32", 48, 32, "051071393225"),
    ("M-Kon-1013MWZXS-50-32", 50, 32, "051071393249"),
    ("M-Kon-1013MWZXS-52-32", 52, 32, "051071393263"),
]


def get_ls_token() -> str:
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("LIGHTSPEED_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


def ls_delete_v21(token: str, variant_id: str) -> tuple[bool, str]:
    if DRY_RUN:
        return True, "DRY_RUN"
    url = f"{LS_BASE_V20}/products/{variant_id}"  # DELETE uses v2.0, not v2.1
    req = urllib.request.Request(url, method="DELETE", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "curl/7.81.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            return True, "DELETED"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, f"HTTP {e.code}: {body[:150]}"


def ls_put_v21(token: str, variant_id: str, payload: dict) -> tuple[bool, str]:
    if DRY_RUN:
        return True, f"DRY_RUN: {json.dumps(payload)}"
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
        return False, f"HTTP {e.code}: {body[:150]}"


def main():
    token = get_ls_token()
    if DRY_RUN:
        print("DRY RUN mode -- no changes will be made\n")

    results = []
    errors = []

    # ---- PHASE 1: Delete 44 old-format variants ----
    print("=" * 60)
    print(f"PHASE 1: Deleting {len(OLD_FORMAT_VARIANTS)} old-format RIGID variants")
    print("=" * 60)
    deleted = 0
    for i, (vid, sku, size, length) in enumerate(OLD_FORMAT_VARIANTS, 1):
        ok, msg = ls_delete_v21(token, vid)
        status = "DELETED" if ok else "FAILED"
        if ok:
            deleted += 1
        else:
            errors.append({"phase": "delete", "id": vid, "sku": sku, "msg": msg})
        results.append({"phase": "delete", "id": vid, "sku": sku, "size": size, "length": length, "status": status, "note": msg})
        sys.stdout.write(f"\r  {i}/{len(OLD_FORMAT_VARIANTS)} -- {status} sku={sku}          ")
        sys.stdout.flush()
        time.sleep(0.15)
    print(f"\n  {deleted}/{len(OLD_FORMAT_VARIANTS)} deleted")

    print()

    # ---- PHASE 2: Fix CUSTOM codes on 2 M-Kon variants ----
    print("=" * 60)
    print(f"PHASE 2: Fixing CUSTOM codes on {len(CUSTOM_CODE_FIXES)} M-Kon RIGID variants")
    print("=" * 60)
    fixed = 0
    for vid, correct_custom, correct_upc in CUSTOM_CODE_FIXES:
        payload = {"details": {"product_codes": [
            {"type": "CUSTOM", "code": correct_custom},
            {"type": "UPC", "code": correct_upc},
        ]}}
        ok, msg = ls_put_v21(token, vid, payload)
        status = "FIXED" if ok else "FAILED"
        if ok:
            fixed += 1
        else:
            errors.append({"phase": "fix_custom", "id": vid, "sku": correct_custom, "msg": msg})
        results.append({"phase": "fix_custom", "id": vid, "sku": correct_custom, "size": "", "length": "", "status": status, "note": msg})
        print(f"  {status} -- {correct_custom}  upc={correct_upc}  ({msg})")
        time.sleep(0.15)
    print(f"  {fixed}/{len(CUSTOM_CODE_FIXES)} custom codes fixed")

    print()

    # ---- Write log ----
    fieldnames = ["phase", "id", "sku", "size", "length", "status", "note"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # ---- Final summary ----
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Phase 1 -- Old-format deletions : {deleted}/{len(OLD_FORMAT_VARIANTS)}")
    print(f"  Phase 2 -- CUSTOM code fixes    : {fixed}/{len(CUSTOM_CODE_FIXES)}")
    print(f"  Expected remaining RIGID: 17 correct M-Kon variants")

    if errors:
        print()
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [{e['phase']}] {e['sku']}  {e['msg']}")
    else:
        print("  No errors.")

    print()
    print("STILL NEEDS CORRINNE (cannot add via API):")
    print("  3 missing RIGID sizes -- add manually under 'COWBOY CUT JEAN* ORIGINAL FIT RIGID':")
    for sku, size, length, upc in MISSING_RIGID:
        print(f"    Size {size}, Length {length}  SKU: {sku}  UPC: {upc}  Supply: $20.50")

    print()
    print(f"Log: {OUT_CSV}")


if __name__ == "__main__":
    main()
