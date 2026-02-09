# Retail Product Label System

A mobile-first product scanner that uses AI vision to extract product information from labels and barcodes.

## Features

- 📷 **Mobile Camera Integration** - Scan products directly from your phone
- 🤖 **AI-Powered Extraction** - GPT-4o vision automatically reads:
  - UPC-A barcodes (12 digits, USA standard)
  - SKU/Style codes
  - Product names and brands
  - Sizes (USA sizing only)
  - Prices (including handwritten markdowns)
- 💾 **Cloud Database** - Saves all scanned products to Supabase
- 📊 **CSV Export** - Export data for Lightspeed POS import
- ✅ **Duplicate Prevention** - Won't save the same SKU/barcode twice
- 🔄 **Rescan Option** - Try again if results look wrong

## Live Demo

**Scanner URL:** [https://nexusbluedev.github.io/retail-product-label-system/](https://nexusbluedev.github.io/retail-product-label-system/)

## How to Use

1. **Open the scanner** on your mobile device
2. **Tap the camera icon** to take a photo of the product label
3. **Review extracted data** - AI fills in all fields automatically
4. **Edit if needed** - You can manually adjust any field
5. **Click Save** - Product is saved to the database
6. **Export CSV** - Download all products for Lightspeed import

## Supported Barcode Types

Primary focus on USA retail standards:
- **UPC-A** (12 digits) - Primary
- **EAN-13** (13 digits) - International products
- **ITF-14** (14 digits) - Shipping/case barcodes
- QR Codes, Code 39, Code 128, Data Matrix

## Technology Stack

- **Frontend:** Pure HTML/CSS/JavaScript (no frameworks)
- **AI Vision:** OpenAI GPT-4o
- **Database:** Supabase (PostgreSQL)
- **Hosting:** GitHub Pages

## Browser Support

- ✅ Safari (iOS) - Full camera support
- ✅ Chrome (Android) - Full camera support
- ✅ Desktop browsers - File upload only (no camera)

## Privacy & Data

- All scanned products are saved to a secure cloud database
- Data is accessible to all users of the scanner
- No personal information is collected
- Images are not stored, only extracted text data

## Developed By

**NexusBlue**  
Contact: [Your contact info]

## License

Proprietary - All rights reserved

---

**Need help?** Contact the development team or report issues via GitHub.
