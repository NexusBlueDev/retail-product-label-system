/**
 * State Module
 * Application state management - stores current images, extracted data, and barcode info
 */

export const state = {
    currentImages: [],       // Array of {base64, preview} objects
    extractedData: null,     // Object from AI extraction
    scannedBarcode: null,    // String (currently unused, for future use)
    lastDetectedCode: null   // String from barcode scanner
};
