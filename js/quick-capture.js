/**
 * Quick Capture Module
 * Speed-focused photo capture: snap images, AI extracts name only,
 * images stored to Supabase Storage for later desktop processing.
 */

import { SUPABASE_URL, SUPABASE_KEY, FUNCTION_URL } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { compressImageToWebP } from './image-compression.js';
import { uploadImage } from './storage.js';
import { eventBus } from './events.js';

/**
 * Show a status message in the capture view
 */
function showCaptureStatus(message, type) {
    const { captureStatus } = getDOMElements();
    if (!captureStatus) return;
    captureStatus.textContent = message;
    captureStatus.className = `status ${type} show`;
    if (type === 'success') {
        setTimeout(() => { captureStatus.className = 'status'; }, 4000);
    }
}

/**
 * Convert a Blob to a base64 data URL
 */
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Failed to read blob'));
        reader.readAsDataURL(blob);
    });
}

/**
 * Extract ONLY the product name from images via the Edge Function.
 * Sends the first image only (sufficient for name detection).
 * @param {string} base64Image - Base64 data URL
 * @returns {Promise<string>} Product name or "Unnamed Product"
 */
async function extractNameOnly(base64Image) {
    try {
        const response = await fetch(FUNCTION_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${state.accessToken}`
            },
            body: JSON.stringify({
                image: base64Image,
                imageNumber: 1,
                totalImages: 1
            })
        });

        if (!response.ok) return 'Unnamed Product';

        const text = await response.text();
        if (!text || text.trim() === '') return 'Unnamed Product';

        const result = JSON.parse(text);
        if (result.success && result.data && result.data.name) {
            return result.data.name;
        }
        return 'Unnamed Product';
    } catch {
        return 'Unnamed Product';
    }
}

/**
 * Process captured files: compress, upload to storage, extract name, save record.
 * @param {FileList|File[]} files - Image files from input or drag/drop
 */
async function processCapture(files) {
    if (!files || files.length === 0) return;

    const dom = getDOMElements();
    dom.captureLoading.style.display = 'block';
    showCaptureStatus('Uploading and extracting name...', 'info');

    try {
        // Generate product ID up front so storage path is known
        const productId = crypto.randomUUID();

        // Compress all images to WebP blobs
        const blobs = await Promise.all(
            Array.from(files).map(f => compressImageToWebP(f))
        );

        // Run uploads + name extraction in parallel for speed
        const [storagePaths, productName] = await Promise.all([
            // Upload all blobs
            Promise.all(blobs.map((blob, i) => uploadImage(blob, productId, i))),
            // Extract name from first image only
            blobToBase64(blobs[0]).then(b64 => extractNameOnly(b64))
        ]);

        // Build image_urls array
        const imageUrls = storagePaths.map(path => ({
            path,
            uploaded_at: new Date().toISOString()
        }));

        // Save product record with status='photo_only'
        const response = await fetch(`${SUPABASE_URL}/rest/v1/products`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${state.accessToken}`,
                'Prefer': 'return=representation'
            },
            body: JSON.stringify({
                id: productId,
                name: productName,
                image_urls: imageUrls,
                status: 'photo_only',
                entered_by: state.currentUser || null
            })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.message || `Save failed (${response.status})`);
        }

        const saved = await response.json();

        // Update session counter
        state.captureCount++;
        dom.captureSessionCount.textContent = `${state.captureCount} product${state.captureCount !== 1 ? 's' : ''} captured this session`;

        // Add to recent captures list
        addRecentCapture(productName, blobs[0], saved[0]?.created_at);

        dom.captureLoading.style.display = 'none';
        showCaptureStatus(`Captured: ${productName}`, 'success');

        // Reset file inputs
        dom.captureCameraInput.value = '';
        dom.captureGalleryInput.value = '';

        eventBus.emit('capture:saved', { id: productId, name: productName });

    } catch (error) {
        dom.captureLoading.style.display = 'none';
        showCaptureStatus(`Error: ${error.message}`, 'error');
        console.error('Quick capture error:', error);
    }
}

/**
 * Add an item to the recent captures list (max 5 shown)
 */
function addRecentCapture(name, thumbnailBlob, timestamp) {
    const dom = getDOMElements();
    dom.recentCaptures.style.display = 'block';

    const thumbUrl = URL.createObjectURL(thumbnailBlob);
    const time = timestamp ? new Date(timestamp).toLocaleTimeString() : 'just now';

    const item = document.createElement('div');
    item.className = 'recent-capture-item';
    item.innerHTML = `
        <img src="${thumbUrl}" class="recent-capture-thumb" alt="">
        <div class="recent-capture-info">
            <div class="recent-capture-name">${name}</div>
            <div class="recent-capture-time">${time}</div>
        </div>
    `;

    // Prepend (newest first) and cap at 5
    dom.recentCapturesList.prepend(item);
    while (dom.recentCapturesList.children.length > 5) {
        const removed = dom.recentCapturesList.lastChild;
        // Revoke blob URL to free memory
        const img = removed.querySelector('img');
        if (img) URL.revokeObjectURL(img.src);
        dom.recentCapturesList.removeChild(removed);
    }
}

/**
 * Initialize Quick Capture event listeners.
 * Called once from app.js initApp().
 */
export function initQuickCapture() {
    const dom = getDOMElements();

    // Camera button
    dom.captureCameraBtn.addEventListener('click', () => {
        dom.captureCameraInput.click();
    });

    // Gallery / upload button
    dom.captureGalleryBtn.addEventListener('click', () => {
        dom.captureGalleryInput.click();
    });

    // File input change handlers
    dom.captureCameraInput.addEventListener('change', (e) => {
        processCapture(e.target.files);
    });

    dom.captureGalleryInput.addEventListener('change', (e) => {
        processCapture(e.target.files);
    });

    // Drag & drop zone
    const dropZone = dom.captureDropZone;
    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
            if (files.length > 0) processCapture(files);
        });

        // Click to open file picker
        dropZone.addEventListener('click', () => {
            dom.captureGalleryInput.click();
        });
    }
}
