/**
 * Database Module
 * Handles saving products and exporting data via Supabase REST API
 */

import { SUPABASE_URL, SUPABASE_KEY } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { collectFormData } from './form-manager.js';
import { eventBus } from './events.js';

/**
 * Fetch total product count from Supabase and update the UI counter
 */
export async function fetchProductCount() {
    const { productCount } = getDOMElements();
    if (!productCount) return;

    try {
        const response = await fetch(`${SUPABASE_URL}/rest/v1/products?select=id`, {
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`,
                'Prefer': 'count=exact',
                'Range': '0-0'
            }
        });
        const range = response.headers.get('content-range'); // e.g. "0-0/47"
        const total = range ? parseInt(range.split('/')[1]) : 0;
        productCount.textContent = total > 0 ? `📦 ${total} products in database` : '';
    } catch {
        // Silently fail — count is non-critical
    }
}

/**
 * Check if a barcode already exists in the database
 * Shows a warning in the UI if found, clears warning if not
 * @param {string} barcode
 */
export async function checkBarcodeExists(barcode) {
    const { barcodeDupWarning } = getDOMElements();
    if (!barcodeDupWarning) return;

    // Skip check when editing (own barcode would trigger false positive)
    if (state.editingId) return;

    if (!barcode || (barcode.length !== 12 && barcode.length !== 13)) {
        barcodeDupWarning.style.display = 'none';
        barcodeDupWarning.textContent = '';
        return;
    }

    try {
        const response = await fetch(
            `${SUPABASE_URL}/rest/v1/products?barcode=eq.${barcode}&select=name,id`,
            {
                headers: {
                    'apikey': SUPABASE_KEY,
                    'Authorization': `Bearer ${SUPABASE_KEY}`
                }
            }
        );
        const data = await response.json();
        if (data && data.length > 0) {
            state.duplicateProductId = data[0].id;
            barcodeDupWarning.textContent = `⚠️ Already in database: ${data[0].name || 'Unknown product'} (ID: ${data[0].id})`;
            barcodeDupWarning.style.display = 'block';
        } else {
            state.duplicateProductId = null;
            barcodeDupWarning.style.display = 'none';
            barcodeDupWarning.textContent = '';
        }
    } catch {
        // Silently fail — pre-check is non-critical
    }
}

/**
 * Save product to Supabase
 */
export async function saveProduct() {
    const { saveBtn, form, imagePreviewList, imagePreviewContainer, cameraInput, galleryInput, successModal, duplicateModal, duplicateTitle, duplicateMessage } = getDOMElements();

    const formData = collectFormData();

    if (!formData.name) {
        showStatus('Product name is required!', 'error');
        return;
    }

    saveBtn.disabled = true;
    const isEditing = !!state.editingId;
    showStatus(isEditing ? 'Updating...' : 'Saving...', 'info');

    console.log(isEditing ? `Updating product ID ${state.editingId}:` : 'Saving product:', formData);

    try {
        const url = isEditing
            ? `${SUPABASE_URL}/rest/v1/products?id=eq.${state.editingId}`
            : `${SUPABASE_URL}/rest/v1/products`;

        const response = await fetch(url, {
            method: isEditing ? 'PATCH' : 'POST',
            headers: {
                'Content-Type': 'application/json',
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`,
                'Prefer': 'return=representation'
            },
            body: JSON.stringify(formData)
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const errorData = await response.json();
            console.error('Error response:', errorData);

            // Supabase returns errors in different formats
            const errorMsg = errorData.message || errorData.error || errorData.hint || JSON.stringify(errorData);
            throw new Error(errorMsg);
        }

        const savedData = await response.json();
        console.log(isEditing ? 'Successfully updated product:' : 'Successfully saved product:', savedData);

        const dom = getDOMElements();

        if (isEditing) {
            // Update mode: show status, clear edit mode, reset form
            showStatus(`✅ Product updated! (ID: ${state.editingId})`, 'success');
            state.editingId = null;
            state.lastSavedProduct = null;
            dom.editModeIndicator.style.display = 'none';
            dom.editModeText.textContent = '';
            saveBtn.textContent = 'Save Product';
        } else {
            // Create mode: store saved product, show success modal
            state.lastSavedProduct = savedData[0];
            showStatus(`✅ Product saved successfully! (ID: ${savedData[0]?.id || 'N/A'})`, 'success');
            setTimeout(() => {
                successModal.classList.add('show');
            }, 500);
        }

        // Clear form and reset
        form.reset();
        dom.barcodeInput.removeAttribute('data-source');
        dom.barcodeDupWarning.style.display = 'none';
        dom.barcodeDupWarning.textContent = '';
        imagePreviewList.innerHTML = '';
        imagePreviewContainer.style.display = 'none';
        cameraInput.value = '';
        galleryInput.value = '';
        saveBtn.disabled = true;
        state.currentImages = [];
        state.extractedData = null;

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });

        fetchProductCount();
        eventBus.emit('product:saved', { product: savedData[0] });

    } catch (error) {
        console.error('Save error details:', error);

        // Parse the error response
        let errorMessage = error.message || '';

        // Check for duplicate errors (Postgres returns different error formats)
        if (errorMessage.toLowerCase().includes('duplicate') ||
            errorMessage.toLowerCase().includes('unique') ||
            errorMessage.includes('23505')) {  // Postgres unique violation error code

            // Set modal message based on which field is duplicate
            let duplicateField = 'This product';
            if (errorMessage.toLowerCase().includes('sku') || errorMessage.includes('unique_sku')) {
                duplicateField = 'A product with this SKU';
            } else if (errorMessage.toLowerCase().includes('barcode') || errorMessage.includes('unique_barcode')) {
                duplicateField = 'A product with this barcode';
            }

            // Update duplicate modal content
            duplicateTitle.textContent = 'Duplicate Product!';
            duplicateMessage.textContent = `${duplicateField} already exists in the database`;

            // Show duplicate modal
            setTimeout(() => {
                duplicateModal.classList.add('show');
            }, 500);

        } else if (errorMessage.includes('violates')) {
            showStatus(`⚠️ DATABASE ERROR: ${errorMessage}`, 'error');
        } else {
            showStatus(`❌ SAVE ERROR: ${errorMessage}`, 'error');
        }

        saveBtn.disabled = false;
    }
}

/**
 * Fetch a full product record for editing, by barcode or SKU
 * @param {string} barcode
 * @param {string} sku
 * @returns {Object|null} Full product object or null if not found
 */
export async function fetchProductForEdit(productId, barcode, sku) {
    const headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': `Bearer ${SUPABASE_KEY}`
    };

    const query = (param, value) =>
        fetch(`${SUPABASE_URL}/rest/v1/products?${param}=eq.${value}&select=*`, { headers })
            .then(r => r.json());

    try {
        // Fire all available lookups in parallel instead of sequentially
        const [byId, byBarcode, bySku] = await Promise.all([
            productId ? query('id', productId) : null,
            barcode   ? query('barcode', barcode) : null,
            sku       ? query('sku', sku) : null,
        ]);

        if (byId     && byId.length > 0)     return byId[0];
        if (byBarcode && byBarcode.length > 0) return byBarcode[0];
        if (bySku    && bySku.length > 0)    return bySku[0];
    } catch (e) {
        console.error('fetchProductForEdit error:', e);
    }

    return null;
}

/**
 * Export all products to CSV
 */
export async function exportData() {
    showStatus('Fetching products...', 'info');

    try {
        const PAGE_SIZE = 500;
        let data = [];
        let page = 0;
        let hasMore = true;

        while (hasMore) {
            const offset = page * PAGE_SIZE;
            const response = await fetch(
                `${SUPABASE_URL}/rest/v1/products?select=*&order=id&offset=${offset}&limit=${PAGE_SIZE}`,
                {
                    headers: {
                        'apikey': SUPABASE_KEY,
                        'Authorization': `Bearer ${SUPABASE_KEY}`
                    }
                }
            );

            if (!response.ok) throw new Error('Failed to fetch products');

            const batch = await response.json();
            data = data.concat(batch);
            hasMore = batch.length === PAGE_SIZE;
            page++;

            if (hasMore) showStatus(`Fetching products... (${data.length} loaded)`, 'info');
        }

        if (data.length === 0) {
            showStatus('No products to export', 'error');
            return;
        }

        // Create CSV with ALL fields
        const headers = [
            'ID',
            'Created At',
            'Updated At',
            'Item Name',
            'Style Number',
            'SKU',
            'Barcode',
            'Brand',
            'Category',
            'Retail Price',
            'Supply Price',
            'Size',
            'Color',
            'Quantity',
            'Tags',
            'Description',
            'Notes',
            'Verified'
        ];

        const csvRows = [headers.join(',')];

        data.forEach(product => {
            const row = [
                product.id,
                product.created_at,
                product.updated_at,
                `"${(product.name || '').replace(/"/g, '""')}"`,
                `"${(product.style_number || '').replace(/"/g, '""')}"`,
                `"${(product.sku || '').replace(/"/g, '""')}"`,
                `"${(product.barcode || '').replace(/"/g, '""')}"`,
                `"${(product.brand_name || '').replace(/"/g, '""')}"`,
                `"${(product.product_category || '').replace(/"/g, '""')}"`,
                product.retail_price || '',
                product.supply_price || '',
                `"${(product.size_or_dimensions || '').replace(/"/g, '""')}"`,
                `"${(product.color || '').replace(/"/g, '""')}"`,
                product.quantity || 1,
                `"${(product.tags || '').replace(/"/g, '""')}"`,
                `"${(product.description || '').replace(/"/g, '""')}"`,
                `"${(product.notes || '').replace(/"/g, '""')}"`,
                product.verified || false
            ];
            csvRows.push(row.join(','));
        });

        const csv = csvRows.join('\n');

        // Download CSV
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `products-${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        showStatus(`✓ Exported ${data.length} products to CSV`, 'success');

    } catch (error) {
        showStatus(`Export failed: ${error.message}`, 'error');
        console.error('Export error:', error);
    }
}
