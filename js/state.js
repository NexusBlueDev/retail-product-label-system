/**
 * State Module
 * Application state management - stores current images, extracted data, and barcode info
 */

export const state = {
    currentImages: [],       // Array of {base64, preview} objects
    extractedData: null,     // Object from AI extraction
    scannedBarcode: null,    // String (currently unused, for future use)
    lastDetectedCode: null,  // String from barcode scanner
    editingId: null,         // Product ID currently being edited (null = create mode)
    lastSavedProduct: null,  // Full product object from last successful save
    duplicateProductId: null, // ID of existing product found by barcode precheck
    accessToken: null,       // Supabase Auth JWT (set on app init via auth.js)
    user: null,              // Supabase Auth user object
    currentUser: null        // Front-end user name (set by user-auth.js)
};
