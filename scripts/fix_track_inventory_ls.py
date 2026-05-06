#!/usr/bin/env python3
"""Set track_inventory=true for all products we created in Lightspeed.

Identifies products by querying lightspeed_index for SKUs matching our format:
  ^[MWKALU]-[A-Z]{2,4}- (e.g. M-ARI-..., W-KON-..., K-SSI-...)

Sends PUT v2.1 {"common": {"track_inventory": true}} for each.

Usage:
    python3 scripts/fix_track_inventory_ls.py [--dry-run] [--limit N]
"""

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
BASE_URL = "https://therodeoshop.retail.lightspeed.app/api/2.1"
SUPABASE_PROJECT = "ayfwyvripnetwrkimxka"
RATE_LIMIT_DELAY = 0.12  # ~8 req/sec

OUT_ERRORS = 'docs/fix_track_inventory_errors.json'
OUT_LOG = 'docs/fix_track_inventory.log'


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


def fetch_our_products(offset=0):
    sql = f"""
        SELECT lightspeed_id, sku, name
        FROM lightspeed_index
        WHERE active = true
          AND sku ~ '^[MWKALU]-[A-Z]{{2,4}}-'
        ORDER BY sku
        OFFSET {offset}
    """
    rows = supabase_query(sql)
    return rows


def put_track_inventory(product_id):
    url = f"{BASE_URL}/products/{product_id}"
    payload = json.dumps({"common": {"track_inventory": True}}).encode()
    req = urllib.request.Request(url, data=payload, method='PUT', headers={
        'Authorization': f'Bearer {LS_TOKEN}',
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, {'status': e.code, 'body': body}


def main():
    load_tokens()

    print(f"Fetching our products from lightspeed_index (offset={OFFSET})...")
    products = fetch_our_products(offset=OFFSET)
    print(f"Found: {len(products)} products to process")

    if LIMIT:
        products = products[:LIMIT]
        print(f"Limiting to {LIMIT} for this run")

    if DRY_RUN:
        print("DRY RUN — no writes")
        for p in products[:5]:
            print(f"  Would PUT track_inventory=true on {p['lightspeed_id']} | {p['sku']} | {p['name'][:40]!r}")
        return

    ok, failed, skipped = 0, [], 0
    for i, product in enumerate(products):
        ls_id = product.get('lightspeed_id', '').strip()
        sku = product.get('sku', '')
        name = product.get('name', '')

        if not ls_id:
            skipped += 1
            continue

        success, err = put_track_inventory(ls_id)
        if success:
            ok += 1
        else:
            failed.append({'lightspeed_id': ls_id, 'sku': sku, 'name': name, 'error': err})

        if (i + 1) % 200 == 0:
            print(f"  Progress: {i+1}/{len(products)} | ok={ok} failed={len(failed)}")

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. Updated: {ok} | Failed: {len(failed)} | Skipped (no id): {skipped}")

    if failed:
        Path(OUT_ERRORS).write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {OUT_ERRORS}")

    Path(OUT_LOG).write_text(json.dumps({
        'total': len(products),
        'ok': ok,
        'failed': len(failed),
        'skipped_no_id': skipped,
    }, indent=2))
    print(f"Log saved to {OUT_LOG}")


if __name__ == '__main__':
    main()
