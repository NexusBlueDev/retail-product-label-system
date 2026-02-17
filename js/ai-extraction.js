/**
 * AI Extraction Module
 * OpenAI Vision API integration via Supabase Edge Function
 */

import { FUNCTION_URL, SUPABASE_KEY } from './config.js';
import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { populateForm } from './form-manager.js';
import { eventBus } from './events.js';

/**
 * Fetch with a 30-second AbortController timeout.
 */
async function fetchWithTimeout(url, options, timeoutMs = 30000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        clearTimeout(timeoutId);
    }
}

/**
 * Extract product data from images using AI.
 * All images are sent in parallel; results are merged in order.
 * @param {Array<string>} images - Array of base64 image data URLs
 */
export async function extractProductData(images) {
    const { loading, saveBtn, rescanBtn } = getDOMElements();

    loading.style.display = 'block';

    try {
        // Fire all requests simultaneously instead of sequentially
        const responses = await Promise.all(
            images.map((image, i) => fetchWithTimeout(FUNCTION_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${SUPABASE_KEY}`
                },
                body: JSON.stringify({
                    image,
                    imageNumber: i + 1,
                    totalImages: images.length
                })
            }))
        );

        // Parse all responses
        const results = await Promise.all(
            responses.map(async (response, i) => {
                if (!response.ok) {
                    throw new Error(`Server error ${response.status}. Please try again.`);
                }
                const text = await response.text();
                if (!text || text.trim() === '') {
                    throw new Error('Empty response from server.');
                }
                try {
                    return JSON.parse(text);
                } catch {
                    console.error(`Parse error for image ${i + 1}`);
                    throw new Error('Invalid response. Please try again in a moment.');
                }
            })
        );

        // Merge strategy: first image (vendor label) has priority for structured data;
        // subsequent images (handwritten) update price and append notes
        let mergedData = {};
        for (let i = 0; i < results.length; i++) {
            const result = results[i];

            if (result.error && result.error.toLowerCase().includes('rate limit')) {
                throw new Error('⏱️ Rate limit reached. Please wait 60 seconds and try again.');
            }
            if (!result.success) {
                throw new Error(result.error || `Extraction failed for image ${i + 1}`);
            }

            const data = result.data;
            if (i === 0) {
                mergedData = { ...data };
            } else {
                if (data.retail_price && data.retail_price > 0) mergedData.retail_price = data.retail_price;
                if (data.notes) {
                    mergedData.notes = mergedData.notes
                        ? `${mergedData.notes}; Additional from image ${i + 1}: ${data.notes}`
                        : `Image ${i + 1}: ${data.notes}`;
                }
            }
        }

        state.extractedData = mergedData;

        // Populate form
        populateForm(state.extractedData);

        loading.style.display = 'none';
        showStatus(`✓ Product detected: ${state.extractedData.name}`, 'success');
        saveBtn.disabled = false;
        rescanBtn.disabled = false;

        eventBus.emit('extraction:complete', { data: state.extractedData });

    } catch (error) {
        loading.style.display = 'none';
        showStatus(`Error: ${error.message}`, 'error');
        console.error('AI extraction error:', error);
    }
}
