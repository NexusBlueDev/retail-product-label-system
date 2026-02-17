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
 * Extract product data from images using AI
 * @param {Array<string>} images - Array of base64 image data URLs
 */
export async function extractProductData(images) {
    const { loading, saveBtn, rescanBtn } = getDOMElements();

    loading.style.display = 'block';

    try {
        let mergedData = {};

        // Process each image
        for (let i = 0; i < images.length; i++) {
            const response = await fetch(FUNCTION_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${SUPABASE_KEY}`
                },
                body: JSON.stringify({
                    image: images[i],
                    imageNumber: i + 1,
                    totalImages: images.length
                })
            });

            if (!response.ok) {
                throw new Error(`Server error ${response.status}. Please try again.`);
            }

            let result;
            try {
                const text = await response.text();
                if (!text || text.trim() === '') {
                    throw new Error('Empty response from server.');
                }
                result = JSON.parse(text);
            } catch (parseError) {
                console.error('Parse error:', parseError);
                throw new Error('Invalid response. Please try again in a moment.');
            }

            // Check for rate limit error
            if (result.error && result.error.toLowerCase().includes('rate limit')) {
                throw new Error('⏱️ Rate limit reached. Please wait 60 seconds and try again.');
            }

            if (!result.success) {
                throw new Error(result.error || `Extraction failed for image ${i + 1}`);
            }

            const data = result.data;

            // Merge strategy: First image (vendor label) has priority for structured data
            // Subsequent images (handwritten) update prices and add notes
            if (i === 0) {
                // First image: use all data (vendor label priority)
                mergedData = { ...data };
            } else {
                // Subsequent images: only update price and append notes
                if (data.retail_price && data.retail_price > 0) {
                    mergedData.retail_price = data.retail_price;
                }
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
