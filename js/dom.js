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
            currentUserLabel: document.getElementById('currentUserLabel'),

            // Menu view
            menuUserLabel: document.getElementById('menuUserLabel'),
            menuProcessBadge: document.getElementById('menuProcessBadge'),

            // Quick Capture view
            captureUserLabel: document.getElementById('captureUserLabel'),
            captureCameraBtn: document.getElementById('captureCameraBtn'),
            captureGalleryBtn: document.getElementById('captureGalleryBtn'),
            captureCameraInput: document.getElementById('captureCameraInput'),
            captureGalleryInput: document.getElementById('captureGalleryInput'),
            captureDropZone: document.getElementById('captureDropZone'),
            captureLoading: document.getElementById('captureLoading'),
            captureStatus: document.getElementById('captureStatus'),
            captureSessionCount: document.getElementById('captureSessionCount'),
            recentCaptures: document.getElementById('recentCaptures'),
            recentCapturesList: document.getElementById('recentCapturesList'),

            // Desktop Processor view
            processorQueueCount: document.getElementById('processorQueueCount'),
            refreshQueueBtn: document.getElementById('refreshQueueBtn'),
            queueList: document.getElementById('queueList'),
            processorPhotos: document.getElementById('processorPhotos'),
            processorAIResults: document.getElementById('processorAIResults'),
            aiResultFields: document.getElementById('aiResultFields'),
            processorAILoading: document.getElementById('processorAILoading'),
            processorForm: document.getElementById('processorForm'),
            processorSaveBtn: document.getElementById('processorSaveBtn'),
            processorSkipBtn: document.getElementById('processorSkipBtn'),

            // Processor form fields (p_ prefixed)
            pName: document.getElementById('p_name'),
            pStyleNumber: document.getElementById('p_style_number'),
            pSku: document.getElementById('p_sku'),
            pBarcode: document.getElementById('p_barcode'),
            pBrandName: document.getElementById('p_brand_name'),
            pProductCategory: document.getElementById('p_product_category'),
            pRetailPrice: document.getElementById('p_retail_price'),
            pSupplyPrice: document.getElementById('p_supply_price'),
            pSizeOrDimensions: document.getElementById('p_size_or_dimensions'),
            pColor: document.getElementById('p_color'),
            pQuantity: document.getElementById('p_quantity'),
            pTags: document.getElementById('p_tags'),
            pDescription: document.getElementById('p_description'),
            pNotes: document.getElementById('p_notes')
        };
    }

    return elements;
}
