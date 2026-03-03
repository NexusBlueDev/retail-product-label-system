/**
 * Storage Module
 * Supabase Storage REST API wrapper for the product-images bucket
 */

import { SUPABASE_URL, SUPABASE_KEY } from './config.js';
import { state } from './state.js';

const BUCKET = 'product-images';

/**
 * Upload a Blob to Supabase Storage.
 * Path: product-images/products/{productId}/{index}.webp
 * @param {Blob} blob - Compressed image blob
 * @param {string} productId - UUID of the product
 * @param {number} index - Image index (0-based)
 * @returns {Promise<string>} Storage path (relative to bucket)
 */
export async function uploadImage(blob, productId, index) {
    const path = `products/${productId}/${index}.webp`;

    const response = await fetch(
        `${SUPABASE_URL}/storage/v1/object/${BUCKET}/${path}`,
        {
            method: 'POST',
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${state.accessToken}`,
                'Content-Type': blob.type || 'image/webp'
            },
            body: blob
        }
    );

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.message || `Upload failed (${response.status})`);
    }

    return path;
}

/**
 * Get a time-limited signed URL for a storage object.
 * @param {string} path - Storage path (e.g. "products/uuid/0.webp")
 * @param {number} expiresIn - Seconds until URL expires (default: 3600 = 1 hour)
 * @returns {Promise<string>} Signed download URL
 */
export async function getSignedUrl(path, expiresIn = 3600) {
    const response = await fetch(
        `${SUPABASE_URL}/storage/v1/object/sign/${BUCKET}/${path}`,
        {
            method: 'POST',
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${state.accessToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ expiresIn })
        }
    );

    if (!response.ok) {
        throw new Error(`Failed to get signed URL (${response.status})`);
    }

    const data = await response.json();
    return `${SUPABASE_URL}/storage/v1${data.signedURL}`;
}

/**
 * Get signed URLs for an array of storage paths.
 * @param {Array<string>} paths - Array of storage paths
 * @returns {Promise<Array<string>>} Array of signed URLs (same order)
 */
export async function getSignedUrls(paths) {
    return Promise.all(paths.map(p => getSignedUrl(p)));
}

/**
 * Download an image from a signed URL and convert to base64 data URL.
 * Used to feed images to the AI extraction Edge Function.
 * @param {string} signedUrl - Signed download URL
 * @returns {Promise<string>} Base64 data URL
 */
export async function fetchImageAsBase64(signedUrl) {
    const response = await fetch(signedUrl);
    if (!response.ok) {
        throw new Error(`Failed to fetch image (${response.status})`);
    }

    const blob = await response.blob();
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Failed to convert image to base64'));
        reader.readAsDataURL(blob);
    });
}
