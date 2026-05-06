#!/usr/bin/env python3
"""Execute deduplication: merge our LS product into conflict product, then delete ours.

For each row in docs/ls_dedupe_for_review.csv:
  1. GET conflict product's current product_codes
  2. Append our_sku as CUSTOM code (if not already present)
  3. PUT full product_codes array to conflict product
  4. If our retail_price > 0 (from Supabase), PUT price_excluding_tax to conflict product
  5. DELETE our LS product (our_product_id IS the LS UUID for our product)
  6. UPDATE Supabase products SET lightspeed_product_id = conflict_product_id WHERE sku = our_sku

Skip rows where conflict_product_id is empty (2 rows).

Note: our_product_id in the CSV is the LS product UUID for our imported product,
      not the Supabase bigint products.id. Use our_sku to join Supabase records.

Usage:
    python3 scripts/ls_dedupe_execute.py [--dry-run] [--limit N] [--offset N]
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
OFFSET = 0
for i, arg in enumerate(sys.argv):
    if arg == '--limit' and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])
    if arg == '--offset' and i + 1 < len(sys.argv):
        OFFSET = int(sys.argv[i + 1])

LS_TOKEN = None
SUPABASE_ACCESS_TOKEN = None
LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
SUPABASE_PROJECT = "ayfwyvripnetwrkimxka"
RATE_LIMIT_DELAY = 0.15  # ~6 req/sec (conservative — 3-4 API calls per row)

CSV_PATH = 'docs/ls_dedupe_for_review.csv'
OUT_ERRORS = 'docs/ls_dedupe_errors.json'
OUT_LOG = 'docs/ls_dedupe_execute.log'


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


def lookup_our_price(our_sku):
    safe_sku = our_sku.replace("'", "''")
    rows = supabase_query(f"""
        SELECT retail_price FROM products
        WHERE sku = '{safe_sku}'
        LIMIT 1
    """)
    if rows and isinstance(rows, list) and rows[0].get('retail_price') is not None:
        try:
            return float(rows[0]['retail_price'])
        except (TypeError, ValueError):
            return None
    return None


def ls_get_product_codes(product_id):
    """Return (product_codes list, error_str) for an LS product via v2.0 GET."""
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

    # v2.0 response wraps in data array; product_codes is on the first variant
    items = data.get('data', [])
    if not items:
        return None, "Empty data array in GET response"
    product = items[0] if isinstance(items, list) else items
    variants = product.get('variants', [])
    if variants:
        codes = variants[0].get('product_codes', [])
    else:
        codes = product.get('product_codes', [])
    return codes, None


def ls_put(product_id, payload_dict, base=LS_BASE_V21):
    url = f"{base}/products/{product_id}"
    payload = json.dumps(payload_dict).encode()
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


def supabase_update_ls_id(our_sku, conflict_product_id):
    safe_sku = our_sku.replace("'", "''")
    supabase_query(f"""
        UPDATE products
        SET lightspeed_product_id = '{conflict_product_id}'
        WHERE sku = '{safe_sku}'
    """)


def process_row(row):
    our_ls_id = row['our_product_id'].strip()   # LS UUID for OUR product
    our_sku = row['our_sku'].strip()
    conflict_product_id = row['conflict_product_id'].strip()

    if not conflict_product_id:
        return {'action': 'skipped', 'our_sku': our_sku, 'reason': 'no conflict_product_id'}

    steps = []
    errors = []

    # Step 1: GET conflict product's current product_codes
    codes, err = ls_get_product_codes(conflict_product_id)
    time.sleep(RATE_LIMIT_DELAY)
    if err:
        return {'action': 'error', 'our_sku': our_sku, 'conflict_product_id': conflict_product_id,
                'steps': steps, 'error': f'GET conflict product failed: {err}'}

    # Step 2: append our_sku as CUSTOM if not already present
    existing_customs = {c['code'] for c in codes if c.get('type') == 'CUSTOM'}
    if our_sku in existing_customs:
        steps.append(f'CUSTOM {our_sku!r} already on conflict — code append skipped')
    else:
        new_codes = list(codes) + [{'type': 'CUSTOM', 'code': our_sku}]
        steps.append(f'Appending CUSTOM {our_sku!r} → conflict now has {len(new_codes)} codes')
        if not DRY_RUN:
            ok, result = ls_put(conflict_product_id, {'details': {'product_codes': new_codes}})
            time.sleep(RATE_LIMIT_DELAY)
            if ok:
                steps.append('PUT product_codes OK')
            else:
                errors.append(f'PUT product_codes failed: {result}')

    # Step 3: sync price if our retail_price > 0
    our_price = lookup_our_price(our_sku)
    time.sleep(RATE_LIMIT_DELAY)
    if our_price and our_price > 0:
        steps.append(f'Syncing price ${our_price:.2f} to conflict')
        if not DRY_RUN:
            ok, result = ls_put(conflict_product_id, {'details': {'price_excluding_tax': our_price}})
            time.sleep(RATE_LIMIT_DELAY)
            if ok:
                steps.append('PUT price OK')
            else:
                errors.append(f'PUT price failed: {result}')
    else:
        steps.append(f'No price to sync (retail_price={our_price})')

    # Step 4: DELETE our LS product
    steps.append(f'Deleting our LS product {our_ls_id}')
    if not DRY_RUN:
        ok, result = ls_delete(our_ls_id)
        time.sleep(RATE_LIMIT_DELAY)
        if ok:
            steps.append('DELETE our LS product OK')
        else:
            errors.append(f'DELETE failed: {result}')

    # Step 5: update Supabase products record
    steps.append(f'Updating Supabase products.lightspeed_product_id → {conflict_product_id} WHERE sku={our_sku!r}')
    if not DRY_RUN:
        supabase_update_ls_id(our_sku, conflict_product_id)
        time.sleep(RATE_LIMIT_DELAY)
        steps.append('Supabase UPDATE OK')

    if errors:
        return {'action': 'error', 'our_sku': our_sku, 'conflict_product_id': conflict_product_id,
                'steps': steps, 'error': '; '.join(errors)}

    return {'action': 'merged', 'our_sku': our_sku, 'conflict_product_id': conflict_product_id, 'steps': steps}


def main():
    load_tokens()

    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        all_rows = list(csv.DictReader(f))

    skipped_no_conflict = [r for r in all_rows if not r['conflict_product_id'].strip()]
    actionable = [r for r in all_rows if r['conflict_product_id'].strip()]

    print(f"Total rows: {len(all_rows)}")
    print(f"Skipped (no conflict_product_id): {len(skipped_no_conflict)}")
    print(f"Actionable: {len(actionable)}")

    if OFFSET:
        actionable = actionable[OFFSET:]
        print(f"Resuming from offset {OFFSET} — {len(actionable)} remaining")

    if LIMIT:
        actionable = actionable[:LIMIT]
        print(f"Limiting to {LIMIT} rows")

    if DRY_RUN:
        print("\nDRY RUN — showing first 5:")
        for row in actionable[:5]:
            print(f"  our_sku={row['our_sku']!r}")
            print(f"    our_ls_id (to delete): {row['our_product_id']!r}")
            print(f"    conflict (to keep):    {row['conflict_product_id']!r} — {row['conflict_product_name'][:50]!r}")
            result = process_row(row)
            for step in result.get('steps', []):
                print(f"    → {step}")
        return

    merged, failed, skipped = 0, [], 0

    for i, row in enumerate(actionable):
        result = process_row(row)

        if result['action'] == 'merged':
            merged += 1
        elif result['action'] == 'skipped':
            skipped += 1
        else:
            failed.append(result)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(actionable)} | merged={merged} failed={len(failed)} skipped={skipped}")

    print(f"\nDone. Merged: {merged} | Failed: {len(failed)} | Skipped: {skipped}")

    if failed:
        Path(OUT_ERRORS).write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {OUT_ERRORS}")

    Path(OUT_LOG).write_text(json.dumps({
        'total_rows': len(all_rows),
        'actionable': len(actionable) + OFFSET,
        'offset': OFFSET,
        'merged': merged,
        'failed': len(failed),
        'skipped_no_conflict': len(skipped_no_conflict),
        'skipped_other': skipped,
    }, indent=2))
    print(f"Log saved to {OUT_LOG}")


if __name__ == '__main__':
    main()
