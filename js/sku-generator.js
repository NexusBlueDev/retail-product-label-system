/**
 * SKU Generator Module
 * Generates product SKUs in format: STYLE-BRAND-COLOR-SIZE (max 15 chars)
 */

// Brand name to code mapping
export const BRAND_MAP = {
    'NIKE': 'NK',
    'ADIDAS': 'AD',
    'UNDER ARMOUR': 'UA',
    'PUMA': 'PM',
    'REEBOK': 'RB',
    'NEW BALANCE': 'NB',
    'VANS': 'VN',
    'CONVERSE': 'CV',
    'JORDAN': 'JD',
    'WRANGLER': 'WR',
    'LEVI': 'LV',
    'LEVIS': 'LV',
    'CARHARTT': 'CH',
    'DICKIES': 'DK',
    'COLE HAAN': 'CH',
    'TIMBERLAND': 'TB'
};

// Color name to code mapping
export const COLOR_MAP = {
    'BLACK': 'BLK',
    'WHITE': 'WHT',
    'RED': 'RED',
    'BLUE': 'BLU',
    'NAVY': 'NVY',
    'GRAY': 'GRY',
    'GREY': 'GRY',
    'GREEN': 'GRN',
    'YELLOW': 'YEL',
    'ORANGE': 'ORG',
    'PURPLE': 'PUR',
    'PINK': 'PNK',
    'BROWN': 'BRN',
    'TAN': 'TAN',
    'KHAKI': 'KHK',
    'BEIGE': 'BGE'
};

/**
 * Generate SKU from product details
 * @param {string} style - Style number
 * @param {string} brand - Brand name
 * @param {string} color - Color
 * @param {string} size - Size or dimensions
 * @returns {string} Generated SKU (max 15 characters)
 */
export function generateSKU(style, brand, color, size) {
    // Clean input
    style = (style || '').trim();
    brand = (brand || '').trim();
    color = (color || '').trim();
    size = (size || '').trim();

    if (!style) {
        return ''; // Can't generate without style number
    }

    let sku = '';

    // 1. Style code (clean and shorten if needed)
    let styleCode = style.toUpperCase()
        .replace(/\s+/g, '') // Remove spaces
        .replace(/[^A-Z0-9\-_.\/]/g, ''); // Remove invalid chars

    // Shorten if too long (keep first 8 chars if over 10)
    if (styleCode.length > 10) {
        styleCode = styleCode.substring(0, 8);
    }
    sku += styleCode;

    // 2. Brand code (2-3 letters)
    if (brand) {
        const brandUpper = brand.toUpperCase();
        const brandCode = BRAND_MAP[brandUpper] || brand.substring(0, 2).toUpperCase();
        sku += '-' + brandCode;
    }

    // 3. Color code (3 letters)
    if (color) {
        const colorUpper = color.toUpperCase();
        const colorCode = COLOR_MAP[colorUpper] || color.substring(0, 3).toUpperCase();
        sku += '-' + colorCode;
    }

    // 4. Size code
    if (size) {
        let sizeCode = size.toUpperCase()
            .replace(/\s+/g, '') // Remove spaces from "15 x 32" → "15X32"
            .replace(/[^A-Z0-9X]/g, ''); // Keep only letters, numbers, and X
        if (sizeCode.length > 6) {
            sizeCode = sizeCode.substring(0, 6);
        }
        sku += '-' + sizeCode;
    }

    // Ensure total length doesn't exceed 15 characters
    if (sku.length > 15) {
        sku = sku.substring(0, 15);
    }

    return sku;
}

/**
 * Generate SKU from DOM form fields
 * Helper function that reads from form inputs
 */
export function generateSKUFromForm() {
    const style = document.getElementById('style_number')?.value || '';
    const brand = document.getElementById('brand_name')?.value || '';
    const color = document.getElementById('color')?.value || '';
    const size = document.getElementById('size_or_dimensions')?.value || '';

    return generateSKU(style, brand, color, size);
}
