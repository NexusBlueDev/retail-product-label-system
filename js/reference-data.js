/**
 * Reference Data Module
 * Centralized lookup tables for categories and supplier names.
 * Data sourced from Corrinne's normalization rules and Lightspeed vendor list.
 * Brand → supplier code mapping lives in sku-generator.js (SUPPLIER_MAP).
 */

// Standard categories — Rodeo Shop's Lightspeed POS categories
export const CATEGORY_LIST = [
    'Footwear - Boots',
    'Footwear - Shoes',
    'Footwear - Work Boots',
    'Footwear - Accessories',
    'Apparel - Jeans',
    'Apparel - Western Shirt',
    'Apparel - T-Shirts & Tanks',
    'Apparel - Hoodies & Sweatshirts',
    'Apparel - Outerwear',
    'Apparel - Socks',
    'Hats - Straw',
    'Hats - Wool',
    'Hats - Felt',
    'Hats - Ball',
    'Accessories - Belts',
    'Accessories - Jewelry',
    'Accessories - Wallets',
    'Equestrian - Ropes',
    'Equestrian - Halter',
    'Gifts & Novelties - Toys',
    'Gifts & Novelties - Cards',
    'Horse Care',
    'Grooming',
    'Leather Care'
];

// Supplier code → full supplier/company name (from Lightspeed vendor list)
export const SUPPLIER_CODE_TO_NAME = {
    'BHS': 'BH Shoe Holdings',
    'ARI': 'Ariat International',
    'KON': 'Kontoor Brands',
    'WMA': 'Westmoor Manufacturing',
    'RBR': 'Rocky Brands',
    'RHE': 'Hatco',
    'RKI': 'Rodeo King',
    'MIN': 'Miller International',
    'DPC': 'Dan Post Boot Company',
    'MFW': 'M&F Western Products',
    'TWX': 'Twisted X',
    'COR': 'Corral',
    'KAR': 'Karman Inc',
    'SMB': 'Smoky Mountain Boots',
    'BHH': 'Bullhide Hats',
    'FBO': 'Fenoglio Boot Co.',
    'ECA': 'Ely Cattleman',
    'CCR': 'Cripple Creek',
    'HBR': 'Hooey Brands',
    'CTU': 'Cowgirl Tuff Co.',
    'WLE': 'Weaver Leather',
    'JTI': 'JT International',
    'SSI': 'Scully',
    'OWB': 'Old West Boots',
    'OTC': 'Outback Trading Co.',
    'JPC': 'JPC Equestrian',
    'CRU': 'Cruel Denim',
    'AUR': 'Aurora World',
    'LT':  'Leanin Tree',
    'ABC': 'Abilene Boot Company',
    'MME': 'Miss Me',
    'CR':  'Cactus Ropes',
    'COW': 'Cowtown',
    'SBI': 'Saddle Barn Inc',
    'HGL': 'Heritage Gloves',
    'RRO': 'Republic Ropes',
    'TRO': 'Troxel',
    'WFA': 'Western Fashion Accessories',
    'TRS': 'The Rodeo Shop',
    'CGL': 'Congress Leather',
    'TKR': 'Tucker',
    'AND': 'Andis Company',
    'OST': 'Oster',
    'WAH': 'Wahl',
    'GEN': 'Generic'
};

// Reverse lookup: supplier name (uppercase) → supplier code
export const SUPPLIER_NAME_TO_CODE = Object.fromEntries(
    Object.entries(SUPPLIER_CODE_TO_NAME).map(([code, name]) => [name.toUpperCase(), code])
);
