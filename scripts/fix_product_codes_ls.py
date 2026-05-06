#!/usr/bin/env python3
"""Fix product codes for the 1,193 products where the barcode write replaced the CUSTOM SKU code.

Root cause: write_barcodes_to_ls.py sent product_codes as a single-element UPC array,
which replaced the entire codes array (removing the CUSTOM/SKU code). Lightspeed also
mirrors the first Custom code into the sku field, so the product SKU changed to the barcode.

Fix: PUT with both CUSTOM (original ls_sku) and UPC (barcode) for all successful rows.

Usage:
    python3 scripts/fix_product_codes_ls.py [--dry-run]
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

REVIEWED_CSV = 'docs/fix_barcodes_lightspeed-reviewed.csv'
FAILURES_JSON = 'docs/write_barcodes_ls_errors.json'
OUT_ERRORS = 'docs/fix_product_codes_ls_errors.json'
OUT_LOG = 'docs/fix_product_codes_ls.log'


def load_token():
    env = Path('.env.local').read_text()
    for line in env.splitlines():
        if line.startswith('LIGHTSPEED_TOKEN='):
            return line.split('=', 1)[1].strip()
    raise ValueError("LIGHTSPEED_TOKEN not found in .env.local")


def put_product_codes(product_id, custom_sku, upc_code):
    url = f"{BASE_URL}/products/{product_id}"
    payload = json.dumps({
        "details": {
            "product_codes": [
                {"type": "CUSTOM", "code": custom_sku},
                {"type": "UPC", "code": upc_code},
            ]
        }
    }).encode()
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


def build_success_list():
    with open(REVIEWED_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    dnu = {'do not use', 'do not use '}
    actionable = [r for r in rows if r.get('Review', '').strip().lower() not in dnu]

    with open(FAILURES_JSON) as f:
        failures = json.load(f)
    failed_ids = {e['product_id'] for e in failures}

    successes = [
        r for r in actionable
        if r['ls_product_id'].strip() not in failed_ids
        and r['ls_product_id'].strip()
        and r['our_barcode'].strip()
        and r['ls_sku'].strip()
    ]
    return successes


def main():
    global LS_TOKEN
    LS_TOKEN = load_token()

    successes = build_success_list()
    print(f"Products to fix: {len(successes)}")

    if DRY_RUN:
        print("DRY RUN — no writes")
        for r in successes[:5]:
            print(f"  Would PUT {r['ls_product_id']} | CUSTOM={r['ls_sku']} | UPC={r['our_barcode']} | {r['ls_name'][:40]!r}")
        return

    ok, failed = 0, []
    for i, row in enumerate(successes):
        product_id = row['ls_product_id'].strip()
        custom_sku = row['ls_sku'].strip()
        upc_code = row['our_barcode'].strip()
        name = row['ls_name'].strip()

        success, resp = put_product_codes(product_id, custom_sku, upc_code)
        if success:
            ok += 1
        else:
            failed.append({
                'product_id': product_id,
                'custom_sku': custom_sku,
                'upc': upc_code,
                'name': name,
                'error': resp,
            })

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(successes)} | ok={ok} failed={len(failed)}")

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. Fixed: {ok} | Failed: {len(failed)}")

    if failed:
        Path(OUT_ERRORS).write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {OUT_ERRORS}")

    Path(OUT_LOG).write_text(json.dumps({
        'total': len(successes),
        'ok': ok,
        'failed': len(failed),
    }, indent=2))
    print(f"Log saved to {OUT_LOG}")


if __name__ == '__main__':
    main()
