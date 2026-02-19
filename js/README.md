# Frontend JavaScript Modules

## Architecture Overview

The frontend uses **ES6 native modules** (`type="module"`) — no build tools required. All modules are loaded by `app.js` as the single entry point.

---

## Module Dependency Diagram

```
app.js (entry point)
├── config.js
├── state.js
├── events.js
├── dom.js
├── auth.js             (Supabase service-account silent login)
│   └── config.js
├── user-auth.js        (per-person login overlay)
│   ├── config.js
│   └── state.js
├── barcode-scanner.js
│   ├── dom.js
│   ├── state.js
│   ├── ui-utils.js
│   └── events.js
├── image-handler.js
│   ├── dom.js
│   ├── state.js
│   ├── ui-utils.js
│   └── events.js
├── ai-extraction.js
│   ├── config.js
│   ├── dom.js
│   ├── state.js
│   ├── ui-utils.js
│   ├── form-manager.js
│   └── events.js
├── form-manager.js
│   ├── dom.js
│   ├── state.js        (reads state.currentUser for entered_by)
│   └── sku-generator.js
├── database.js
│   ├── config.js
│   ├── dom.js
│   ├── state.js
│   ├── ui-utils.js
│   └── events.js
└── ui-utils.js
    ├── dom.js
    └── state.js
```

---

## Module Reference

### Foundational Modules (no dependencies on each other)

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `config.js` | Supabase/API configuration | `SUPABASE_URL`, `SUPABASE_KEY`, `FUNCTION_URL`, `AUTH_EMAIL`, `AUTH_PASSWORD` |
| `state.js` | Shared application state | `state` (mutable object) |
| `events.js` | Cross-module event bus | `eventBus` |
| `dom.js` | Cached DOM references | `getDOMElements()` |

### Auth Modules

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `auth.js` | Supabase service-account silent login | `ensureAuthenticated()` |
| `user-auth.js` | Per-person login overlay (PIN gate) | `loadUsers()`, `validatePin()`, `createUser()`, `getCurrentUser()`, `setCurrentUser()`, `clearCurrentUser()`, `showUserLoginOverlay()` |

### Utility Modules

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `ui-utils.js` | Status messages, modal control | `showStatus()`, `closeModal()`, `closeDuplicateModal()` |
| `sku-generator.js` | SKU generation logic | `generateSKU()`, `generateSKUFromForm()`, `BRAND_MAP`, `COLOR_MAP` |

### Feature Modules

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `barcode-scanner.js` | Quagga2 barcode scanning | `startBarcodeScanner()`, `stopBarcodeScanner()`, `captureBarcodeAndStop()` |
| `image-handler.js` | Image selection, compression, previews | `handleImageSelection()`, `compressImage()`, `clearImages()`, `updatePreviews()` |
| `ai-extraction.js` | OpenAI Vision API calls | `extractProductData(images)` |
| `form-manager.js` | Form population and data collection | `populateForm()`, `setupSKUAutoGeneration()`, `collectFormData()` |
| `database.js` | Supabase save, export, and lookups | `saveProduct()`, `exportData()`, `fetchProductCount()`, `checkBarcodeExists()`, `fetchProductForEdit()` |

### Entry Point

| Module | Purpose |
|--------|---------|
| `app.js` | Initializes app, wires all event listeners, manages startup sequence |

---

## Event Bus Events

| Event | Emitted by | Payload |
|-------|-----------|---------|
| `barcode:scanned` | `barcode-scanner.js` | `{ code: string }` |
| `images:selected` | `image-handler.js` | `{ count: number }` |
| `extraction:complete` | `ai-extraction.js` | `{ data: object }` |
| `product:saved` | `database.js` | `{ product: object }` |

---

## State Object

```javascript
// js/state.js
{
  currentImages: [],        // Array of { base64, preview } objects
  extractedData: null,      // Last AI extraction result
  scannedBarcode: null,     // Currently scanned barcode (unused, legacy)
  lastDetectedCode: null,   // Barcode detected by Quagga2 (pre-capture)
  editingId: null,          // Product ID being edited (null = create mode)
  lastSavedProduct: null,   // Full product object from last successful save
  duplicateProductId: null, // ID found by barcode precheck (used for Edit Existing)
  accessToken: null,        // Supabase Auth JWT (set by auth.js on startup)
  user: null,               // Supabase Auth user object
  currentUser: null         // Front-end user name (set by user-auth.js after PIN login)
}
```

---

## Customization

### Add a Brand Code
Edit `js/sku-generator.js` → `BRAND_MAP`:
```javascript
'YOUR BRAND': 'YB',
```

### Add a Color Code
Edit `js/sku-generator.js` → `COLOR_MAP`:
```javascript
'NAVY BLUE': 'NVY',
```

---

## Notes

- `image-compression.js` is loaded as a regular `<script>` (not a module) in `index.html`, making `compressImageToWebP()` available as a global function called by `image-handler.js`.
- Modal close functions (`closeModal`, `closeDuplicateModal`) are exposed to the global `window` scope in `app.js` to support inline `onclick` HTML attributes.
- Edit functions (`editLastSaved`, `cancelEdit`, `editDuplicateProduct`) are also on `window` for the same reason. `editLastSaved` re-populates the form from `state.lastSavedProduct` and switches to PATCH mode. `editDuplicateProduct` fetches the conflicting product by ID (stored in `state.duplicateProductId` by `checkBarcodeExists`) before calling `editLastSaved`.
- `window.switchUser` is set in `initApp()`. It calls `clearCurrentUser()` (clears `localStorage`) then reloads the page, which triggers `showUserLoginOverlay()` again.
- **Startup sequence in `app.js`:** `ensureAuthenticated()` (service JWT) → check `getCurrentUser()` from localStorage → if no saved user, `await showUserLoginOverlay()` → `initApp()`. The JWT refresh interval runs independently every 55 minutes.
- `user-auth.js` uses `state.accessToken` for all Supabase REST calls to `app_users`. The service-account JWT handles everything — no per-user Supabase credentials exist.
