/**
 * UI Utilities Module
 * Helper functions for status messages and modals
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';

/**
 * Show a status message to the user
 * @param {string} message - Message to display
 * @param {string} type - Message type: 'info', 'success', or 'error'
 */
export function showStatus(message, type) {
    const { status } = getDOMElements();
    status.textContent = message;
    status.className = `status ${type} show`;
    setTimeout(() => {
        status.classList.remove('show');
    }, 5000);
}

/**
 * Close the success modal
 */
export function closeModal() {
    const { successModal } = getDOMElements();
    successModal.classList.remove('show');
}

/**
 * Close the duplicate warning modal and reset form for next product
 */
export function closeDuplicateModal() {
    const {
        duplicateModal,
        form,
        imagePreviewList,
        imagePreviewContainer,
        cameraInput,
        galleryInput,
        saveBtn,
        status
    } = getDOMElements();

    // Close the modal
    duplicateModal.classList.remove('show');

    // Clear form and reset (same as success flow)
    form.reset();
    imagePreviewList.innerHTML = '';
    imagePreviewContainer.style.display = 'none';
    cameraInput.value = '';
    galleryInput.value = '';
    saveBtn.disabled = true;

    // Reset state
    state.currentImages = [];
    state.extractedData = null;

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Hide any lingering status messages
    status.classList.remove('show');
}
