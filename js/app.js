/**
 * Main Application Entry Point
 * Initializes the app and wires all modules together
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { eventBus } from './events.js';
import { ensureAuthenticated } from './auth.js';
import { startBarcodeScanner, stopBarcodeScanner, captureBarcodeAndStop } from './barcode-scanner.js';
import { handleImageSelection, clearImages } from './image-handler.js';
import { extractProductData } from './ai-extraction.js';
import { setupSKUAutoGeneration, populateForm } from './form-manager.js';
import { saveProduct, exportData, fetchProductCount, checkBarcodeExists, fetchProductForEdit } from './database.js';
import { showStatus, closeModal, closeDuplicateModal } from './ui-utils.js';

/**
 * Returns a function that delays invoking fn until after wait ms have elapsed
 * since the last time it was called.
 */
function debounce(fn, wait) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}

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

    // Barcode pre-check: only fire after user stops typing, and only for complete barcodes
    const debouncedBarcodeCheck = debounce((value) => {
        if (/^\d{12,13}$/.test(value)) checkBarcodeExists(value);
    }, 500);
    dom.barcodeInput.addEventListener('input', () => {
        debouncedBarcodeCheck(dom.barcodeInput.value.trim());
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

        // Set the saved SKU directly — populateForm is now synchronous so this is safe
        if (product.sku) dom.skuInput.value = product.sku;

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
        const product = await fetchProductForEdit(state.duplicateProductId, barcode, sku);
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

/**
 * Authenticate silently then initialize the app.
 * Caches the Supabase Auth JWT in state so database.js can use it.
 */
async function startApp() {
    try {
        const session = await ensureAuthenticated();
        state.accessToken = session.access_token;
        state.user = session.user;
        initApp();

        // Proactively refresh the JWT every 55 minutes (tokens expire after 1 hour)
        setInterval(async () => {
            try {
                const refreshed = await ensureAuthenticated();
                state.accessToken = refreshed.access_token;
                state.user = refreshed.user;
            } catch (e) {
                console.error('Background token refresh failed:', e);
            }
        }, 55 * 60 * 1000);
    } catch (error) {
        console.error('Authentication failed:', error);
        const statusEl = document.getElementById('status');
        if (statusEl) {
            statusEl.textContent = '❌ Authentication failed. Please reload the page.';
            statusEl.className = 'status error';
            statusEl.style.display = 'block';
        }
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startApp);
} else {
    startApp();
}
