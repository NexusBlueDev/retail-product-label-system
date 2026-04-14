/**
 * Form Manager Module
 * Handles form population, validation, post-processing, and SKU auto-generation
 */

import { getDOMElements } from './dom.js';
import { generateSKUFromForm, getSupplierCode, getGenderCode, getColorCode, SUPPLIER_MAP } from './sku-generator.js';
import { showStatus } from './ui-utils.js';
import { state } from './state.js';

// ========================================
// Brand name normalization — fix common AI misspellings and variants
// ========================================
const BRAND_NORMALIZE = {
    'ARIAT': 'Ariat', 'ARIET': 'Ariat', 'ARIATT': 'Ariat',
    'WRANGLER': 'Wrangler', 'WRANLER': 'Wrangler', 'WRANLGER': 'Wrangler',
    'ROCK & ROLL DENIM': 'Rock & Roll Denim', 'ROCK AND ROLL DENIM': 'Rock & Roll Denim',
    'ROCK & ROLL': 'Rock & Roll Denim', 'ROCK AND ROLL': 'Rock & Roll Denim',
    'ROCK & ROLL COWGIRL': 'Rock & Roll Denim',
    'CINCH': 'Cinch', 'TWISTED X': 'Twisted X', 'TWISTEDX': 'Twisted X',
    'JUSTIN': 'Justin', 'JUSTIN BOOTS': 'Justin',
    'GEORGIA BOOT': 'Georgia Boot', 'GEORGIA': 'Georgia Boot',
    'SMOKY MOUNTAIN': 'Smoky Mountain', 'SMOKEY MOUNTAIN': 'Smoky Mountain',
    'SMOKY MOUNTAIN BOOTS': 'Smoky Mountain', 'SMOKEY MOUNTAIN BOOTS': 'Smoky Mountain',
    'DAN POST': 'Dan Post', 'DANPOST': 'Dan Post',
    'CORRAL': 'Corral', 'CORRAL BOOTS': 'Corral',
    'BULLHIDE': 'Bullhide', 'BULLHIDE HATS': 'Bullhide',
    'STETSON': 'Stetson', 'RESISTOL': 'Resistol',
    'CHARLIE 1 HORSE': 'Charlie 1 Horse',
    'TONY LAMA': 'Tony Lama', 'TONYLAMA': 'Tony Lama',
    'NOCONA': 'Nocona Belt Co.', 'NOCONA BELT': 'Nocona Belt Co.',
    'PANHANDLE': 'Panhandle Slim', 'PANHANDLE SLIM': 'Panhandle Slim',
    'ROPER': 'Roper', 'TIN HAUL': 'Tin Haul',
    'HOOEY': 'Hooey', 'DOUBLE H': 'H & H', 'DOUBLE-H': 'H & H',
    'H & H': 'H & H', 'H&H': 'H & H',
    'CAROLINA': 'Carolina', 'PHANTOM RIDER': 'H & H',
    'COWGIRL TUFF': 'Cowgirl Tuff', 'CRUEL DENIM': 'Cruel Denim',
    'CRUEL GIRLS': 'Cruel Girls', 'CRUEL': 'Cruel Denim',
    'M&F': 'M&F', 'M&F WESTERN': 'M&F', 'TWISTER': 'M&F',
    'BLAZIN ROXX': 'Blazin Roxx', 'FENOGLIO': 'Fenoglio',
    'OLD WEST': 'Old West', 'OUTBACK TRADING': 'Outback Trading Co.',
    'WEAVER': 'Weaver Leather', 'WEAVER LEATHER': 'Weaver Leather',
    'LEANIN TREE': 'Leanin Tree', 'LEANING TREE': 'Leanin Tree',
    'ELY CATTLEMAN': 'Ely Cattleman', 'CRIPPLE CREEK': 'Cripple Creek',
    'DURANGO': 'Durango', 'LAREDO': 'Laredo', 'CHIPPEWA': 'Chippewa',
    'PALM PALS': 'Palm Pals', 'AURORA WORLD': 'Aurora World',
    'MISS ME': 'Miss Me', 'CACTUS ROPES': 'Cactus Ropes',
    'SCULLY': 'Scully', 'TOUGH 1': 'Tough 1',
};

// Tag normalization — standardize gender tags
const TAG_NORMALIZE = {
    'WOMEN': 'Women', 'WOMAN': 'Women', 'LADIES': 'Women', "WOMEN'S": 'Women',
    'WOMENS': 'Women', 'GALS': 'Women', 'W': 'Women',
    'MEN': 'Men', 'MENS': 'Men', "MEN'S": 'Men',
    'KIDS': 'Kids', 'YOUTH': 'Kids', 'INFANT': 'Kids', 'INFANTS': 'Kids',
    'TODDLER': 'Kids', 'BABY': 'Kids',
    'ADULT': 'Adult', 'ADULTS': 'Adult', 'UNISEX': 'Adult',
    'BOYS': 'Kids, Boys', 'GIRLS': 'Kids, Girls',
};

// Category normalization — fix common AI variants
const CATEGORY_NORMALIZE = {
    'FOOTWEAR - BOOT': 'Footwear - Boots',
    'FOOTWEAR - SHOE': 'Footwear - Shoes',
    'FOOTWEAR - SNEAKER': 'Footwear - Shoes',
    'FOOTWEAR - SNEAKERS': 'Footwear - Shoes',
    'FOOTWEAR - SANDAL': 'Footwear - Shoes',
    'FOOTWEAR - SANDALS': 'Footwear - Shoes',
    'APPAREL - JEAN': 'Apparel - Jeans',
    'APPAREL - PANT': 'Apparel - Jeans',
    'APPAREL - PANTS': 'Apparel - Jeans',
    'APPAREL - TROUSERS': 'Apparel - Jeans',
    'APPAREL - TROUSER': 'Apparel - Jeans',
    'APPAREL - HOODIE': 'Apparel - Hoodies & Sweatshirts',
    'APPAREL - SWEATSHIRT': 'Apparel - Hoodies & Sweatshirts',
    'APPAREL - T-SHIRT': 'Apparel - T-Shirts & Tanks',
    'APPAREL - TANK': 'Apparel - T-Shirts & Tanks',
    'APPAREL - JACKET': 'Apparel - Outerwear',
    'APPAREL - VEST': 'Apparel - Outerwear',
    'FOOTWEAR - ACCESSORY': 'Footwear - Accessories',
    'FOOTWEAR - ACCESSORIES': 'Footwear - Accessories',
    'FOOTWEAR - INSOLE': 'Footwear - Accessories',
};

/**
 * Post-process AI extraction data — clean and normalize before showing to staff
 */
export function postProcessExtraction(data) {
    // 1. Normalize brand name
    if (data.brand_name) {
        const brandUpper = data.brand_name.trim().toUpperCase();
        data.brand_name = BRAND_NORMALIZE[brandUpper] || data.brand_name.trim();
    }

    // 2. Normalize tags (gender)
    if (data.tags) {
        const primaryTag = data.tags.split(',')[0].trim().toUpperCase();
        const normalized = TAG_NORMALIZE[primaryTag];
        if (normalized) {
            // Preserve secondary tags like Clearance
            const secondary = data.tags.split(',').slice(1).map(t => t.trim()).filter(t => t);
            data.tags = [normalized, ...secondary].join(', ');
        }
    }

    // 3. Normalize category
    if (data.product_category) {
        const catUpper = data.product_category.trim().toUpperCase();
        data.product_category = CATEGORY_NORMALIZE[catUpper] || data.product_category.trim();
    }

    // 4. Clean color — remove parentheses, numeric prefixes, expand abbreviations
    if (data.color) {
        let color = data.color.trim();
        color = color.replace(/^\(/, '').replace(/\)$/, '');  // Strip parens
        color = color.replace(/^\d+-?\s*/, '');  // Strip numeric prefix like "07 "
        if (color.length <= 2) {
            const abbrevMap = { 'MC': 'Multicolor', 'BU': 'Blue', 'BR': 'Brown', 'BC': 'Black', 'PU': 'Purple', 'BK': 'Black', 'WH': 'White', 'RD': 'Red', 'GR': 'Green', 'NV': 'Navy' };
            color = abbrevMap[color.toUpperCase()] || color;
        }
        data.color = color;
    }

    // 5. Clean style number — remove trailing spaces, fix "..." to null
    if (data.style_number) {
        data.style_number = data.style_number.trim();
        if (data.style_number.includes('...') || data.style_number.includes('…')) {
            data.style_number = null;
        }
    }

    // 6. Clean barcode — must be numeric only, 12-13 digits
    if (data.barcode) {
        const cleaned = data.barcode.replace(/\s/g, '');
        if (/^\d{12,13}$/.test(cleaned)) {
            data.barcode = cleaned;
        } else {
            data.barcode = null;  // Invalid barcode — clear it
        }
    }

    // 7. Clearance rule — price ending in .00 or .97
    if (data.retail_price) {
        const priceStr = String(data.retail_price);
        if (priceStr.endsWith('.00') || priceStr.endsWith('.97')) {
            if (!data.tags) {
                data.tags = 'Clearance';
            } else if (!data.tags.toLowerCase().includes('clearance')) {
                data.tags += ', Clearance';
            }
        }
    }

    // 8. If no style number, use barcode as fallback
    if (!data.style_number && data.barcode) {
        data.style_number = data.barcode;
    }

    return data;
}

/**
 * Populate form with extracted product data
 * @param {Object} data - Product data from AI extraction
 */
export function populateForm(data) {
    const dom = getDOMElements();

    // Post-process AI output before populating form
    data = postProcessExtraction(data);

    dom.nameInput.value = data.name || '';

    // Map SKU data to style_number if present
    dom.styleNumberInput.value = data.style_number || '';

    // Only populate barcode if NOT scanned (scanned is authoritative)
    if (dom.barcodeInput.getAttribute('data-source') !== 'scanned') {
        dom.barcodeInput.value = data.barcode || '';
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

    // Generate SKU using Corrinne's formula
    const generatedSKU = generateSKUFromForm();
    if (generatedSKU) {
        dom.skuInput.value = generatedSKU;
    }

    // Validate barcode length
    if (dom.barcodeInput.value && dom.barcodeInput.value.length !== 12 && dom.barcodeInput.value.length !== 13) {
        showStatus(`Warning: Barcode has ${dom.barcodeInput.value.length} digits (should be 12 or 13). Use UPC scanner!`, 'error');
    }

    // Show supplier code in status for staff awareness
    if (data.brand_name) {
        const code = getSupplierCode(data.brand_name);
        if (code === 'GEN') {
            showStatus(`Unknown supplier for "${data.brand_name}" — verify brand name`, 'error');
        }
    }
}

/**
 * Setup SKU auto-generation listeners
 */
export function setupSKUAutoGeneration() {
    const fieldIds = ['style_number', 'brand_name', 'color', 'size_or_dimensions', 'tags', 'product_category'];

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
        notes: dom.notesInput.value || null,
        entered_by: state.currentUser || null,
        status: 'complete'
    };
}
