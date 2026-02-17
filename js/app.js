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
import { setupSKUAutoGeneration, populateForm } from './form-manager.js';
import { saveProduct, exportData, fetchProductCount, checkBarcodeExists, fetchProductForEdit } from './database.js';
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

    // Barcode pre-check: warn if barcode already exists in database
    dom.barcodeInput.addEventListener('input', () => {
        checkBarcodeExists(dom.barcodeInput.value.trim());
    });

    // Modal close handlers
    window.closeModal = closeModal;
    window.closeDuplicateModal = closeDuplicateModal;

    // Edit last saved product
    window.editLastSaved = () => {
        const product = state.lastSavedProduct;
        if (!product) return;

        // Close success modal
        closeModal();

        // Populate form fields
        populateForm(product);

        // Manually set fields populateForm doesn't cover
        dom.quantityInput.value = product.quantity || 1;
        dom.barcodeInput.value = product.barcode || '';
        dom.barcodeInput.removeAttribute('data-source');

        // Set the saved SKU directly (don't let auto-generate overwrite it)
        setTimeout(() => {
            if (product.sku) dom.skuInput.value = product.sku;
        }, 150);

        // Enter edit mode
        state.editingId = product.id;
        dom.editModeIndicator.style.display = 'block';
        dom.editModeText.textContent = product.name || `ID ${product.id}`;
        dom.saveBtn.textContent = 'Update Product';
        dom.saveBtn.disabled = false;

        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Cancel edit mode
    window.cancelEdit = () => {
        state.editingId = null;
        state.lastSavedProduct = null;
        dom.form.reset();
        dom.barcodeInput.removeAttribute('data-source');
        dom.editModeIndicator.style.display = 'none';
        dom.editModeText.textContent = '';
        dom.saveBtn.textContent = 'Save Product';
        dom.saveBtn.disabled = true;
    };

    // Edit the existing product that caused a duplicate error
    window.editDuplicateProduct = async () => {
        closeDuplicateModal();
        const barcode = dom.barcodeInput.value.trim();
        const sku = dom.skuInput.value.trim();
        showStatus('Loading existing product...', 'info');
        const product = await fetchProductForEdit(barcode, sku);
        if (product) {
            state.lastSavedProduct = product;
            window.editLastSaved();
        } else {
            showStatus('Could not find existing product', 'error');
        }
    };
}

/**
 * Initialize event bus listeners
 */
function initEventBusListeners() {
    // When barcode is scanned, it's already handled in barcode-scanner.js
    // We just listen here for any additional actions needed
    eventBus.on('barcode:scanned', ({ code }) => {
        console.log('Barcode scanned:', code);
        checkBarcodeExists(code);
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

    // Load product count on startup
    fetchProductCount();

    console.log('✅ App initialized with modular architecture');
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
