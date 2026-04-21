/**
 * SKU Generator Module
 * Generates product SKUs using Corrinne's formula for Lightspeed POS import:
 * GENDER-SUPPLIER_CODE-STYLE-COLOR_CODE-SIZE_VALUE[-WIDTH_OR_LENGTH]
 */

// Lightspeed vendor supplier codes — must match Lightspeed POS vendor list
export const SUPPLIER_MAP = {
    // BHSH (BH Shoe Holdings)
    'JUSTIN': 'BHS', 'JUSTIN BOOTS': 'BHS', 'TONY LAMA': 'BHS',
    'NOCONA BOOTS': 'BHS', 'CHIPPEWA': 'BHS', 'DOUBLE H': 'BHS',
    'DOUBLE-H': 'BHS', 'H & H': 'BHS', 'H&H': 'BHS',
    'CAROLINA': 'BHS', 'PHANTOM RIDER': 'BHS',
    // Ariat
    'ARIAT': 'ARI', 'HD XTREME WORK': 'ARI', 'HD XTREME': 'ARI',
    // Kontoor Brands
    'WRANGLER': 'KON', 'LEE': 'KON',
    // Westmoor Manufacturing
    'ROCK & ROLL DENIM': 'WMA', 'ROCK AND ROLL DENIM': 'WMA',
    'ROCK & ROLL COWGIRL': 'WMA', 'PANHANDLE': 'WMA',
    'PANHANDLE SLIM': 'WMA', 'POWDER RIVER': 'WMA',
    'POWDER RIVER OUTFITTERS': 'WMA', 'HOOEY X ROCK & ROLL DENIM': 'WMA',
    // Rocky Brands
    'GEORGIA BOOT': 'RBR', 'DURANGO': 'RBR', 'ROCKY': 'RBR',
    // Hatco
    'STETSON': 'RHE', 'RESISTOL': 'RHE', 'CHARLIE 1 HORSE': 'RHE',
    'BAILEY': 'RHE', 'TUFF HEDEMAN': 'RHE', 'TUFF HEDEMAN BY RESISTOL': 'RHE',
    'RODEO KING': 'RKI',
    // Miller / Cinch
    'CINCH': 'MIN',
    // Dan Post Boot Company
    'DAN POST': 'DPC', 'LAREDO': 'DPC', 'DINGO': 'DPC',
    // M&F Western
    'M&F': 'MFW', 'M&F WESTERN': 'MFW', 'M&F WESTERN PRODUCTS': 'MFW',
    'TWISTER': 'MFW', 'NOCONA BELT CO.': 'MFW', 'NOCONA BELT CO': 'MFW',
    'BLAZIN ROXX': 'MFW', 'CRUMRINE': 'MFW',
    // Twisted X
    'TWISTED X': 'TWX', 'BLACK STAR': 'TWX',
    // Corral
    'CORRAL': 'COR', 'CIRCLE G': 'COR',
    // Karman Inc
    'ROPER': 'KAR', 'TIN HAUL': 'KAR',
    // Smoky Mountain
    'SMOKY MOUNTAIN': 'SMB', 'SMOKY MOUNTAIN BOOTS': 'SMB', 'SMOKEY MOUNTAIN': 'SMB',
    // Bullhide
    'BULLHIDE': 'BHH', 'BULLHIDE HATS': 'BHH',
    // Others
    'FENOGLIO': 'FBO', 'FENOGLIO BOOTS': 'FBO',
    'ELY CATTLEMAN': 'ECA', 'CRIPPLE CREEK': 'CCR',
    'HOOEY': 'HBR', 'COWGIRL TUFF': 'CTU',
    'WEAVER': 'WLE', 'WEAVER LEATHER': 'WLE',
    'TOUGH 1': 'JTI', 'JT INT\'L': 'JTI',
    'SCULLY': 'SSI', 'OLD WEST': 'OWB',
    'OUTBACK TRADING': 'OTC', 'OUTBACK TRADING CO.': 'OTC',
    'JPC EQUESTRIAN': 'JPC', 'OVATION': 'JPC',
    'CRUEL': 'CRU', 'CRUEL DENIM': 'CRU', 'CRUEL GIRLS': 'CRU',
    'AURORA WORLD': 'AUR', 'PALM PALS': 'AUR',
    'LEANIN TREE': 'LT', 'LEANING TREE': 'LT',
    'ABILENE': 'ABC', 'ABILENE BOOT CO.': 'ABC',
    'MISS ME': 'MME', 'CACTUS ROPES': 'CR',
    'COWTOWN': 'COW', 'SADDLE BARN': 'SBI',
    'HERITAGE': 'HGL', 'HERITAGE PERFORMANCE': 'HGL',
    'REPUBLIC ROPES': 'RRO', 'TROXEL': 'TRO',
    'WESTERN FASHION': 'WFA', 'THE RODEO SHOP': 'TRS',
    'CONGRESS LEATHER': 'CGL', 'TUCKER': 'TKR',
    'ANDIS': 'AND', 'OSTER': 'OST', 'WAHL': 'WAH',
};

// Color abbreviation map — matches Corrinne's normalization codes
export const COLOR_MAP = {
    'BLACK': 'BLA', 'BROWN': 'BRO', 'WHITE': 'WHI', 'BLUE': 'BLU',
    'NAVY': 'NAV', 'RED': 'RED', 'GREEN': 'GRN', 'GRAY': 'GRA',
    'GREY': 'GRA', 'TAN': 'TAN', 'PINK': 'PNK', 'PURPLE': 'PUR',
    'ORANGE': 'ORG', 'YELLOW': 'YEL', 'TURQUOISE': 'TUR',
    'NATURAL': 'NAT', 'CHARCOAL': 'CHA', 'SILVER': 'SIL',
    'GOLD': 'GLD', 'CREAM': 'CRM', 'IVORY': 'IVR', 'CORAL': 'CRL',
    'OLIVE': 'OLV', 'RUST': 'RST', 'WINE': 'WIN', 'BURGUNDY': 'WIN',
    'SAND': 'SND', 'TEAL': 'TEA', 'BONE': 'BON', 'CHOCOLATE': 'CHO',
    'KHAKI': 'KHA', 'MINT': 'MNT', 'PEACH': 'PEA', 'PLUM': 'PLM',
    'SAGE': 'SAG', 'DENIM': 'DEN', 'CAMEL': 'CAM', 'MULTICOLOR': 'MUL',
    'DARK BROWN': 'DBR', 'LIGHT BROWN': 'LBR', 'MEDIUM BROWN': 'MBR',
    'DARK VINTAGE': 'DAR', 'MEDIUM VINTAGE': 'MED', 'DARK WASH': 'DAR',
    'MEDIUM WASH': 'MED', 'LIGHT WASH': 'LTW',
};

// Gender derivation from tags
export const GENDER_MAP = {
    'WOMEN': 'W', 'WOMAN': 'W', 'LADIES': 'W', "WOMEN'S": 'W',
    'MEN': 'M', 'MENS': 'M', "MEN'S": 'M',
    'KIDS': 'K', 'YOUTH': 'K', 'INFANT': 'K', 'TODDLER': 'K',
    'BOYS': 'B', 'GIRLS': 'G',
    'ADULT': 'A', 'UNISEX': 'A',
};

/**
 * Get supplier code from brand name
 */
export function getSupplierCode(brand) {
    if (!brand) return 'GEN';
    const key = brand.trim().toUpperCase();
    // Direct match
    if (SUPPLIER_MAP[key]) return SUPPLIER_MAP[key];
    // Partial match — check if brand starts with a known key
    for (const [mapKey, code] of Object.entries(SUPPLIER_MAP)) {
        if (key.startsWith(mapKey) || mapKey.startsWith(key)) return code;
    }
    return 'GEN';
}

/**
 * Get color code from color name
 */
export function getColorCode(color) {
    if (!color) return null;
    const upper = color.trim().toUpperCase();
    // Direct match
    if (COLOR_MAP[upper]) return COLOR_MAP[upper];
    // Two-word match (e.g., "Dark Brown")
    for (const [mapKey, code] of Object.entries(COLOR_MAP)) {
        if (upper.startsWith(mapKey)) return code;
    }
    // Slash-separated: first letter of each part
    if (color.includes('/')) {
        const parts = color.split('/');
        return parts.map(p => p.trim()[0] || '').join('').toUpperCase().substring(0, 3);
    }
    // Fallback: first 3 chars
    return upper.substring(0, 3);
}

/**
 * Get gender code from tags string
 */
export function getGenderCode(tags) {
    if (!tags) return 'A';
    const upper = tags.trim().toUpperCase();
    // Check each word in tags
    for (const word of upper.split(/[,\s]+/)) {
        const trimmed = word.trim();
        if (GENDER_MAP[trimmed]) return GENDER_MAP[trimmed];
    }
    return 'A';
}

/**
 * Parse size string into size_value and width/length value
 * @returns {{ sizeValue: string, widthLengthValue: string|null, widthLengthType: string|null }}
 */
export function parseSize(sizeStr, category) {
    if (!sizeStr) return { sizeValue: null, widthLengthValue: null, widthLengthType: null };
    const s = sizeStr.trim();
    const cat = (category || '').toLowerCase();

    const isFootwear = /boot|shoe|footwear|sandal|slipper|sneaker|moccasin|loafer/i.test(cat);
    const isJeans = /jean|pant|trouser/i.test(cat);

    if (isFootwear) {
        // "5 1/2 B" → 5.5, B
        const fracMatch = s.match(/^(\d+)\s+(\d)\/(\d)\s*([A-Z]{1,4})?$/i);
        if (fracMatch) {
            const decimal = parseInt(fracMatch[1]) + parseInt(fracMatch[2]) / parseInt(fracMatch[3]);
            return { sizeValue: String(decimal), widthLengthValue: fracMatch[4] || 'NA', widthLengthType: 'Width' };
        }
        // "10.5 EE" or "10 D"
        const numWidth = s.match(/^(\d+\.?\d*)\s+([A-Z]{1,4})(?:\s|$)/i);
        if (numWidth) {
            return { sizeValue: numWidth[1], widthLengthValue: numWidth[2].toUpperCase(), widthLengthType: 'Width' };
        }
        // "10.5" or "10" alone
        const numOnly = s.match(/^(\d+\.?\d*)$/);
        if (numOnly) {
            return { sizeValue: numOnly[1], widthLengthValue: 'NA', widthLengthType: 'Width' };
        }
    }

    if (isJeans) {
        // "32 x 30" or "32-30"
        const wxl = s.match(/^(\d+)\s*[xX\-]\s*(\d+)$/);
        if (wxl) {
            return { sizeValue: wxl[1], widthLengthValue: wxl[2], widthLengthType: 'Length' };
        }
        // "29 S" or "29 Short"
        const sizeLen = s.match(/^(\d+(?:\/\d+)?)\s+(S|Short|R|Regular|L|Long|XL|XLong|XLONG)$/i);
        if (sizeLen) {
            const lenMap = { 'SHORT': 'S', 'REGULAR': 'R', 'LONG': 'L', 'XLONG': 'XL' };
            const lenVal = lenMap[sizeLen[2].toUpperCase()] || sizeLen[2].toUpperCase().charAt(0);
            return { sizeValue: sizeLen[1], widthLengthValue: lenVal, widthLengthType: 'Length' };
        }
    }

    // Apparel sizes — pass through, no width/length
    return { sizeValue: s, widthLengthValue: null, widthLengthType: null };
}

/**
 * Sanitize a style_number to match Lightspeed's SKU regex: ^[a-zA-Z0-9_/()#\-\|\.]+$
 * Drops anything after the first whitespace (catches embedded color codes like
 * "MSW9165087 LIM") and strips disallowed characters.
 *
 * April 2026 incident: unsanitized style_numbers caused 1,129 LS POST rejections
 * and 544 orphan standalone products. See HANDOFF.md session log.
 */
export function sanitizeStyleNumber(style) {
    if (!style) return style;
    const cleaned = String(style).trim().split(/\s/)[0].replace(/[^a-zA-Z0-9_/()#\-|.]/g, '');
    return cleaned || null;
}

/**
 * Generate SKU using Corrinne's formula:
 * GENDER-SUPPLIER_CODE-STYLE-COLOR_CODE-SIZE_VALUE[-WIDTH_OR_LENGTH]
 */
export function generateSKU(style, brand, color, size, tags, category) {
    style = sanitizeStyleNumber(style) || '';
    brand = (brand || '').trim();
    if (!style && !brand) return '';

    const gender = getGenderCode(tags);
    const supplierCode = getSupplierCode(brand);

    // Leanin Tree special case
    if (supplierCode === 'LT' && style) {
        return 'LT-' + style.padStart(5, '0');
    }

    const colorCode = getColorCode(color);
    const { sizeValue, widthLengthValue } = parseSize(size, category);

    // Sanitize size parts — LS SKU regex rejects quotes, apostrophes, spaces
    const sanitizePart = v => v ? String(v).replace(/\s+/g, '-').replace(/[^a-zA-Z0-9_/()#\-|.]/g, '') || null : null;

    // Build SKU with only real parts
    let parts = [gender, supplierCode];
    if (style) parts.push(style);
    if (colorCode) parts.push(colorCode);
    if (sizeValue) parts.push(sanitizePart(sizeValue));
    if (widthLengthValue) parts.push(sanitizePart(widthLengthValue));

    return parts.join('-');
}

/**
 * Generate SKU from DOM form fields
 */
export function generateSKUFromForm() {
    const style = document.getElementById('style_number')?.value || '';
    const brand = document.getElementById('brand_name')?.value || '';
    const color = document.getElementById('color')?.value || '';
    const size = document.getElementById('size_or_dimensions')?.value || '';
    const tags = document.getElementById('tags')?.value || '';
    const category = document.getElementById('product_category')?.value || '';

    return generateSKU(style, brand, color, size, tags, category);
}
