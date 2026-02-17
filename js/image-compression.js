/**
 * Image Compression Module
 * Compresses images using WebP (with JPEG fallback), returning Blobs
 * for efficient memory management — avoids storing large base64 strings.
 */

/**
 * Compress a File to a WebP (or JPEG) Blob.
 * Returns a Blob, not a base64 string, so the caller can:
 *   - create a preview with URL.createObjectURL(blob)
 *   - convert to base64 once for the API (single FileReader)
 *
 * @param {File|Blob} file - The image file to compress
 * @param {number} maxWidth - Maximum width in pixels (default: 1920)
 * @param {number} quality - Compression quality 0-1 (default: 0.85)
 * @returns {Promise<Blob>} Compressed image blob
 */
export function compressImageToWebP(file, maxWidth = 1920, quality = 0.85) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = (e) => {
            const img = new Image();

            img.onload = () => {
                const scale = Math.min(1, maxWidth / img.width);
                const width = Math.floor(img.width * scale);
                const height = Math.floor(img.height * scale);

                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;

                canvas.getContext('2d').drawImage(img, 0, 0, width, height);

                canvas.toBlob((blob) => {
                    if (blob) {
                        console.log(`Compressed: ${(file.size / 1024 / 1024).toFixed(2)}MB → ${(blob.size / 1024 / 1024).toFixed(2)}MB (WebP)`);
                        resolve(blob);
                    } else {
                        // WebP not supported — fall back to JPEG blob
                        canvas.toBlob((jpegBlob) => {
                            if (jpegBlob) {
                                console.log(`Compressed: ${(file.size / 1024 / 1024).toFixed(2)}MB → ${(jpegBlob.size / 1024 / 1024).toFixed(2)}MB (JPEG fallback)`);
                                resolve(jpegBlob);
                            } else {
                                reject(new Error('Canvas toBlob failed'));
                            }
                        }, 'image/jpeg', quality);
                    }
                }, 'image/webp', quality);
            };

            img.onerror = () => reject(new Error('Failed to load image'));
            img.src = e.target.result;
        };

        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsDataURL(file);
    });
}

/**
 * Compress a base64 data URL (e.g. from camera capture) to a base64 string.
 *
 * @param {string} dataUrl - Base64 data URL
 * @param {number} maxWidth - Maximum width in pixels (default: 1920)
 * @param {number} quality - Compression quality 0-1 (default: 0.85)
 * @returns {Promise<string>} Compressed base64 data URL
 */
export function compressBase64Image(dataUrl, maxWidth = 1920, quality = 0.85) {
    return new Promise((resolve, reject) => {
        const img = new Image();

        img.onload = () => {
            const scale = Math.min(1, maxWidth / img.width);
            const width = Math.floor(img.width * scale);
            const height = Math.floor(img.height * scale);

            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;

            canvas.getContext('2d').drawImage(img, 0, 0, width, height);

            canvas.toBlob((blob) => {
                if (blob) {
                    const reader = new FileReader();
                    reader.onload = (e) => {
                        console.log(`Camera image compressed: ${(dataUrl.length / 1024 / 1024).toFixed(2)}MB → ${(e.target.result.length / 1024 / 1024).toFixed(2)}MB`);
                        resolve(e.target.result);
                    };
                    reader.readAsDataURL(blob);
                } else {
                    resolve(canvas.toDataURL('image/jpeg', quality));
                }
            }, 'image/webp', quality);
        };

        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = dataUrl;
    });
}
