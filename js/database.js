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
 * Save product to Supabase
 */
export async function saveProduct() {
    const { saveBtn, form, imagePreviewList, imagePreviewContainer, cameraInput, galleryInput, status, successModal, duplicateModal, duplicateTitle, duplicateMessage } = getDOMElements();

    const formData = collectFormData();

    if (!formData.name) {
        showStatus('Product name is required!', 'error');
        return;
    }

    saveBtn.disabled = true;
    showStatus('Saving...', 'info');

    console.log('Saving product with data:', formData);

    try {
        const response = await fetch(`${SUPABASE_URL}/rest/v1/products`, {
            method: 'POST',
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
        console.log('Successfully saved product:', savedData);

        // Show success status message
        showStatus(`✅ Product saved successfully! (ID: ${savedData[0]?.id || 'N/A'})`, 'success');

        // Show success modal after 500ms
        setTimeout(() => {
            successModal.classList.add('show');
        }, 500);

        // Clear form and reset
        form.reset();
        imagePreviewList.innerHTML = '';
        imagePreviewContainer.style.display = 'none';
        cameraInput.value = '';
        galleryInput.value = '';
        saveBtn.disabled = true;
        state.currentImages = [];
        state.extractedData = null;

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });

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
 * Export all products to CSV
 */
export async function exportData() {
    showStatus('Fetching products...', 'info');

    try {
        const response = await fetch(`${SUPABASE_URL}/rest/v1/products?select=*&order=created_at.desc`, {
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to fetch products');
        }

        const data = await response.json();

        if (!data || data.length === 0) {
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
