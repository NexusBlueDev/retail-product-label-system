#!/usr/bin/env python3
"""Execute Corrinne-approved merges from docs/ls_duplicate_merge_review-REVIEWED.csv.

For each approved row:
  1. DELETE the delete_id from LS (soft-delete — frees the CUSTOM code)
  2. UPDATE Supabase products.lightspeed_product_id = keep_id WHERE lightspeed_product_id = delete_id
  3. If 'Do this' specifies a new SKU (starts with 'Use SKU' or 'Use sKU'):
     a. GET keep product's current product_codes
     b. Replace any existing CUSTOM code with the new SKU (preserve UPC codes)
     c. PUT updated codes to keep product via v2.1

Four rows have suspicious SKU assignments (size label in keep_sku doesn't match 'Do this' SKU):
  - 2f0852cd (16W-L Nashville) → "16W-R" SKU — appears to be a cyclic shift
  - f3dbd2d8 (16W-R Nashville) → "18W-L" SKU — appears to be a cyclic shift
  - 7d1b6dea (18W-L Nashville) → "16W-L" SKU — appears to be a cyclic shift
  - 7214c374 (33-X-L Nashville) → "28-XL" SKU — large size discrepancy
Delete + Supabase update still execute; only the CUSTOM code update is held for confirmation.

Usage:
    python3 scripts/ls_merge_reviewed.py [--dry-run] [--limit N]
"""

import csv
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DRY_RUN = '--dry-run' in sys.argv
LIMIT = None
for i, arg in enumerate(sys.argv):
    if arg == '--limit' and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

LS_TOKEN = None
SUPABASE_ACCESS_TOKEN = None
LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
SUPABASE_PROJECT = "ayfwyvripnetwrkimxka"
RATE_LIMIT_DELAY = 0.2

CSV_PATH = 'docs/ls_duplicate_merge_review-REVIEWED.csv'
OUT_LOG = 'docs/ls_merge_reviewed.log'

# These keep_ids have suspicious 'Do this' SKU assignments — delete proceeds, SKU update is held.
SUSPICIOUS_KEEP_IDS = {
    '2f0852cd-21e2-4386-805a-55c00439e5d3',  # 16W-L Nashville keep → requested "16W-R" SKU
    'f3dbd2d8-489b-4b4e-aa0e-5e9004846395',  # 16W-R Nashville keep → requested "18W-L" SKU
    '7d1b6dea-4919-4b49-b06c-920b3a7ea0ba',  # 18W-L Nashville keep → requested "16W-L" SKU
    '7214c374-c764-4c10-b11f-189284326477',  # 33-X-L Nashville keep → requested "28-XL" SKU
}


def load_tokens():
    global LS_TOKEN, SUPABASE_ACCESS_TOKEN
    env = Path('.env.local').read_text()
    for line in env.splitlines():
        if line.startswith('LIGHTSPEED_TOKEN='):
            LS_TOKEN = line.split('=', 1)[1].strip()
        elif line.startswith('SUPABASE_ACCESS_TOKEN='):
            SUPABASE_ACCESS_TOKEN = line.split('=', 1)[1].strip()
    if not LS_TOKEN:
        raise ValueError("LIGHTSPEED_TOKEN not found in .env.local")
    if not SUPABASE_ACCESS_TOKEN:
        raise ValueError("SUPABASE_ACCESS_TOKEN not found in .env.local")


def supabase_query(sql):
    url = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT}/database/query"
    payload = json.dumps({"query": sql})
    result = subprocess.run(
        ['curl', '-s', '-X', 'POST', url,
         '-H', f'Authorization: Bearer {SUPABASE_ACCESS_TOKEN}',
         '-H', 'Content-Type: application/json',
         '-d', payload],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def ls_get_product_codes(product_id):
    url = f"{LS_BASE_V20}/products/{product_id}"
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {LS_TOKEN}',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return None, f"HTTP {e.code}: {body[:200]}"
    items = data.get('data', [])
    if not items:
        return [], None
    product = items[0] if isinstance(items, list) else items
    variants = product.get('variants', [])
    codes = variants[0].get('product_codes', []) if variants else product.get('product_codes', [])
    return codes, None


def ls_put_codes(product_id, codes):
    url = f"{LS_BASE_V21}/products/{product_id}"
    payload = json.dumps({'details': {'product_codes': codes}}).encode()
    req = urllib.request.Request(url, data=payload, method='PUT', headers={
        'Authorization': f'Bearer {LS_TOKEN}',
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, {'status': e.code, 'body': body[:300]}


def ls_delete(product_id):
    url = f"{LS_BASE_V20}/products/{product_id}"
    req = urllib.request.Request(url, method='DELETE', headers={
        'Authorization': f'Bearer {LS_TOKEN}',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, {'status': e.code, 'body': body[:300]}


def update_supabase_ls_id(delete_id, keep_id):
    safe_del = delete_id.replace("'", "''")
    safe_keep = keep_id.replace("'", "''")
    rows = supabase_query(f"""
        UPDATE products
        SET lightspeed_product_id = '{safe_keep}'
        WHERE lightspeed_product_id = '{safe_del}'
        RETURNING id, sku
    """)
    return rows if isinstance(rows, list) else []


def parse_new_sku(do_this):
    """Extract SKU string from 'Use SKU ...' or 'Use sKU ...' instruction."""
    s = do_this.strip()
    lower = s.lower()
    if lower.startswith('use sku'):
        return s[7:].strip()
    return None


def process_row(row, log_lines):
    keep_sku = row['keep_sku'].strip()
    keep_id = row['keep_id'].strip()
    delete_sku = row['delete_sku'].strip()
    delete_id = row['delete_id'].strip()
    approve = row['corrinne_approve'].strip()
    do_this = row.get('Do this', '').strip()

    if not approve:
        log_lines.append(f"  SKIP (no approval): {delete_sku}")
        return 'skipped'

    steps = []
    errors = []

    # Step 1: DELETE the duplicate LS product
    steps.append(f"DELETE LS {delete_id} ({delete_sku})")
    if not DRY_RUN:
        ok, res = ls_delete(delete_id)
        time.sleep(RATE_LIMIT_DELAY)
        if ok:
            steps.append(f"  DELETE OK (status={res})")
        elif isinstance(res, dict) and res.get('status') == 404:
            steps.append(f"  DELETE 404 — already gone (OK)")
        else:
            errors.append(f"DELETE failed: {res}")

    # Step 2: UPDATE Supabase lightspeed_product_id
    steps.append(f"Supabase UPDATE lp_id: {delete_id} → {keep_id}")
    if not DRY_RUN:
        updated = update_supabase_ls_id(delete_id, keep_id)
        time.sleep(RATE_LIMIT_DELAY)
        skus = [r.get('sku', r.get('id', '?')) for r in updated]
        steps.append(f"  Updated {len(updated)} row(s): {skus}")

    # Step 3: Update CUSTOM code on keep product (if 'Do this' has a SKU)
    new_sku = parse_new_sku(do_this) if do_this else None
    if new_sku:
        if keep_id in SUSPICIOUS_KEEP_IDS:
            steps.append(f"  HELD — suspicious SKU: '{keep_sku}' → '{new_sku}'")
            steps.append(f"    Looks like a spreadsheet shift or size mismatch — confirm before applying.")
        else:
            steps.append(f"PUT CUSTOM code {new_sku!r} on keep {keep_id}")
            if not DRY_RUN:
                codes, err = ls_get_product_codes(keep_id)
                time.sleep(RATE_LIMIT_DELAY)
                if err:
                    errors.append(f"GET keep codes failed: {err}")
                else:
                    non_custom = [c for c in (codes or []) if c.get('type') != 'CUSTOM']
                    new_codes = non_custom + [{'type': 'CUSTOM', 'code': new_sku}]
                    ok, res = ls_put_codes(keep_id, new_codes)
                    time.sleep(RATE_LIMIT_DELAY)
                    if ok:
                        steps.append(f"  PUT OK — CUSTOM={new_sku!r}, total {len(new_codes)} code(s)")
                    else:
                        errors.append(f"PUT codes failed: {res}")

    tag = '[DRY]' if DRY_RUN else ('ERR' if errors else 'OK ')
    log_lines.append(f"  [{tag}] keep={keep_sku} | delete={delete_sku}")
    for s in steps:
        log_lines.append(f"       {s}")
    if errors:
        log_lines.append(f"       ERRORS: {errors}")

    return 'error' if errors else 'ok'


def main():
    load_tokens()

    rows = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get('keep_id', '').strip():
                continue
            rows.append(row)

    if LIMIT:
        rows = rows[:LIMIT]

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Processing {len(rows)} rows from {CSV_PATH}")

    log_lines = [f"ls_merge_reviewed.py — {'DRY RUN' if DRY_RUN else 'LIVE'} — {len(rows)} rows\n"]
    counts = {'ok': 0, 'skipped': 0, 'error': 0}
    held = []

    for i, row in enumerate(rows, 1):
        keep_sku = row.get('keep_sku', '').strip()
        keep_id = row.get('keep_id', '').strip()
        delete_sku = row.get('delete_sku', '').strip()
        do_this = row.get('Do this', '').strip()
        print(f"  [{i}/{len(rows)}] {delete_sku[:60]}")
        log_lines.append(f"\n--- Row {i}: keep={keep_sku} | delete={delete_sku} ---")

        status = process_row(row, log_lines)
        counts[status] = counts.get(status, 0) + 1

        if keep_id in SUSPICIOUS_KEEP_IDS and do_this:
            new_sku = parse_new_sku(do_this)
            if new_sku:
                held.append({'keep_sku': keep_sku, 'keep_id': keep_id, 'requested_sku': new_sku})

    log_lines.append(f"\n{'='*60}")
    log_lines.append(f"SUMMARY: OK={counts.get('ok',0)} | Skipped={counts.get('skipped',0)} | Errors={counts.get('error',0)}")

    if held:
        # Deduplicate (same keep_id may appear in multiple rows)
        seen = set()
        unique_held = [h for h in held if not (h['keep_id'] in seen or seen.add(h['keep_id']))]
        log_lines.append(f"\nHELD SKU UPDATES ({len(unique_held)}) — needs Corrinne confirmation:")
        for h in unique_held:
            log_lines.append(f"  keep_id={h['keep_id']}")
            log_lines.append(f"    current keep_sku : {h['keep_sku']}")
            log_lines.append(f"    requested new SKU: {h['requested_sku']}")
        log_lines.append(f"\n  Note: rows for 16W-L/16W-R/18W-L Nashville products have 'Do this' SKUs")
        log_lines.append(f"  that appear to be a 3-way cyclic shift (each product gets another's size).")
        log_lines.append(f"  Row for 33-X-L Nashville has 'Do this'='28-XL' — large size discrepancy.")
        log_lines.append(f"  Please confirm intended SKUs and re-run with --apply-held flag (to be added).")

    out_text = '\n'.join(log_lines)
    Path(OUT_LOG).write_text(out_text)

    print(f"\nDone. OK={counts.get('ok',0)}, Skipped={counts.get('skipped',0)}, Errors={counts.get('error',0)}")
    if held:
        print(f"HELD: {len(set(h['keep_id'] for h in held))} suspicious SKU updates — see {OUT_LOG}")
    print(f"Log: {OUT_LOG}")


if __name__ == '__main__':
    main()
