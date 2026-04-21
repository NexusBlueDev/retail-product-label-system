-- Fix product_category values that were stored as raw Lightspeed JSON objects
-- instead of just the category name string.
-- Root cause: populateLSFields() in enhanced-processor.js was writing lsData.category
-- directly to the form without extracting the .name field from the JSON.
-- Applied: 2026-04-21

UPDATE products
SET product_category = (product_category::jsonb)->>'name'
WHERE product_category IS NOT NULL
  AND product_category LIKE '{%';
