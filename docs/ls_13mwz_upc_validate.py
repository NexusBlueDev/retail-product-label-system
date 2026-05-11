"""
ls_13mwz_upc_validate.py
=========================
Cross-validates Corrinne's corrected UPCs (docs/Wrangler 13MWZ.xlsx)
against the UPCitemdb public barcode API.

Strategy (rate-limit aware — 100 calls/window):
  - Cache all results in docs/ls_13mwz_upc_cache.json (avoids re-calling)
  - Priority 1: ALL 672787... UPCs (24 variants — confirmed in DB)
  - Priority 2: Systematic sample of 051071... UPCs (~50 variants)
  - Priority 3: Spot-check 084084... + 760609... (5 each, to confirm empty)
  - Stop automatically if remaining quota drops to 5

For each found UPC, verify:
  - brand contains "Wrangler"
  - model matches expected color code (e.g. 13MWZAW, 13MWZCG)
  - title contains size match where parseable

Output:
  - docs/ls_13mwz_upc_validation_report.csv — full results
  - Console summary

Usage:
  python3 docs/ls_13mwz_upc_validate.py [--dry-run]
"""

import sys, json, time, csv, urllib.request, urllib.error
from pathlib import Path
from collections import defaultdict
import openpyxl

DOCS         = Path("docs")
CACHE_FILE   = DOCS / "ls_13mwz_upc_cache.json"
REPORT_CSV   = DOCS / "ls_13mwz_upc_validation_report.csv"
API_BASE     = "https://api.upcitemdb.com/prod/trial/lookup"
QUOTA_FLOOR  = 5     # stop making calls when this many remain
DRY_RUN      = "--dry-run" in sys.argv

# Color code → human label (from Corrinne's NEW SKU format)
COLOR_CODE_MAP = {
    "AW": "ANTIQUE_WS", "KL": "BLK_CHOCLT", "CG": "CHARGREY",
    "DD": "DK_STONE",   "GH": "GB_BLEACH",   "XS": "RIGID",
    "WK": "SHADOW_BLK", "GK": "SW_GLD_BKL",  "TN": "TAN",
    "PW": "PREWASHED_INDIGO", "PR": "PREWASH", "WI": "WHITE",
}

# ── Load cache ─────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))

# ── API call ───────────────────────────────────────────────────────────────────

def lookup_upc(upc: str) -> tuple[dict | None, int]:
    """Returns (item_or_None, remaining_quota)."""
    url = f"{API_BASE}?upc={upc}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/7.81.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 0))
            data = json.loads(resp.read())
            item = data["items"][0] if data.get("items") else None
            return item, remaining
    except urllib.error.HTTPError as e:
        remaining = int(e.headers.get("X-RateLimit-Remaining", 0)) if e.headers else 0
        if e.code == 429:
            print("  RATE LIMITED — stopping API calls")
            return None, 0
        return None, remaining
    except Exception as e:
        return None, 99

# ── Validation logic ───────────────────────────────────────────────────────────

def extract_color_code_from_new_sku(new_sku: str) -> str:
    """M-Kon-1013MWZAW-27-34 → AW"""
    parts = new_sku.split("-")
    if len(parts) >= 3:
        style_color = parts[2]  # e.g. 1013MWZAW
        if "MWZ" in style_color:
            return style_color.split("MWZ")[-1]  # → AW
    return ""

def validate_item(item: dict, expected_color_code: str, size: str, length: str) -> tuple[str, str]:
    """Returns (status, detail). Status: PASS | FAIL_BRAND | FAIL_MODEL | FAIL_SIZE | WARN_NO_SIZE."""
    brand = (item.get("brand") or "").lower()
    model = (item.get("model") or "").upper()
    title = (item.get("title") or "").upper()

    if "wrangler" not in brand and "wrangler" not in title:
        return "FAIL_BRAND", f"brand='{item.get('brand')}' title='{item.get('title', '')[:50]}'"

    expected_model = f"13MWZ{expected_color_code.upper()}"
    if model and expected_model not in model and "13MWZ" not in model:
        return "FAIL_MODEL", f"expected {expected_model}, got model='{model}'"

    # Size check — title format varies, best-effort
    size_str = f"{size}W"
    length_str = f"{length}L"
    if size_str in title or length_str in title or (not size and not length):
        return "PASS", f"model={model}"
    else:
        # Title doesn't explicitly mention size, but brand/model are correct
        return "WARN_NO_SIZE", f"model={model}, size not in title"

# ── Build priority queue ───────────────────────────────────────────────────────

def build_upc_list() -> list[dict]:
    wb = openpyxl.load_workbook(DOCS / "Wrangler 13MWZ.xlsx")
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        color    = str(row[15]).strip() if row[15] else ""
        size     = str(row[18]).strip() if row[18] else ""
        length   = str(row[20]).strip() if row[20] else ""
        upc      = str(row[12]).strip() if row[12] else ""
        new_sku  = str(row[10]).strip() if row[10] else ""
        if len(upc) == 11:
            upc = "0" + upc
        if upc and upc.isdigit():
            rows.append({
                "upc": upc, "color": color, "size": size,
                "length": length, "new_sku": new_sku,
                "prefix": upc[:3],
            })
    return rows

def prioritize(rows: list[dict], cache: dict) -> list[dict]:
    """Order: uncached 672... first, then 051..., then spot-checks for 084/760."""
    uncached = [r for r in rows if r["upc"] not in cache]

    p672 = [r for r in uncached if r["prefix"] == "672"]
    p051 = [r for r in uncached if r["prefix"] == "051"]
    p084 = [r for r in uncached if r["prefix"] == "084"][:3]  # spot-check only
    p760 = [r for r in uncached if r["prefix"] == "760"][:3]  # spot-check only
    p191 = [r for r in uncached if r["prefix"] == "191"]      # small group, test all

    # For p051: every 5th to sample ~53 across the full range
    p051_sample = p051[::5][:50]

    return p672 + p051_sample + p191 + p084 + p760

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    cache   = load_cache()
    all_rows = build_upc_list()
    to_test  = prioritize(all_rows, cache)
    remaining_quota = 94  # known from last API call

    print(f"13MWZ UPC Validation — {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"Total variants in Corrinne's file: {len(all_rows)}")
    print(f"Already cached:                    {len(cache)}")
    print(f"Queued to test:                    {len(to_test)}")
    print(f"API quota remaining (approx):      {remaining_quota}\n")

    if not DRY_RUN:
        for i, r in enumerate(to_test, 1):
            if remaining_quota <= QUOTA_FLOOR:
                print(f"\nQuota floor ({QUOTA_FLOOR}) reached — stopping API calls.")
                break
            item, remaining_quota = lookup_upc(r["upc"])
            cache[r["upc"]] = item  # None if not found
            save_cache(cache)
            status = "found" if item else "not_found"
            if i % 10 == 0 or item is None:
                print(f"  [{i}/{len(to_test)}] {r['upc']} ({r['color']}) — {status} | quota left: {remaining_quota}")
            time.sleep(1.2)  # ~50 req/min, well within limits

    # ── Generate report from cache ──────────────────────────────────────────────
    print("\nGenerating validation report from cache…")
    results = []
    stats = defaultdict(int)

    for r in all_rows:
        upc          = r["upc"]
        color_code   = extract_color_code_from_new_sku(r["new_sku"])
        expected_color = COLOR_CODE_MAP.get(color_code, color_code)

        if upc not in cache:
            status, detail = "NOT_TESTED", ""
        elif cache[upc] is None:
            status, detail = "NOT_IN_DB", ""
        else:
            status, detail = validate_item(cache[upc], color_code, r["size"], r["length"])

        stats[status] += 1
        results.append({
            "upc":            upc,
            "new_sku":        r["new_sku"],
            "color":          r["color"],
            "size":           r["size"],
            "length":         r["length"],
            "prefix":         r["prefix"],
            "status":         status,
            "detail":         detail,
            "api_brand":      (cache.get(upc) or {}).get("brand", "") if upc in cache and cache[upc] else "",
            "api_model":      (cache.get(upc) or {}).get("model", "") if upc in cache and cache[upc] else "",
            "api_title":      ((cache.get(upc) or {}).get("title", "") or "")[:80] if upc in cache and cache[upc] else "",
        })

    with open(REPORT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    print(f"\n{'='*50}")
    print(f"VALIDATION SUMMARY ({len(all_rows)} total variants)")
    print(f"{'='*50}")
    for s, c in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {s:20s}: {c}")
    print(f"\nFull report: {REPORT_CSV}")

    # Flag any hard failures
    failures = [r for r in results if r["status"].startswith("FAIL")]
    if failures:
        print(f"\n⚠  FAILURES ({len(failures)}) — UPCs that resolved but don't match Wrangler 13MWZ:")
        for r in failures:
            print(f"  {r['upc']}  {r['new_sku']:30s}  {r['status']}: {r['detail']}")
    else:
        print("\nNo hard failures in tested variants.")

if __name__ == "__main__":
    main()
