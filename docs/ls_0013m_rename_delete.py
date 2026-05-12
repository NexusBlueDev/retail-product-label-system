"""
ls_0013m_rename_delete.py
=========================
Two-phase cleanup for the 0013M Navy family (aa01454d-24f9-48e0-a1ad-74366fb12cbb):

Phase 1 — Rename: All 106 variants get renamed to "Cowboy Cut Original Fit - 13MWZ - NAVY"
  (removing the old "/ 27x31" size-in-name format, matching per-color family convention)
  Uses: PUT v2.1 {"common": {"name": "..."}}

Phase 2 — Delete dupes: The 14 variants that errored during UPC fix (genuine duplicates
  of PREWASHED_INDIGO per-color family) are soft-deleted.
  Uses: DELETE v2.0 /products/{id}

Per Corrinne (S21): rename confirmed as "Cowboy Cut Original Fit - 13MWZ - NAVY".

Usage:
  python3 docs/ls_0013m_rename_delete.py [--dry-run] [--phase1-only] [--phase2-only]

Audit log: docs/ls_0013m_rename_delete_audit.csv
"""

import sys
import csv
import json
import time
import datetime
import urllib.request
import urllib.error

FAMILY_ID = "aa01454d-24f9-48e0-a1ad-74366fb12cbb"
NEW_NAME = "Cowboy Cut Original Fit - 13MWZ - NAVY"
CATALOG_FILE = "docs/ls_fresh_catalog.json"
UPC_AUDIT_FILE = "docs/ls_0013m_upc_fix_audit.csv"
AUDIT_FILE = "docs/ls_0013m_rename_delete_audit.csv"

LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
HEADERS = {"User-Agent": "curl/7.81.0"}

DRY_RUN = "--dry-run" in sys.argv
PHASE1_ONLY = "--phase1-only" in sys.argv
PHASE2_ONLY = "--phase2-only" in sys.argv


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
        return json.loads(resp.read())


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


def ls_delete(token: str, pid: str) -> tuple[dict, int]:
    url = f"{LS_BASE_V20}/products/{pid}"
    req = urllib.request.Request(url, method="DELETE", headers={
        **HEADERS,
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            return (json.loads(body) if body else {}), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, e.code


def get_family_product_ids() -> list[str]:
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)
    return [p["id"] for p in catalog if p.get("family_id") == FAMILY_ID]


def get_error_product_ids() -> list[tuple[str, str]]:
    """Returns list of (product_id, item_description) for the 14 ERROR rows."""
    rows = []
    with open(UPC_AUDIT_FILE) as f:
        for row in csv.DictReader(f):
            if row["action"] == "ERROR":
                rows.append((row["ls_product_id"], row["item"]))
    return rows


def run():
    print("=" * 65)
    print("0013M Rename + Delete Dupes")
    print(f"Mode: {'DRY RUN — no writes' if DRY_RUN else 'LIVE'}")
    do_phase1 = not PHASE2_ONLY
    do_phase2 = not PHASE1_ONLY
    print(f"Phase 1 (rename):   {'YES' if do_phase1 else 'SKIP'}")
    print(f"Phase 2 (delete):   {'YES' if do_phase2 else 'SKIP'}")
    print("=" * 65)

    token = get_token()
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    audit_rows = []

    # ── Phase 1: Rename ────────────────────────────────────────────────────────
    if do_phase1:
        product_ids = get_family_product_ids()
        print(f"\n[Phase 1] Renaming {len(product_ids)} variants → \"{NEW_NAME}\"")

        stats = {"renamed": 0, "error": 0, "dry_run": 0}
        for i, pid in enumerate(product_ids, 1):
            try:
                prod_data = ls_get(token, pid)
                prod = prod_data.get("data", prod_data)
                current_name = prod.get("name", "")
            except Exception as e:
                print(f"  [{i:3d}] GET error {pid[:8]}: {e}")
                stats["error"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "1-rename",
                    "ls_product_id": pid, "item": pid[:8],
                    "action": "ERROR", "notes": f"GET failed: {e}",
                })
                time.sleep(0.3)
                continue

            opts = {o["name"]: o["value"] for o in (prod.get("variant_options") or [])}
            size = opts.get("Size", "?")
            length = opts.get("Length", "?")
            item_desc = f"{current_name} / {size}x{length}"

            if current_name == NEW_NAME:
                print(f"  [{i:3d}] SKIP (already correct) {size}x{length}")
                audit_rows.append({
                    "timestamp": timestamp, "phase": "1-rename",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "SKIP_ALREADY_CORRECT", "notes": "",
                })
                time.sleep(0.15)
                continue

            if DRY_RUN:
                print(f"  [{i:3d}] ~ {size}x{length}  \"{current_name}\" → \"{NEW_NAME}\"")
                stats["dry_run"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "1-rename",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "DRY_RUN_RENAME", "notes": f"Would rename to: {NEW_NAME}",
                })
                time.sleep(0.15)
                continue

            result, http_status = ls_put(token, pid, {"common": {"name": NEW_NAME}})
            if http_status in (200, 204):
                print(f"  [{i:3d}] ✓ {size}x{length}  renamed")
                stats["renamed"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "1-rename",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "RENAMED", "notes": f"old={current_name}",
                })
            else:
                print(f"  [{i:3d}] ERROR {http_status} {size}x{length}: {str(result)[:100]}")
                stats["error"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "1-rename",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "ERROR", "notes": f"HTTP {http_status}: {str(result)[:150]}",
                })
            time.sleep(0.4)

        print(f"\n  Renamed: {stats['renamed']}  Dry-run: {stats['dry_run']}  Errors: {stats['error']}")

    # ── Phase 2: Delete duplicates ─────────────────────────────────────────────
    if do_phase2:
        error_ids = get_error_product_ids()
        print(f"\n[Phase 2] Deleting {len(error_ids)} UPC-duplicate variants from 0013M family")
        print("  (These are genuine duplicates of PREWASHED_INDIGO per-color family variants)")

        stats2 = {"deleted": 0, "error": 0, "dry_run": 0}
        for i, (pid, item_desc) in enumerate(error_ids, 1):
            if DRY_RUN:
                print(f"  [{i:2d}] ~ DELETE {pid[:8]} ({item_desc[:60]})")
                stats2["dry_run"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "2-delete",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "DRY_RUN_DELETE", "notes": "Duplicate of PREWASHED_INDIGO per-color family",
                })
                continue

            result, http_status = ls_delete(token, pid)
            if http_status in (200, 204):
                print(f"  [{i:2d}] ✓ DELETED {pid[:8]} ({item_desc[:60]})")
                stats2["deleted"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "2-delete",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "DELETED", "notes": "Duplicate of PREWASHED_INDIGO per-color family",
                })
            else:
                print(f"  [{i:2d}] ERROR {http_status} {pid[:8]}: {str(result)[:100]}")
                stats2["error"] += 1
                audit_rows.append({
                    "timestamp": timestamp, "phase": "2-delete",
                    "ls_product_id": pid, "item": item_desc,
                    "action": "ERROR", "notes": f"HTTP {http_status}: {str(result)[:150]}",
                })
            time.sleep(0.4)

        print(f"\n  Deleted: {stats2['deleted']}  Dry-run: {stats2['dry_run']}  Errors: {stats2['error']}")

    # ── Write audit ────────────────────────────────────────────────────────────
    with open(AUDIT_FILE, "w", newline="") as f:
        if audit_rows:
            w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
            w.writeheader()
            w.writerows(audit_rows)

    print(f"\nAudit log: {AUDIT_FILE}")
    print("Done.")


if __name__ == "__main__":
    run()
