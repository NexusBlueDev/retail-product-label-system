import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

/**
 * DB-backed rate limiter — works across all Deno Deploy instances.
 * Requires the rate_limits table (see supabase/migrations/create_rate_limits.sql).
 * Falls back to allowing the request if the DB check itself errors.
 */
async function checkRateLimit(
  identifier: string,
  maxRequests = 10,
  windowMs = 60000
): Promise<boolean> {
  const supabaseUrl = Deno.env.get('SUPABASE_URL')
  const serviceKey  = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')

  if (!supabaseUrl || !serviceKey) {
    console.warn('Rate limit DB env vars not set — skipping rate check')
    return true
  }

  const headers = {
    'apikey': serviceKey,
    'Authorization': `Bearer ${serviceKey}`,
    'Content-Type': 'application/json',
  }

  const windowStart = new Date(Date.now() - windowMs).toISOString()

  try {
    // Count recent requests for this identifier within the window
    const countRes = await fetch(
      `${supabaseUrl}/rest/v1/rate_limits?select=id&identifier=eq.${encodeURIComponent(identifier)}&created_at=gte.${windowStart}`,
      { headers: { ...headers, 'Prefer': 'count=exact', 'Range': '0-0' } }
    )
    const range = countRes.headers.get('content-range') // e.g. "0-0/7"
    const count = range ? parseInt(range.split('/')[1]) : 0

    if (count >= maxRequests) return false

    // Record this request
    await fetch(`${supabaseUrl}/rest/v1/rate_limits`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ identifier }),
    })

    // Lazily purge old records (fire-and-forget — don't block the response)
    fetch(
      `${supabaseUrl}/rest/v1/rate_limits?created_at=lt.${new Date(Date.now() - windowMs * 10).toISOString()}`,
      { method: 'DELETE', headers }
    ).catch(() => {})

    return true
  } catch (e) {
    console.error('Rate limit DB error — failing open:', e)
    return true // fail open: don't block legitimate requests if DB is unavailable
  }
}

function validateImage(imageData: string): { valid: boolean; error?: string } {
  // Check format
  if (!imageData.startsWith('data:image/')) {
    return { valid: false, error: 'Invalid image format. Must be a data URL (data:image/...)' }
  }

  // Check size (max 20MB base64 ≈ 15MB original)
  if (imageData.length > 20_000_000) {
    return { valid: false, error: 'Image too large. Maximum 15MB allowed.' }
  }

  // Check if it's actually base64
  const base64Pattern = /^data:image\/(png|jpeg|jpg|webp);base64,/
  if (!base64Pattern.test(imageData.substring(0, 50))) {
    return { valid: false, error: 'Invalid base64 encoding' }
  }

  return { valid: true }
}

function validateBarcode(barcode: string | null): string | null {
  if (!barcode) return null

  // Remove all whitespace
  const cleaned = barcode.replace(/\s/g, '')

  // Must be exactly 12 or 13 digits (UPC-A or EAN-13)
  if (!/^\d{12,13}$/.test(cleaned)) {
    console.warn(`Invalid barcode format: ${barcode} (cleaned: ${cleaned})`)
    return null
  }

  return cleaned
}

// Optimized prompt (150 lines vs 395)
const EXTRACTION_PROMPT = `You are a retail inventory specialist extracting product data from images for Lightspeed POS import.

## BARCODE EXTRACTION (HIGHEST PRIORITY)

**Primary Rule: UPC-A (12 digits) - USA Retail Standard**
- Locate vertical barcode bars
- Find the 12-digit number CLOSEST to bars (0-5mm distance)
- Must be printed (never handwritten)
- Remove spaces before returning

**Fallback: EAN-13 (13 digits) if no 12-digit UPC found**

**Proximity Validation:**
- Correct barcode: 0-5mm from bars (visually grouped)
- Wrong number: 20-50mm away (corners, bottom of label)

**Example:** If "196414964851" is 2mm from bars and "4560478836" is 40mm away → use 196414964851

## DATA EXTRACTION RULES

**Printed Manufacturer Label (PRIMARY SOURCE):**
✅ Barcode, Style Number, Brand, Size, Product Name

**Handwritten Notes (SECONDARY - pricing only):**
✅ Current retail price, markdown notes
❌ NEVER for: barcode, style, size, brand

**USA Sizes Only:**
- Apparel: S, M, L, XL, 2XL, numeric (2, 4, 6)
- Pants: "32 x 34" (with space)
- Shoes: "10", "11.5 M"
- Ignore EU/UK sizes

**Price:** Use LOWEST visible price (handwritten markdowns accepted)

## FIELD MAPPING

- **barcode**: 12-13 digits from printed label (UPC/EAN)
- **style_number**: Manufacturer's code (e.g., "DD1383-100", "C41704")
- **size_or_dimensions**: USA size with space: "15 x 32"
- **retail_price**: Lowest visible price (handwritten OK)
- **color**: Product color (e.g., "Black", "Navy Blue")
- **product_category**: Format: "Type - Subtype" (e.g., "Apparel - Jeans")

## OUTPUT FORMAT

Return ONLY valid JSON (no markdown):

{
  "style_number": "string or null",
  "barcode": "string or null - 12-13 digits, no spaces",
  "name": "string - product name",
  "brand_name": "string or null",
  "product_category": "string or null",
  "retail_price": "number or null",
  "supply_price": null,
  "size_or_dimensions": "string or null",
  "color": "string or null",
  "quantity": 1,
  "tags": "string or null - gender/category",
  "description": "string or null",
  "notes": "string or null - price context, materials"
}

## EXAMPLES

### Example 1: Wrangler Jeans
**Visible:** Printed tag with bars, "0 19168 38328 70" beneath bars (13 digits), "09MWFQG" labeled STYLE, "15 x 32" size, handwritten sticker "$19.95", crossed-out "$39.99"

**Output:**
{
  "style_number": "09MWFQG",
  "barcode": "0191683832870",
  "name": "Wrangler Retro Jeans",
  "brand_name": "Wrangler",
  "product_category": "Apparel - Jeans",
  "retail_price": 19.95,
  "supply_price": null,
  "size_or_dimensions": "15 x 32",
  "color": null,
  "quantity": 1,
  "tags": "Men",
  "description": "Slim fit denim",
  "notes": "Original $39.99, handwritten markdown $19.95"
}

### Example 2: Cole Haan Sneakers
**Visible:** Box label with bars on right, "196414964851" 2mm from bars (12 digits), "4560478836" at bottom (40mm away, 10 digits), "C41704" labeled STYLE, "13 M" size

**Output:**
{
  "style_number": "C41704",
  "barcode": "196414964851",
  "name": "Cole Haan GRD SPRT JOURNEY SNKR",
  "brand_name": "Cole Haan",
  "product_category": "Footwear - Sneakers",
  "retail_price": 30.50,
  "supply_price": null,
  "size_or_dimensions": "13 M",
  "color": "Sea Stone/Lava SMK",
  "quantity": 1,
  "tags": "Men",
  "description": "Sneakers",
  "notes": "Internal item# 4560478836 (not UPC)"
}

## VALIDATION CHECKLIST

Before returning:
□ Barcode is 12 or 13 digits (no letters, no symbols)
□ Barcode came from number CLOSEST to bars (0-5mm)
□ Size formatted with space: "15 x 32" not "15x32"
□ USA sizes only (no EU/UK)
□ Used handwritten price if visible
□ Only extracted clearly readable data (null if uncertain)`

async function callOpenAIWithRetry(
  apiKey: string,
  image: string,
  maxRetries = 2
): Promise<any> {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 30000) // 30s timeout

      const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model: 'gpt-4o',
          messages: [
            {
              role: 'user',
              content: [
                { type: 'text', text: EXTRACTION_PROMPT },
                {
                  type: 'image_url',
                  image_url: { url: image }
                }
              ]
            }
          ],
          max_tokens: 800, // Reduced from 1000 (shorter prompt = fewer tokens needed)
          temperature: 0.1
        }),
        signal: controller.signal
      })

      clearTimeout(timeoutId)

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error?.message || `API error: ${response.status}`)
      }

      return await response.json()

    } catch (error) {
      // If this was the last attempt, throw the error
      if (attempt === maxRetries) {
        throw error
      }

      // Wait before retrying (exponential backoff)
      const delay = 1000 * Math.pow(2, attempt)
      console.log(`Attempt ${attempt + 1} failed, retrying in ${delay}ms...`)
      await new Promise(resolve => setTimeout(resolve, delay))
    }
  }
}

serve(async (req) => {
  const startTime = Date.now()

  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Rate limiting (use IP or a header-based identifier)
    const identifier = req.headers.get('x-forwarded-for') || 'unknown'
    if (!await checkRateLimit(identifier, 10, 60000)) {
      return new Response(
        JSON.stringify({
          success: false,
          error: 'Rate limit exceeded. Maximum 10 requests per minute.'
        }),
        { headers: { ...corsHeaders, 'Content-Type': 'application/json' }, status: 429 }
      )
    }

    // Parse request
    const { image } = await req.json()

    if (!image) {
      throw new Error('No image provided in request body')
    }

    // Validate image
    const validation = validateImage(image)
    if (!validation.valid) {
      throw new Error(validation.error)
    }

    // Get OpenAI API key
    const openaiApiKey = Deno.env.get('OPENAI_API_KEY')
    if (!openaiApiKey) {
      throw new Error('OpenAI API key not configured')
    }

    // Call OpenAI with retry logic
    const data = await callOpenAIWithRetry(openaiApiKey, image)

    if (data.error) {
      throw new Error(data.error.message)
    }

    const content = data.choices[0].message.content

    // Parse JSON response
    const jsonMatch = content.match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      throw new Error('No valid JSON found in API response')
    }

    const extractedData = JSON.parse(jsonMatch[0])

    // Validate and clean barcode
    if (extractedData.barcode) {
      extractedData.barcode = validateBarcode(extractedData.barcode)
    }

    // Structured logging
    const duration = Date.now() - startTime
    console.log(JSON.stringify({
      timestamp: new Date().toISOString(),
      function: 'extract-product',
      duration_ms: duration,
      success: true,
      fields_extracted: Object.keys(extractedData).filter(k => extractedData[k] !== null).length,
      has_barcode: !!extractedData.barcode,
      has_style_number: !!extractedData.style_number,
      tokens_used: data.usage?.total_tokens || 0
    }))

    return new Response(
      JSON.stringify({ success: true, data: extractedData }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )

  } catch (error) {
    const duration = Date.now() - startTime

    // Structured error logging
    console.error(JSON.stringify({
      timestamp: new Date().toISOString(),
      function: 'extract-product',
      duration_ms: duration,
      success: false,
      error: error.message,
      error_type: error.name
    }))

    // User-friendly error messages
    let userMessage = error.message
    if (error.message.includes('rate_limit')) {
      userMessage = 'OpenAI rate limit reached. Please wait 60 seconds and try again.'
    } else if (error.message.includes('timeout') || error.message.includes('abort')) {
      userMessage = 'Request timeout. Please check your internet connection and try again.'
    } else if (error.message.includes('JSON')) {
      userMessage = 'Invalid response format. Please try taking a clearer photo.'
    }

    return new Response(
      JSON.stringify({ success: false, error: userMessage }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' }, status: 400 }
    )
  }
})
