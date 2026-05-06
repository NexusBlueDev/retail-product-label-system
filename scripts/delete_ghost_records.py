#!/usr/bin/env python3
"""Delete ghost records from products table and their Supabase Storage images.

Ghost records: status='enhanced_complete' AND name='NA' (scan artifacts, no real data).
Deletes Storage objects first, then DB rows.

Usage: python3 scripts/delete_ghost_records.py [--dry-run]
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DRY_RUN = '--dry-run' in sys.argv

# Load credentials
ACCESS_TOKEN = None
SUPABASE_KEY = None
SUPABASE_URL = None
for line in Path('.env.local').read_text().splitlines():
    if line.startswith('SUPABASE_ACCESS_TOKEN='):
        ACCESS_TOKEN = line.split('=', 1)[1].strip()

SUPABASE_URL = 'https://ayfwyvripnetwrkimxka.supabase.co'
SUPABASE_KEY = 'sb_publishable_54gmrrTrRQFdHNshMr8aMw_CeH9r02k'

SUPABASE_PROJECT = 'ayfwyvripnetwrkimxka'
SQL_URL = f'https://api.supabase.com/v1/projects/{SUPABASE_PROJECT}/database/query'
STORAGE_URL = f'{SUPABASE_URL}/storage/v1/object/product-images'


def sql(query):
    payload = json.dumps({'query': query}).encode()
    req = urllib.request.Request(SQL_URL, data=payload, headers={
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def delete_storage_batch(paths):
    """Delete a batch of storage objects via Supabase Storage bulk delete."""
    payload = json.dumps({'prefixes': paths}).encode()
    req = urllib.request.Request(
        f'{SUPABASE_URL}/storage/v1/object/product-images',
        data=payload,
        method='DELETE',
        headers={
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return False, {'status': e.code, 'body': e.read().decode()[:300]}


# --- Fetch ghost records ---
print("Fetching ghost records...")
rows = sql("SELECT id, image_urls FROM products WHERE status = 'enhanced_complete' AND (name = 'NA' OR name IS NULL OR name = '') ORDER BY id")
print(f"Found: {len(rows)} ghost records")

if not rows:
    print("Nothing to delete.")
    sys.exit(0)

# --- Collect image paths ---
all_image_paths = []
for r in rows:
    urls = r.get('image_urls') or []
    if isinstance(urls, str):
        urls = json.loads(urls)
    for img in urls:
        path = img.get('path', '')
        if path:
            all_image_paths.append(path)

print(f"Storage objects to delete: {len(all_image_paths)}")

if DRY_RUN:
    print("\nDRY RUN — no writes")
    print(f"  Would delete {len(rows)} DB rows")
    print(f"  Would delete {len(all_image_paths)} Storage objects")
    print("  Sample IDs:", [r['id'] for r in rows[:5]])
    sys.exit(0)

# --- Delete Storage objects in batches of 100 ---
storage_ok = 0
storage_failed = []
batch_size = 100
for i in range(0, len(all_image_paths), batch_size):
    batch = all_image_paths[i:i + batch_size]
    ok, resp = delete_storage_batch(batch)
    if ok:
        storage_ok += len(batch)
    else:
        storage_failed.extend(batch)
        print(f"  Storage batch failed: {resp}")
    if (i // batch_size + 1) % 5 == 0:
        print(f"  Storage progress: {min(i + batch_size, len(all_image_paths))}/{len(all_image_paths)}")
    time.sleep(0.1)

print(f"Storage deleted: {storage_ok} | failed: {len(storage_failed)}")

# --- Delete DB rows ---
ids = [str(r['id']) for r in rows]
# Delete in batches to avoid query size limits
db_deleted = 0
batch_size = 500
for i in range(0, len(ids), batch_size):
    batch = ids[i:i + batch_size]
    id_list = ', '.join(batch)
    result = sql(f"DELETE FROM products WHERE id IN ({id_list}) RETURNING id")
    db_deleted += len(result)

print(f"DB rows deleted: {db_deleted}")

# --- Summary ---
print(f"\n=== Phase 1A Complete ===")
print(f"Ghost records deleted: {db_deleted}")
print(f"Storage objects deleted: {storage_ok}")
if storage_failed:
    print(f"Storage failures (paths): {storage_failed[:5]}")

# Save log
log = {
    'ghost_records_deleted': db_deleted,
    'storage_objects_deleted': storage_ok,
    'storage_failures': len(storage_failed),
}
Path('docs/delete_ghost_records.log').write_text(json.dumps(log, indent=2))
print("Log saved to docs/delete_ghost_records.log")
