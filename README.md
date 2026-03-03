# Retail Product Label System - Product Scanner

A mobile-first AI-powered product scanner for retail inventory management with real-time barcode scanning and multi-field extraction.

## 🚀 Live Application

**Scanner URL:** [https://nexusbluedev.github.io/retail-product-label-system/](https://nexusbluedev.github.io/retail-product-label-system/)

---

## ✨ Features

### 🏠 **Three-Mode Workflow (v4.0)**
After login, a menu lets you choose how to work:
- **Product Scanner** — Full scan/photo/AI/review/save flow (original mode)
- **Quick Capture** — Speed-snap photos, AI extracts name only, images stored for later desktop processing
- **Process Photos** — Desktop 3-column view: queue of photo-only products, AI extraction results, editable form with copy buttons

### 📊 **Real-Time Barcode Scanner**
- Hardware barcode scanning using device camera
- UPC-A (12 digits) and EAN-13 (13 digits) support
- Manual capture button for controlled scanning
- 99%+ accuracy with live validation
- Scanned barcodes take priority over AI extraction

### 📷 **Multi-Image AI Extraction**
- Take multiple photos per product (vendor label + handwritten notes)
- GPT-4o vision automatically extracts:
  - Product name and brand
  - Style/manufacturer codes
  - Sizes (USA sizing only)
  - Colors
  - Prices (including handwritten markdowns)
  - Categories and descriptions
- First image priority (printed labels) over subsequent images (handwritten)

### 🔢 **Intelligent SKU Generation**
- Auto-generates SKU from: `STYLE-BRAND-COLOR-SIZE`
- Example: `DD1383100-NK-WHT-9`
- Max 15 characters (Lightspeed POS compatible)
- Pre-configured brand codes (NK, AD, UA, WR, LV, etc.)
- Manual override available

### 👤 **Per-User Login & Tracking**
- "Who's scanning?" overlay shown before the app loads
- Tap your name → enter 4-digit PIN → app unlocks
- Self-service account creation (any user can add a new name + PIN)
- Session remembered across reloads; "Switch" link in header to hand off
- Every saved product records who entered it (`entered_by` field)

### 💾 **Database Features**
- Real-time sync to Supabase PostgreSQL
- Duplicate prevention (unique SKU and barcode constraints)
- Automatic timestamps (created_at, updated_at)
- Quantity tracking with default value of 1
- Full field validation before save

### 📤 **Complete CSV Export**
Exports all 19 fields:
- ID, Created At, Updated At
- Item Name, Style Number, SKU, Barcode
- Brand, Category, Retail Price, Supply Price
- Size, Color, Quantity
- Tags, Description, Notes, Verified, **Entered By**

---

## 📱 How to Use

### **Option 1: Scan Barcode First (Recommended)**
1. Click **📊 Scan UPC** button
2. Position camera over barcode
3. Wait for "✓ Found: [code]" message
4. Click **📸 Capture Barcode** button
5. Click **📷 Take Photo** to capture product label
6. Click **🔍 Process Images with AI**
7. Review extracted data (barcode won't be overwritten)
8. Edit any fields if needed
9. Click **Save Product**

### **Option 2: Photos Only (AI Extracts Everything)**
1. Click **📷 Take Photo** or **🖼️ Photos**
2. Take photo(s) of product label
3. Click **🔍 Process Images with AI**
4. AI extracts all fields including barcode
5. Review and edit
6. Click **Save Product**

### **Multi-Image Workflow**
1. Take photo of printed manufacturer label (for barcode, style, size)
2. Take photo of handwritten price sticker (for current price)
3. Process both → AI merges data intelligently
4. Vendor label data has priority

---

## 🎯 Data Fields

### **Automatically Extracted**
- **Product Name** (required)
- **Style Number** - Manufacturer's style code
- **Brand Name**
- **Product Category** - Format: "Type - Subtype"
- **Retail Price** - Current selling price
- **Size/Dimensions** - USA sizes only
- **Color** - Product color
- **Tags** - Gender/category tags
- **Description** - Product details
- **Notes** - Additional information

### **Auto-Generated**
- **SKU** - Generated from Style + Brand + Color + Size
- **Quantity** - Defaults to 1

### **Scanner/Manual Entry**
- **Barcode** - UPC-A or EAN-13 from scanner or AI

### **System Fields**
- **ID** - Auto-incremented database ID
- **Created At** - Timestamp when added
- **Updated At** - Last modification timestamp
- **Verified** - Manual verification flag
- **Entered By** - Name of person who saved or last edited the record

---

## 📁 Repository Structure

```
retail-product-label-system/
├── index.html                  # Single-page app (4 view containers)
├── js/                         # 18 ES6 modules
│   ├── app.js                  # Entry point, init + orchestration
│   ├── navigation.js           # View controller (menu/scanner/capture/processor)
│   ├── storage.js              # Supabase Storage REST API
│   ├── quick-capture.js        # Quick Capture mode
│   ├── desktop-processor.js    # Desktop Processor mode
│   └── ...                     # 13 other modules (see ARCHITECTURE.md)
├── styles/
│   ├── main.css                # Base reset and layout
│   ├── components.css          # Forms, buttons, menu, capture styles
│   ├── modals.css              # Success/duplicate modals
│   └── desktop.css             # Processor 3-column grid layout
├── supabase/
│   ├── config.toml             # Edge Function configuration
│   ├── functions/
│   │   └── extract-product/    # AI extraction Edge Function (Deno)
│   └── migrations/             # 8 SQL migration files (reference)
├── docs/                       # Project concept and planning docs
├── CLAUDE.md                   # Claude Code execution rules
├── HANDOFF.md                  # Project state and session log
├── TODO.md                     # Human action items
├── ARCHITECTURE.md             # System design and data flow
└── package.json                # Supabase CLI devDependency
```

---

## 🔧 Technical Details

### **Technology Stack**
- **Frontend:** Pure HTML/CSS/JavaScript (no frameworks, no build tools)
- **Module System:** ES6 native modules (18 modules, single entry point)
- **Barcode Scanner:** QuaggaJS 2 v1.12.1 (open source)
- **AI Vision:** OpenAI GPT-4o (via Supabase Edge Function)
- **Database:** Supabase (PostgreSQL with Row Level Security)
- **Hosting:** GitHub Pages (auto-deploys on push to main)

### **Browser Support**
- ✅ Safari (iOS) - Full camera and scanner support
- ✅ Chrome (Android) - Full camera and scanner support
- ✅ Desktop browsers - File upload (no live camera)

### **Barcode Types Supported**
- **UPC-A** (12 digits) - Primary USA retail standard
- **EAN-13** (13 digits) - International products
- Code 128, Code 39 (disabled to prevent misreads)

### **AI Processing (Edge Function)**
- **Source:** `supabase/functions/extract-product/index.ts`
- Model: GPT-4o (vision)
- Temperature: 0.1 (low for consistency)
- Validates barcode proximity to scannable bars
- Prioritizes printed labels over handwritten
- USA retail standards (sizes, formats)
- Rate limiting: 10 requests/min per IP (DB-backed)
- Retry: Exponential backoff, 2 max retries, 30s timeout

### **Edge Function Deployment**
```bash
# Deploy the extract-product Edge Function
npm run deploy:function

# Set OpenAI API key (required once, stored in Supabase secrets)
npx supabase secrets set OPENAI_API_KEY=sk-...
```

---

## 📊 Export to Lightspeed POS

1. Click **Export CSV** button
2. Download complete product database
3. Import CSV into Lightspeed POS
4. All fields mapped for direct import

**CSV Format:**
- 21 columns with headers (including Entered By, Status, Image Count)
- Quoted fields (handles commas/special chars)
- Sorted by creation date (newest first)

---

## 🔒 Data & Privacy

- All data stored in secure Supabase cloud database
- Products and user names visible to all users of the scanner
- User names and PINs stored in Supabase (internal tool, PINs not hashed)
- Product images stored in private Supabase Storage bucket (UID-scoped access)
- HTTPS encrypted connections

---

## 🐛 Troubleshooting

### **Barcode Scanner Not Working**
- Ensure camera permissions are granted
- Hold phone steady over barcode
- Ensure good lighting
- Try tapping screen to refocus camera
- Barcode must be 12 or 13 digits (UPC/EAN)

### **AI Extraction Errors**
- "Rate limit reached" - Wait 60 seconds and try again
- "No JSON found" - Check internet connection
- "Invalid response" - Retry or use different photo

### **Fields Not Populating**
- Style Number → populates from AI extraction
- SKU → auto-generates when Style/Brand/Color/Size entered
- Barcode → use scanner button for accuracy

### **Duplicate Errors**
- SKU or Barcode already exists in database
- Edit to make unique or check existing products

---

## 🎨 Customization

### **Brand Codes**
Edit `js/sku-generator.js` → `BRAND_MAP` to add your brands:
```javascript
'YOUR BRAND': 'YB',
```

### **Color Codes**
Edit `js/sku-generator.js` → `COLOR_MAP` for your color names:
```javascript
'NAVY BLUE': 'NVY',
```

---

## 📞 Support

For issues or feature requests:
- Check function logs in Supabase Dashboard
- Review browser console for errors
- Contact: [Your support contact]

---

## 📝 Version History

- **v4.0 (Current - Mar 2026)** - Three-Mode Workflow ✅
  - Post-login menu with Product Scanner, Quick Capture, Process Photos
  - Quick Capture: speed-snap photos, AI name only, Supabase Storage persistence
  - Desktop Processor: 3-column queue/AI/form view with copy buttons
  - All modes persist images to Supabase Storage
  - Products track status (photo_only / complete)
  - CSV export includes Status and Image Count (21 fields)
  - **Status: Production Ready**

- **v3.4 (Feb 2026)** - Per-User Login & Tracking ✅
  - "Who's scanning?" login overlay with name buttons + PIN entry
  - Self-service user creation (Add User from login screen)
  - `entered_by` field saved on every product create and edit
  - CSV export includes Entered By column (19 fields total)
  - Session persists via localStorage; Switch link in header
  - **Status: Production Ready**

- **v3.3 (Feb 2026)** - Modular Architecture + Edit/Duplicate Workflow ✅
  - Split monolithic 1100-line index.html into 13 ES6 modules
  - No build tools required (native browser modules)
  - Edit saved product from success modal (PATCH instead of POST)
  - Edit existing product from duplicate modal
  - Barcode duplicate pre-check warning before save attempt
  - Supabase Auth (silent auto-login, JWT refresh every 55 min)
  - **Status: Superseded by v3.4**

- **v3.2 (Feb 2026)** - Phase 1 Optimizations
  - 50% AI cost reduction via optimized prompts
  - WebP image compression (60% size reduction)
  - Retry logic with exponential backoff
  - Duplicate detection modal
  - **Status: Superseded by v3.3**

- **v3.1 (Feb 2026)** - Production stable release ✅
  - Fixed quantity field (was missing from form)
  - Fixed style_number database saving
  - Added comprehensive error logging
  - Enhanced duplicate detection messages
  - All 18 fields confirmed working
  - **Status: Superseded by v3.2**
  
- **v3.0** - Major feature release
  - Added real-time barcode scanner
  - Added style number and auto-SKU generation
  - Added quantity tracking
  
- **v2.0** - Multi-image support, color field, improved AI

- **v1.0** - Initial release with basic scanning

---

**Current Status:** ✅ Fully Operational - All Features Working
**Last Tested:** March 3, 2026
**Developed by:** NexusBlue Development Team
