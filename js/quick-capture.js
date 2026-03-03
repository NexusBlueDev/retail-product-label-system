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
 * Process captured files: compress, upload to storage, save record immediately,
 * then update name in background when AI finishes.
 * @param {FileList|File[]} files - Image files from input or drag/drop
 */
async function processCapture(files) {
    if (!files || files.length === 0) return;

    const dom = getDOMElements();
    dom.captureLoading.style.display = 'block';
    dom.captureNextBtn.style.display = 'none';
    showCaptureStatus('Compressing and uploading...', 'info');

    try {
        // UUID for storage folder path only — DB auto-generates the bigint ID
        const storageKey = crypto.randomUUID();

        // Compress all images to WebP at 1200px (smaller = faster upload + AI)
        const blobs = await Promise.all(
            Array.from(files).map(f => compressImageToWebP(f, 1200))
        );

        // Upload images to Storage (don't wait for AI — that's slow)
        const storagePaths = await Promise.all(
            blobs.map((blob, i) => uploadImage(blob, storageKey, i))
        );

        // Build image_urls array
        const imageUrls = storagePaths.map(path => ({
            path,
            uploaded_at: new Date().toISOString()
        }));

        // Save product record IMMEDIATELY with placeholder name
        const response = await fetch(`${SUPABASE_URL}/rest/v1/products`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${state.accessToken}`,
                'Prefer': 'return=representation'
            },
            body: JSON.stringify({
                name: 'Processing...',
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
        const savedId = saved[0]?.id || '?';

        // Update session counter
        state.captureCount++;
        dom.captureSessionCount.textContent = `${state.captureCount} product${state.captureCount !== 1 ? 's' : ''} captured this session`;

        // Add to recent captures list (will update name when AI finishes)
        addRecentCapture('Processing...', savedId, blobs[0], saved[0]?.created_at);

        dom.captureLoading.style.display = 'none';
        showCaptureStatus(`Saved! (ID: ${savedId}) — extracting name...`, 'success');

        // Show "Capture Next" button so user can keep going
        dom.captureNextBtn.style.display = 'block';

        // Reset file inputs
        dom.captureCameraInput.value = '';
        dom.captureGalleryInput.value = '';

        eventBus.emit('capture:saved', { id: savedId, name: 'Processing...' });

        // ── Background: extract name and update the record ──
        blobToBase64(blobs[0]).then(b64 => extractNameOnly(b64)).then(productName => {
            if (productName && productName !== 'Unnamed Product') {
                // PATCH the name on the DB record
                fetch(`${SUPABASE_URL}/rest/v1/products?id=eq.${savedId}`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'apikey': SUPABASE_KEY,
                        'Authorization': `Bearer ${state.accessToken}`
                    },
                    body: JSON.stringify({ name: productName })
                }).then(() => {
                    // Update the recent capture entry with the real name
                    updateRecentCaptureName(savedId, productName);
                    showCaptureStatus(`Saved: ${productName} (ID: ${savedId})`, 'success');
                }).catch(e => console.error('Name PATCH failed:', e));
            }
        }).catch(e => console.error('Background name extraction failed:', e));

    } catch (error) {
        dom.captureLoading.style.display = 'none';
        showCaptureStatus(`Error: ${error.message}`, 'error');
        console.error('Quick capture error:', error);
    }
}

/**
 * Add an item to the recent captures list (max 5 shown)
 */
function addRecentCapture(name, id, thumbnailBlob, timestamp) {
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
            <div class="recent-capture-time">ID: ${id} · ${time}</div>
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
 * Update the name in the recent captures list after AI extraction completes.
 */
function updateRecentCaptureName(id, name) {
    const dom = getDOMElements();
    const items = dom.recentCapturesList.querySelectorAll('.recent-capture-item');
    for (const item of items) {
        const timeEl = item.querySelector('.recent-capture-time');
        if (timeEl && timeEl.textContent.includes(`ID: ${id}`)) {
            const nameEl = item.querySelector('.recent-capture-name');
            if (nameEl) nameEl.textContent = name;
            break;
        }
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

    // "Capture Next" button — opens camera for the next product
    dom.captureNextBtn.addEventListener('click', () => {
        dom.captureNextBtn.style.display = 'none';
        dom.captureCameraInput.click();
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
