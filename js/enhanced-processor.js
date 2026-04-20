/**
 * Enhanced Processor Module
 * Same photo_only queue as Desktop Processor, but with:
 *  - Lightspeed catalog lookup (barcode → LS product data)
 *  - Expanded normalization (size splitting, supplier codes, gender, color codes)
 *  - Three-source display: AI (blue) | Lightspeed (green) | Editable Form (white)
 *  - New derived fields saved to products table
 *
 * Saves with status='enhanced_complete' to avoid interfering with existing processor.
 */

import { SUPABASE_URL, SUPABASE_KEY, FUNCTION_URL, LS_UPSERT_URL } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { fetchPhotoOnlyProducts } from './database.js';
import { getSignedUrl, getSignedUrls, fetchImageAsBase64 } from './storage.js';
import { eventBus } from './events.js';
import { postProcessExtraction } from './form-manager.js';
import { getSupplierCode, getGenderCode, getColorCode, parseSize, generateSKU, sanitizeStyleNumber } from './sku-generator.js';
import { CATEGORY_LIST, SUPPLIER_CODE_TO_NAME, SUPPLIER_NAME_TO_CODE } from './reference-data.js';

// ── Field mapping ────────────────────────────────────────────────────
// Maps AI extraction keys → enhanced processor form input IDs (ep_ prefixed)
const EP_FIELD_MAP = {
    name:              'ep_name',
    style_number:      'ep_style_number',
    sku:               'ep_sku',
    barcode:           'ep_barcode',
    brand_name:        'ep_brand_name',
    supplier_name:     'ep_supplier_name',
    product_category:  'ep_product_category',
    retail_price:      'ep_retail_price',
    supply_price:      'ep_supply_price',
    size_or_dimensions:'ep_size_or_dimensions',
    color:             'ep_color',
    quantity:          'ep_quantity',
    tags:              'ep_tags',
    description:       'ep_description',
    notes:             'ep_notes'
};

// Maps Lightspeed index fields → AI extraction field names for comparison
const LS_TO_AI = {
    name:         'name',
    brand:        'brand_name',
    category:     'product_category',
    retail_price: 'retail_price',
    supply_price: 'supply_price',
    supplier:     'supplier'
};

// Track which source populated each form field
let dataSource = {};

// ── Queue Management ─────────────────────────────────────────────────

async function loadQueue() {
    const dom = getDOMElements();
    dom.epQueueList.innerHTML = '<div class="queue-empty">Loading...</div>';

    const items = await fetchPhotoOnlyProducts();
    state.epQueue = items;

    dom.epQueueCount.textContent = `${items.length} item${items.length !== 1 ? 's' : ''} in queue`;

    if (items.length === 0) {
        dom.epQueueList.innerHTML = '<div class="queue-empty">No photo-only products to process</div>';
        return;
    }

    dom.epQueueList.innerHTML = '';
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
        dom.epQueueList.appendChild(el);

        // Load thumbnail
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
            }).catch(() => {});
        }
    });
}

// ── Queue Item Selection ─────────────────────────────────────────────

async function selectQueueItem(item) {
    const dom = getDOMElements();

    // Highlight active
    dom.epQueueList.querySelectorAll('.queue-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === String(item.id));
    });

    state.epCurrentItem = item;
    state.epAIData = null;
    state.epLightspeedData = null;
    dataSource = {};

    // Reset
    dom.epForm.reset();
    clearAllFields();
    dom.epAIResults.style.display = 'none';
    dom.epLightspeedPanel.style.display = 'none';
    dom.epDerivedFields.style.display = 'none';
    dom.epSaveBtn.disabled = true;
    dom.epCopyAllBtn.disabled = true;

    // Load photos
    const paths = (item.image_urls || []).map(u => u.path);
    if (paths.length === 0) {
        dom.epPhotos.innerHTML = '<p class="processor-placeholder">No images stored for this product</p>';
        return;
    }

    dom.epPhotos.innerHTML = '<p class="processor-placeholder">Loading photos...</p>';

    // Check for cached AI extraction
    const hasCache = item.ai_cache && Object.keys(item.ai_cache).length > 0;
    if (hasCache) {
        processAIData(item.ai_cache);
    }

    try {
        const signedUrls = await getSignedUrls(paths);
        dom.epPhotos.innerHTML = `
            <div class="processor-photo-count">${paths.length} photo${paths.length !== 1 ? 's' : ''} for ID: ${item.id}</div>
            ${signedUrls.map(url => `<img src="${url}" alt="Product photo">`).join('')}
        `;

        if (!hasCache) {
            runAIExtraction(signedUrls);
        }
    } catch (e) {
        dom.epPhotos.innerHTML = '<p class="processor-placeholder">Failed to load photos</p>';
        console.error('Enhanced processor photo load error:', e);
    }
}

// ── AI Extraction ────────────────────────────────────────────────────

async function runAIExtraction(signedUrls) {
    const dom = getDOMElements();
    dom.epAILoading.style.display = 'block';

    try {
        const base64Images = await Promise.all(
            signedUrls.map(url => fetchImageAsBase64(url))
        );

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

        // Merge (same strategy as desktop processor)
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

        dom.epAILoading.style.display = 'none';
        processAIData(merged);

    } catch (e) {
        dom.epAILoading.style.display = 'none';
        console.error('Enhanced processor AI extraction error:', e);
        dom.epSaveBtn.disabled = false;
    }
}

// ── Enhanced Post-Processing ─────────────────────────────────────────

/**
 * Take raw AI data, run normalization, derive fields, look up Lightspeed.
 */
function processAIData(rawData) {
    const dom = getDOMElements();

    // 1. Run existing normalization (brand fix, tag fix, category fix, etc.)
    const data = postProcessExtraction({ ...rawData });

    // 2. Derive new fields
    const supplierCode = getSupplierCode(data.brand_name);
    const gender = getGenderCode(data.tags);
    const colorCode = getColorCode(data.color);
    const sizeParsed = parseSize(data.size_or_dimensions, data.product_category);
    const sku = generateSKU(data.style_number, data.brand_name, data.color, data.size_or_dimensions, data.tags, data.product_category);

    // Derive supplier name from supplier code
    const supplierName = SUPPLIER_CODE_TO_NAME[supplierCode] || '';

    // Attach derived fields to AI data
    data.sku = sku;
    data.supplier_name = supplierName;
    state.epAIData = {
        ...data,
        _derived: {
            supplier_code: supplierCode,
            supplier_name: supplierName,
            gender: gender,
            color_code: colorCode,
            size_value: sizeParsed.sizeValue,
            width_length: sizeParsed.widthLengthType,
            width_length_value: sizeParsed.widthLengthValue,
            sku: sku
        }
    };

    // 3. Populate AI fields (blue column)
    populateAIFields(state.epAIData);
    populateDerivedFields(state.epAIData._derived);

    dom.epAIResults.style.display = 'block';
    dom.epDerivedFields.style.display = 'block';
    dom.epSaveBtn.disabled = false;
    dom.epCopyAllBtn.disabled = false;

    // 4. Look up in Lightspeed
    lookupLightspeed(data.barcode, data.style_number);
}

// ── Lightspeed Lookup ────────────────────────────────────────────────

async function lookupLightspeed(barcode, styleNumber) {
    const dom = getDOMElements();
    state.epLightspeedData = null;

    let match = null;

    // Try barcode first (most reliable)
    if (barcode && /^\d{12,13}$/.test(barcode)) {
        try {
            const response = await fetch(
                `${SUPABASE_URL}/rest/v1/lightspeed_index?barcode=eq.${barcode}&limit=1`,
                {
                    headers: {
                        'apikey': SUPABASE_KEY,
                        'Authorization': `Bearer ${state.accessToken}`
                    }
                }
            );
            const results = await response.json();
            if (results && results.length > 0) match = results[0];
        } catch (e) {
            console.error('LS barcode lookup error:', e);
        }
    }

    // Fallback: try style number as SKU search
    if (!match && styleNumber && styleNumber.length >= 4) {
        try {
            const response = await fetch(
                `${SUPABASE_URL}/rest/v1/lightspeed_index?sku=ilike.*${encodeURIComponent(styleNumber)}*&limit=3`,
                {
                    headers: {
                        'apikey': SUPABASE_KEY,
                        'Authorization': `Bearer ${state.accessToken}`
                    }
                }
            );
            const results = await response.json();
            if (results && results.length > 0) match = results[0];
        } catch (e) {
            console.error('LS style lookup error:', e);
        }
    }

    if (match) {
        state.epLightspeedData = match;
        populateLSFields(match);
        showLightspeedPanel(match);
    } else {
        dom.epLightspeedPanel.style.display = 'none';
        clearLSFields();
    }
}

// ── Field Population ─────────────────────────────────────────────────

function populateAIFields(data) {
    const view = document.getElementById('enhancedProcessorView');
    if (!view) return;
    view.querySelectorAll('[data-ep-ai]').forEach(input => {
        const key = input.dataset.epAi;
        const value = data[key] ?? '';
        input.value = value;
    });
}

function populateLSFields(lsData) {
    const view = document.getElementById('enhancedProcessorView');
    if (!view) return;
    const fieldMap = {
        name: lsData.name || '',
        brand_name: lsData.brand || '',
        supplier_name: lsData.supplier || '',
        product_category: lsData.category || '',
        retail_price: lsData.retail_price || '',
        supply_price: lsData.supply_price || '',
        description: ''
    };

    // Extract variant options into fields
    const vo = lsData.variant_options || {};
    if (vo.Size) fieldMap.size_or_dimensions = vo.Size;
    if (vo.Color) fieldMap.color = vo.Color;

    view.querySelectorAll('[data-ep-ls]').forEach(input => {
        const key = input.dataset.epLs;
        const value = fieldMap[key] ?? '';
        input.value = value;
    });
}

function populateDerivedFields(derived) {
    const dom = getDOMElements();
    const fields = {
        ep_supplier_code: derived.supplier_code,
        ep_gender: derived.gender,
        ep_size_value: derived.size_value,
        ep_width_length: derived.width_length,
        ep_width_length_value: derived.width_length_value,
        ep_color_code: derived.color_code,
        ep_sku_generated: derived.sku
    };
    Object.entries(fields).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) el.value = val || '';
    });
}

function showLightspeedPanel(lsData) {
    const dom = getDOMElements();
    dom.epLightspeedPanel.style.display = 'block';

    const vo = lsData.variant_options || {};
    const variantStr = Object.entries(vo).map(([k, v]) => `${k}: ${v}`).join(' | ');

    dom.epLightspeedDetails.innerHTML = `
        <strong>${lsData.name || 'Unknown'}</strong>
        ${lsData.variant_name ? `<br>Variant: ${lsData.variant_name}` : ''}
        <br>Brand: ${lsData.brand || '—'} | Category: ${lsData.category || '—'}
        <br>Supplier: ${lsData.supplier || '—'}
        ${lsData.retail_price ? `<br>Price: $${Number(lsData.retail_price).toFixed(2)}` : ''}
        ${variantStr ? `<br>Options: ${variantStr}` : ''}
    `;
}

function clearAllFields() {
    const view = document.getElementById('enhancedProcessorView');
    if (!view) return;
    view.querySelectorAll('[data-ep-ai]').forEach(i => { i.value = ''; });
    view.querySelectorAll('[data-ep-ls]').forEach(i => { i.value = ''; });
    ['ep_supplier_code', 'ep_supplier_name', 'ep_gender', 'ep_size_value', 'ep_width_length',
     'ep_width_length_value', 'ep_color_code', 'ep_sku_generated', 'ep_lightspeed_product_id'
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
}

function clearLSFields() {
    const view = document.getElementById('enhancedProcessorView');
    if (!view) return;
    view.querySelectorAll('[data-ep-ls]').forEach(i => { i.value = ''; });
}

// ── Copy / Auto-fill ─────────────────────────────────────────────────

/**
 * Auto-fill form from best available source: LS wins > AI wins > empty.
 */
function copyAllFields() {
    const ai = state.epAIData || {};
    const ls = state.epLightspeedData;
    dataSource = {};

    // Map LS fields to AI field names for priority comparison
    const lsValues = {};
    if (ls) {
        lsValues.name = ls.name;
        lsValues.brand_name = ls.brand;
        lsValues.supplier_name = ls.supplier;
        lsValues.product_category = ls.category;
        lsValues.retail_price = ls.retail_price;
        lsValues.supply_price = ls.supply_price;
        const vo = ls.variant_options || {};
        if (vo.Size) lsValues.size_or_dimensions = vo.Size;
        if (vo.Color) lsValues.color = vo.Color;
    }

    Object.entries(EP_FIELD_MAP).forEach(([aiKey, inputId]) => {
        const input = document.getElementById(inputId);
        if (!input) return;

        const lsVal = lsValues[aiKey];
        const aiVal = ai[aiKey];

        if (lsVal !== undefined && lsVal !== null && lsVal !== '') {
            input.value = lsVal;
            dataSource[aiKey] = 'lightspeed';
        } else if (aiVal !== undefined && aiVal !== null && aiVal !== '') {
            input.value = aiVal;
            dataSource[aiKey] = 'ai';
        }
    });

    // Also fill SKU from derived
    const skuInput = document.getElementById('ep_sku');
    if (skuInput && ai._derived && ai._derived.sku) {
        skuInput.value = ai._derived.sku;
        dataSource.sku = 'ai';
    }

    // Fill lightspeed_product_id if we have a match
    if (ls) {
        const lsIdInput = document.getElementById('ep_lightspeed_product_id');
        if (lsIdInput) lsIdInput.value = ls.lightspeed_id;
    }
}

// ── Save & Skip ──────────────────────────────────────────────────────

async function saveAndComplete() {
    const dom = getDOMElements();
    const item = state.epCurrentItem;
    if (!item) return;

    const nameInput = document.getElementById('ep_name');
    const name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
        alert('Product name is required');
        return;
    }

    dom.epSaveBtn.disabled = true;
    dom.epSaveBtn.textContent = 'Saving...';

    const getVal = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() || null : null;
    };

    // Capture the existing LS ID from the form before building formData.
    // lightspeed_product_id is excluded from the first PATCH and handled
    // after the LS upsert resolves — avoids a race between two concurrent PATCHes.
    const existingLsId = getVal('ep_lightspeed_product_id');

    const formData = {
        name,
        style_number: sanitizeStyleNumber(getVal('ep_style_number')),
        sku: getVal('ep_sku') ? getVal('ep_sku').toUpperCase() : null,
        barcode: getVal('ep_barcode'),
        brand_name: getVal('ep_brand_name'),
        product_category: getVal('ep_product_category'),
        retail_price: parseFloat(getVal('ep_retail_price')) || null,
        supply_price: parseFloat(getVal('ep_supply_price')) || null,
        size_or_dimensions: getVal('ep_size_or_dimensions'),
        color: getVal('ep_color'),
        quantity: parseInt(getVal('ep_quantity')) || 1,
        tags: getVal('ep_tags'),
        description: getVal('ep_description'),
        notes: getVal('ep_notes'),
        entered_by: state.currentUser || item.entered_by || null,
        // Enhanced fields
        supplier_name: getVal('ep_supplier_name'),
        supplier_code: getVal('ep_supplier_code'),
        gender: getVal('ep_gender'),
        size_value: getVal('ep_size_value'),
        width_length: getVal('ep_width_length'),
        width_length_value: getVal('ep_width_length_value'),
        color_code: getVal('ep_color_code'),
        data_source: Object.keys(dataSource).length > 0 ? dataSource : null,
        status: 'enhanced_complete',
        ai_cache: null
    };

    try {
        // Step 1: Save to our Supabase DB
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

        // Step 2: Upsert to Lightspeed (non-fatal — LS sync failure does not block save)
        dom.epSaveBtn.textContent = 'Syncing LS...';
        let finalLsId = existingLsId;
        try {
            const lsResult = await syncToLightspeed(formData, state.accessToken);
            if (lsResult?.lightspeed_id) finalLsId = lsResult.lightspeed_id;
            if (lsResult?.action === 'error') {
                console.warn('LS sync failed (non-fatal):', lsResult.message);
            }
        } catch (lsErr) {
            console.warn('LS sync error (non-fatal):', lsErr);
        }

        // Step 3: Single consolidated PATCH with final lightspeed_product_id
        if (finalLsId) {
            await fetch(`${SUPABASE_URL}/rest/v1/products?id=eq.${item.id}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'apikey': SUPABASE_KEY,
                    'Authorization': `Bearer ${state.accessToken}`,
                },
                body: JSON.stringify({ lightspeed_product_id: finalLsId })
            }).catch(() => {});
        }

        removeFromQueueAndAdvance(item.id);
        dom.epSaveBtn.textContent = 'Save & Complete (Enhanced)';

        eventBus.emit('enhancedProcessor:saved', { id: item.id });

    } catch (e) {
        alert(`Save failed: ${e.message}`);
        dom.epSaveBtn.disabled = false;
        dom.epSaveBtn.textContent = 'Save & Complete (Enhanced)';
        console.error('Enhanced processor save error:', e);
    }
}

async function syncToLightspeed(formData, accessToken) {
    const payload = {
        name: formData.name,
        sku: formData.sku,
        barcode: formData.barcode,
        style_number: formData.style_number,
        brand_name: formData.brand_name,
        supplier_name: formData.supplier_name,
        product_category: formData.product_category,
        retail_price: formData.retail_price,
        supply_price: formData.supply_price,
        description: formData.description,
        gender: formData.tags,
    };

    const res = await fetch(LS_UPSERT_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'apikey': SUPABASE_KEY,
            'Authorization': `Bearer ${accessToken}`,
        },
        body: JSON.stringify(payload),
    });

    if (!res.ok) {
        throw new Error(`ls-upsert HTTP ${res.status}`);
    }

    return res.json();
}

function skipItem() {
    const item = state.epCurrentItem;
    if (!item) return;

    const idx = state.epQueue.findIndex(q => q.id === item.id);
    const next = state.epQueue[idx + 1] || state.epQueue[0];

    if (next && next.id !== item.id) {
        selectQueueItem(next);
    } else {
        resetView();
    }
}

function removeFromQueueAndAdvance(completedId) {
    const dom = getDOMElements();

    state.epQueue = state.epQueue.filter(q => q.id !== completedId);
    state.epCurrentItem = null;
    state.epAIData = null;
    state.epLightspeedData = null;

    const queueEl = dom.epQueueList.querySelector(`[data-id="${completedId}"]`);
    if (queueEl) queueEl.remove();

    dom.epQueueCount.textContent = `${state.epQueue.length} item${state.epQueue.length !== 1 ? 's' : ''} in queue`;

    if (state.epQueue.length > 0) {
        selectQueueItem(state.epQueue[0]);
    } else {
        resetView();
    }
}

function resetView() {
    const dom = getDOMElements();
    state.epCurrentItem = null;
    state.epAIData = null;
    state.epLightspeedData = null;

    dom.epPhotos.innerHTML = '<p class="processor-placeholder">Select an item from the queue</p>';
    dom.epAIResults.style.display = 'none';
    dom.epLightspeedPanel.style.display = 'none';
    dom.epDerivedFields.style.display = 'none';
    clearAllFields();
    dom.epForm.reset();
    dom.epSaveBtn.disabled = true;
    dom.epCopyAllBtn.disabled = true;

    if (state.epQueue.length === 0) {
        dom.epQueueList.innerHTML = '<div class="queue-empty">All items processed!</div>';
    }
}

// ── Per-Field Copy Buttons ───────────────────────────────────────────

/**
 * Get a Lightspeed field value mapped to the AI key namespace.
 */
function getLSFieldValue(aiKey) {
    const ls = state.epLightspeedData;
    if (!ls) return null;
    const map = {
        name: ls.name,
        brand_name: ls.brand,
        supplier_name: ls.supplier,
        product_category: ls.category,
        retail_price: ls.retail_price,
        supply_price: ls.supply_price,
    };
    const vo = ls.variant_options || {};
    if (vo.Size) map.size_or_dimensions = vo.Size;
    if (vo.Color) map.color = vo.Color;
    return map[aiKey] ?? null;
}

/**
 * Handle a per-field copy button click (AI→Form or LS→Form).
 */
function handleEPCopyField(btn) {
    const source = btn.dataset.epSource; // 'ai' or 'ls'
    const field = btn.dataset.epField;   // AI key like 'name', 'brand_name', etc.
    const inputId = EP_FIELD_MAP[field];
    if (!inputId) return;

    const input = document.getElementById(inputId);
    if (!input) return;

    let value;
    if (source === 'ai') {
        value = state.epAIData?.[field];
    } else {
        value = getLSFieldValue(field);
    }

    if (value === undefined || value === null || value === '') return;

    input.value = value;
    dataSource[field] = source === 'ai' ? 'ai' : 'lightspeed';

    // Dispatch input event to trigger SKU regeneration + cross-population
    input.dispatchEvent(new Event('input', { bubbles: true }));

    // Green flash feedback
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 600);
}

// ── Dynamic SKU Regeneration ────────────────────────────────────────

/**
 * Regenerate all derived fields from current form values.
 * Called on any SKU-affecting field change.
 */
function regenerateDerivedFields() {
    const getVal = id => document.getElementById(id)?.value?.trim() || '';

    const style = getVal('ep_style_number');
    const brand = getVal('ep_brand_name');
    const color = getVal('ep_color');
    const size = getVal('ep_size_or_dimensions');
    const tags = getVal('ep_tags');
    const category = getVal('ep_product_category');

    const supplierCode = getSupplierCode(brand);
    const gender = getGenderCode(tags);
    const colorCode = getColorCode(color);
    const sizeParsed = parseSize(size, category);
    const sku = generateSKU(style, brand, color, size, tags, category);

    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val || '';
    };

    setVal('ep_supplier_code', supplierCode);
    setVal('ep_gender', gender);
    setVal('ep_color_code', colorCode);
    setVal('ep_size_value', sizeParsed.sizeValue);
    setVal('ep_width_length', sizeParsed.widthLengthType);
    setVal('ep_width_length_value', sizeParsed.widthLengthValue);
    setVal('ep_sku_generated', sku);
    setVal('ep_sku', sku);
}

/**
 * Attach input listeners on form fields that affect SKU generation.
 */
function setupEPSKUListeners() {
    const skuFieldIds = [
        'ep_style_number', 'ep_brand_name', 'ep_color',
        'ep_size_or_dimensions', 'ep_tags', 'ep_product_category'
    ];
    skuFieldIds.forEach(id => {
        const field = document.getElementById(id);
        if (field) field.addEventListener('input', regenerateDerivedFields);
    });
}

// ── Category Datalist ───────────────────────────────────────────────

/**
 * Populate the category datalist from reference data.
 */
function populateCategoryDatalist() {
    const datalist = document.getElementById('epCategoryOptions');
    if (!datalist) return;
    CATEGORY_LIST.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat;
        datalist.appendChild(opt);
    });
}

// ── Supplier / Brand Cross-Population ───────────────────────────────

/**
 * Wire up brand ↔ supplier name ↔ supplier code cross-population.
 * Changing brand auto-fills supplier name + code.
 * Changing supplier code auto-fills supplier name.
 * Changing supplier name auto-fills supplier code.
 */
function setupCrossPopulation() {
    const brandField = document.getElementById('ep_brand_name');
    const supplierNameField = document.getElementById('ep_supplier_name');
    const supplierCodeField = document.getElementById('ep_supplier_code');

    if (brandField) {
        brandField.addEventListener('input', () => {
            const code = getSupplierCode(brandField.value);
            if (supplierCodeField) supplierCodeField.value = code;
            if (supplierNameField) supplierNameField.value = SUPPLIER_CODE_TO_NAME[code] || '';
        });
    }

    if (supplierCodeField) {
        supplierCodeField.addEventListener('input', () => {
            const code = supplierCodeField.value.trim().toUpperCase();
            if (supplierNameField && SUPPLIER_CODE_TO_NAME[code]) {
                supplierNameField.value = SUPPLIER_CODE_TO_NAME[code];
            }
        });
    }

    if (supplierNameField) {
        supplierNameField.addEventListener('input', () => {
            const name = supplierNameField.value.trim().toUpperCase();
            if (SUPPLIER_NAME_TO_CODE[name] && supplierCodeField) {
                supplierCodeField.value = SUPPLIER_NAME_TO_CODE[name];
            }
        });
    }
}

// ── Initialization ───────────────────────────────────────────────────

export function initEnhancedProcessor() {
    const dom = getDOMElements();

    if (dom.epRefreshQueueBtn) dom.epRefreshQueueBtn.addEventListener('click', loadQueue);
    if (dom.epSaveBtn) dom.epSaveBtn.addEventListener('click', saveAndComplete);
    if (dom.epSkipBtn) dom.epSkipBtn.addEventListener('click', skipItem);
    if (dom.epCopyAllBtn) dom.epCopyAllBtn.addEventListener('click', copyAllFields);

    // Per-field copy buttons (delegated on the grid)
    const fieldGrid = document.getElementById('epFieldGrid');
    if (fieldGrid) {
        fieldGrid.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-ep-copy');
            if (btn) handleEPCopyField(btn);
        });
    }

    // Dynamic SKU regeneration on form field changes
    setupEPSKUListeners();

    // Category dropdown
    populateCategoryDatalist();

    // Supplier ↔ Brand cross-population
    setupCrossPopulation();

    // Load queue when enhanced processor view is shown
    eventBus.on('view:changed', ({ view }) => {
        if (view === 'enhancedProcessor') loadQueue();
    });
}
