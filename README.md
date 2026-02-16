# Retail Product Label System - Product Scanner

A mobile-first AI-powered product scanner for retail inventory management with real-time barcode scanning and multi-field extraction.

## 🚀 Live Application

**Scanner URL:** [https://nexusbluedev.github.io/retail-product-label-system/](https://nexusbluedev.github.io/retail-product-label-system/)

---

## ✨ Features

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

### 💾 **Database Features**
- Real-time sync to Supabase PostgreSQL
- Duplicate prevention (unique SKU and barcode constraints)
- Automatic timestamps (created_at, updated_at)
- Quantity tracking with default value of 1
- Full field validation before save

### 📤 **Complete CSV Export**
Exports all 18 fields:
- ID, Created At, Updated At
- Item Name, Style Number, SKU, Barcode
- Brand, Category, Retail Price, Supply Price
- Size, Color, Quantity
- Tags, Description, Notes, Verified

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

---

## 🔧 Technical Details

### **Technology Stack**
- **Frontend:** Pure HTML/CSS/JavaScript (no frameworks)
- **Barcode Scanner:** QuaggaJS 2 (open source)
- **AI Vision:** OpenAI GPT-4o
- **Database:** Supabase (PostgreSQL)
- **Hosting:** GitHub Pages

### **Browser Support**
- ✅ Safari (iOS) - Full camera and scanner support
- ✅ Chrome (Android) - Full camera and scanner support
- ✅ Desktop browsers - File upload (no live camera)

### **Barcode Types Supported**
- **UPC-A** (12 digits) - Primary USA retail standard
- **EAN-13** (13 digits) - International products
- Code 128, Code 39 (disabled to prevent misreads)

### **AI Processing**
- Model: GPT-4o (vision)
- Temperature: 0.1 (low for consistency)
- Validates barcode proximity to scannable bars
- Prioritizes printed labels over handwritten
- USA retail standards (sizes, formats)

---

## 📊 Export to Lightspeed POS

1. Click **Export CSV** button
2. Download complete product database
3. Import CSV into Lightspeed POS
4. All fields mapped for direct import

**CSV Format:**
- 18 columns with headers
- Quoted fields (handles commas/special chars)
- Sorted by creation date (newest first)

---

## 🔒 Data & Privacy

- All data stored in secure Supabase cloud database
- Products visible to all users of the scanner
- No personal information collected
- Images processed but not stored
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
Edit the `brandMap` in the HTML to add your brands:
```javascript
'YOUR BRAND': 'YB',
```

### **Color Codes**
Edit the `colorMap` for your color names:
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

- **v3.1 (Current - Feb 2026)** - Production stable release ✅
  - Fixed quantity field (was missing from form)
  - Fixed style_number database saving
  - Added comprehensive error logging
  - Enhanced duplicate detection messages
  - All 18 fields confirmed working
  - **Status: Production Ready**
  
- **v3.0** - Major feature release
  - Added real-time barcode scanner
  - Added style number and auto-SKU generation
  - Added quantity tracking
  
- **v2.0** - Multi-image support, color field, improved AI

- **v1.0** - Initial release with basic scanning

---

**Current Status:** ✅ Fully Operational - All Features Working  
**Last Tested:** February 16, 2026  
**Developed by:** NexusBlue Development Team
