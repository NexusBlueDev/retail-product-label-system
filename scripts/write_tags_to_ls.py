#!/usr/bin/env python3
"""Write normalized demographic tags from our Supabase products to matching LS products.

Sources:
  - products.tags (text, comma-separated) → normalize to canonical LS tag UUIDs
  - products.retail_price ending in .97 → add Clearance tag

Tag normalization:
  Men / Mens / MNS / Men's             → Men       (95f3fa5b-4ab0-452f-982a-026f9a738fa5)
  Women / Womens / Woman / Women's     → Women     (d9ba208c-b139-45ac-998e-774dcea07449)
  Ladies / WMS                         → Women
  Kids / Kid's / Kids?                 → Kids      (41a95de2-1c29-4bb7-ba04-78756cb2f139)
  Boys / Boy                           → BOYS      (012e8190-50c1-4071-a6ae-6a21d150fe43)
  Girls / Girl                         → GIRLS     (1a7d98bf-1a04-4e9a-b6e6-8b92f6fdc3d8)
  Adult / Adults                       → Adult     (e8071db8-4a36-4ede-8383-0c3dd83567c5)
  Youth / YTH                          → Youth     (f77cb111-92c5-4451-a22e-528fd5f8255c)
  Infant / Infants / Toddler           → Infant/Toddler (976e073c-af50-40ab-aabd-2bdea394924a)
  Unisex                               → Unisex    (cc0620e0-90bd-49b1-a6d1-24a6f2ae6aab)
  Clearance                            → Clearance (9a915378-5288-420b-8902-50963d08b68c) [created S14]

LS product matching:
  1. products.lightspeed_product_id if set
  2. lightspeed_index WHERE sku = products.sku AND active = true

Operation is ADDITIVE — existing LS tag_ids are merged, never replaced.

Usage:
    python3 scripts/write_tags_to_ls.py [--dry-run] [--limit N] [--offset N]
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
LS_BASE_V20 = "https://therodeoshop.retail.lightspeed.app/api/2.0"
LS_BASE_V21 = "https://therodeoshop.retail.lightspeed.app/api/2.1"
SUPABASE_PROJECT = "ayfwyvripnetwrkimxka"
RATE_LIMIT_DELAY = 0.15

OUT_ERRORS = 'docs/write_tags_ls_errors.json'
OUT_LOG = 'docs/write_tags_ls.log'

# Canonical LS tag UUID mapping — normalization target per token (case-insensitive)
TAG_UUID_MAP = {
    'men': '95f3fa5b-4ab0-452f-982a-026f9a738fa5',
    'mens': '95f3fa5b-4ab0-452f-982a-026f9a738fa5',
    "men's": '95f3fa5b-4ab0-452f-982a-026f9a738fa5',
    'mns': '95f3fa5b-4ab0-452f-982a-026f9a738fa5',
    'women': 'd9ba208c-b139-45ac-998e-774dcea07449',
    'womens': 'd9ba208c-b139-45ac-998e-774dcea07449',
    "women's": 'd9ba208c-b139-45ac-998e-774dcea07449',
    'woman': 'd9ba208c-b139-45ac-998e-774dcea07449',
    'ladies': 'd9ba208c-b139-45ac-998e-774dcea07449',
    'wms': 'd9ba208c-b139-45ac-998e-774dcea07449',
    'kids': '41a95de2-1c29-4bb7-ba04-78756cb2f139',
    "kid's": '41a95de2-1c29-4bb7-ba04-78756cb2f139',
    'kids?': '41a95de2-1c29-4bb7-ba04-78756cb2f139',
    'boys': '012e8190-50c1-4071-a6ae-6a21d150fe43',
    'boy': '012e8190-50c1-4071-a6ae-6a21d150fe43',
    'girls': '1a7d98bf-1a04-4e9a-b6e6-8b92f6fdc3d8',
    'girl': '1a7d98bf-1a04-4e9a-b6e6-8b92f6fdc3d8',
    'adult': 'e8071db8-4a36-4ede-8383-0c3dd83567c5',
    'adults': 'e8071db8-4a36-4ede-8383-0c3dd83567c5',
    'youth': 'f77cb111-92c5-4451-a22e-528fd5f8255c',
    'yth': 'f77cb111-92c5-4451-a22e-528fd5f8255c',
    'infant': '976e073c-af50-40ab-aabd-2bdea394924a',
    'infants': '976e073c-af50-40ab-aabd-2bdea394924a',
    'toddler': '976e073c-af50-40ab-aabd-2bdea394924a',
    'toddlers': '976e073c-af50-40ab-aabd-2bdea394924a',
    'infant/toddler': '976e073c-af50-40ab-aabd-2bdea394924a',
    'unisex': 'cc0620e0-90bd-49b1-a6d1-24a6f2ae6aab',
    'clearance': '9a915378-5288-420b-8902-50963d08b68c',
}

CLEARANCE_UUID = '9a915378-5288-420b-8902-50963d08b68c'


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


def fetch_products_to_tag():
    """
    Returns rows: {sku, tags, retail_price, ls_id}
    ls_id is from lightspeed_product_id if set, otherwise from lightspeed_index.
    """
    rows = supabase_query("""
        SELECT
            p.sku,
            p.tags,
            p.retail_price,
            COALESCE(p.lightspeed_product_id, li.lightspeed_id) AS ls_id
        FROM products p
        LEFT JOIN lightspeed_index li
            ON li.sku = p.sku AND li.active = true
        WHERE
            (p.tags IS NOT NULL AND p.tags != '')
            OR (p.retail_price IS NOT NULL AND (p.retail_price::text LIKE '%.97'))
        ORDER BY p.sku
    """)
    # Filter to only rows where we have an LS ID
    return [r for r in rows if r.get('ls_id')]


def normalize_tags(tags_text, retail_price):
    """Return set of canonical LS tag UUIDs from our messy tags string + price."""
    uuids = set()

    if tags_text:
        tokens = [t.strip().lower().rstrip('.,;') for t in tags_text.split(',')]
        for token in tokens:
            if not token:
                continue
            uuid = TAG_UUID_MAP.get(token)
            if uuid:
                uuids.add(uuid)
            # else: unrecognized token — silently drop (F, Tack, Tall, Earrings, etc.)

    if retail_price:
        try:
            price_str = str(retail_price).strip()
            if price_str.endswith('.97'):
                uuids.add(CLEARANCE_UUID)
        except (ValueError, TypeError):
            pass

    return uuids


def ls_get_tag_ids(ls_id):
    """Return (tag_ids list, error_str) — existing tag UUIDs on LS product."""
    url = f"{LS_BASE_V20}/products/{ls_id}"
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
    return product.get('tag_ids', []), None


def ls_put_tag_ids(ls_id, tag_ids):
    url = f"{LS_BASE_V21}/products/{ls_id}"
    payload = json.dumps({'common': {'tag_ids': list(tag_ids)}}).encode()
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
    load_tokens()

    print("Fetching products to tag from Supabase...")
    products = fetch_products_to_tag()
    print(f"Found {len(products)} products with LS IDs and tags/clearance-price")

    if OFFSET:
        products = products[OFFSET:]
        print(f"Resuming from offset {OFFSET} — {len(products)} remaining")
    if LIMIT:
        products = products[:LIMIT]
        print(f"Limiting to {LIMIT}")

    if DRY_RUN:
        print("\nDRY RUN — showing first 5:")
        for row in products[:5]:
            our_uuids = normalize_tags(row.get('tags'), row.get('retail_price'))
            print(f"  sku={row['sku']!r}")
            print(f"    tags_raw={row['tags']!r} price={row['retail_price']}")
            print(f"    → tag UUIDs: {sorted(our_uuids)}")
            print(f"    ls_id={row['ls_id']!r}")
        return

    ok, skipped, failed = 0, 0, []

    for i, row in enumerate(products):
        sku = row['sku']
        ls_id = row['ls_id']
        tags_text = row.get('tags', '')
        retail_price = row.get('retail_price')

        our_uuids = normalize_tags(tags_text, retail_price)
        if not our_uuids:
            skipped += 1
            continue

        # GET existing tag_ids (additive)
        existing, err = ls_get_tag_ids(ls_id)
        time.sleep(RATE_LIMIT_DELAY)
        if err:
            failed.append({'sku': sku, 'ls_id': ls_id, 'error': f'GET failed: {err}'})
            continue

        merged = set(existing) | our_uuids
        if merged == set(existing):
            # Nothing new to add
            skipped += 1
            continue

        ok_put, result = ls_put_tag_ids(ls_id, merged)
        time.sleep(RATE_LIMIT_DELAY)
        if ok_put:
            ok += 1
        else:
            failed.append({'sku': sku, 'ls_id': ls_id, 'tags': tags_text, 'error': f'PUT failed: {result}'})

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(products)} | updated={ok} failed={len(failed)} skipped={skipped}")

    print(f"\nDone. Updated: {ok} | Failed: {len(failed)} | Skipped (no new tags): {skipped}")

    if failed:
        Path(OUT_ERRORS).write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {OUT_ERRORS}")

    Path(OUT_LOG).write_text(json.dumps({
        'total': len(products) + OFFSET,
        'offset': OFFSET,
        'updated': ok,
        'failed': len(failed),
        'skipped_no_new_tags': skipped,
    }, indent=2))
    print(f"Log saved to {OUT_LOG}")


if __name__ == '__main__':
    main()
