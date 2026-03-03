/**
 * Quick Capture Module
 * Speed-focused photo capture: stage multiple photos for one product,
 * then save all at once. AI extracts name in background after save.
 *
 * Flow: Add photos → see previews → Save Product → Next Product
 */

import { SUPABASE_URL, SUPABASE_KEY, FUNCTION_URL } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { compressImageToWebP } from './image-compression.js';
import { uploadImage } from './storage.js';
import { eventBus } from './events.js';

// Staged blobs for the current product (not yet saved)
let stagedBlobs = [];

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

// ── Staging ──────────────────────────────────────────────────────────

/**
 * Add photos to the staging area (compress first, show previews).
 * Does NOT save — user clicks "Save Product" when ready.
 */
async function stagePhotos(files) {
    if (!files || files.length === 0) return;

    const dom = getDOMElements();
    showCaptureStatus(`Compressing ${files.length} photo${files.length !== 1 ? 's' : ''}...`, 'info');

    // Compress each file to WebP at 1200px
    const newBlobs = await Promise.all(
        Array.from(files).map(f => compressImageToWebP(f, 1200))
    );

    stagedBlobs.push(...newBlobs);

    // Update previews
    renderStagedPreviews();

    // Reset file inputs
    dom.captureCameraInput.value = '';
    dom.captureGalleryInput.value = '';

    // Show save button, update photo count
    dom.captureSaveBtn.style.display = 'block';
    dom.captureNextBtn.style.display = 'none';
    showCaptureStatus(`${stagedBlobs.length} photo${stagedBlobs.length !== 1 ? 's' : ''} staged — add more or save`, 'info');
}

/**
 * Render thumbnail previews of all staged photos.
 */
function renderStagedPreviews() {
    const dom = getDOMElements();
    const container = dom.capturePreviews;
    if (!container) return;

    // Revoke old preview URLs
    container.querySelectorAll('img').forEach(img => {
        if (img.src.startsWith('blob:')) URL.revokeObjectURL(img.src);
    });

    if (stagedBlobs.length === 0) {
        container.style.display = 'none';
        container.innerHTML = '';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = stagedBlobs.map((blob, i) => {
        const url = URL.createObjectURL(blob);
        return `<div class="staged-thumb">
            <img src="${url}" alt="Photo ${i + 1}">
            <span class="staged-thumb-num">${i + 1}</span>
        </div>`;
    }).join('');
}

// ── Save ─────────────────────────────────────────────────────────────

/**
 * Save all staged photos as ONE product.
 * Uploads to Storage, creates DB record, then extracts name in background.
 */
async function saveProduct() {
    if (stagedBlobs.length === 0) return;

    const dom = getDOMElements();
    dom.captureLoading.style.display = 'block';
    dom.captureSaveBtn.disabled = true;
    showCaptureStatus('Uploading photos...', 'info');

    try {
        // UUID for storage folder path — all photos go under one folder
        const storageKey = crypto.randomUUID();

        // Upload all staged blobs to Storage under the same storageKey
        const storagePaths = await Promise.all(
            stagedBlobs.map((blob, i) => uploadImage(blob, storageKey, i))
        );

        const imageUrls = storagePaths.map(path => ({
            path,
            uploaded_at: new Date().toISOString()
        }));

        // Save product record with all photos (DB auto-generates bigint ID)
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
        const photoCount = stagedBlobs.length;
        const firstBlob = stagedBlobs[0];

        // Update session counter
        state.captureCount++;
        dom.captureSessionCount.textContent = `${state.captureCount} product${state.captureCount !== 1 ? 's' : ''} captured this session`;

        // Add to recent captures
        addRecentCapture('Processing...', savedId, photoCount, firstBlob, saved[0]?.created_at);

        // Clear staging
        clearStaging();

        dom.captureLoading.style.display = 'none';
        dom.captureSaveBtn.style.display = 'none';
        dom.captureSaveBtn.disabled = false;
        showCaptureStatus(`Saved! ID: ${savedId} (${photoCount} photos) — extracting name...`, 'success');

        // Show "Next Product" button
        dom.captureNextBtn.style.display = 'block';

        eventBus.emit('capture:saved', { id: savedId, name: 'Processing...' });

        // ── Background: extract name and update the record ──
        blobToBase64(firstBlob).then(b64 => extractNameOnly(b64)).then(productName => {
            if (productName && productName !== 'Unnamed Product') {
                fetch(`${SUPABASE_URL}/rest/v1/products?id=eq.${savedId}`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'apikey': SUPABASE_KEY,
                        'Authorization': `Bearer ${state.accessToken}`
                    },
                    body: JSON.stringify({ name: productName })
                }).then(() => {
                    updateRecentCaptureName(savedId, productName);
                    showCaptureStatus(`Saved: ${productName} — ID: ${savedId} (${photoCount} photos)`, 'success');
                }).catch(e => console.error('Name PATCH failed:', e));
            }
        }).catch(e => console.error('Background name extraction failed:', e));

    } catch (error) {
        dom.captureLoading.style.display = 'none';
        dom.captureSaveBtn.disabled = false;
        showCaptureStatus(`Error: ${error.message}`, 'error');
        console.error('Quick capture error:', error);
    }
}

/**
 * Clear all staged photos (without saving).
 */
function clearStaging() {
    // Revoke preview URLs
    const dom = getDOMElements();
    if (dom.capturePreviews) {
        dom.capturePreviews.querySelectorAll('img').forEach(img => {
            if (img.src.startsWith('blob:')) URL.revokeObjectURL(img.src);
        });
    }
    stagedBlobs = [];
    renderStagedPreviews();
}

// ── Recent Captures ──────────────────────────────────────────────────

/**
 * Add an item to the recent captures list (max 5 shown)
 */
function addRecentCapture(name, id, photoCount, thumbnailBlob, timestamp) {
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
            <div class="recent-capture-time">ID: ${id} · ${photoCount} photo${photoCount !== 1 ? 's' : ''} · ${time}</div>
        </div>
    `;

    dom.recentCapturesList.prepend(item);
    while (dom.recentCapturesList.children.length > 5) {
        const removed = dom.recentCapturesList.lastChild;
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

// ── Initialization ───────────────────────────────────────────────────

/**
 * Initialize Quick Capture event listeners.
 * Called once from app.js initApp().
 */
export function initQuickCapture() {
    const dom = getDOMElements();

    // Camera button — stages photos (doesn't save yet)
    dom.captureCameraBtn.addEventListener('click', () => {
        dom.captureCameraInput.click();
    });

    // Gallery / upload button
    dom.captureGalleryBtn.addEventListener('click', () => {
        dom.captureGalleryInput.click();
    });

    // Save Product button — saves all staged photos as one product
    dom.captureSaveBtn.addEventListener('click', saveProduct);

    // "Next Product" button — clears staging, opens camera
    dom.captureNextBtn.addEventListener('click', () => {
        dom.captureNextBtn.style.display = 'none';
        clearStaging();
        dom.captureCameraInput.click();
    });

    // File input change handlers — stage photos, not save
    dom.captureCameraInput.addEventListener('change', (e) => {
        stagePhotos(e.target.files);
    });

    dom.captureGalleryInput.addEventListener('change', (e) => {
        stagePhotos(e.target.files);
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
            if (files.length > 0) stagePhotos(files);
        });

        dropZone.addEventListener('click', () => {
            dom.captureGalleryInput.click();
        });
    }
}
