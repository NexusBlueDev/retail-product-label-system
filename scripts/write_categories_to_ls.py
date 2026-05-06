#!/usr/bin/env python3
"""Phase C: Write approved categories to Lightspeed.

Reads fix_categories_lightspeed-reviewed.csv:
- "no" rows: use the "Use instead" column value (mapped to product_type_id)
- "ok" rows: use our_category (mapped to product_type_id)
- blank: skipped

PUTs product_type_id to LS v2.1 API via common key.

Usage: python3 scripts/write_categories_to_ls.py [--dry-run]
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

# Complete category name → LS product_type_id map
CATEGORY_MAP = {
    'Accessories - Bags & Gear': '0d253e6b-0d08-479f-8789-74e2d8b7cab4',
    'Accessories - Belts': 'fee1cc9c-d4f7-4eae-8b53-23a70e64d5e1',
    'Accessories - Buckles': 'e38184d8-e605-4286-a6b7-3f605a06c88b',
    'Accessories - Fragrance': '963d9f41-dce1-4bf2-b6f5-3491d4121e08',
    'Accessories - Gloves': '8069b302-8b07-42e9-867d-18bfd0c55b74',
    'Accessories - Jewelry': '59047891-c8ab-494d-b2cb-8094e07561f6',
    'Accessories - Knives & Small Tools': '7f9c0242-5608-4f55-8517-be29cf5f6cb5',
    'Accessories - Scarves/Bandanas/Neckwear': 'be1627ae-364b-46f0-a263-8e958f415ba9',
    'Accessories - Wallets & Purses': '7ad733fd-0be9-4e98-b40d-1fca10cf87ff',
    'Apparel - Apparel Accessories': 'af0dfaa1-d4dc-4628-adea-2bb522dedc3c',
    'Apparel - Dresses': '213699af-8774-47db-916c-729cd57a4354',
    'Apparel - Hoodies & Sweatshirts': '5f4808fe-8422-4ad0-9417-bf0ecd9d4660',
    'Apparel - Infant/Toddler': 'f78abefd-3276-44be-8ad8-c67f40a147b4',  # LS: "Infant and Toddler"
    'Apparel - Jeans': '39d2c133-a413-49b1-93a2-afca9b7dcd73',
    'Apparel - Knit Shirts & Polos': 'f7701c67-686d-493d-aab6-1602a3589300',
    'Apparel - Mid-Layer': '9d0d782d-90a5-46d0-8168-a0289c1bcbde',
    'Apparel - Outerwear': 'e63df03e-cc7c-466d-83fa-cdb7a2720ac9',
    'Apparel - Pants': '28342184-c60e-41c6-aedf-6480511d84ae',
    'Apparel - Shorts': '519a34ef-fa8d-40c0-b659-091b8f1f1e75',
    'Apparel - Skirts/Skorts': '65b2d1e9-dbc2-4698-9afe-de26153e8702',
    'Apparel - Socks': '74855d35-d100-4f07-b5df-d8aa13e2ac39',
    'Apparel - Suits & Sport Coats': 'c21abd22-f47a-452d-acf1-dab28b701e61',
    'Apparel - Sweaters': '6f6fff05-134b-4758-bcea-9ad5490e2935',
    'Apparel - T-Shirts & Tanks': 'ffa5c15b-fac6-4d99-9bf6-fc2c5c956ceb',
    'Apparel - Tops/Blouses': '7f10c011-8bcb-4765-bbc4-5baefe5c95f1',
    'Apparel - Undergarments': '1be6f864-a59e-4c61-992b-bc3582fd6a6b',
    'Apparel - Western Shirt': '1c719408-7e86-472e-a6fe-e614f79e9a82',   # nearest: Western Woven Shirts
    'Apparel - Western Woven Shirts': '1c719408-7e86-472e-a6fe-e614f79e9a82',
    'Footwear - Boots': '6152c899-f9e2-4263-9208-203fb5db1c4d',
    'Footwear - Footwear Accessories & Care': '03467e59-8dd8-434e-9c8d-3f88b57ca37a',
    'Footwear - Other Boots': '0f4917a0-9798-42ff-9de5-7e7f469cc651',
    'Footwear - Shoes': '59c4312f-0edf-4664-823e-07f1cd78563f',
    'Footwear - Slippers': '73f21abf-4d0c-4e8b-8720-fe4e77ef4409',
    'Footwear - Western Boots': 'd4fcc16b-0b26-4e7e-af7b-99a0960ba8db',
    'Footwear - Work Boots': '7b09d6e3-052b-4984-8b2b-1b58500be968',
    'Gifts & Novelties - Books/Magazines/Cards': '4652d318-6650-433d-9af3-dc689d2d541a',
    'Gifts & Novelties - Books/Magazines/Papers/Cards': '4652d318-6650-433d-9af3-dc689d2d541a',  # Corrinne's name
    'Gifts & Novelties - Gift Items/Small Goods': 'f9576af8-88ba-4adf-a3f7-7af03ffe5125',  # LS: ...HomeDecor
    'Gifts & Novelties - Toys': '3249fbb4-2805-45fd-b970-9d8082cd927b',
    'Gifts & Novelties-Gift Items/Small Goods/HomeDecor': 'f9576af8-88ba-4adf-a3f7-7af03ffe5125',
    'Hats': '19e2d810-1c26-4bc8-835e-730ef761e6ed',
    'Hats - Caps/Beanies/Novelty': '12b58218-8990-443a-a117-b2dc5af33912',
    'Hats - Felt Cowboy Hats': 'd99a9f0e-0606-4af6-bfca-4fdbec80ac3e',
    'Hats - Hat Accessories & Care': 'c8849fdf-7d3a-4741-87e8-03feaad9aae8',
    'Hats - Leather': '2452247b-016c-43f2-82bf-83ff7647a4cc',
    'Hats - Straw Cowboy Hats': 'a4ce7686-0249-4f73-a15a-a79e4b1d2ebf',
    'Horse - Unknown': '2addb1c8-906b-492b-a9e6-77335f9827db',  # nearest: Horse/Rodeo - Unknown
    'Horse/Rodeo - Feed, Water & Stable Supplies': '301a0c3e-e6db-4836-b055-d86565c332d5',
    'Horse/Rodeo - Rider gear': 'b7b05d40-b4ed-455b-975d-a8f8ec159914',
    'Horse/Rodeo - Unknown': '2addb1c8-906b-492b-a9e6-77335f9827db',
    'Horse/Rodeo-Blanket,Sheet,Protect-Leg Protect&Ship': 'b7824302-3d8d-444c-9157-95737d510b99',
    'Horse/Rodeo-Blankets, Sheets, Protection&Covers': '8998531f-14fd-4459-9a9e-7402bcc4bb54',
    'Horse/Rodeo-Health, Care, Groom-Hoof & Ferrier': '73812e11-48b2-4f76-bbee-d21b7cbc0220',
    'Horse/Rodeo-Health, Care, Grooming-Groom Tools': 'b8bcea50-2154-45d1-99f5-a241fcaa5598',
    'Horse/Rodeo-Health, Care, Grooming-Health&Vet': '4d6cdb91-ddb6-4e54-b55a-b2b6518e04ed',
    'Horse/Rodeo-Leather Care&Tools-Leather Care': '14a33f24-af35-45a5-89c8-d75795581225',
    'Horse/Rodeo-Rodeo&Livestock Equip-Bull&Stock Gear': '21f58ce3-8f0a-40ee-ac68-262c7680a710',
    'Horse/Rodeo-Rodeo&Livestock Equip-Roping Gear': 'bdd851ee-530e-4b03-9b10-cb2360854829',
    'Horse/Rodeo-Rodeo&Livestock Equip-Train&Handle': 'b7b26829-3913-4351-8418-27d686a17e90',
    'Horse/Rodeo-Tack&RidingEquip-Headstalls,Bits,Ctrl': 'a4a45950-5fc9-4286-a602-2e62759a9d3a',
    'Horse/Rodeo-Tack&RidingEquip-Saddles&Accessories': 'e79848d1-b467-4cfc-8013-0ddf26b63ecb',
}


def load_token():
    env = Path('.env.local').read_text()
    for line in env.splitlines():
        if line.startswith('LIGHTSPEED_TOKEN='):
            return line.split('=', 1)[1].strip()
    raise ValueError("LIGHTSPEED_TOKEN not found in .env.local")


def put_category(product_id, product_type_id):
    url = f"{BASE_URL}/products/{product_id}"
    payload = json.dumps({"common": {"product_category_id": product_type_id}}).encode()
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

    with open('docs/fix_categories_lightspeed-reviewed.csv', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    actionable = []
    no_type_id = []
    skipped_blank = 0

    for r in rows:
        reviewed = r.get('Reviewed', '').strip().lower()
        if reviewed == 'no':
            cat_name = r.get('Use instead', '').strip()
        elif reviewed == 'ok':
            cat_name = r.get('our_category', '').strip()
        else:
            skipped_blank += 1
            continue

        type_id = CATEGORY_MAP.get(cat_name)
        product_id = r.get('ls_product_id', '').strip()

        if not product_id:
            skipped_blank += 1
            continue

        if not type_id:
            no_type_id.append({'product_id': product_id, 'cat_name': cat_name, 'ls_name': r.get('ls_name', '')})
            continue

        actionable.append({'product_id': product_id, 'type_id': type_id, 'cat_name': cat_name, 'ls_name': r.get('ls_name', '')})

    print(f"Total rows: {len(rows)}")
    print(f"Actionable (have type_id): {len(actionable)}")
    print(f"No type_id found (skipped): {len(no_type_id)}")
    print(f"Blank/skipped: {skipped_blank}")

    if no_type_id:
        print("\nUnresolved categories:")
        for r in no_type_id[:10]:
            print(f"  {r['cat_name']!r} | {r['ls_name']!r}")

    if DRY_RUN:
        print("\nDRY RUN — no writes")
        for r in actionable[:5]:
            print(f"  Would PUT {r['product_id']} type_id={r['type_id']} cat={r['cat_name']!r}")
        return

    ok, failed = 0, []
    for i, row in enumerate(actionable):
        success, resp = put_category(row['product_id'], row['type_id'])
        if success:
            ok += 1
        else:
            failed.append({**row, 'error': resp})

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(actionable)} | ok={ok} failed={len(failed)}")

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. Updated: {ok} | Failed: {len(failed)} | Skipped: {skipped_blank} | No type_id: {len(no_type_id)}")

    if failed:
        out = Path('docs/write_categories_ls_errors.json')
        out.write_text(json.dumps(failed, indent=2))
        print(f"Errors saved to {out}")

    log = Path('docs/write_categories_ls.log')
    log.write_text(json.dumps({
        'total_rows': len(rows),
        'actionable': len(actionable),
        'ok': ok,
        'failed': len(failed),
        'no_type_id': len(no_type_id),
        'skipped_blank': skipped_blank,
    }, indent=2))
    print(f"Log saved to {log}")


if __name__ == '__main__':
    main()
