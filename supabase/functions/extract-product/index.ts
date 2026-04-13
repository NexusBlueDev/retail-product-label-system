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

// Enhanced prompt with normalization lessons learned from 6,000+ products
const EXTRACTION_PROMPT = `You are a western wear retail inventory specialist extracting product data from images for The Rodeo Shop's Lightspeed POS import.

## BARCODE EXTRACTION (HIGHEST PRIORITY)

**Primary Rule: UPC-A (12 digits) - USA Retail Standard**
- Locate vertical barcode bars
- Find the 12-digit number CLOSEST to bars (0-5mm distance)
- Must be printed (never handwritten)
- Remove ALL spaces before returning
- Barcode MUST be digits only (0-9). If you cannot read all digits clearly, return null — NEVER use "..." or partial numbers

**Fallback: EAN-13 (13 digits) if no 12-digit UPC found**

**Proximity Validation:**
- Correct barcode: 0-5mm from bars (visually grouped)
- Wrong number: 20-50mm away (corners, bottom of label)

## DATA EXTRACTION RULES

**Printed Manufacturer Label (PRIMARY SOURCE):**
Barcode, Style Number, Brand, Size, Product Name, Color

**Handwritten Notes (SECONDARY - pricing only):**
Current retail price, markdown notes
NEVER use handwritten data for: barcode, style, size, brand

**CRITICAL — If you cannot read a field clearly, return null. NEVER guess or use "..." for partial data.**

## STYLE NUMBER RULES
- Extract the manufacturer's style/model number exactly as printed
- Common formats: "10053533" (Ariat 8-digit), "DPC5001" (Dan Post), "09MWFQG" (Wrangler), "MDM0003" (Twisted X)
- Wrangler adult jeans often start with "10" prefix: 1013MWZ, 1009MWZ — do NOT drop the leading "10"
- If labeled "STYLE" or "STYLE #" on the tag, that's the style number
- NEVER include color codes as part of the style number (e.g., "10053533BLK" should be "10053533" with color "Black")

## BRAND NAME — Use these EXACT spellings:
Ariat, Wrangler, Rock & Roll Denim, Cinch, Twisted X, Justin, Georgia Boot, Smoky Mountain, Dan Post, Corral, Bullhide, Stetson, Resistol, Charlie 1 Horse, Tony Lama, Panhandle Slim, Roper, Tin Haul, Hooey, Cruel Denim, Cruel Girls, Cowgirl Tuff, Fenoglio, Durango, Laredo, Chippewa, H & H, Abilene, Outback Trading Co., Weaver Leather, Leanin Tree, Ely Cattleman, Cactus Ropes, Blazin Roxx, Nocona Belt Co., M&F, Old West, Scully, Tough 1, Miss Me, Palm Pals

## TAGS — Gender/audience. Use EXACTLY one of:
- "Women" (never Ladies, Woman, Gals, Women's)
- "Men" (never Mens, Man)
- "Kids" (for children/youth/infant/toddler)
- "Kids, Girls" (for girls specifically)
- "Kids, Boys" (for boys specifically)
- "Adult" (for unisex/gender-neutral items)
Add ", Clearance" if the price ends in .00 or .97

## SIZE FORMAT
- Boots/shoes: "10.5 D" or "6 B" or "11 EE" (number + space + width letter)
- Jeans/pants: "32 x 30" (waist x inseam with spaces around x)
- Apparel: "S", "M", "L", "XL", "XXL", "2XL"
- Hats: "6 3/4", "7 1/8" (fractional)
- Kids: "4T", "6-12M", "2T"
- If only a number with no width for boots, just the number: "10"

## COLOR — Return the FULL color name:
- "Black" not "BLK", "Brown" not "BRN", "Navy" not "NVY"
- Multi-word: "Dark Brown", "Light Blue", "Charcoal Heather"
- Slash for combos: "Black/White", "Brown/Turquoise"
- NEVER return numeric color codes (like "07" or "171")

## CATEGORY — Use one of these standard formats:
Footwear - Boots, Footwear - Shoes, Footwear - Work Boots, Footwear - Accessories,
Apparel - Jeans, Apparel - Western Shirt, Apparel - T-Shirts & Tanks, Apparel - Hoodies & Sweatshirts, Apparel - Outerwear, Apparel - Socks,
Hats - Straw, Hats - Wool, Hats - Felt, Hats - Ball,
Accessories - Belts, Accessories - Jewelry, Accessories - Wallets,
Equestrian - Ropes, Equestrian - Halter,
Gifts & Novelties - Toys, Gifts & Novelties - Cards,
Horse Care, Grooming, Leather Care

## PRICE
- Use the LOWEST visible price (handwritten markdowns are the current price)
- Note original price in the notes field: "Original $39.99"

## OUTPUT FORMAT

Return ONLY valid JSON (no markdown, no code fences):

{
  "style_number": "string or null",
  "barcode": "string or null - 12-13 DIGITS ONLY, no spaces, no letters",
  "name": "string - product name including brand",
  "brand_name": "string or null - use exact spelling from brand list above",
  "product_category": "string or null - use standard format from list above",
  "retail_price": "number or null",
  "supply_price": null,
  "size_or_dimensions": "string or null - formatted per size rules above",
  "color": "string or null - full color name, never abbreviations",
  "quantity": 1,
  "tags": "string or null - Women/Men/Kids/Adult + optional Clearance",
  "description": "string or null - brief product description",
  "notes": "string or null - price context, condition notes"
}

## VALIDATION CHECKLIST

Before returning:
1. Barcode is EXACTLY 12 or 13 digits (no letters, no symbols, no "...")
2. Barcode came from number CLOSEST to bars (0-5mm)
3. Style number does NOT contain color codes appended to it
4. Brand name matches exact spelling from the brand list
5. Tags use standardized values (Women/Men/Kids/Adult)
6. Color is a full word (Black not BLK)
7. Category matches a standard format from the list
8. If ANY field is uncertain, return null for that field`

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
