# Data Normalization & Lightspeed Import — Complete Playbook
**Created:** 2026-04-13 | **Last Updated:** 2026-04-13
**Project:** Retail Product Label System — The Rodeo Shop
**Purpose:** Normalize scanned product data and import into Lightspeed X-Series POS

---

## Overview

Staff scan product labels with the mobile app. GPT-4o extracts structured data into the `products` table (Supabase). This playbook normalizes that raw data and pushes it to Lightspeed POS.

**Pipeline:** Scanner App → Supabase `products` → `normalized_products` table → CSV review → Lightspeed POS

---

## Phase 1: Create & Populate the Normalized Table

### 1a. Create the table (one-time, already done)

```sql
CREATE TABLE normalized_products (
    id bigserial PRIMARY KEY,
    product_id bigint NOT NULL REFERENCES products(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    item_name text NOT NULL,
    style_number text,
    modified_style text,
    sku text,
    barcode text,
    barcode_digits integer,
    supplier_code text,
    supplier text,
    brand text,
    category text,
    retail_price numeric,
    supply_price numeric,
    size text,            -- Literal "Size" when value exists
    size_value text,
    width_length text,    -- "Width" or "Length"
    width_length_value text,
    color text,           -- Literal "Color" when value exists
    color_value text,     -- Full color name
    color_code text,      -- 2-4 char abbreviation
    quantity integer DEFAULT 1,
    tags text,
    gender text,
    close_out text,
    description text,
    notes text,
    verified boolean DEFAULT false,
    entered_by text,
    status text DEFAULT 'pending',
    image_count integer DEFAULT 0,
    normalization_status text DEFAULT 'pending',
    lightspeed_product_id text,
    normalized_at timestamptz,
    UNIQUE(product_id)
);
```

### 1b. Populate from scanner data

```sql
INSERT INTO normalized_products (product_id, created_at, updated_at, item_name, style_number, 
    barcode, barcode_digits, brand, category, retail_price, supply_price, color_value, 
    quantity, tags, description, notes, verified, entered_by, image_count, normalization_status)
SELECT id, created_at, updated_at, name, style_number, barcode,
    CASE WHEN barcode IS NOT NULL AND barcode != '' THEN length(barcode) ELSE 0 END,
    brand_name, product_category, retail_price, supply_price, color,
    quantity, tags, description, notes, verified, entered_by,
    COALESCE(jsonb_array_length(image_urls), 0), 'pending'
FROM products WHERE status = 'complete' ORDER BY id;
```

**Also pull raw size from products table:**
```sql
UPDATE normalized_products np
SET size_value = p.size_or_dimensions
FROM products p
WHERE np.product_id = p.id AND p.size_or_dimensions IS NOT NULL AND p.size_or_dimensions != '';
```

---

## Phase 2: Lightspeed Catalog Fetch (Cache Locally)

**Purpose:** Match our products against what's already in Lightspeed. Determine update vs create.

**Important:** Our scanner data updates Lightspeed. NEVER pull Lightspeed data back into ours. Lightspeed is the destination, not a source for pricing.

### Fetch the full catalog

```python
# Paginate through all products (10K per page, ~8 requests for 70K products)
# API: GET https://therodeoshop.retail.lightspeed.app/api/2.0/products?page_size=10000&after={version}
# Auth: Bearer {lightspeed_personal_token}
# Rate limit: ~350 req/5 min
```

### Build local indexes

Cache to JSON files in `docs/`:
- `ls_fresh_barcode_idx.json` — barcode → lightspeed_product_id
- `ls_fresh_sku_idx.json` — sku → lightspeed_product_id
- `ls_fresh_name_idx.json` — name (uppercase) → lightspeed_product_id

**CRITICAL:** Always refresh this cache immediately before import. Stale IDs cause mass failures.

---

## Phase 3: Price Research

### Priority order for retail price:
1. **Our scanned price** (from the physical label) — best source
2. **Highest price among same style_number** in our data
3. **Internet lookup** — brand website for supplier price × 2, rounded down to .95
4. **Flag for manual review** if truly unfindable

### Fill missing prices from siblings first (zero API calls):
```sql
UPDATE normalized_products np
SET retail_price = sub.max_price
FROM (
    SELECT style_number, MAX(retail_price) as max_price
    FROM normalized_products
    WHERE retail_price IS NOT NULL AND style_number IS NOT NULL
    GROUP BY style_number
) sub
WHERE np.style_number = sub.style_number AND np.retail_price IS NULL;
```

### Clearance rule:
```sql
-- Price ending in .00 or .97 → add Clearance to tags
UPDATE normalized_products 
SET tags = CASE 
    WHEN tags IS NULL OR tags = '' THEN 'Clearance'
    WHEN tags NOT ILIKE '%clearance%' THEN tags || ', Clearance'
    ELSE tags
END
WHERE retail_price IS NOT NULL
AND (retail_price::text LIKE '%.00' OR retail_price::text LIKE '%.97');
```

---

## Phase 4: Apply Normalization Rules

### Rule 1: Tags & Gender Standardization

**All tag variants must be standardized:**
- Women, Woman, Ladies, Women's, W, Gals → `Women`
- Men, Mens → `Men`
- Kids, Kid's, Youth, Baby, Infant, Infants → `Kids`
- Kids + Girls → `Kids, Girls`
- Kids + Boys → `Kids, Boys`
- Adult, Adults, Unisex → `Adult`
- `, Clearance` kept as secondary tag
- `, F` stripped (internal flag, not a tag)

**Gender codes:** M, W, K, B, G, A

**Inference from item names when tags are empty:**
- `LD ` prefix = Ladies = W
- `Women's`, `Ladies`, `Cowgirl` in name = W
- `Men's`, `Mens` in name = M
- `Kid`, `Child`, `Youth`, `Toddler`, `Jr.` = K
- `Boy` = B, `Girl` = G
- Accessories, horse care, grooming = A

### Rule 2: Supplier Codes (Must Match Lightspeed Vendor List)

**Official vendor code mapping (from Lightspeed):**

| Vendor | Code | Brands |
|--------|------|--------|
| BHSH (BH Shoe Holdings) | BHS | Justin, Tony Lama, Nocona Boots, Chippewa, Double-H, Carolina, Phantom Rider |
| Ariat International | ARI | Ariat, HD Xtreme Work |
| Kontoor Brands | KON | Wrangler, Lee |
| Westmoor Manufacturing | WMA | Rock & Roll Denim, Panhandle Slim, Powder River, Hooey x Rock & Roll |
| Rocky Brands US | RBR | Georgia Boot, Durango |
| HATCO (RHE Hatco) | RHE | Stetson, Resistol, Charlie 1 Horse, Bailey, Tuff Hedeman, Master Hatters of TX |
| Miller Brands LLC | MIN | Cinch |
| Dan Post Boot Company | DPC | Dan Post, Laredo, Dingo |
| M&F Western Products | MFW | M&F, Twister, Nocona Belt Co., Blazin Roxx, Crumrine, 3-D BeltCo, Milano Hat |
| Twisted X Inc | TWX | Twisted X, Black Star |
| Corral Boots Company | COR | Corral, Circle G |
| Karman Inc | KAR | Roper, Tin Haul |
| Smokey Mountain Boots | SMB | Smoky Mountain |
| Bullhide Hats | BHH | Bullhide, Montecarlo |
| Fenoglio Boots | FBO | Fenoglio |
| Ely Cattleman | ECA | Ely Cattleman, Cumberland Outfitters |
| Hooey Brands LLC | HBR | Hooey |
| Cowgirl Tuff | CTU | Cowgirl Tuff |
| Weaver Leather | WLE | Weaver |
| JT International | JTI | Tough 1, JT Int'l |
| Scully Sportswear | SSI | Scully |
| Old West Boots | OWB | Old West |
| Outback Trading Co | OTC | Outback Trading |
| JPC Equestrian | JPC | JPC, Ovation, EquiStar, Devon-Aire, Star Rider |
| Jacks Manufacturing | JMA | Jacks, Valhoma, Mustang Manufacturing |
| Cruel Denim | CRU | Cruel, Cruel Girls, Cruel Denim |
| Aurora World | AUR | Palm Pals, Aurora World |
| Leanin Tree | LT | Leanin Tree |
| Heritage Gloves | HGL | Heritage Performance Riding Gloves |
| Saddle Barn Inc | SBI | Saddle Barn, World Champion |
| Republic Ropes | RRO | Republic Ropes, Rattler Rope |
| Cactus Ropes | CR | Cactus Ropes |
| Cowtown Boots | COW | Cowtown |
| Abilene | ABC | Abilene |
| Cripple Creek/Sidran | CCR | Cripple Creek |
| Rodeo King | RKI | Rodeo King |
| Troxel | TRO | Troxel |
| Western Fashion | WFA | Western Fashion |
| Miss Me | MME | Miss Me |

**New vendor codes (need to be added to Lightspeed):**

| Code | Vendor | Products |
|------|--------|----------|
| TRS | The Rodeo Shop | Custom shop merch |
| CGL | Congress Leather | Chaps, leather goods |
| TKR | Tucker Saddlery | Equestrian |
| AND | Andis Company | Clipper blades |
| OST | Oster Professional | Clipper assemblies |
| WAH | Wahl Clipper Corp | Grooming tools |
| FAR | Farnam Companies | Absorbine, Pyranha |
| FIE | Fiebing's Company | Leather care, Bickmore |
| WFY | W.F. Young Inc | Cowboy Magic, Shapley's |
| GEN | Generic Supplier | Catch-all for unknowns |

### Rule 3: Size Parsing

**The raw `size_or_dimensions` field must be split into:**
- `size` — literal "Size" when a value exists
- `size_value` — the numeric/text size
- `width_length` — "Width" or "Length"
- `width_length_value` — D, EE, B, M, 30, 32, S, R, L, etc.

**Footwear (Width context):**
- `10 D` → size_value=10, width=D
- `10.5 EE` → size_value=10.5, width=EE
- `5 1/2 B` → size_value=5.5, width=B (convert fractions)
- `6` alone → size_value=6, width=NA
- Width codes: D, EE, EEE, B, M, C, W, 2E, NA

**Jeans/Pants (Length context):**
- `32 x 30` or `32-30` → size_value=32, length=30
- `29 S` / `29 Short` → size_value=29, length=S
- `28 R` / `28 Regular` → size_value=28, length=R
- `27 L` / `27 Long` → size_value=27, length=L
- `31/11 XLong` → size_value=31/11, length=XL
- `6X REGULAR` → size_value=6X, length=R

**Apparel (no width/length):**
- S, M, L, XL, XXL, XXXL, XS, 2XL, 3XL, OSFA, OSFM — pass through
- `XX-Large` → XXL, `X-Large` → XL

**Hats:** Pass through decimal sizes (6.75, 7.125, etc.)

**CRITICAL — Variant consistency:** All products sharing a style_number MUST have the same variant option structure. If ANY sibling has width/color, ALL siblings must (use NA for missing).

### Rule 4: Color Codes

- `color` field = literal "Color" when value exists
- `color_value` = full color name (cleaned: no parentheses, no numeric prefixes, no trailing spaces)
- `color_code` = 2-4 char abbreviation

**Common mappings:** BLA=Black, BRO=Brown, WHI=White, BLU=Blue, NAV=Navy, RED=Red, GRN=Green, GRA=Gray, TAN=Tan, PNK=Pink, PUR=Purple, TUR=Turquoise, NAT=Natural, CHA=Charcoal, SIL=Silver, GLD=Gold, CRM=Cream, OLV=Olive, MUL=Multicolor, CMO=Camo, DBR=Dark Brown, LBR=Light Brown, MBR=Medium Brown

**Color cleanup rules:**
- Strip parentheses: `(Natural)` → `Natural`
- Strip numeric prefixes: `07 Black` → `Black`
- Expand abbreviations: MC→Multicolor, BU→Blue, BR→Brown, BC→Black, PU→Purple
- Slash colors: first letter of each part (Black/Pink → BPI)

### Rule 5: SKU Formula (Corrinne's formula)

```
SKU = Gender + "-" + SupplierCode + "-" + StyleNumber + "-" + ColorCode + "-" + SizeValue [+ "-" + WidthLengthValue]
```

**Examples:**
- `M-BHS-DH4655-TT-14-EE` — Men's, BHSH, style DH4655, color Tan, size 14, width EE
- `W-COR-A4333-BW-5-M` — Women's, Corral, style A4333, Black/White, size 5, width M
- `LT-00736` — Leanin Tree card (special: just LT + zero-padded style)

**Rules:**
- Include each part only if real data exists — don't put NA or NOSTYLE in the SKU
- Leanin Tree cards: `LT-{5-digit zero-padded style}` (no gender, color, size)
- If no style number → use barcode as style
- If no style AND no barcode → move to review

### Rule 6: Data Quality Gates (must pass before import)

Products go to `needs_review` if ANY of these are true:
- `...` in style_number or barcode (AI couldn't read full label)
- `?` in barcode
- Non-numeric barcode (letters, spaces, `add 1`, `a +1`)
- No style number AND no barcode
- No retail price
- Item name is just "Lightspeed" or "INVENTORY STOP"

---

## Phase 5: Export for Review

### Two CSVs:
1. `docs/normalized_ready.csv` — products passing all quality gates
2. `docs/normalized_needs_review.csv` — products needing human attention

### CSV format requirements:
- UTF-8 BOM encoding (`utf-8-sig`) for Excel compatibility
- All fields quoted (`QUOTE_ALL`) so barcodes/styles aren't interpreted as numbers
- None values → empty string, never "None"
- All 30 columns in order matching the table schema

---

## Phase 6: Lightspeed Import

### API Details
- **Base URL:** `https://therodeoshop.retail.lightspeed.app/api/2.0`
- **Auth:** `Authorization: Bearer {lightspeed_personal_token}`
- **Rate limit:** ~350 req/5 min — use 55 req/min to be safe
- **Tax model:** Tax-exclusive — use `price_excluding_tax`, NOT `price_including_tax`

### Import Logic

```
For each product:
  1. Check if SKU exists in Lightspeed (fresh cache lookup)
     → YES: PUT /products/{id} (update price, variants)
     → NO: Continue to create
  
  2. Check if barcode exists in Lightspeed
     → YES: Skip barcode in payload (avoid duplicate error)
  
  3. POST /products (create)
     → 422 "Already exists": Retry with name + " ({sku})" appended
     → 422 SKU error: Clean SKU and retry
     → 429 rate limit: Wait 15 seconds and retry
```

### Create payload structure:
```json
{
    "name": "Product Name",
    "sku": "M-BHS-DH4655-TT-14-EE",
    "price_excluding_tax": 199.95,
    "supply_price": 0,
    "active": true,
    "description": "Product description",
    "variant_options": [
        {"name": "Size", "value": "14"},
        {"name": "Width", "value": "EE"},
        {"name": "Color", "value": "Tan"}
    ],
    "product_codes": [
        {"type": "UPC", "code": "889871002494"}
    ]
}
```

### Update payload (existing products):
- Same as create but WITHOUT `name` (keep Lightspeed's name)
- Use `PUT /products/{lightspeed_id}`

---

## Lessons Learned

### 1. Cache IDs expire fast
The Lightspeed catalog has 70K+ products. Product IDs can change. **Always refresh the cache immediately before import.** Never use a cache more than a few minutes old for writes.

### 2. Tax model matters
The Rodeo Shop is a **tax-exclusive** retailer. Using `price_including_tax` causes 422 errors on every request. Use `price_excluding_tax`.

### 3. Variant consistency is mandatory
Lightspeed rejects product families where some variants have Size+Width+Color and others only have Size. **Every product in a style family must have identical variant option names.** Fill missing values with `NA`.

### 4. Barcode uniqueness is enforced
Lightspeed won't let you create a product with a barcode that already exists on another product. **Check the barcode index before including it in the create payload.** If it conflicts, skip the barcode — the product can still be created without one.

### 5. Name uniqueness is enforced
Product names must be unique across the entire catalog. If a name already exists, append the SKU in parentheses: `"Product Name (M-BHS-DH4655-TT-14-EE)"`.

### 6. Scanner data is the pricing source of truth
The scanned label prices are more accurate than Lightspeed's existing prices. We update Lightspeed FROM our data, never the reverse. The only exception: if we have NO price at all, then we research the brand website.

### 7. Supplier codes must match Lightspeed vendors
The AI scanner sometimes gets brand names wrong (misspellings, variants). Every brand must map to an official Lightspeed vendor code. Keep the vendor mapping table up to date as new brands appear.

### 8. "..." means the AI couldn't read the label
Any field containing `...` is partial/unreliable data. Treat it as blank and move the item to review. The staff need to physically re-check those items.

### 9. Non-numeric barcodes are scanner errors
Real barcodes are digits only. If a barcode contains letters, spaces, or text like `add 1`, it's a scanning artifact. Move to review.

### 10. Batch by brand for internet research
When looking up missing data on brand websites, deduplicate by style_number first. If 15 items share style `3147`, look it up once. Search pattern: `{brand} {style_number} site:{brand_website}`.

### 11. Test with 5 products before full import
Always run a test batch of 5 creates to verify the API payload format. The Lightspeed API returns different errors for different issues (tax model, name uniqueness, barcode conflicts, SKU format) — catch them all before committing to a 2-hour bulk import.

### 12. Style number digit errors are common
The AI scanner drops or adds digits, especially with Ariat (8-digit styles) and Wrangler (prefix issues like `13MWZ` vs `1013MWZ`). Within each brand, compare style numbers for near-matches and verify against the brand's catalog.

---

## Files Reference

| File | Purpose |
|------|---------|
| `docs/DATA_ANALYSIS_INSTRUCTIONS.md` | This playbook |
| `docs/normalized_ready.csv` | Products ready for Lightspeed import |
| `docs/normalized_needs_review.csv` | Products needing human review |
| `docs/lightspeed_cache.json` | Full Lightspeed catalog cache |
| `docs/ls_fresh_barcode_idx.json` | Fresh barcode → LS product ID index |
| `docs/ls_fresh_sku_idx.json` | Fresh SKU → LS product ID index |
| `docs/ls_fresh_name_idx.json` | Fresh name → LS product ID index |
| `docs/brand_research_cache.json` | Internet research results for pricing |
| `docs/lightspeed_import_log_v2.json` | Import progress/error log |
| `docs/lightspeed_import_v2.py` | Import script (the working version) |
| `docs/For Import products-2026-04-03.xlsx` | Original spreadsheet (Corrinne's work) |

---

## Running the Import Again (New Data)

When new products are scanned and need to be normalized + imported:

1. **Insert new products** into `normalized_products` from `products` table (same INSERT as Phase 1b, but only for new `product_id`s not already in the table)
2. **Apply all normalization rules** (Phase 4) — gender, supplier codes, size parsing, color codes, SKU formula
3. **Run quality gates** — move items with `...`, missing data, etc. to review
4. **Export CSVs** for human review
5. **Refresh Lightspeed cache** (Phase 2) — always fresh before import
6. **Run import script** (`docs/lightspeed_import_v2.py`)

**Estimated time for 1,000 new products:** ~20 min normalization + ~20 min import
