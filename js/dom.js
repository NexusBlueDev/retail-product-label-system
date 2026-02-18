/**
 * DOM Module
 * Centralized DOM element references with lazy initialization
 */

let elements = null;

/**
 * Get cached DOM elements
 * Elements are queried once and cached for performance
 * @returns {Object} Object containing all DOM element references
 */
export function getDOMElements() {
    if (!elements) {
        elements = {
            // Barcode scanner elements
            scanBarcodeBtn: document.getElementById('scanBarcodeBtn'),
            captureBarcodeBtn: document.getElementById('captureBarcodeBtn'),
            stopScanBtn: document.getElementById('stopScanBtn'),
            barcodeScannerContainer: document.getElementById('barcodeScannerContainer'),
            scanResult: document.getElementById('scanResult'),

            // Image input elements
            cameraBtn: document.getElementById('cameraBtn'),
            galleryBtn: document.getElementById('galleryBtn'),
            cameraInput: document.getElementById('cameraInput'),
            galleryInput: document.getElementById('galleryInput'),
            imagePreviewContainer: document.getElementById('imagePreviewContainer'),
            imagePreviewList: document.getElementById('imagePreviewList'),

            // Action buttons
            processBtn: document.getElementById('processBtn'),
            clearBtn: document.getElementById('clearBtn'),
            saveBtn: document.getElementById('saveBtn'),
            exportBtn: document.getElementById('exportBtn'),
            rescanBtn: document.getElementById('rescanBtn'),

            // Status and loading
            status: document.getElementById('status'),
            loading: document.getElementById('loading'),

            // Form
            form: document.getElementById('productForm'),

            // Form fields
            nameInput: document.getElementById('name'),
            styleNumberInput: document.getElementById('style_number'),
            skuInput: document.getElementById('sku'),
            barcodeInput: document.getElementById('barcode'),
            quantityInput: document.getElementById('quantity'),
            brandNameInput: document.getElementById('brand_name'),
            productCategoryInput: document.getElementById('product_category'),
            retailPriceInput: document.getElementById('retail_price'),
            supplyPriceInput: document.getElementById('supply_price'),
            sizeInput: document.getElementById('size_or_dimensions'),
            colorInput: document.getElementById('color'),
            tagsInput: document.getElementById('tags'),
            descriptionInput: document.getElementById('description'),
            notesInput: document.getElementById('notes'),

            // Modals
            successModal: document.getElementById('successModal'),
            duplicateModal: document.getElementById('duplicateModal'),
            duplicateTitle: document.getElementById('duplicateTitle'),
            duplicateMessage: document.getElementById('duplicateMessage'),

            // Informational
            productCount: document.getElementById('productCount'),
            barcodeDupWarning: document.getElementById('barcodeDupWarning'),

            // Edit mode
            editModeIndicator: document.getElementById('editModeIndicator'),
            editModeText: document.getElementById('editModeText'),

            // User tracking
            currentUserLabel: document.getElementById('currentUserLabel')
        };
    }

    return elements;
}
