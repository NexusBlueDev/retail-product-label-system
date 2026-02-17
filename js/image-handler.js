/**
 * Image Handler Module
 * Handles image selection, compression, and preview management
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { eventBus } from './events.js';

/**
 * Handle image selection from camera or gallery
 * @param {Event} e - Change event from file input
 */
export async function handleImageSelection(e) {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    showStatus(`${files.length} image(s) selected ✓`, 'info');

    // Add to current images
    for (const file of files) {
        const base64 = await compressImage(file);
        state.currentImages.push({
            base64: base64,
            preview: await createPreviewUrl(file)
        });
    }

    // Show preview container and update previews
    updatePreviews();

    const { cameraInput, galleryInput } = getDOMElements();
    // Clear file inputs for next selection
    cameraInput.value = '';
    galleryInput.value = '';

    eventBus.emit('images:selected', { count: state.currentImages.length });
}

/**
 * Create preview URL from file
 * @param {File} file - Image file
 * @returns {Promise<string>} Data URL
 */
export function createPreviewUrl(file) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.readAsDataURL(file);
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
 * Compress image using WebP format
 * @param {File} file - Image file to compress
 * @returns {Promise<string>} Compressed base64 data URL
 */
export async function compressImage(file) {
    // Use improved compression from image-compression.js
    // WebP format (30-50% smaller), 1920px max, 85% quality
    try {
        const compressed = await compressImageToWebP(file, 1920, 0.85);
        console.log(`Image compressed: ${(file.size / 1024 / 1024).toFixed(2)}MB → ${(compressed.length / 1024 / 1024).toFixed(2)}MB`);
        return compressed;
    } catch (error) {
        console.error('Compression error, using fallback:', error);
        // Fallback to JPEG if WebP fails
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const maxWidth = 1920;
                    const scale = Math.min(1, maxWidth / img.width);
                    canvas.width = img.width * scale;
                    canvas.height = img.height * scale;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    resolve(canvas.toDataURL('image/jpeg', 0.85));
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }
}

/**
 * Clear all selected images
 */
export function clearImages() {
    state.currentImages = [];
    updatePreviews();
    showStatus('Images cleared', 'info');
}
