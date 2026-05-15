"""
ls_upc_fix.py
=============
Applies UPC corrections from Corrinne's reviewed audit sheet to Lightspeed.

Source: docs/ls_upc_audit-response.csv  (columns: ID, UPC, NEW UPC, Custom 1, Custom 2, ...)

Rules:
  - NEW UPC column has a valid 12/13-digit code  -> use it directly
  - NEW UPC column is empty (16 "other issues")  -> clear the UPC (remove from product_codes)
  - NEW UPC column is corrupted by Excel (decimal prefix like "63.9952356641444")
    -> auto-correct: prepend "0" to original 11-digit UPC, log as AUTO_CORRECTED

API: PUT v2.1 /products/{id}
  {"details": {"product_codes": [<CUSTOM codes>, <UPC if applicable>]}}

product_codes PUT replaces the full array — always include CUSTOM + UPC together.

Outputs:
  docs/ls_upc_fix_log.csv   — one row per variant: ID, action, old_upc, new_upc, status, note
  docs/ls_upc_fix_errors.csv — subset: only errors/failures for Corrinne's review

Usage:
  python3 docs/ls_upc_fix.py [--dry-run]
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DOCS = Path("docs")
INPUT_CSV = DOCS / "ls_upc_audit-response.csv"
LOG_CSV = DOCS / "ls_upc_fix_log.csv"
ERRORS_CSV = DOCS / "ls_upc_fix_errors.csv"

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.1"
HEADERS_BASE = {"User-Agent": "curl/7.81.0", "Content-Type": "application/json", "Accept": "application/json"}
SLEEP_BETWEEN = 1.1   # stay under 55 req/min
DRY_RUN = "--dry-run" in sys.argv


# ── Credentials ───────────────────────────────────────────────────────────────

def get_ls_token() -> str:
    for line in Path(".env.local").read_text().splitlines():
        if line.startswith("LIGHTSPEED_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


# ── LS API ────────────────────────────────────────────────────────────────────

def ls_put(token: str, variant_id: str, payload: dict) -> tuple[dict, int]:
    url = f"{LS_BASE}/products/{variant_id}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  429 rate limit — sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            body = {}
            try:
                body = json.loads(e.read())
            except Exception:
                pass
            return body, e.code
    return {}, 0


# ── UPC resolution ────────────────────────────────────────────────────────────

def resolve_new_upc(row: dict) -> tuple[str, str]:
    """
    Returns (upc_to_write, action) where:
      upc_to_write: the corrected UPC string, or "" to clear UPC
      action: USE_NEW | AUTO_CORRECTED | CLEAR
    """
    original = row["UPC"].strip()
    new_raw = row.get("NEW UPC", "").strip()

    if not new_raw:
        # 16 "other issues" rows — Corrinne said remove the UPC
        return "", "CLEAR"

    # Valid 12/13-digit code
    if new_raw.isdigit() and len(new_raw) in (12, 13):
        return new_raw, "USE_NEW"

    # Corrupted by Excel: decimal prefix = retail_price + original UPC
    # e.g. "63.9952356641444" where original UPC is "52356641444" (11 digits)
    # Auto-correct: prepend "0" to original 11-digit UPC
    if len(original) == 11 and original.isdigit():
        corrected = "0" + original
        return corrected, "AUTO_CORRECTED"

    # Unknown corruption — skip and log
    return "", "SKIP_UNKNOWN"


def build_product_codes(new_upc: str, row: dict) -> list[dict]:
    codes = []
    for col in ("Custom 1", "Custom 2"):
        val = row.get(col, "").strip()
        if val:
            codes.append({"type": "CUSTOM", "code": val})
    if new_upc:
        codes.append({"type": "UPC", "code": new_upc})
    return codes


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if DRY_RUN:
        print("DRY RUN — no LS writes will occur.", flush=True)

    token = get_ls_token()

    rows = list(csv.DictReader(open(INPUT_CSV)))
    print(f"Loaded {len(rows):,} rows from {INPUT_CSV}", flush=True)

    log_fields = ["ID", "Name", "action", "old_upc", "new_upc", "status", "http_status", "note"]
    log_rows = []

    stats = {"USE_NEW": 0, "AUTO_CORRECTED": 0, "CLEAR": 0, "SKIP_UNKNOWN": 0,
             "ok": 0, "error": 0}
    auto_corrected_ids = []

    for i, row in enumerate(rows, 1):
        variant_id = row["ID"].strip()
        original_upc = row["UPC"].strip()
        name = row["Name"].strip()

        new_upc, action = resolve_new_upc(row)

        if action == "SKIP_UNKNOWN":
            print(f"  [{i}/{len(rows)}] SKIP_UNKNOWN {variant_id} — UPC={original_upc}, NEW='{row.get('NEW UPC','')}'", flush=True)
            log_rows.append({
                "ID": variant_id, "Name": name, "action": action,
                "old_upc": original_upc, "new_upc": "",
                "status": "SKIPPED", "http_status": "", "note": f"Cannot parse NEW UPC: {row.get('NEW UPC','')}",
            })
            stats["SKIP_UNKNOWN"] += 1
            continue

        stats[action] += 1
        if action == "AUTO_CORRECTED":
            auto_corrected_ids.append(variant_id)

        product_codes = build_product_codes(new_upc, row)
        payload = {"details": {"product_codes": product_codes}}

        if i % 100 == 1:
            print(f"  [{i}/{len(rows)}] {action} {variant_id} UPC: {original_upc} -> {new_upc or '(cleared)'}", flush=True)

        if DRY_RUN:
            log_rows.append({
                "ID": variant_id, "Name": name, "action": action,
                "old_upc": original_upc, "new_upc": new_upc,
                "status": "DRY_RUN", "http_status": "", "note": "",
            })
            stats["ok"] += 1
            continue

        resp_body, http_status = ls_put(token, variant_id, payload)
        time.sleep(SLEEP_BETWEEN)

        if http_status in (200, 201):
            status = "OK"
            note = ""
            stats["ok"] += 1
        else:
            status = "ERROR"
            note = json.dumps(resp_body)[:200]
            stats["error"] += 1
            print(f"  ERROR [{i}] {variant_id} http={http_status} {note}", flush=True)

        log_rows.append({
            "ID": variant_id, "Name": name, "action": action,
            "old_upc": original_upc, "new_upc": new_upc,
            "status": status, "http_status": http_status, "note": note,
        })

    # Write full log
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=log_fields)
        w.writeheader()
        w.writerows(log_rows)

    # Write errors-only CSV for Corrinne
    error_rows = [r for r in log_rows if r["status"] == "ERROR"]
    with open(ERRORS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=log_fields)
        w.writeheader()
        w.writerows(error_rows)

    print(f"\n{'='*60}", flush=True)
    print(f"DONE", flush=True)
    print(f"  USE_NEW:        {stats['USE_NEW']:,}", flush=True)
    print(f"  AUTO_CORRECTED: {stats['AUTO_CORRECTED']:,} (leading-zero added to 11-digit UPCs with Excel-corrupted NEW UPC)", flush=True)
    print(f"  CLEAR:          {stats['CLEAR']:,} (UPC removed — 'other issues' rows)", flush=True)
    print(f"  SKIP_UNKNOWN:   {stats['SKIP_UNKNOWN']:,}", flush=True)
    print(f"  OK:             {stats['ok']:,}", flush=True)
    print(f"  ERROR:          {stats['error']:,}", flush=True)
    print(f"\nFull log:   {LOG_CSV}", flush=True)
    print(f"Error log:  {ERRORS_CSV} ({len(error_rows)} rows)", flush=True)

    if auto_corrected_ids:
        print(f"\nNOTE: {len(auto_corrected_ids)} variants had corrupted NEW UPC values in Corrinne's sheet", flush=True)
        print(f"(Excel formatted them as retail_price + UPC). Auto-corrected by prepending '0' to", flush=True)
        print(f"the original 11-digit UPC — same fix as all other 11-digit UPCs.", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\nCompleted at {ts}", flush=True)


if __name__ == "__main__":
    main()
