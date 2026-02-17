/**
 * Barcode Scanner Module
 * Quagga2 barcode scanner integration for UPC/EAN barcodes
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { eventBus } from './events.js';

/**
 * Start the barcode scanner
 */
export function startBarcodeScanner() {
    const { barcodeScannerContainer, scanResult } = getDOMElements();

    barcodeScannerContainer.style.display = 'block';
    scanResult.textContent = 'Scanning for barcode...';
    scanResult.style.color = '#666';
    state.lastDetectedCode = null;

    Quagga.init({
        inputStream: {
            name: "Live",
            type: "LiveStream",
            target: document.querySelector('#interactive'),
            constraints: {
                width: 640,
                height: 480,
                facingMode: "environment"
            },
        },
        decoder: {
            readers: [
                "upc_reader",
                "ean_reader"
            ]
        },
    }, function(err) {
        if (err) {
            console.error(err);
            showStatus('Error starting scanner: ' + err.message, 'error');
            return;
        }
        Quagga.start();
    });

    // Simple detection - shows code immediately when detected
    Quagga.onDetected(function(result) {
        const code = result.codeResult.code;

        // Only accept 12 or 13 digit codes
        if (code.length === 12 || code.length === 13) {
            state.lastDetectedCode = code;
            scanResult.textContent = `✓ Found: ${code} - Click CAPTURE to use it`;
            scanResult.style.color = '#34C759';
            scanResult.style.fontWeight = 'bold';
        }
    });
}

/**
 * Stop the barcode scanner
 */
export function stopBarcodeScanner() {
    const { barcodeScannerContainer, scanResult } = getDOMElements();

    Quagga.stop();
    barcodeScannerContainer.style.display = 'none';
    scanResult.textContent = '';
    state.lastDetectedCode = null;
}

/**
 * Capture the last detected barcode
 */
export function captureBarcodeAndStop() {
    const { barcodeInput } = getDOMElements();

    if (state.lastDetectedCode) {
        barcodeInput.value = state.lastDetectedCode;
        barcodeInput.setAttribute('data-source', 'scanned');
        eventBus.emit('barcode:scanned', { code: state.lastDetectedCode });
        stopBarcodeScanner();
    }
}
