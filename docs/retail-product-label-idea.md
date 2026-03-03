# Product Label Scanning System  
Reference Plan and Build Guide (v1)

## 1) Purpose

Build a fast, scan-first system that allows staff to photograph a product label, extract structured product data, verify it quickly, and export it in a format that can be imported into Lightspeed.

The primary goal is speed to usable data, not automation perfection.

---

## 2) Guiding Principles

- One scan equals one product
- Do not guess or hallucinate missing data
- Human verification is required before export
- Variants are explicitly deferred
- CSV export is the system boundary
- v1 must be buildable in under one hour

---

## 3) v1 Scope (What We Are Building Now)

### Included
- Single-page landing interface
- Image upload (camera-first)
- OCR extraction
- ChatGPT structured parsing
- Editable review form
- Product record storage
- CSV and optional Excel export
- Export logging

### Excluded (by design)
- Variants and size runs
- Multi-item scans
- Automatic Lightspeed API updates
- Advanced enrichment

---

## 4) User Workflow

### Step 1: Scan
- User taps a single capture field
- Takes a photo of a product label
- Image is stored and linked to a scan record

### Step 2: Extract
- OCR extracts all visible text
- Raw OCR text is stored
- ChatGPT converts OCR text into structured product fields

### Step 3: Verify
- UI shows:
  - Original image
  - Structured fields
- User edits any field
- User confirms the product as verified

### Step 4: Save and Export
- Verified product is saved to a product table
- User selects records for export
- CSV is generated in Lightspeed-compatible format

---

## 5) Data Model (v1)

### Scans
Stores raw intake and processing artifacts.

Fields:
- scan_id
- created_at
- image_reference
- raw_ocr_text
- raw_llm_json
- status

---

### Products (Normalized)
One row per scan, this is the export source.

Core fields:
- product_id
- scan_id
- sku (nullable)
- barcode (nullable)
- product_name
- brand
- category
- retail_price (nullable)
- supply_price (nullable)
- size_or_dimensions (optional)
- notes
- verified
- verified_at

Future-proof fields (inactive in v1):
- has_potential_variants
- variant_source_scan_id

---

## 6) OCR and AI Responsibilities

### OCR
- Extract all text
- No assumptions
- No filtering
- Store raw output

### ChatGPT
- Convert OCR text to structured JSON
- Follow strict rules:
  - Return null if unknown
  - Prices numeric only
  - Barcode digits only
  - Do not invent values
- Output JSON only

---

## 7) Human Verification Rules

- All records must be reviewed before export
- Missing fields are acceptable if truly absent
- Notes may contain size or contextual info
- Verification is explicit (checkbox or action)

---

## 8) Export Rules

- One CSV row per product
- No variants
- Stable column order
- Matches Lightspeed import template
- CSV is the contract boundary

Supported formats:
- CSV (required)
- Excel (optional)

---

## 9) Variants (Deferred, Planned)

### v1 Behavior
- No variant creation
- No variant inference
- No variant export

### UI
- Sidebar placeholder:
  Variants (coming soon)

### Future Phase
- User selects existing product
- Triggers variant discovery as a separate workflow
- Variant updates exported as a separate inventory update

This future work will reuse:
- Original scan image
- Normalized product data

---

## 10) Tooling (v1)

Required:
- Retool (UI, storage, export)
- Google Vision OCR (text extraction)
- OpenAI ChatGPT API (structuring)
- Lightspeed (import target)

No backend hosting required for v1.

---

## 11) Deployment Strategy

### v1
- Hosted inside Retool
- Live immediately
- Used in production for validation

### Future Phase
- Rebuild UI as custom web app
- Reuse:
  - Schema
  - Prompts
  - Workflow
  - CSV format
- Deploy on owned server and domain

Retool is treated as a working prototype and reference implementation.

---

## 12) Definition of Success for v1

- Staff can scan a label in seconds
- Extracted data is mostly correct
- Verification is fast and minimal
- CSV imports cleanly into Lightspeed
- No rework required after export

---

## 13) Next Steps

Immediate:
- Register required apps
- Build the single-page form
- Test with real label images

Near-term:
- Tighten prompts based on real scans
- Lock Lightspeed column mapping
- Add minor UX polish

Later:
- Variants workflow
- API-based Lightspeed sync
- Self-hosted deployment
