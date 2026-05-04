"""
sku_regen.py — Regenerate old-format SKUs to current formula.

Old format: STYLE-BRAND_CODE-COLOR-SIZE  (no gender prefix)
New format: GENDER-SUPPLIER_CODE-STYLE-COLOR_CODE-SIZE_VALUE[-WIDTH]

Reads old-format records from /tmp/old_sku_records.json, applies current
formula, outputs a preview CSV, and optionally applies updates to Supabase.

Usage:
    python3 docs/sku_regen.py             # dry-run, show preview
    python3 docs/sku_regen.py --apply     # write updates to DB
"""

import json, os, sys, re, requests
from datetime import datetime, timezone

DOCS         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DOCS)
ENV_FILE     = os.path.join(PROJECT_ROOT, ".env.local")
INPUT_FILE   = "/tmp/old_sku_records.json"
PREVIEW_CSV  = os.path.join(DOCS, "sku_regen_preview.csv")

SUPABASE_API = "https://api.supabase.com/v1/projects/ayfwyvripnetwrkimxka/database/query"

APPLY = "--apply" in sys.argv

def load_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ACCESS_TOKEN = load_env().get("SUPABASE_ACCESS_TOKEN", "")

# ── Formula maps (mirrors sku-generator.js exactly) ──────────────────────────

SUPPLIER_MAP = {
    'JUSTIN': 'BHS', 'JUSTIN BOOTS': 'BHS', 'TONY LAMA': 'BHS',
    'NOCONA BOOTS': 'BHS', 'CHIPPEWA': 'BHS', 'DOUBLE H': 'BHS',
    'DOUBLE-H': 'BHS', 'H & H': 'BHS', 'H&H': 'BHS',
    'CAROLINA': 'BHS', 'PHANTOM RIDER': 'BHS',
    'ARIAT': 'ARI', 'HD XTREME WORK': 'ARI', 'HD XTREME': 'ARI',
    'WRANGLER': 'KON', 'LEE': 'KON',
    'ROCK & ROLL DENIM': 'WMA', 'ROCK AND ROLL DENIM': 'WMA',
    'ROCK & ROLL COWGIRL': 'WMA', 'PANHANDLE': 'WMA',
    'PANHANDLE SLIM': 'WMA', 'POWDER RIVER': 'WMA',
    'POWDER RIVER OUTFITTERS': 'WMA', 'HOOEY X ROCK & ROLL DENIM': 'WMA',
    'GEORGIA BOOT': 'RBR', 'DURANGO': 'RBR', 'ROCKY': 'RBR',
    'STETSON': 'RHE', 'RESISTOL': 'RHE', 'CHARLIE 1 HORSE': 'RHE',
    'BAILEY': 'RHE', 'TUFF HEDEMAN': 'RHE', 'TUFF HEDEMAN BY RESISTOL': 'RHE',
    'RODEO KING': 'RKI',
    'CINCH': 'MIN',
    'DAN POST': 'DPC', 'LAREDO': 'DPC', 'DINGO': 'DPC',
    'M&F': 'MFW', 'M&F WESTERN': 'MFW', 'M&F WESTERN PRODUCTS': 'MFW',
    'TWISTER': 'MFW', 'NOCONA BELT CO.': 'MFW', 'NOCONA BELT CO': 'MFW',
    'BLAZIN ROXX': 'MFW', 'CRUMRINE': 'MFW',
    'TWISTED X': 'TWX', 'BLACK STAR': 'TWX',
    'CORRAL': 'COR', 'CIRCLE G': 'COR',
    'ROPER': 'KAR', 'TIN HAUL': 'KAR',
    'SMOKY MOUNTAIN': 'SMB', 'SMOKY MOUNTAIN BOOTS': 'SMB', 'SMOKEY MOUNTAIN': 'SMB',
    'BULLHIDE': 'BHH', 'BULLHIDE HATS': 'BHH',
    'FENOGLIO': 'FBO', 'FENOGLIO BOOTS': 'FBO',
    'ELY CATTLEMAN': 'ECA', 'CRIPPLE CREEK': 'CCR',
    'HOOEY': 'HBR', 'COWGIRL TUFF': 'CTU',
    'WEAVER': 'WLE', 'WEAVER LEATHER': 'WLE',
    'TOUGH 1': 'JTI', 'TOUGH1': 'JTI', "JT INT'L": 'JTI',
    'SCULLY': 'SSI', 'OLD WEST': 'OWB',
    'OUTBACK TRADING': 'OTC', 'OUTBACK TRADING CO.': 'OTC',
    'JPC EQUESTRIAN': 'JPC', 'OVATION': 'JPC',
    'CRUEL': 'CRU', 'CRUEL DENIM': 'CRU', 'CRUEL GIRLS': 'CRU',
    'AURORA WORLD': 'AUR', 'PALM PALS': 'AUR',
    'LEANIN TREE': 'LT', 'LEANING TREE': 'LT',
    'ABILENE': 'ABC', 'ABILENE BOOT CO.': 'ABC',
    'MISS ME': 'MME', 'CACTUS ROPES': 'CR',
    'COWTOWN': 'COW', 'SADDLE BARN': 'SBI',
    'HERITAGE': 'HGL', 'HERITAGE PERFORMANCE': 'HGL',
    'REPUBLIC ROPES': 'RRO', 'TROXEL': 'TRO',
    'WESTERN FASHION': 'WFA', 'THE RODEO SHOP': 'TRS',
    'CONGRESS LEATHER': 'CGL', 'TUCKER': 'TKR',
    'ANDIS': 'AND', 'OSTER': 'OST', 'WAHL': 'WAH',
}

COLOR_MAP = {
    'BLACK': 'BLA', 'BROWN': 'BRO', 'WHITE': 'WHI', 'BLUE': 'BLU',
    'NAVY': 'NAV', 'RED': 'RED', 'GREEN': 'GRN', 'GRAY': 'GRA',
    'GREY': 'GRA', 'TAN': 'TAN', 'PINK': 'PNK', 'PURPLE': 'PUR',
    'ORANGE': 'ORG', 'YELLOW': 'YEL', 'TURQUOISE': 'TUR',
    'NATURAL': 'NAT', 'CHARCOAL': 'CHA', 'SILVER': 'SIL',
    'GOLD': 'GLD', 'CREAM': 'CRM', 'IVORY': 'IVR', 'CORAL': 'CRL',
    'OLIVE': 'OLV', 'RUST': 'RST', 'WINE': 'WIN', 'BURGUNDY': 'WIN',
    'SAND': 'SND', 'TEAL': 'TEA', 'BONE': 'BON', 'CHOCOLATE': 'CHO',
    'KHAKI': 'KHA', 'MINT': 'MNT', 'PEACH': 'PEA', 'PLUM': 'PLM',
    'SAGE': 'SAG', 'DENIM': 'DEN', 'CAMEL': 'CAM', 'MULTICOLOR': 'MUL',
    'DARK BROWN': 'DBR', 'LIGHT BROWN': 'LBR', 'MEDIUM BROWN': 'MBR',
    'DARK VINTAGE': 'DAR', 'MEDIUM VINTAGE': 'MED', 'DARK WASH': 'DAR',
    'MEDIUM WASH': 'MED', 'LIGHT WASH': 'LTW',
}

GENDER_MAP = {
    'WOMEN': 'W', 'WOMAN': 'W', 'LADIES': 'W', "WOMEN'S": 'W',
    'MEN': 'M', 'MENS': 'M', "MEN'S": 'M',
    'KIDS': 'K', 'YOUTH': 'K', 'INFANT': 'K', 'TODDLER': 'K',
    'BOYS': 'B', 'GIRLS': 'G',
    'ADULT': 'A', 'UNISEX': 'A',
}

def get_gender_code(tags):
    if not tags:
        return 'A'
    upper = tags.strip().upper()
    for word in re.split(r'[,\s]+', upper):
        word = word.strip()
        if word in GENDER_MAP:
            return GENDER_MAP[word]
    return 'A'

def get_supplier_code(brand):
    if not brand:
        return 'GEN'
    key = brand.strip().upper()
    if key in SUPPLIER_MAP:
        return SUPPLIER_MAP[key]
    for map_key, code in SUPPLIER_MAP.items():
        if key.startswith(map_key) or map_key.startswith(key):
            return code
    return 'GEN'

def get_color_code(color):
    if not color:
        return None
    upper = color.strip().upper()
    if upper in COLOR_MAP:
        return COLOR_MAP[upper]
    for map_key, code in COLOR_MAP.items():
        if upper.startswith(map_key):
            return code
    if '/' in color:
        parts = color.split('/')
        return ''.join(p.strip()[0] for p in parts if p.strip()).upper()[:3]
    return upper[:3]

def sanitize_style(style):
    if not style:
        return style
    cleaned = re.sub(r'[^a-zA-Z0-9_/()#\-|.]', '', str(style).strip().split()[0])
    return cleaned or None

def sanitize_part(v):
    if not v:
        return None
    return re.sub(r'[^a-zA-Z0-9_/()#\-|.]', '', str(v).replace(' ', '-')) or None

def parse_size(size_str, category):
    if not size_str:
        return None, None
    s = size_str.strip()
    cat = (category or '').lower()

    is_footwear = bool(re.search(r'boot|shoe|footwear|sandal|slipper|sneaker|moccasin|loafer', cat, re.I))
    is_jeans    = bool(re.search(r'jean|pant|trouser', cat, re.I))

    if is_footwear:
        m = re.match(r'^(\d+)\s+(\d)/(\d)\s*([A-Z]{1,4})?$', s, re.I)
        if m:
            decimal = int(m.group(1)) + int(m.group(2)) / int(m.group(3))
            return str(decimal), m.group(4) or 'NA'
        m = re.match(r'^(\d+\.?\d*)\s+([A-Z]{1,4})(?:\s|$)', s, re.I)
        if m:
            return m.group(1), m.group(2).upper()
        m = re.match(r'^(\d+\.?\d*)$', s)
        if m:
            return m.group(1), 'NA'

    if is_jeans:
        m = re.match(r'^(\d+)\s*[xX\-]\s*(\d+)$', s)
        if m:
            return m.group(1), m.group(2)
        m = re.match(r'^(\d+(?:/\d+)?)\s+(S|Short|R|Regular|L|Long|XL|XLong|XLONG)$', s, re.I)
        if m:
            len_map = {'SHORT': 'S', 'REGULAR': 'R', 'LONG': 'L', 'XLONG': 'XL'}
            lv = len_map.get(m.group(2).upper(), m.group(2).upper()[0])
            return m.group(1), lv

    return s, None

def generate_sku(style, brand, color, size, tags, category):
    style = sanitize_style(style) or ''
    brand = (brand or '').strip()
    if not style and not brand:
        return ''

    gender        = get_gender_code(tags)
    supplier_code = get_supplier_code(brand)

    if supplier_code == 'LT' and style:
        return 'LT-' + style.zfill(5)

    color_code          = get_color_code(color)
    size_value, width_v = parse_size(size, category)

    parts = [gender, supplier_code]
    if style:      parts.append(style)
    if color_code: parts.append(color_code)
    if size_value: parts.append(sanitize_part(size_value))
    if width_v:    parts.append(sanitize_part(width_v))

    return '-'.join(p for p in parts if p)

# ── Main ─────────────────────────────────────────────────────────────────────

def sql(query):
    r = requests.post(
        SUPABASE_API,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"query": query},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        print(f"SQL error {r.status_code}: {r.text[:300]}")
        return None
    return r.json()

with open(INPUT_FILE) as f:
    records = json.load(f)

print(f"Processing {len(records)} records...")

updates   = []   # (id, old_sku, new_sku)
no_change = 0
no_result = 0

style_backfills = []  # (id, extracted_style) — for records where style_number was null

for r in records:
    style = r.get('style_number')

    # When style_number is null, extract from old SKU: first dash-component
    # e.g. "09MWFQG" → "09MWFQG", "SGK54L-JU-BLK-6.5B" → "SGK54L"
    if not style and r.get('sku'):
        style = sanitize_style(r['sku'].split('-')[0])
        if style:
            style_backfills.append((r['id'], style))

    new_sku = generate_sku(
        style,
        r.get('brand_name'),
        r.get('color'),
        r.get('size_or_dimensions'),
        r.get('tags'),
        r.get('product_category'),
    )
    if not new_sku:
        no_result += 1
        continue
    if new_sku == r['sku']:
        no_change += 1
        continue
    updates.append((r['id'], r['sku'], new_sku))

print(f"  Would update SKU:          {len(updates)}")
print(f"  Would backfill style_number: {len(style_backfills)}")
print(f"  No change:                 {no_change}")
print(f"  No result (skip):          {no_result}")

# Write preview CSV
with open(PREVIEW_CSV, 'w') as f:
    f.write("id,old_sku,new_sku\n")
    for rec_id, old, new in updates:
        f.write(f'{rec_id},"{old}","{new}"\n')
print(f"\nPreview written to {PREVIEW_CSV}")

# Sample preview
print("\nSample changes (first 15):")
print(f"{'ID':<8} {'OLD SKU':<35} {'NEW SKU'}")
print("-" * 85)
for rec_id, old, new in updates[:15]:
    print(f"{rec_id:<8} {old:<35} {new}")

if not APPLY:
    print(f"\nDRY RUN — run with --apply to write {len(updates)} SKU updates + {len(style_backfills)} style_number backfills.")
    sys.exit(0)

BATCH = 50

# ── Apply style_number backfills first ────────────────────────────────────────
if style_backfills:
    print(f"\nBackfilling style_number for {len(style_backfills)} records...")
    for i in range(0, len(style_backfills), BATCH):
        batch = style_backfills[i:i + BATCH]
        cases = '\n'.join(f"WHEN id = {rid} THEN '{s.replace(chr(39), chr(39)*2)}'" for rid, s in batch)
        ids   = ','.join(str(rid) for rid, _ in batch)
        q = f"UPDATE products SET style_number = CASE {cases} END, updated_at = NOW() WHERE id IN ({ids})"
        sql(q)

# ── Apply SKU updates in batches ──────────────────────────────────────────────
print(f"\nApplying {len(updates)} SKU updates...")
BATCH = 50
updated = 0
errors  = 0

for i in range(0, len(updates), BATCH):
    batch = updates[i:i + BATCH]
    cases = '\n'.join(f"WHEN id = {rec_id} THEN '{new_sku.replace(chr(39), chr(39)*2)}'" for rec_id, _, new_sku in batch)
    ids   = ','.join(str(rec_id) for rec_id, _, _ in batch)
    q = f"UPDATE products SET sku = CASE {cases} END, updated_at = NOW() WHERE id IN ({ids})"
    result = sql(q)
    if result is None:
        errors += len(batch)
    else:
        updated += len(batch)
    if (i // BATCH + 1) % 5 == 0:
        print(f"  {updated} updated so far...")

print(f"\nDone. Updated: {updated} | Errors: {errors}")
