/**
 * Form Manager Module
 * Handles form population, validation, and SKU auto-generation
 */

import { getDOMElements } from './dom.js';
import { generateSKUFromForm } from './sku-generator.js';
import { showStatus } from './ui-utils.js';

/**
 * Populate form with extracted product data
 * @param {Object} data - Product data from AI extraction
 */
export function populateForm(data) {
    const dom = getDOMElements();

    dom.nameInput.value = data.name || '';

    // Map SKU data to style_number if present
    dom.styleNumberInput.value = data.style_number || data.sku || '';

    // Don't populate SKU yet - let it auto-generate from other fields

    // Only populate barcode if NOT scanned (scanned is authoritative)
    if (dom.barcodeInput.getAttribute('data-source') !== 'scanned') {
        dom.barcodeInput.value = data.barcode || '';
        // Always dispatch so the debounced duplicate check fires (clears stale warning when barcode is empty)
        dom.barcodeInput.dispatchEvent(new Event('input'));
    }

    dom.brandNameInput.value = data.brand_name || '';
    dom.productCategoryInput.value = data.product_category || '';
    dom.retailPriceInput.value = data.retail_price || 0;
    dom.supplyPriceInput.value = data.supply_price || '';
    dom.sizeInput.value = data.size_or_dimensions || '';
    dom.colorInput.value = data.color || '';
    dom.tagsInput.value = data.tags || '';
    dom.descriptionInput.value = data.description || '';
    dom.notesInput.value = data.notes || '';

    // Generate SKU — all fields are set synchronously above, so this runs immediately
    const generatedSKU = generateSKUFromForm();
    if (generatedSKU) {
        dom.skuInput.value = generatedSKU;
    }

    // Validate barcode length
    if (dom.barcodeInput.value && (dom.barcodeInput.value.length !== 12 && dom.barcodeInput.value.length !== 13)) {
        showStatus(`⚠️ Warning: Barcode has ${dom.barcodeInput.value.length} digits (should be 12 or 13). Use UPC scanner!`, 'error');
    }
}

/**
 * Setup SKU auto-generation listeners
 */
export function setupSKUAutoGeneration() {
    const fieldIds = ['style_number', 'brand_name', 'color', 'size_or_dimensions'];

    fieldIds.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            field.addEventListener('input', () => {
                const generatedSKU = generateSKUFromForm();
                const { skuInput } = getDOMElements();
                skuInput.value = generatedSKU;
            });
        }
    });
}

/**
 * Collect form data for saving
 * @returns {Object} Form data object
 */
export function collectFormData() {
    const dom = getDOMElements();

    const skuValue = dom.skuInput.value;
    const capitalizedSku = skuValue ? skuValue.toUpperCase() : null;

    return {
        name: dom.nameInput.value,
        style_number: dom.styleNumberInput.value || null,
        sku: capitalizedSku,
        barcode: dom.barcodeInput.value || null,
        brand_name: dom.brandNameInput.value || null,
        product_category: dom.productCategoryInput.value || null,
        retail_price: parseFloat(dom.retailPriceInput.value) || null,
        supply_price: parseFloat(dom.supplyPriceInput.value) || null,
        size_or_dimensions: dom.sizeInput.value || null,
        color: dom.colorInput.value || null,
        quantity: parseInt(dom.quantityInput.value) || 1,
        tags: dom.tagsInput.value || null,
        description: dom.descriptionInput.value || null,
        notes: dom.notesInput.value || null
    };
}
