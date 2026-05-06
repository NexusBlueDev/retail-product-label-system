#!/usr/bin/env python3
"""Build a side-by-side dedupe CSV for Corrinne.

For each of the 532 barcode conflicts, shows:
  - the product WE tried to update (from write_barcodes_ls_errors.json)
  - the product that ALREADY has that barcode in LS (looked up via lightspeed_index)

Output: docs/ls_dedupe_for_review.csv
Corrinne fills in 'keep_which': "ours", "conflict", or "neither"
"""

import csv
import json
import urllib.request
import urllib.parse
from pathlib import Path

# Load token + access token
LS_TOKEN = None
ACCESS_TOKEN = None
for line in Path('.env.local').read_text().splitlines():
    if line.startswith('LIGHTSPEED_TOKEN='):
        LS_TOKEN = line.split('=', 1)[1].strip()
    elif line.startswith('SUPABASE_ACCESS_TOKEN='):
        ACCESS_TOKEN = line.split('=', 1)[1].strip()

SUPABASE_PROJECT = 'ayfwyvripnetwrkimxka'
SUPABASE_SQL_URL = f'https://api.supabase.com/v1/projects/{SUPABASE_PROJECT}/database/query'


def supabase_query(sql):
    payload = json.dumps({'query': sql}).encode()
    req = urllib.request.Request(SUPABASE_SQL_URL, data=payload, headers={
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def extract_category_name(cat_raw):
    if not cat_raw:
        return ''
    if isinstance(cat_raw, dict):
        return cat_raw.get('name', '')
    try:
        return json.loads(cat_raw).get('name', '')
    except Exception:
        return str(cat_raw)[:80]


# Load errors
with open('docs/write_barcodes_ls_errors.json') as f:
    errors = json.load(f)
print(f"Errors loaded: {len(errors)}")

# Parse conflict IDs from error bodies
conflict_ids = set()
parsed_errors = []
for err in errors:
    our_id = err['product_id']
    barcode = err['barcode']
    our_name = err['name']
    try:
        body = err['error']['body']
        parsed_body = json.loads(body) if isinstance(body, str) else body
        fields = parsed_body.get('fields', {})
        conflict_id = fields.get('existing_code_UPC_id', '')
    except Exception:
        conflict_id = ''
    if conflict_id:
        conflict_ids.add(conflict_id)
    parsed_errors.append({
        'our_id': our_id,
        'barcode': barcode,
        'our_name': our_name,
        'conflict_id': conflict_id,
    })

print(f"Unique conflict product IDs: {len(conflict_ids)}")

# Batch lookup conflict products in lightspeed_index
# Also look up "our" products to get their SKU/category
our_ids = {e['our_id'] for e in parsed_errors}
all_ids = conflict_ids | our_ids
print(f"Total IDs to look up in lightspeed_index: {len(all_ids)}")

# Split into batches of 500 (SQL IN clause limit)
id_list = list(all_ids)
index_map = {}
for i in range(0, len(id_list), 100):
    batch = id_list[i:i+500]
    id_str = ', '.join(f"'{x}'" for x in batch)
    sql = f"SELECT lightspeed_id, name, sku, category FROM lightspeed_index WHERE lightspeed_id IN ({id_str})"
    rows = supabase_query(sql)
    for r in rows:
        index_map[r['lightspeed_id']] = r
    print(f"  Batch {i//500 + 1}: fetched {len(rows)} rows (running total: {len(index_map)})")

print(f"Index map populated: {len(index_map)} products")

# Build output rows
out_rows = []
for e in parsed_errors:
    our = index_map.get(e['our_id'], {})
    conflict = index_map.get(e['conflict_id'], {}) if e['conflict_id'] else {}

    out_rows.append({
        'barcode': e['barcode'],
        'our_product_id': e['our_id'],
        'our_product_name': e['our_name'],
        'our_sku': our.get('sku', ''),
        'our_category': extract_category_name(our.get('category', '')),
        'conflict_product_id': e['conflict_id'],
        'conflict_product_name': conflict.get('name', ''),
        'conflict_sku': conflict.get('sku', ''),
        'conflict_category': extract_category_name(conflict.get('category', '')),
        'keep_which': '',
        'notes': '',
    })

out = Path('docs/ls_dedupe_for_review.csv')
fieldnames = [
    'barcode',
    'our_product_id', 'our_product_name', 'our_sku', 'our_category',
    'conflict_product_id', 'conflict_product_name', 'conflict_sku', 'conflict_category',
    'keep_which', 'notes',
]

with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(out_rows)

# Summary stats
both_named = sum(1 for r in out_rows if r['our_product_name'] and r['conflict_product_name'])
conflict_missing = sum(1 for r in out_rows if not r['conflict_product_name'])

print(f"\nDone. {len(out_rows)} rows → {out}")
print(f"  Both sides named:            {both_named}")
print(f"  Conflict name missing:       {conflict_missing} (newer products not in our index)")
print(f"\nCorrinne fills in 'keep_which': 'ours', 'conflict', or 'neither'")
