/**
 * Navigation Module
 * View controller — shows/hides top-level views and manages navigation state
 */

import { state } from './state.js';
import { eventBus } from './events.js';

const VIEW_IDS = {
    menu: 'menuView',
    scanner: 'scannerView',
    quickCapture: 'quickCaptureView',
    processor: 'processorView',
    enhancedProcessor: 'enhancedProcessorView'
};

/**
 * Navigate to a named view.
 * Hides all views, shows the target, and toggles the fixed bottom bar.
 * @param {string} viewName - One of: 'menu', 'scanner', 'quickCapture', 'processor'
 */
export function navigateTo(viewName) {
    // Hide all views
    Object.values(VIEW_IDS).forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Show target
    const target = document.getElementById(VIEW_IDS[viewName]);
    if (target) target.style.display = 'block';

    // Fixed bottom buttons are only visible on the scanner view
    const buttonGroup = document.querySelector('.button-group');
    const productCount = document.getElementById('productCount');
    if (buttonGroup) buttonGroup.style.display = viewName === 'scanner' ? 'flex' : 'none';
    if (productCount) productCount.style.display = viewName === 'scanner' ? 'block' : 'none';

    // Toggle body padding (bottom bar needs 80px clearance)
    document.body.classList.toggle('no-bottom-bar', viewName !== 'scanner');

    state.currentView = viewName;
    eventBus.emit('view:changed', { view: viewName });
}

/**
 * Set up delegated click handler for [data-nav] links.
 * Any element with data-nav="menu" (etc.) will trigger navigation.
 */
export function initNavigation() {
    document.body.addEventListener('click', (e) => {
        const link = e.target.closest('[data-nav]');
        if (link) {
            e.preventDefault();
            navigateTo(link.dataset.nav);
        }
    });
}
