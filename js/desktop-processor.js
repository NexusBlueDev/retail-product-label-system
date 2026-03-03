/**
 * Desktop Processor Module
 * Three-column workflow: queue sidebar → AI extraction → editable form
 * Processes photo_only products into fully completed records.
 */

import { SUPABASE_URL, SUPABASE_KEY, FUNCTION_URL } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { fetchPhotoOnlyProducts } from './database.js';
import { getSignedUrl, getSignedUrls, fetchImageAsBase64 } from './storage.js';
import { eventBus } from './events.js';

// ── Field mapping ────────────────────────────────────────────────────
// Maps AI extraction keys → processor form input IDs (p_ prefixed)
const FIELD_MAP = {
    name:              'p_name',
    style_number:      'p_style_number',
    sku:               'p_sku',
    barcode:           'p_barcode',
    brand_name:        'p_brand_name',
    product_category:  'p_product_category',
    retail_price:      'p_retail_price',
    supply_price:      'p_supply_price',
    size_or_dimensions:'p_size_or_dimensions',
    color:             'p_color',
    quantity:          'p_quantity',
    tags:              'p_tags',
    description:       'p_description',
    notes:             'p_notes'
};

const FIELD_LABELS = {
    name: 'Name', style_number: 'Style #', sku: 'SKU', barcode: 'Barcode',
    brand_name: 'Brand', product_category: 'Category', retail_price: 'Retail Price',
    supply_price: 'Supply Price', size_or_dimensions: 'Size', color: 'Color',
    quantity: 'Quantity', tags: 'Tags', description: 'Description', notes: 'Notes'
};

// ── Queue Management ─────────────────────────────────────────────────

/**
 * Load the photo-only queue and render it in the sidebar.
 * Queue items show ID + photo count. Thumbnails load progressively.
 */
async function loadQueue() {
    const dom = getDOMElements();
    dom.queueList.innerHTML = '<div class="queue-empty">Loading...</div>';

    const items = await fetchPhotoOnlyProducts();
    state.processorQueue = items;

    dom.processorQueueCount.textContent = `${items.length} item${items.length !== 1 ? 's' : ''} in queue`;

    if (items.length === 0) {
        dom.queueList.innerHTML = '<div class="queue-empty">No photo-only products to process</div>';
        return;
    }

    dom.queueList.innerHTML = '';
    items.forEach(item => {
        const el = document.createElement('div');
        el.className = 'queue-item';
        el.dataset.id = item.id;

        const imageCount = Array.isArray(item.image_urls) ? item.image_urls.length : 0;

        el.innerHTML = `
            <div class="queue-item-thumb">📷</div>
            <div class="queue-item-info">
                <div class="queue-item-name">ID: ${item.id}</div>
                <div class="queue-item-date">${imageCount} photo${imageCount !== 1 ? 's' : ''}</div>
            </div>
        `;

        el.addEventListener('click', () => selectQueueItem(item));
        dom.queueList.appendChild(el);

        // Load thumbnail from first image in background
        if (imageCount > 0 && item.image_urls[0].path) {
            getSignedUrl(item.image_urls[0].path).then(url => {
                const thumbDiv = el.querySelector('.queue-item-thumb');
                if (thumbDiv) {
                    thumbDiv.innerHTML = '';
                    const img = document.createElement('img');
                    img.src = url;
                    img.alt = `ID ${item.id}`;
                    img.className = 'queue-thumb-img';
                    thumbDiv.appendChild(img);
                }
            }).catch(() => { /* keep emoji fallback */ });
        }
    });
}

/**
 * Select a queue item: fetch signed URLs, display ALL photos, run AI extraction.
 */
async function selectQueueItem(item) {
    const dom = getDOMElements();

    // Highlight active item
    dom.queueList.querySelectorAll('.queue-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === String(item.id));
    });

    state.processorCurrentItem = item;
    state.processorAIData = null;

    // Reset form + AI panel
    dom.processorForm.reset();
    dom.processorAIResults.style.display = 'none';
    dom.aiResultFields.innerHTML = '';
    dom.processorSaveBtn.disabled = true;
    disableCopyButtons(true);

    // Pre-fill name from the record (Quick Capture may have extracted it)
    dom.pName.value = (item.name && item.name !== 'Processing...') ? item.name : '';

    // Load ALL photos for this product
    const paths = (item.image_urls || []).map(u => u.path);
    if (paths.length === 0) {
        dom.processorPhotos.innerHTML = '<p class="processor-placeholder">No images stored for this product</p>';
        return;
    }

    dom.processorPhotos.innerHTML = '<p class="processor-placeholder">Loading photos...</p>';

    try {
        const signedUrls = await getSignedUrls(paths);
        dom.processorPhotos.innerHTML = `
            <div class="processor-photo-count">${paths.length} photo${paths.length !== 1 ? 's' : ''} for ID: ${item.id}</div>
            ${signedUrls.map(url => `<img src="${url}" alt="Product photo">`).join('')}
        `;

        // Run AI extraction on ALL photos
        runAIExtraction(signedUrls);
    } catch (e) {
        dom.processorPhotos.innerHTML = '<p class="processor-placeholder">Failed to load photos</p>';
        console.error('selectQueueItem photo load error:', e);
    }
}

// ── AI Extraction ────────────────────────────────────────────────────

/**
 * Download images as base64 and send to the Edge Function for full extraction.
 * Sends ALL photos (same as original scanner) for comprehensive data capture.
 */
async function runAIExtraction(signedUrls) {
    const dom = getDOMElements();
    dom.processorAILoading.style.display = 'block';

    try {
        // Convert signed URLs to base64 (parallel)
        const base64Images = await Promise.all(
            signedUrls.map(url => fetchImageAsBase64(url))
        );

        // Send all images to Edge Function (parallel, same pattern as scanner)
        const responses = await Promise.all(
            base64Images.map((image, i) => fetch(FUNCTION_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${state.accessToken}`
                },
                body: JSON.stringify({
                    image,
                    imageNumber: i + 1,
                    totalImages: base64Images.length
                })
            }))
        );

        const results = await Promise.all(
            responses.map(async (r) => {
                if (!r.ok) return null;
                const text = await r.text();
                try { return JSON.parse(text); } catch { return null; }
            })
        );

        // Merge results (same strategy as ai-extraction.js)
        let merged = {};
        for (let i = 0; i < results.length; i++) {
            const result = results[i];
            if (!result || !result.success) continue;
            const data = result.data;
            if (i === 0) {
                merged = { ...data };
            } else {
                if (data.retail_price && data.retail_price > 0) merged.retail_price = data.retail_price;
                if (data.notes) {
                    merged.notes = merged.notes
                        ? `${merged.notes}; Additional: ${data.notes}`
                        : data.notes;
                }
            }
        }

        state.processorAIData = merged;
        dom.processorAILoading.style.display = 'none';

        // Display AI results in form-style input fields
        renderAIResults(merged);
        disableCopyButtons(false);
        dom.processorSaveBtn.disabled = false;

    } catch (e) {
        dom.processorAILoading.style.display = 'none';
        dom.processorAIResults.style.display = 'block';
        dom.aiResultFields.innerHTML = '<p style="color:#C62828;">AI extraction failed. You can enter data manually.</p>';
        dom.processorSaveBtn.disabled = false;
        console.error('AI extraction error:', e);
    }
}

/**
 * Render AI extraction results as read-only input fields.
 * These mirror the editable form on the right so the user can see
 * exactly what AI found and copy individual values.
 */
function renderAIResults(data) {
    const dom = getDOMElements();
    dom.processorAIResults.style.display = 'block';

    dom.aiResultFields.innerHTML = Object.entries(FIELD_LABELS).map(([key, label]) => {
        const value = data[key] ?? '';
        const isLong = key === 'description' || key === 'notes';
        const inputHtml = isLong
            ? `<textarea class="ai-field-input" data-ai-key="${key}" readonly>${value}</textarea>`
            : `<input type="text" class="ai-field-input" data-ai-key="${key}" value="${String(value).replace(/"/g, '&quot;')}" readonly>`;
        return `<div class="ai-field-row">
            <label class="ai-field-label">${label}</label>
            ${inputHtml}
        </div>`;
    }).join('');
}

// ── Copy Buttons ─────────────────────────────────────────────────────

/**
 * Enable/disable all copy buttons.
 */
function disableCopyButtons(disabled) {
    document.querySelectorAll('#processorForm .btn-copy-field').forEach(btn => {
        btn.disabled = disabled;
    });
    const copyAll = document.getElementById('copyAllBtn');
    if (copyAll) copyAll.disabled = disabled;
}

/**
 * Handle a single copy-field button click.
 * Reads from state.processorAIData, writes to the matching input.
 */
function handleCopyField(btn) {
    const fieldId = btn.dataset.field;
    const input = document.getElementById(fieldId);
    if (!input || !state.processorAIData) return;

    // Map p_fieldId back to AI data key
    const aiKey = fieldId.replace('p_', '');
    const value = state.processorAIData[aiKey];
    if (value === undefined || value === null) return;

    input.value = value;

    // Green flash feedback
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 600);
}

/**
 * Copy all AI fields to the form at once.
 */
function copyAllFields() {
    if (!state.processorAIData) return;

    Object.entries(FIELD_MAP).forEach(([aiKey, inputId]) => {
        const value = state.processorAIData[aiKey];
        if (value === undefined || value === null) return;
        const input = document.getElementById(inputId);
        if (input) input.value = value;
    });

    // Flash all copy buttons briefly
    document.querySelectorAll('#processorForm .btn-copy-field').forEach(btn => {
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 600);
    });
}

// ── Save & Skip ──────────────────────────────────────────────────────

/**
 * Collect processor form data and PATCH the product to status='complete'.
 */
async function saveAndComplete() {
    const dom = getDOMElements();
    const item = state.processorCurrentItem;
    if (!item) return;

    const name = dom.pName.value.trim();
    if (!name) {
        alert('Product name is required');
        return;
    }

    dom.processorSaveBtn.disabled = true;
    dom.processorSaveBtn.textContent = 'Saving...';

    const formData = {
        name,
        style_number: dom.pStyleNumber.value || null,
        sku: dom.pSku.value ? dom.pSku.value.toUpperCase() : null,
        barcode: dom.pBarcode.value || null,
        brand_name: dom.pBrandName.value || null,
        product_category: dom.pProductCategory.value || null,
        retail_price: parseFloat(dom.pRetailPrice.value) || null,
        supply_price: parseFloat(dom.pSupplyPrice.value) || null,
        size_or_dimensions: dom.pSizeOrDimensions.value || null,
        color: dom.pColor.value || null,
        quantity: parseInt(dom.pQuantity.value) || 1,
        tags: dom.pTags.value || null,
        description: dom.pDescription.value || null,
        notes: dom.pNotes.value || null,
        entered_by: state.currentUser || item.entered_by || null,
        status: 'complete'
    };

    try {
        const response = await fetch(
            `${SUPABASE_URL}/rest/v1/products?id=eq.${item.id}`,
            {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'apikey': SUPABASE_KEY,
                    'Authorization': `Bearer ${state.accessToken}`,
                    'Prefer': 'return=representation'
                },
                body: JSON.stringify(formData)
            }
        );

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.message || `Save failed (${response.status})`);
        }

        // Remove from queue and select next
        removeFromQueueAndAdvance(item.id);
        dom.processorSaveBtn.textContent = 'Save & Complete';

        eventBus.emit('processor:saved', { id: item.id });

    } catch (e) {
        alert(`Save failed: ${e.message}`);
        dom.processorSaveBtn.disabled = false;
        dom.processorSaveBtn.textContent = 'Save & Complete';
        console.error('Processor save error:', e);
    }
}

/**
 * Skip the current item without saving.
 */
function skipItem() {
    const item = state.processorCurrentItem;
    if (!item) return;

    // Move to next item in queue
    const idx = state.processorQueue.findIndex(q => q.id === item.id);
    const next = state.processorQueue[idx + 1] || state.processorQueue[0];

    if (next && next.id !== item.id) {
        selectQueueItem(next);
    } else {
        // Only one item — reset to placeholder
        resetProcessorView();
    }
}

/**
 * Remove completed item from queue UI and state, advance to next.
 */
function removeFromQueueAndAdvance(completedId) {
    const dom = getDOMElements();

    // Remove from state
    state.processorQueue = state.processorQueue.filter(q => q.id !== completedId);
    state.processorCurrentItem = null;
    state.processorAIData = null;

    // Remove from DOM
    const queueEl = dom.queueList.querySelector(`[data-id="${completedId}"]`);
    if (queueEl) queueEl.remove();

    // Update count
    dom.processorQueueCount.textContent = `${state.processorQueue.length} item${state.processorQueue.length !== 1 ? 's' : ''} in queue`;

    // Select next or show empty state
    if (state.processorQueue.length > 0) {
        selectQueueItem(state.processorQueue[0]);
    } else {
        resetProcessorView();
    }
}

/**
 * Reset the processor view to empty/placeholder state.
 */
function resetProcessorView() {
    const dom = getDOMElements();
    state.processorCurrentItem = null;
    state.processorAIData = null;

    dom.processorPhotos.innerHTML = '<p class="processor-placeholder">Select an item from the queue</p>';
    dom.processorAIResults.style.display = 'none';
    dom.aiResultFields.innerHTML = '';
    dom.processorForm.reset();
    dom.processorSaveBtn.disabled = true;
    disableCopyButtons(true);

    if (state.processorQueue.length === 0) {
        dom.queueList.innerHTML = '<div class="queue-empty">All items processed!</div>';
    }
}

// ── Initialization ───────────────────────────────────────────────────

/**
 * Initialize Desktop Processor event listeners.
 * Called once from app.js initApp().
 */
export function initDesktopProcessor() {
    const dom = getDOMElements();

    // Refresh queue button
    dom.refreshQueueBtn.addEventListener('click', loadQueue);

    // Save & Complete button
    dom.processorSaveBtn.addEventListener('click', saveAndComplete);

    // Skip button
    dom.processorSkipBtn.addEventListener('click', skipItem);

    // Delegated click handler for copy buttons
    dom.processorForm.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-copy-field');
        if (btn) handleCopyField(btn);
    });

    // Copy All button
    if (dom.copyAllBtn) {
        dom.copyAllBtn.addEventListener('click', copyAllFields);
    }

    // Load queue when processor view is shown
    eventBus.on('view:changed', ({ view }) => {
        if (view === 'processor') loadQueue();
    });
}

/**
 * Get the current photo-only queue count (for menu badge).
 * @returns {Promise<number>}
 */
export async function getPhotoOnlyCount() {
    try {
        const response = await fetch(
            `${SUPABASE_URL}/rest/v1/products?status=eq.photo_only&select=id`,
            {
                headers: {
                    'apikey': SUPABASE_KEY,
                    'Authorization': `Bearer ${state.accessToken}`,
                    'Prefer': 'count=exact',
                    'Range': '0-0'
                }
            }
        );
        const range = response.headers.get('content-range');
        return range ? parseInt(range.split('/')[1]) : 0;
    } catch {
        return 0;
    }
}
