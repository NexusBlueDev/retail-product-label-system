/**
 * Barcode Scanner Module
 * Quagga2 barcode scanner integration for UPC/EAN barcodes
 */

import { getDOMElements } from './dom.js';
import { state } from './state.js';
import { showStatus } from './ui-utils.js';
import { eventBus } from './events.js';

const QUAGGA_URL = 'https://cdn.jsdelivr.net/npm/@ericblade/quagga2@1.12.1/dist/quagga.min.js';
let quaggaLoaded = false;
let detectionHandler = null;

function loadQuagga() {
    if (quaggaLoaded || window.Quagga) {
        quaggaLoaded = true;
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = QUAGGA_URL;
        script.onload = () => { quaggaLoaded = true; resolve(); };
        script.onerror = () => reject(new Error('Failed to load Quagga2'));
        document.head.appendChild(script);
    });
}

/**
 * Start the barcode scanner
 */
export async function startBarcodeScanner() {
    const { barcodeScannerContainer, scanResult } = getDOMElements();

    try {
        await loadQuagga();
    } catch (err) {
        showStatus('Failed to load barcode scanner library', 'error');
        return;
    }

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

    // Unregister any previous handler before adding a new one (prevents accumulation)
    if (detectionHandler) {
        Quagga.offDetected(detectionHandler);
    }

    detectionHandler = function(result) {
        const code = result.codeResult.code;
        if (code.length === 12 || code.length === 13) {
            state.lastDetectedCode = code;
            scanResult.textContent = `✓ Found: ${code} - Click CAPTURE to use it`;
            scanResult.style.color = '#34C759';
            scanResult.style.fontWeight = 'bold';
        }
    };

    Quagga.onDetected(detectionHandler);
}

/**
 * Stop the barcode scanner
 */
export function stopBarcodeScanner() {
    const { barcodeScannerContainer, scanResult } = getDOMElements();

    if (detectionHandler) {
        Quagga.offDetected(detectionHandler);
        detectionHandler = null;
    }
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
