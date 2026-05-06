#!/usr/bin/env python3
"""Phase B: Write approved barcodes to Lightspeed.

Reads fix_barcodes_lightspeed-reviewed.csv, skips "Do Not Use" rows,
PUTs each barcode to LS v2.1 API as a UPC product_code.

Usage: python3 scripts/write_barcodes_to_ls.py [--dry-run]
"""

import csv
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DRY_RUN = '--dry-run' in sys.argv
LS_TOKEN = None
BASE_URL = "https://therodeoshop.retail.lightspeed.app/api/2.1"
RATE_LIMIT_DELAY = 0.12  # ~8 req/sec

def load_token():
    env = Path('.env.local').read_text()
    for line in env.splitlines():
        if line.startswith('LIGHTSPEED_TOKEN='):
            return line.split('=', 1)[1].strip()
    raise ValueError("LIGHTSPEED_TOKEN not found in .env.local")

def put_barcode(product_id, barcode, custom_sku):
    # product_codes is a FULL ARRAY REPLACEMENT — must include CUSTOM (SKU) or it gets wiped.
    url = f"{BASE_URL}/products/{product_id}"
    payload = json.dumps({"details": {"product_codes": [
        {"type": "CUSTOM", "code": custom_sku},
        {"type": "UPC", "code": barcode},
    ]}}).encode()
    req = urllib.request.Request(url, data=payload, method='PUT', headers={
        'Authorization': f'Bearer {LS_TOKEN}',
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, {'status': e.code, 'body': body}

def main():
    global LS_TOKEN
    LS_TOKEN = load_token()

    with open('docs/fix_barcodes_lightspeed-reviewed.csv', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    dnu = {'do not use', 'do not use '}
    actionable = [r for r in rows if r.get('Review', '').strip().lower() not in dnu]

    print(f"Total rows: {len(rows)}")
    print(f"Do Not Use (skipped): {len(rows) - len(actionable)}")
    print(f"To write: {len(actionable)}")
    if DRY_RUN:
        print("DRY RUN — no writes")
        for r in actionable[:5]:
            print(f"  Would PUT {r['ls_product_id']} barcode={r['our_barcode']} ({r['ls_name']!r})")
        return

    ok, failed, skipped = 0, [], 0
    for i, row in enumerate(actionable):
        product_id = row['ls_product_id'].strip()
        barcode = row['our_barcode'].strip()
        custom_sku = row['ls_sku'].strip()
        name = row['ls_name'].strip()

        if not product_id or not barcode or not custom_sku:
            skipped += 1
            continue

        success, resp = put_barcode(product_id, barcode, custom_sku)
        if success:
            ok += 1
        else:
            failed.append({'product_id': product_id, 'barcode': barcode, 'name': name, 'error': resp})

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(actionable)} | ok={ok} failed={len(failed)}")

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. Updated: {ok} | Failed: {len(failed)} | Skipped (empty): {skipped}")

    if failed:
        out = Path('docs/write_barcodes_ls_errors.json')
        out.write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {out}")

    # Summary log
    log = Path('docs/write_barcodes_ls.log')
    log.write_text(json.dumps({
        'total_actionable': len(actionable),
        'ok': ok,
        'failed': len(failed),
        'skipped_empty': skipped,
        'dnu_excluded': len(rows) - len(actionable),
    }, indent=2))
    print(f"Log saved to {log}")

if __name__ == '__main__':
    main()
