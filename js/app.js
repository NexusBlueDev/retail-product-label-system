/**
 * Main Application Entry Point
 * Initializes the app and wires all modules together
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { eventBus } from './events.js';
import { startBarcodeScanner, stopBarcodeScanner, captureBarcodeAndStop } from './barcode-scanner.js';
import { handleImageSelection, clearImages } from './image-handler.js';
import { extractProductData } from './ai-extraction.js';
import { setupSKUAutoGeneration } from './form-manager.js';
import { saveProduct, exportData } from './database.js';
import { showStatus, closeModal, closeDuplicateModal } from './ui-utils.js';

/**
 * Initialize all event listeners
 */
function initEventListeners() {
    const dom = getDOMElements();

    // Barcode scanner events
    dom.scanBarcodeBtn.addEventListener('click', startBarcodeScanner);
    dom.captureBarcodeBtn.addEventListener('click', captureBarcodeAndStop);
    dom.stopScanBtn.addEventListener('click', stopBarcodeScanner);

    // Image selection events
    dom.cameraBtn.addEventListener('click', () => {
        dom.cameraInput.click();
    });

    dom.galleryBtn.addEventListener('click', () => {
        dom.galleryInput.click();
    });

    dom.cameraInput.addEventListener('change', handleImageSelection);
    dom.galleryInput.addEventListener('change', handleImageSelection);

    // Process images with AI
    dom.processBtn.addEventListener('click', async () => {
        if (state.currentImages.length === 0) {
            showStatus('Please select images first', 'error');
            return;
        }

        dom.processBtn.disabled = true;
        showStatus(`Processing ${state.currentImages.length} image(s) with AI...`, 'info');

        const base64Images = state.currentImages.map(img => img.base64);
        await extractProductData(base64Images);

        dom.processBtn.disabled = false;
    });

    // Clear images
    dom.clearBtn.addEventListener('click', clearImages);

    // Save product
    dom.saveBtn.addEventListener('click', saveProduct);

    // Export to CSV
    dom.exportBtn.addEventListener('click', exportData);

    // Rescan images
    dom.rescanBtn.addEventListener('click', async () => {
        if (state.currentImages.length > 0) {
            dom.rescanBtn.disabled = true;
            showStatus('Rescanning images...', 'info');
            const base64Images = state.currentImages.map(img => img.base64);
            await extractProductData(base64Images);
            dom.rescanBtn.disabled = false;
        }
    });

    // Modal close handlers
    window.closeModal = closeModal;
    window.closeDuplicateModal = closeDuplicateModal;
}

/**
 * Initialize event bus listeners
 */
function initEventBusListeners() {
    // When barcode is scanned, it's already handled in barcode-scanner.js
    // We just listen here for any additional actions needed
    eventBus.on('barcode:scanned', ({ code }) => {
        console.log('Barcode scanned:', code);
    });

    eventBus.on('images:selected', ({ count }) => {
        console.log(`${count} images selected`);
    });

    eventBus.on('extraction:complete', ({ data }) => {
        console.log('Extraction complete:', data);
    });

    eventBus.on('product:saved', ({ product }) => {
        console.log('Product saved:', product);
    });
}

/**
 * Initialize the application
 */
function initApp() {
    // Pre-cache DOM elements
    getDOMElements();

    // Setup SKU auto-generation
    setupSKUAutoGeneration();

    // Initialize event listeners
    initEventListeners();

    // Initialize event bus listeners
    initEventBusListeners();

    console.log('✅ App initialized with modular architecture');
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
