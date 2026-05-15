"""
ls_bracket_names.py
====================
Finds all Lightspeed variants whose product name contains [, ], (, or ) and
attempts to match each one to a "clean" counterpart in an existing product family.

Match logic (per Corrinne S24 request):
  For each bracket-name variant:
    1. Extract the SKU embedded in the name  (e.g. "W-MIN-MSK7901003-LIL-LIL-XS")
    2. From that SKU, extract: brand prefix, style, color, size (+ length/width if present)
    3. Search LS catalog for a non-bracket variant with:
         - Same style code (from SKU)
         - Same color option value
         - Same size option value
         - Same length/width values if present
       Prefer variants in a real product family (has family_id).
    4. If UPC is present on both, also cross-check UPC match.

Output CSVs:
  docs/ls_bracket_names.csv        — all bracket-name variants (same cols as UPC audit + match info)
  docs/ls_bracket_match_pairs.csv  — matched pairs: bracket variant | clean family variant | action
  docs/ls_bracket_unmatched.csv    — bracket variants with no match found

Columns in ls_bracket_names.csv:
  ID, Name, UPC, Auto-Generated, Custom 1, Custom 2, Product Category,
  Variant_option_one_name, Variant_option_one_value,
  Variant_option_two_name, Variant_option_two_value,
  Variant_option_three_name, Variant_option_three_value,
  Variant_option_four_name, Variant_option_four_value,
  Tags, Supply price, Retail price, Brand, Supplier, Supplier Code,
  Active, Track Inventory, Family ID, embedded_sku

Usage:
  python3 docs/ls_bracket_names.py             # fresh live fetch
  python3 docs/ls_bracket_names.py --use-cache # use cached catalog if <6h old
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DOCS = Path("docs")
CACHE_FILE = DOCS / "ls_bracket_names_cache.json"
OUTPUT_ALL = DOCS / "ls_bracket_names.csv"
OUTPUT_PAIRS = DOCS / "ls_bracket_match_pairs.csv"
OUTPUT_UNMATCHED = DOCS / "ls_bracket_unmatched.csv"

LS_BASE = "https://therodeoshop.retail.lightspeed.app/api/2.0"
HEADERS = {"User-Agent": "curl/7.81.0"}
PAGE_SIZE = 250
SLEEP_BETWEEN_PAGES = 1.1

USE_CACHE = "--use-cache" in sys.argv
CACHE_MAX_AGE_SECS = 6 * 3600

BRACKET_PAT = re.compile(r"[\[\]()\{\}]")


# ── Credentials ───────────────────────────────────────────────────────────────

def get_token() -> str:
    for line in Path(".env.local").read_text().splitlines():
        if line.startswith("LIGHTSPEED_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("LIGHTSPEED_TOKEN not found in .env.local")


# ── LS API ────────────────────────────────────────────────────────────────────

def ls_get(token: str, path: str, params: dict = None):
    url = f"{LS_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={**HEADERS, "Authorization": f"Bearer {token}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                return body.get("data", []), body.get("version")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 20 * (attempt + 1)
                print(f"  429 rate limit — sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
    return [], None


def fetch_all_products(token: str) -> list:
    if USE_CACHE and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_MAX_AGE_SECS:
            print(f"Using cached catalog ({age/3600:.1f}h old).", flush=True)
            return json.loads(CACHE_FILE.read_text())

    print("Fetching all products from Lightspeed (~6-8 min)...", flush=True)
    all_products = []
    after = 0
    page = 0

    while True:
        page += 1
        params = {"page_size": str(PAGE_SIZE)}
        if after > 0:
            params["after"] = str(after)

        if page % 25 == 1:
            print(f"  Page {page} (after={after}, fetched: {len(all_products):,})", flush=True)

        data, version_info = ls_get(token, "products", params)
        if not data:
            break

        all_products.extend(data)
        time.sleep(SLEEP_BETWEEN_PAGES)

        if isinstance(version_info, dict) and "max" in version_info:
            after = version_info["max"]
        elif data:
            after = data[-1].get("version", 0)

        if len(data) < PAGE_SIZE:
            break

    print(f"Fetched {len(all_products):,} products.", flush=True)
    CACHE_FILE.write_text(json.dumps(all_products))
    return all_products


# ── Field extractors ──────────────────────────────────────────────────────────

def extract_upc(p: dict) -> str:
    for c in (p.get("product_codes") or []):
        if c.get("type") == "UPC":
            return str(c.get("code", "")).strip()
    return ""


def extract_customs(p: dict) -> list:
    return [str(c.get("code", "")).strip()
            for c in (p.get("product_codes") or [])
            if c.get("type") in ("CUSTOM", "custom")]


def extract_category(p: dict) -> str:
    cat = p.get("product_category")
    if not cat:
        return ""
    if isinstance(cat, dict):
        return cat.get("name", "")
    if isinstance(cat, str):
        try:
            return json.loads(cat).get("name", cat)
        except Exception:
            return cat
    return ""


def extract_variant_options(p: dict) -> list:
    opts = p.get("variant_options") or []
    if isinstance(opts, list):
        return [(o.get("name", ""), o.get("value", "")) for o in opts if isinstance(o, dict)]
    if isinstance(opts, dict):
        return list(opts.items())
    return []


def extract_brand(p: dict) -> str:
    b = p.get("brand")
    return b.get("name", "") if isinstance(b, dict) else str(b or "")


def extract_supplier(p: dict) -> str:
    sups = p.get("product_suppliers") or []
    if isinstance(sups, list) and sups:
        s = sups[0]
        if isinstance(s, dict):
            return s.get("supplier_name") or s.get("name") or ""
    return str(p.get("supplier") or "")


def extract_supplier_code(p: dict) -> str:
    sc = p.get("supplier_code")
    if sc:
        return str(sc).strip()
    sups = p.get("product_suppliers") or []
    if isinstance(sups, list) and sups:
        s = sups[0]
        if isinstance(s, dict) and s.get("code"):
            return str(s["code"]).strip()
    return ""


def extract_tags(p: dict) -> str:
    return ", ".join(str(t) for t in (p.get("tag_ids") or []))


def opt_lookup(opts: list, idx: int) -> tuple[str, str]:
    return opts[idx] if idx < len(opts) else ("", "")


# ── SKU parsing ───────────────────────────────────────────────────────────────

SKU_IN_NAME = re.compile(r"\[([^\]]+)\]|\(([^)]+)\)")


def extract_embedded_sku(name: str) -> str:
    """Pull the SKU from bracket/paren portion of the name."""
    for m in SKU_IN_NAME.finditer(name):
        val = (m.group(1) or m.group(2) or "").strip()
        # SKU typically has hyphens and looks like W-MIN-MSK7901003-LIL-LIL-XS
        if "-" in val and len(val) > 5:
            return val
        if val:
            return val
    return ""


def parse_sku_parts(sku: str) -> dict:
    """
    Parse SKU into components. Our SKU format (from sku-generator.js):
      {STYLE}-{BRAND}-{COLOR}-{SIZE}  (up to 15 chars, truncated)

    But many SKUs in LS are the full import SKU like:
      W-MIN-MSK7901003-LIL-LIL-XS  (brand-gender-style-color-color2-size)
    or simply the style code.

    Returns dict with keys: style, color, size, length, raw
    """
    parts = sku.split("-")
    return {
        "raw": sku,
        "parts": parts,
        "style": parts[2] if len(parts) >= 3 else (parts[0] if parts else sku),
    }


# ── Match logic ───────────────────────────────────────────────────────────────

def normalize_opt(val: str) -> str:
    return val.strip().upper()


def build_clean_index(all_products: list) -> dict:
    """
    Build a lookup: (style_fragment, color_norm, size_norm) -> list of clean variants

    "clean" = name does NOT contain bracket/paren chars
    """
    index = {}
    for p in all_products:
        name = p.get("name", "")
        if BRACKET_PAT.search(name):
            continue
        opts = extract_variant_options(p)

        color = ""
        size = ""
        for opt_name, opt_val in opts:
            n = opt_name.lower()
            if "color" in n:
                color = normalize_opt(opt_val)
            elif "size" in n:
                size = normalize_opt(opt_val)

        sku = str(p.get("sku") or "").strip()
        customs = extract_customs(p)
        all_codes = [sku] + customs

        for code in all_codes:
            if not code:
                continue
            parts = code.split("-")
            # index by each part segment as a style candidate
            for part in parts:
                if len(part) >= 4:
                    key = (part.upper(), color, size)
                    index.setdefault(key, []).append(p)

    return index


def find_match(bracket_variant: dict, bracket_opts: list, embedded_sku: str,
               clean_index: dict, all_clean: dict) -> dict | None:
    """Try to find a clean counterpart for a bracket-name variant."""
    color = ""
    size = ""
    for opt_name, opt_val in bracket_opts:
        n = opt_name.lower()
        if "color" in n:
            color = normalize_opt(opt_val)
        elif "size" in n:
            size = normalize_opt(opt_val)

    sku_parts = parse_sku_parts(embedded_sku) if embedded_sku else {}
    candidates = []

    if embedded_sku:
        for part in sku_parts.get("parts", []):
            if len(part) >= 4:
                key = (part.upper(), color, size)
                for cand in clean_index.get(key, []):
                    candidates.append(cand)

    # Deduplicate candidates by ID
    seen = set()
    unique = []
    for c in candidates:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)

    if not unique:
        return None

    # Prefer variants that are in a product family (have non-null family_id)
    with_family = [c for c in unique if c.get("family_id")]
    pool = with_family if with_family else unique

    # If only one candidate, use it
    if len(pool) == 1:
        return pool[0]

    # UPC cross-check as tiebreaker
    bv_upc = extract_upc(bracket_variant)
    if bv_upc:
        upc_match = [c for c in pool if extract_upc(c) == bv_upc]
        if upc_match:
            return upc_match[0]

    # Return first (best style-color-size match)
    return pool[0]


# ── Row builder ───────────────────────────────────────────────────────────────

ALL_FIELDS = [
    "ID", "Name", "UPC", "Auto-Generated", "Custom 1", "Custom 2",
    "Product Category",
    "Variant_option_one_name", "Variant_option_one_value",
    "Variant_option_two_name", "Variant_option_two_value",
    "Variant_option_three_name", "Variant_option_three_value",
    "Variant_option_four_name", "Variant_option_four_value",
    "Tags", "Supply price", "Retail price",
    "Brand", "Supplier", "Supplier Code",
    "Active", "Track Inventory", "Family ID", "embedded_sku",
]

PAIR_FIELDS = [
    "bracket_id", "bracket_name", "bracket_upc", "bracket_sku", "bracket_custom1",
    "bracket_color", "bracket_size",
    "clean_id", "clean_name", "clean_upc", "clean_sku", "clean_custom1",
    "clean_color", "clean_size",
    "match_confidence", "action",
]


def build_row(p: dict) -> dict:
    opts = extract_variant_options(p)
    customs = extract_customs(p)
    name = p.get("name", "")
    embedded_sku = extract_embedded_sku(name)

    def on(i): return opt_lookup(opts, i)

    active = p.get("is_active")
    if active is None:
        active = p.get("active")
    track = p.get("track_inventory")
    if track is None:
        track = p.get("has_inventory")

    return {
        "ID": p.get("id", ""),
        "Name": name,
        "UPC": extract_upc(p),
        "Auto-Generated": str(p.get("sku") or "").strip(),
        "Custom 1": customs[0] if len(customs) > 0 else "",
        "Custom 2": customs[1] if len(customs) > 1 else "",
        "Product Category": extract_category(p),
        "Variant_option_one_name": on(0)[0],
        "Variant_option_one_value": on(0)[1],
        "Variant_option_two_name": on(1)[0],
        "Variant_option_two_value": on(1)[1],
        "Variant_option_three_name": on(2)[0],
        "Variant_option_three_value": on(2)[1],
        "Variant_option_four_name": on(3)[0],
        "Variant_option_four_value": on(3)[1],
        "Tags": extract_tags(p),
        "Supply price": p.get("supply_price", ""),
        "Retail price": p.get("price_excluding_tax", ""),
        "Brand": extract_brand(p),
        "Supplier": extract_supplier(p),
        "Supplier Code": extract_supplier_code(p),
        "Active": active,
        "Track Inventory": track,
        "Family ID": p.get("family_id") or "",
        "embedded_sku": embedded_sku,
    }


def get_color_size(p: dict) -> tuple[str, str]:
    opts = extract_variant_options(p)
    color, size = "", ""
    for n, v in opts:
        nl = n.lower()
        if "color" in nl:
            color = v
        elif "size" in nl:
            size = v
    return color, size


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = get_token()
    products = fetch_all_products(token)

    print("Scanning for bracket/paren names...", flush=True)
    bracket_variants = [p for p in products if BRACKET_PAT.search(p.get("name", ""))]
    print(f"Found {len(bracket_variants):,} variants with bracket/paren in name.", flush=True)

    # Build rows for all-variants CSV
    all_rows = [build_row(p) for p in bracket_variants]
    with open(OUTPUT_ALL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ALL_FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"Wrote {OUTPUT_ALL}", flush=True)

    # Build match index from non-bracket variants
    print("Building match index from clean variants...", flush=True)
    clean_index = build_clean_index(products)
    clean_by_id = {p["id"]: p for p in products if not BRACKET_PAT.search(p.get("name", ""))}

    pair_rows = []
    unmatched_rows = []

    for p in bracket_variants:
        opts = extract_variant_options(p)
        embedded_sku = extract_embedded_sku(p.get("name", ""))
        match = find_match(p, opts, embedded_sku, clean_index, clean_by_id)

        bv_color, bv_size = get_color_size(p)
        bv_upc = extract_upc(p)
        bv_sku = str(p.get("sku") or "").strip()
        bv_customs = extract_customs(p)

        if match:
            mv_color, mv_size = get_color_size(match)
            mv_upc = extract_upc(match)
            mv_customs = extract_customs(match)

            color_match = normalize_opt(bv_color) == normalize_opt(mv_color)
            size_match = normalize_opt(bv_size) == normalize_opt(mv_size)
            upc_match = bv_upc and mv_upc and bv_upc == mv_upc

            if upc_match:
                confidence = "HIGH (UPC match)"
            elif color_match and size_match:
                confidence = "MEDIUM (color+size match)"
            elif color_match or size_match:
                confidence = "LOW (partial match)"
            else:
                confidence = "SPECULATIVE"

            pair_rows.append({
                "bracket_id": p.get("id", ""),
                "bracket_name": p.get("name", ""),
                "bracket_upc": bv_upc,
                "bracket_sku": bv_sku,
                "bracket_custom1": bv_customs[0] if bv_customs else "",
                "bracket_color": bv_color,
                "bracket_size": bv_size,
                "clean_id": match.get("id", ""),
                "clean_name": match.get("name", ""),
                "clean_upc": mv_upc,
                "clean_sku": str(match.get("sku") or "").strip(),
                "clean_custom1": mv_customs[0] if mv_customs else "",
                "clean_color": mv_color,
                "clean_size": mv_size,
                "match_confidence": confidence,
                "action": "MERGE_AND_DELETE_BRACKET",
            })
        else:
            row = build_row(p)
            row["match_note"] = "No matching clean variant found — needs manual review"
            unmatched_rows.append(row)

    with open(OUTPUT_PAIRS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PAIR_FIELDS)
        w.writeheader()
        w.writerows(pair_rows)

    unmatched_fields = ALL_FIELDS + ["match_note"]
    with open(OUTPUT_UNMATCHED, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=unmatched_fields)
        w.writeheader()
        w.writerows(unmatched_rows)

    print(f"\nResults:", flush=True)
    print(f"  Bracket variants total:  {len(bracket_variants):,}", flush=True)
    print(f"  Matched to clean family: {len(pair_rows):,}", flush=True)
    print(f"  Unmatched (needs review):{len(unmatched_rows):,}", flush=True)
    print(f"\nOutputs:", flush=True)
    print(f"  All bracket variants: {OUTPUT_ALL}", flush=True)
    print(f"  Match pairs:          {OUTPUT_PAIRS}", flush=True)
    print(f"  Unmatched:            {OUTPUT_UNMATCHED}", flush=True)

    # Confidence breakdown
    from collections import Counter
    conf_counts = Counter(r["match_confidence"] for r in pair_rows)
    print(f"\nMatch confidence breakdown:", flush=True)
    for conf, cnt in sorted(conf_counts.items(), key=lambda x: -x[1]):
        print(f"  {conf}: {cnt:,}", flush=True)


if __name__ == "__main__":
    main()
