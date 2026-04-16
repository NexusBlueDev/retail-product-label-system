#!/usr/bin/env python3
"""
Lightspeed Cleanup — Phase 1: Delete Orphaned Standalone Products
Reads manifest from Phase 0, deletes each product via DELETE /products/{id}.
Saves progress after every deletion for resumability.

Prerequisite: docs/ls_cleanup_manifest.json must exist (from Phase 0).
"""

import json
import subprocess
import time
import sys
from datetime import datetime, timezone

# === Config ===
LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_TOKEN = subprocess.run(
    ["bash", "-c", "grep '^LIGHTSPEED_TOKEN=' /home/nexusblue/dev/retail-product-label-system/.env.local | cut -d= -f2-"],
    capture_output=True, text=True
).stdout.strip()
DOCS = "/home/nexusblue/dev/retail-product-label-system/docs"
PROGRESS_FILE = f"{DOCS}/ls_cleanup_phase1_progress.json"
REQ_DELAY = 1.1  # 55 req/min safe rate

def ls_delete(product_id):
    """DELETE a product from Lightspeed."""
    time.sleep(REQ_DELAY)
    for attempt in range(3):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", "DELETE",
               f"{LS_BASE}/products/{product_id}",
               "-H", f"Authorization: Bearer {LS_TOKEN}",
               "-H", "Accept: application/json"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        parts = r.stdout.rsplit('\n', 1)
        body = parts[0] if parts else ''
        status = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
        if status == 429:
            print(f"  Rate limited (attempt {attempt+1}), waiting 15s...")
            time.sleep(15)
            continue
        return status, body
    return status, body

def load_progress():
    """Load progress from previous run (for resumability)."""
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"deleted": [], "failed": [], "skipped": []}

def save_progress(progress):
    """Save progress after each deletion."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

def main():
    print(f"Lightspeed Cleanup — Phase 1: Delete Orphans")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Load manifest
    manifest_path = f"{DOCS}/ls_cleanup_manifest.json"
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print("ERROR: ls_cleanup_manifest.json not found. Run Phase 0 first.")
        sys.exit(1)

    orphans = manifest["orphans"]
    total = len(orphans)
    print(f"Manifest loaded: {total} orphans to delete")

    # Safety check: verify count is within expected range
    EXPECTED_MIN = 3500
    EXPECTED_MAX = 5500
    if total < EXPECTED_MIN or total > EXPECTED_MAX:
        print(f"SAFETY HALT: Orphan count {total} is outside expected range [{EXPECTED_MIN}, {EXPECTED_MAX}]")
        print("This may indicate a problem with the Phase 0 manifest. Aborting.")
        sys.exit(1)

    # Load progress (resume from previous run)
    progress = load_progress()
    already_deleted = set(progress["deleted"])
    already_failed = set(d["id"] for d in progress["failed"])
    print(f"Previous progress: {len(already_deleted)} deleted, {len(already_failed)} failed")

    # Process deletions
    remaining = [o for o in orphans if o["id"] not in already_deleted and o["id"] not in already_failed]
    print(f"Remaining to delete: {len(remaining)}")
    print()

    success_count = len(already_deleted)
    fail_count = len(already_failed)

    for i, orphan in enumerate(remaining):
        pid = orphan["id"]
        name = orphan["name"][:50]

        status, body = ls_delete(pid)

        if status in (200, 204):
            success_count += 1
            progress["deleted"].append(pid)
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{success_count}/{total}] Deleted: {name} ({pid[:8]}...)")
        elif status == 404:
            # Already gone — count as success
            success_count += 1
            progress["deleted"].append(pid)
            if (i + 1) % 50 == 0:
                print(f"  [{success_count}/{total}] Already gone: {name}")
        else:
            fail_count += 1
            progress["failed"].append({"id": pid, "name": name, "status": status, "body": body[:200]})
            print(f"  FAILED [{fail_count}]: {name} — HTTP {status}: {body[:100]}")

        # Save progress every 10 deletions
        if (i + 1) % 10 == 0:
            save_progress(progress)

    # Final save
    save_progress(progress)

    # Summary
    print()
    print("=" * 60)
    print(f"PHASE 1 COMPLETE")
    print(f"  Deleted:   {success_count}")
    print(f"  Failed:    {fail_count}")
    print(f"  Total:     {total}")
    print(f"  Progress:  {PROGRESS_FILE}")
    print(f"  Finished:  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    if fail_count > 0:
        print(f"\nWARNING: {fail_count} deletions failed. Review {PROGRESS_FILE} for details.")

if __name__ == "__main__":
    main()
