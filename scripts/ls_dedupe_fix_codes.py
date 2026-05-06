#!/usr/bin/env python3
"""Retry the product_codes PUT step for dedupe rows that failed with 422.

All 530 rows in docs/ls_dedupe_errors.json had their LS product DELETED and Supabase
UPDATED successfully. The only failure was the product_codes PUT (because our product
still held the CUSTOM code at that point). Now that our products are deleted, the codes
are freed and can be assigned to the conflict product.

Usage:
    python3 scripts/ls_dedupe_fix_codes.py [--dry-run] [--limit N]
"""

import json
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
LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
RATE_LIMIT_DELAY = 0.15

ERRORS_PATH = 'docs/ls_dedupe_errors.json'
OUT_LOG = 'docs/ls_dedupe_fix_codes.log'
OUT_ERRORS = 'docs/ls_dedupe_fix_codes_errors.json'


def load_token():
    global LS_TOKEN
    env = Path('.env.local').read_text()
    for line in env.splitlines():
        if line.startswith('LIGHTSPEED_TOKEN='):
            LS_TOKEN = line.split('=', 1)[1].strip()
    if not LS_TOKEN:
        raise ValueError("LIGHTSPEED_TOKEN not found in .env.local")


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
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"
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


def main():
    load_token()

    errors = json.loads(Path(ERRORS_PATH).read_text())
    print(f"Rows to fix: {len(errors)}")

    if LIMIT:
        errors = errors[:LIMIT]
        print(f"Limiting to {LIMIT}")

    if DRY_RUN:
        print("DRY RUN — showing first 3:")
        for e in errors[:3]:
            print(f"  conflict={e['conflict_product_id']!r} our_sku={e['our_sku']!r}")
        return

    ok, failed = 0, []

    for i, row in enumerate(errors):
        conflict_id = row['conflict_product_id']
        our_sku = row['our_sku']

        # GET current codes on conflict product
        codes, err = ls_get_product_codes(conflict_id)
        time.sleep(RATE_LIMIT_DELAY)
        if err:
            failed.append({'our_sku': our_sku, 'conflict_product_id': conflict_id, 'error': f'GET failed: {err}'})
            continue

        # Check if our_sku is already there (idempotent)
        existing_customs = {c['code'] for c in codes if c.get('type') == 'CUSTOM'}
        if our_sku in existing_customs:
            ok += 1
            continue

        new_codes = list(codes) + [{'type': 'CUSTOM', 'code': our_sku}]
        ok_put, result = ls_put_codes(conflict_id, new_codes)
        time.sleep(RATE_LIMIT_DELAY)

        if ok_put:
            ok += 1
        else:
            failed.append({'our_sku': our_sku, 'conflict_product_id': conflict_id, 'error': f'PUT failed: {result}'})

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(errors)} | ok={ok} failed={len(failed)}")

    print(f"\nDone. OK: {ok} | Failed: {len(failed)}")

    if failed:
        Path(OUT_ERRORS).write_text(json.dumps(failed, indent=2))
        print(f"Remaining errors: {OUT_ERRORS}")

    Path(OUT_LOG).write_text(json.dumps({'total': len(errors), 'ok': ok, 'failed': len(failed)}, indent=2))
    print(f"Log: {OUT_LOG}")


if __name__ == '__main__':
    main()
