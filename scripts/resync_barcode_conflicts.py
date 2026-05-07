"""
Remediate 532 products where S13 UPC write failed with "Product codes must be unique."

Background:
  - S13 (2026-05-06): write_barcodes_to_ls.py got 422 conflicts for 532 products.
  - S14 (2026-05-06): LS deduplication deleted 530 duplicate products.
  - After S14, the conflict products are soft-deleted. Their barcodes appear to have
    been freed from uniqueness enforcement. The ACTIVE product for each item is the
    original LS product whose CUSTOM code was updated by S14's dedupe process.

This script:
  1. For each of the 532 failed products:
     a. Looks up the active LS product by searching for our SKU.
     b. Writes the UPC to the active product via v2.1 PUT details.product_codes.
     c. Updates our Supabase DB lightspeed_product_id to the active product UUID.
  2. Reports what was fixed, what still conflicts, and what needs manual review.

Usage:
    python3 scripts/resync_barcode_conflicts.py [--dry-run] [--limit N] [--offset N]

Output:
    docs/resync_results.json        — full results (written, conflict, manual_review)
    docs/resync_manual_review.csv   — rows that couldn't be auto-resolved
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import csv
import os
import sys
import time
import argparse

LS_BASE_V20 = 'https://therodeoshop.retail.lightspeed.app/api/2.0'
LS_BASE_V21 = 'https://therodeoshop.retail.lightspeed.app/api/2.1'
SB_URL = 'https://ayfwyvripnetwrkimxka.supabase.co'

ERRORS_FILE   = 'docs/write_barcodes_ls_errors.json'
RESULTS_FILE  = 'docs/resync_results.json'
REVIEW_CSV    = 'docs/resync_manual_review.csv'


def load_env():
    token_ls = token_sb = None
    with open('.env.local') as f:
        for line in f:
            if line.startswith('LIGHTSPEED_TOKEN='):
                token_ls = line.strip().split('=', 1)[1]
            elif line.startswith('SUPABASE_ACCESS_TOKEN='):
                token_sb = line.strip().split('=', 1)[1]
    if not token_ls:
        raise RuntimeError('LIGHTSPEED_TOKEN not found')
    if not token_sb:
        raise RuntimeError('SUPABASE_ACCESS_TOKEN not found')
    return token_ls, token_sb


def ls_headers(token):
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Accept': 'application/json'}


def ls_get(token, path, base=LS_BASE_V20):
    url = f'{base}/{path}'
    req = urllib.request.Request(url, headers=ls_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}'), e.code


def ls_put(token, product_id, payload_dict):
    url = f'{LS_BASE_V21}/products/{product_id}'
    payload = json.dumps(payload_dict).encode()
    req = urllib.request.Request(url, data=payload, method='PUT', headers=ls_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}'), e.code


def ls_search(token, q):
    path = f'search?type=products&q={urllib.parse.quote(q)}&limit=10'
    data, status = ls_get(token, path)
    if status != 200:
        return []
    return (data.get('data') or [])


MGMT_BASE = 'https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query'

def sb_sql(sb_token, query):
    """Run a SQL query via Supabase Management API."""
    payload = json.dumps({'query': query}).encode()
    req = urllib.request.Request(MGMT_BASE, data=payload, method='POST', headers={
        'Authorization': f'Bearer {sb_token}',
        'Content-Type': 'application/json',
        'User-Agent': 'curl/7.81.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        return (json.loads(body) if body else []), e.code


def get_our_db_product(sb_token, ls_product_id):
    """Get our DB product row by lightspeed_product_id."""
    safe = ls_product_id.replace("'", "''")
    rows, _ = sb_sql(sb_token, f"SELECT id, sku, barcode, lightspeed_product_id FROM products "
                               f"WHERE lightspeed_product_id = '{safe}' LIMIT 1")
    return rows[0] if rows else None


def sb_patch_ls_id(sb_token, db_id, new_ls_id):
    """Update products.lightspeed_product_id for a given DB product id."""
    safe = new_ls_id.replace("'", "''")
    _, status = sb_sql(sb_token, f"UPDATE products SET lightspeed_product_id = '{safe}' WHERE id = {db_id}")
    return status


def find_active_ls_product(token, our_sku, barcode):
    """
    Find the active LS product that should hold our barcode.
    Strategy: search by barcode first (may already be assigned), then by SKU.
    """
    # Search by barcode
    if barcode:
        results = ls_search(token, barcode)
        for p in results:
            if not p.get('deleted_at') and p.get('active'):
                return p

    # Search by SKU
    if our_sku:
        results = ls_search(token, our_sku)
        # Prefer exact CUSTOM code match
        for p in results:
            if not p.get('deleted_at') and p.get('active'):
                codes = p.get('product_codes') or []
                if any(c.get('code') == our_sku for c in codes):
                    return p
        # Fallback: any active match
        for p in results:
            if not p.get('deleted_at') and p.get('active'):
                return p

    return None


def write_upc_to_product(token, product, barcode):
    """
    Add UPC to an LS product's product_codes without overwriting existing codes.
    Returns (success: bool, detail: str).
    """
    existing_codes = product.get('product_codes') or []
    # Check if UPC already present
    if any(c.get('type', '').upper() == 'UPC' and c.get('code') == barcode for c in existing_codes):
        return True, 'already_present'

    # Preserve non-UPC codes, add our UPC
    new_codes = [c for c in existing_codes if c.get('type', '').upper() != 'UPC']
    new_codes.append({'type': 'UPC', 'code': barcode})

    resp, status = ls_put(token, product['id'], {'details': {'product_codes': new_codes}})
    if status in (200, 201, 204):
        return True, 'written'
    return False, f'PUT {status}: {json.dumps(resp)[:150]}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    ls_token, sb_token = load_env()

    with open(ERRORS_FILE) as f:
        errors = json.load(f)

    start = args.offset
    end = start + args.limit if args.limit else len(errors)
    batch = errors[start:end]

    print(f'Processing {len(batch)} of {len(errors)} entries (offset={start})'
          f'{"  DRY RUN" if args.dry_run else ""}')

    written = 0
    already_ok = 0
    still_conflict = 0
    manual_review = 0
    results = []

    for i, entry in enumerate(batch):
        old_ls_id = entry['product_id']
        barcode = entry['barcode']
        name = entry['name']

        if (i + 1) % 20 == 0:
            print(f'  [{i+1}/{len(batch)}] written={written} already_ok={already_ok} '
                  f'conflict={still_conflict} review={manual_review}')

        # Find our DB product (may have been updated already)
        db_row = get_our_db_product(sb_token, old_ls_id)
        our_sku = db_row['sku'] if db_row else None
        db_id = db_row['id'] if db_row else None

        time.sleep(0.06)

        # Find the active LS product
        active_product = find_active_ls_product(ls_token, our_sku, barcode)

        if not active_product:
            results.append({'old_ls_id': old_ls_id, 'barcode': barcode, 'name': name,
                             'outcome': 'manual_review', 'detail': 'No active LS product found'})
            manual_review += 1
            continue

        active_id = active_product['id']

        if args.dry_run:
            results.append({'old_ls_id': old_ls_id, 'active_ls_id': active_id,
                             'barcode': barcode, 'name': name, 'outcome': 'would_write'})
            continue

        # Write UPC
        ok, detail = write_upc_to_product(ls_token, active_product, barcode)
        time.sleep(0.06)

        if ok:
            label = 'already_present' if detail == 'already_present' else 'written'
            # Update our DB lightspeed_product_id if it still points to the old (deleted) product
            if db_id and active_id != old_ls_id:
                status = sb_patch_ls_id(sb_token, db_id, active_id)
                db_note = f'DB updated to {active_id}' if status in (200, 201, 204) else f'DB update failed ({status})'
            else:
                db_note = 'DB pointer unchanged'

            results.append({'old_ls_id': old_ls_id, 'active_ls_id': active_id,
                             'barcode': barcode, 'name': name, 'outcome': label,
                             'db_note': db_note})
            if label == 'already_present':
                already_ok += 1
            else:
                written += 1
        elif '422' in detail:
            results.append({'old_ls_id': old_ls_id, 'active_ls_id': active_id,
                             'barcode': barcode, 'name': name, 'outcome': 'conflict',
                             'detail': detail})
            still_conflict += 1
        else:
            results.append({'old_ls_id': old_ls_id, 'active_ls_id': active_id,
                             'barcode': barcode, 'name': name, 'outcome': 'manual_review',
                             'detail': detail})
            manual_review += 1

    print(f'\nDone. Written: {written} | Already OK: {already_ok} | '
          f'Still conflicting: {still_conflict} | Manual review: {manual_review}')

    with open(RESULTS_FILE, 'w') as f:
        json.dump({'written': written, 'already_ok': already_ok,
                   'still_conflict': still_conflict, 'manual_review': manual_review,
                   'results': results}, f, indent=2)
    print(f'Results → {RESULTS_FILE}')

    review_rows = [r for r in results if r['outcome'] in ('conflict', 'manual_review')]
    if review_rows:
        with open(REVIEW_CSV, 'w', newline='') as f:
            fields = ['old_ls_id', 'active_ls_id', 'barcode', 'name', 'outcome', 'detail', 'db_note']
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in review_rows:
                w.writerow({k: r.get(k, '') for k in fields})
        print(f'Manual review CSV → {REVIEW_CSV}  ({len(review_rows)} rows)')


if __name__ == '__main__':
    main()
