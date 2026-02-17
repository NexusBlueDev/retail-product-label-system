/**
 * Image Compression Utility
 * Reduces image size by 50-70% before sending to OpenAI API
 *
 * Usage:
 *   const compressed = await compressImage(file, 1920, 0.85);
 *   // Or for even better compression:
 *   const webp = await compressImageToWebP(file, 1920, 0.85);
 */

/**
 * Compress image to JPEG (good browser support)
 *
 * @param {File|Blob} file - The image file to compress
 * @param {number} maxWidth - Maximum width (default: 1920px)
 * @param {number} quality - JPEG quality 0-1 (default: 0.85)
 * @returns {Promise<string>} Base64 data URL
 */
async function compressImage(file, maxWidth = 1920, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = async (e) => {
      const img = new Image();

      img.onload = () => {
        // Calculate new dimensions maintaining aspect ratio
        const scale = Math.min(1, maxWidth / img.width);
        const width = Math.floor(img.width * scale);
        const height = Math.floor(img.height * scale);

        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;

        // Draw and compress
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);

        // Convert to JPEG (better compression than PNG)
        const compressed = canvas.toDataURL('image/jpeg', quality);

        console.log(`Image compressed: ${(e.target.result.length / 1024 / 1024).toFixed(2)}MB → ${(compressed.length / 1024 / 1024).toFixed(2)}MB`);

        resolve(compressed);
      };

      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = e.target.result;
    };

    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

/**
 * Compress image to WebP (30-50% smaller than JPEG at same quality)
 * Falls back to JPEG if WebP not supported
 *
 * @param {File|Blob} file - The image file to compress
 * @param {number} maxWidth - Maximum width (default: 1920px)
 * @param {number} quality - WebP quality 0-1 (default: 0.85)
 * @returns {Promise<string>} Base64 data URL
 */
async function compressImageToWebP(file, maxWidth = 1920, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = async (e) => {
      const img = new Image();

      img.onload = () => {
        // Calculate dimensions
        const scale = Math.min(1, maxWidth / img.width);
        const width = Math.floor(img.width * scale);
        const height = Math.floor(img.height * scale);

        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;

        // Draw image
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);

        // Try WebP first (better compression)
        canvas.toBlob(
          (blob) => {
            if (blob) {
              // WebP succeeded - convert blob to data URL
              const webpReader = new FileReader();
              webpReader.onload = (e) => {
                const compressed = e.target.result;
                console.log(`Image compressed to WebP: ${(file.size / 1024 / 1024).toFixed(2)}MB → ${(blob.size / 1024 / 1024).toFixed(2)}MB (${Math.round((1 - blob.size / file.size) * 100)}% reduction)`);
                resolve(compressed);
              };
              webpReader.readAsDataURL(blob);
            } else {
              // WebP not supported - fallback to JPEG
              console.log('WebP not supported, using JPEG');
              const jpeg = canvas.toDataURL('image/jpeg', quality);
              resolve(jpeg);
            }
          },
          'image/webp',
          quality
        );
      };

      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = e.target.result;
    };

    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

/**
 * Compress image from camera capture (already base64)
 *
 * @param {string} dataUrl - Base64 data URL from camera
 * @param {number} maxWidth - Maximum width (default: 1920px)
 * @param {number} quality - Quality 0-1 (default: 0.85)
 * @param {boolean} useWebP - Use WebP format (default: true)
 * @returns {Promise<string>} Compressed base64 data URL
 */
async function compressBase64Image(dataUrl, maxWidth = 1920, quality = 0.85, useWebP = true) {
  return new Promise((resolve, reject) => {
    const img = new Image();

    img.onload = () => {
      // Calculate dimensions
      const scale = Math.min(1, maxWidth / img.width);
      const width = Math.floor(img.width * scale);
      const height = Math.floor(img.height * scale);

      // Create canvas
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;

      // Draw image
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, width, height);

      if (useWebP) {
        // Try WebP
        canvas.toBlob(
          (blob) => {
            if (blob) {
              const reader = new FileReader();
              reader.onload = (e) => {
                const originalSize = dataUrl.length / 1024 / 1024;
                const compressedSize = e.target.result.length / 1024 / 1024;
                console.log(`Camera image compressed: ${originalSize.toFixed(2)}MB → ${compressedSize.toFixed(2)}MB (${Math.round((1 - compressedSize / originalSize) * 100)}% reduction)`);
                resolve(e.target.result);
              };
              reader.readAsDataURL(blob);
            } else {
              // Fallback to JPEG
              const jpeg = canvas.toDataURL('image/jpeg', quality);
              resolve(jpeg);
            }
          },
          'image/webp',
          quality
        );
      } else {
        // JPEG
        const compressed = canvas.toDataURL('image/jpeg', quality);
        const originalSize = dataUrl.length / 1024 / 1024;
        const compressedSize = compressed.length / 1024 / 1024;
        console.log(`Camera image compressed: ${originalSize.toFixed(2)}MB → ${compressedSize.toFixed(2)}MB`);
        resolve(compressed);
      }
    };

    img.onerror = () => reject(new Error('Failed to load image'));
    img.src = dataUrl;
  });
}

// Example usage in your existing code:

// For file input (photos button):
// document.getElementById('photos').addEventListener('change', async function(e) {
//   const files = Array.from(e.target.files);
//   for (const file of files) {
//     const compressed = await compressImageToWebP(file, 1920, 0.85);
//     capturedImages.push(compressed); // Use compressed instead of original
//   }
// });

// For camera capture:
// async function capturePhoto() {
//   const video = document.getElementById('video');
//   const canvas = document.createElement('canvas');
//   canvas.width = video.videoWidth;
//   canvas.height = video.videoHeight;
//   const ctx = canvas.getContext('2d');
//   ctx.drawImage(video, 0, 0);
//   const rawImage = canvas.toDataURL('image/jpeg', 1.0);
//
//   // Compress before storing
//   const compressed = await compressBase64Image(rawImage, 1920, 0.85, true);
//   capturedImages.push(compressed);
// }

/**
 * Check WebP support
 * @returns {Promise<boolean>}
 */
async function supportsWebP() {
  return new Promise((resolve) => {
    const webP = new Image();
    webP.onload = webP.onerror = () => {
      resolve(webP.height === 2);
    };
    webP.src = 'data:image/webp;base64,UklGRjoAAABXRUJQVlA4IC4AAACyAgCdASoCAAIALmk0mk0iIiIiIgBoSygABc6WWgAA/veff/0PP8bA//LwYAAA';
  });
}

// Export functions (if using modules)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    compressImage,
    compressImageToWebP,
    compressBase64Image,
    supportsWebP
  };
}
