/**
 * Image Handler Module
 * Handles image selection, compression, and preview management
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { eventBus } from './events.js';
import { compressImageToWebP } from './image-compression.js';

/**
 * Handle image selection from camera or gallery.
 * Single-pass pipeline: file → blob → preview URL + base64 (one FileReader total).
 * @param {Event} e - Change event from file input
 */
export async function handleImageSelection(e) {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    showStatus(`${files.length} image(s) selected ✓`, 'info');

    for (const file of files) {
        const blob = await compressImageToWebP(file);

        // Reuse the same blob for both preview and API — no second file read
        const preview = URL.createObjectURL(blob);
        const base64 = await blobToBase64(blob);

        state.currentImages.push({ base64, preview });
    }

    updatePreviews();

    const { cameraInput, galleryInput } = getDOMElements();
    cameraInput.value = '';
    galleryInput.value = '';

    eventBus.emit('images:selected', { count: state.currentImages.length });
}

/**
 * Convert a Blob to a base64 data URL (single FileReader).
 * @param {Blob} blob
 * @returns {Promise<string>}
 */
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = () => reject(new Error('Failed to convert blob to base64'));
        reader.readAsDataURL(blob);
    });
}

/**
 * Update preview thumbnails display
 */
export function updatePreviews() {
    const { imagePreviewContainer, imagePreviewList } = getDOMElements();

    if (state.currentImages.length === 0) {
        imagePreviewContainer.style.display = 'none';
        return;
    }

    imagePreviewContainer.style.display = 'block';
    imagePreviewList.innerHTML = '';

    state.currentImages.forEach((img, index) => {
        const imgWrapper = document.createElement('div');
        imgWrapper.style.cssText = 'position: relative; width: 80px; height: 80px;';

        const imgEl = document.createElement('img');
        imgEl.src = img.preview;
        imgEl.style.cssText = 'width: 100%; height: 100%; object-fit: cover; border-radius: 8px; border: 2px solid #007AFF;';

        const label = document.createElement('div');
        label.textContent = index + 1;
        label.style.cssText = 'position: absolute; top: 2px; right: 2px; background: #007AFF; color: white; border-radius: 50%; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold;';

        imgWrapper.appendChild(imgEl);
        imgWrapper.appendChild(label);
        imagePreviewList.appendChild(imgWrapper);
    });
}

/**
 * Clear all selected images, revoking blob preview URLs to free memory.
 */
export function clearImages() {
    state.currentImages.forEach(img => {
        if (img.preview && img.preview.startsWith('blob:')) {
            URL.revokeObjectURL(img.preview);
        }
    });
    state.currentImages = [];
    updatePreviews();
    showStatus('Images cleared', 'info');
}
