import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

/**
 * ls-upsert — Lightspeed X-Series lookup-first upsert proxy.
 *
 * Searches LS by barcode (primary) then SKU (fallback) then name.
 * If found: updates price_excluding_tax + supply_price via PUT v2.1 (nested under "details").
 * If not found: creates standalone product via POST v2.0.
 *
 * v2.1 PUT schema: fields must nest under "details" key — top-level fields are rejected 422.
 * This proxy exists because the LS personal access token cannot be held in the browser.
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

const LS_BASE_V20 = 'https://therodeoshop.retail.lightspeed.app/api/2.0'
const LS_BASE_V21 = 'https://therodeoshop.retail.lightspeed.app/api/2.1'

// LS variant attribute IDs (stable for The Rodeo Shop production store)
const ATTR_SIZE_ID  = '8d72c173-2d55-4ef6-9813-d6bfbed613b2'
const ATTR_COLOR_ID = 'c67f4856-9113-4447-aea0-6a4d9cafb176'

// Fallback variant def when neither size nor color is provided
const STANDALONE_VARIANT_DEF = [{ attribute_id: ATTR_SIZE_ID, value: 'One Size' }]

// Demographic + clearance tag name → LS UUID (production store)
const TAG_NAME_TO_UUID: Record<string, string> = {
  'men':       '95f3fa5b-4ab0-452f-982a-026f9a738fa5',
  'women':     'd9ba208c-b139-45ac-998e-774dcea07449',
  'kids':      '41a95de2-1c29-4bb7-ba04-78756cb2f139',
  'unisex':    'cc0620e0-90bd-49b1-a6d1-24a6f2ae6aab',
  'adult':     'e8071db8-4a36-4ede-8383-0c3dd83567c5',
  'youth':     'f77cb111-92c5-4451-a22e-528fd5f8255c',
  'clearance': '9a915378-5288-420b-8902-50963d08b68c',
  'mens':      'b7155272-65fd-4ce7-8db7-6eb08eedfd5d',
  'womens':    '8634387e-5a79-4000-9dbc-ad7500b6358b',
  "women's":   'c8549b12-2cf0-4a45-af39-abdc7ab163ea',
  "kid's":     '0e7a4d84-1706-4788-a2c5-e62ccf512899',
  'ladies':    'dd30ccb7-fdf9-44d5-bee3-66ba21b54aae',
}

function resolveTagIds(tags: string | null, retail_price: number | null): string[] {
  const ids = new Set<string>()
  if (tags) {
    for (const token of tags.split(/[,|]+/)) {
      const key = token.trim().toLowerCase()
      const uuid = TAG_NAME_TO_UUID[key]
      if (uuid) ids.add(uuid)
    }
  }
  if (retail_price !== null && retail_price !== undefined) {
    if (Math.round(retail_price * 100) % 100 === 97) ids.add(TAG_NAME_TO_UUID['clearance'])
  }
  return [...ids]
}

function buildVariantDefs(size: string | null, color: string | null): Array<Record<string, string>> {
  const defs: Array<Record<string, string>> = []
  if (size && size.trim() && size.trim().toLowerCase() !== 'one size') {
    defs.push({ attribute_id: ATTR_SIZE_ID, value: size.trim() })
  }
  if (color && color.trim()) {
    defs.push({ attribute_id: ATTR_COLOR_ID, value: color.trim() })
  }
  return defs.length > 0 ? defs : STANDALONE_VARIANT_DEF
}

// Module-scope cache — lives for the isolate lifetime (typically minutes).
// Good enough for brand/supplier lookups: small lists, rarely changes.
let brandCache: Map<string, string> | null = null
let supplierCache: Map<string, string> | null = null
let categoryCache: Map<string, string> | null = null

interface LsProduct {
  id: string
  sku: string
  name: string
  active: boolean
  deleted_at: string | null
  price_excluding_tax: number
  supply_price: number
  variant_parent_id: string | null
}

interface UpsertRequest {
  name: string
  sku: string | null
  barcode: string | null
  style_number: string | null
  brand_name: string | null
  supplier_name: string | null
  product_category: string | null
  retail_price: number | null
  supply_price: number | null
  description: string | null
  gender: string | null
  size_or_dimensions: string | null
  color: string | null
  tags: string | null
}

interface UpsertResult {
  action: 'updated' | 'created' | 'skipped' | 'error'
  lightspeed_id: string | null
  sku: string | null
  message: string
}

function lsHeaders(token: string) {
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }
}

async function lsGet(token: string, path: string, base = LS_BASE_V20): Promise<{ data: unknown; status: number }> {
  const res = await fetch(`${base}/${path}`, { headers: lsHeaders(token) })
  const body = await res.json().catch(() => ({}))
  return { data: body, status: res.status }
}

async function lsPut(token: string, uuid: string, payload: Record<string, unknown>): Promise<{ data: unknown; status: number }> {
  const res = await fetch(`${LS_BASE_V21}/products/${uuid}`, {
    method: 'PUT',
    headers: lsHeaders(token),
    body: JSON.stringify(payload),
  })
  const body = await res.json().catch(() => ({}))
  return { data: body, status: res.status }
}

async function lsPost(token: string, payload: Record<string, unknown>): Promise<{ data: unknown; status: number }> {
  const res = await fetch(`${LS_BASE_V20}/products`, {
    method: 'POST',
    headers: lsHeaders(token),
    body: JSON.stringify(payload),
  })
  const body = await res.json().catch(() => ({}))
  return { data: body, status: res.status }
}

async function loadPaginatedList(
  token: string,
  path: string,
  nameKey: string,
  idKey: string,
): Promise<Map<string, string>> {
  const map = new Map<string, string>()
  let after: string | null = null

  for (let page = 0; page < 20; page++) {
    const url = after ? `${path}?after=${after}&limit=250` : `${path}?limit=250`
    const { data, status } = await lsGet(token, url)
    if (status !== 200) break

    const items = (data as { data?: unknown[] })?.data ?? []
    if (!Array.isArray(items) || items.length === 0) break

    for (const item of items as Record<string, string>[]) {
      const name = item[nameKey]
      const id = item[idKey]
      if (name && id) map.set(name.toUpperCase(), id)
    }

    const meta = (data as { meta?: { cursor?: { next?: string } } })?.meta
    after = meta?.cursor?.next ?? null
    if (!after) break
  }

  return map
}

async function ensureCaches(token: string): Promise<void> {
  const loads: Promise<void>[] = []

  if (!brandCache) {
    loads.push(
      loadPaginatedList(token, 'brands', 'name', 'id').then(m => { brandCache = m })
    )
  }
  if (!supplierCache) {
    loads.push(
      loadPaginatedList(token, 'suppliers', 'name', 'id').then(m => { supplierCache = m })
    )
  }
  if (!categoryCache) {
    loads.push(
      loadPaginatedList(token, 'product_types', 'name', 'id').then(m => { categoryCache = m })
    )
  }

  if (loads.length > 0) await Promise.all(loads)
}

function resolveId(cache: Map<string, string> | null, name: string | null): string | null {
  if (!cache || !name) return null
  return cache.get(name.toUpperCase()) ?? null
}

async function searchByBarcode(token: string, barcode: string): Promise<LsProduct | null> {
  const { data, status } = await lsGet(token, `search?type=products&q=${encodeURIComponent(barcode)}&limit=10`)
  if (status !== 200) return null

  const items = ((data as { data?: unknown[] })?.data ?? []) as LsProduct[]
  return items.find(p => !p.deleted_at && p.active) ?? null
}

async function searchBySku(token: string, sku: string): Promise<LsProduct | null> {
  const { data, status } = await lsGet(token, `search?type=products&q=${encodeURIComponent(sku)}&limit=10`)
  if (status !== 200) return null

  const items = ((data as { data?: unknown[] })?.data ?? []) as LsProduct[]
  // Exact SKU match preferred
  return items.find(p => !p.deleted_at && p.active && p.sku?.toUpperCase() === sku.toUpperCase())
    ?? items.find(p => !p.deleted_at && p.active)
    ?? null
}

async function searchByName(token: string, name: string): Promise<LsProduct | null> {
  const { data, status } = await lsGet(token, `search?type=products&q=${encodeURIComponent(name)}&limit=10`)
  if (status !== 200) return null
  const items = ((data as { data?: unknown[] })?.data ?? []) as LsProduct[]
  return items.find(p => !p.deleted_at && p.active && p.name?.toLowerCase() === name.toLowerCase()) ?? null
}

async function updateProduct(token: string, product: LsProduct, req: UpsertRequest): Promise<UpsertResult> {
  // v2.1 PUT schema:
  //   "details" key — variant-level fields (price, supply_price, is_active)
  //   "common" key  — product-level fields (brand_id, product_suppliers, name)
  // Flat top-level fields return 422 "Unknown field in payload".
  const details: Record<string, unknown> = { is_active: true }

  if (req.retail_price !== null && req.retail_price !== undefined) {
    details.price_excluding_tax = req.retail_price
  }
  if (req.supply_price !== null && req.supply_price !== undefined) {
    details.supply_price = req.supply_price
  }

  const payload: Record<string, unknown> = { details }

  // Resolve brand + supplier via common key when either is provided.
  // Never sends empty IDs (would clear existing values).
  if (req.brand_name || req.supplier_name) {
    await ensureCaches(token)
    const common: Record<string, unknown> = {}
    const brandId = resolveId(brandCache, req.brand_name)
    if (brandId) common.brand_id = brandId
    const supplierId = resolveId(supplierCache, req.supplier_name)
    if (supplierId) common.product_suppliers = [{ supplier_id: supplierId, price: 0 }]
    if (Object.keys(common).length > 0) payload.common = common
  }

  const { status } = await lsPut(token, product.id, payload)

  if (status === 200 || status === 204) {
    return { action: 'updated', lightspeed_id: product.id, sku: product.sku, message: 'Price updated in Lightspeed' }
  }

  // PUT rejected — product exists in LS but prices not updated.
  // Non-fatal: return the found ID so our DB records the correct lightspeed_product_id.
  console.warn(`ls-upsert: PUT ${product.id} returned ${status} — prices not updated but product exists`)
  return { action: 'skipped', lightspeed_id: product.id, sku: product.sku, message: `Product found in LS (id: ${product.id}) but price update returned ${status}` }
}

async function createProduct(token: string, req: UpsertRequest): Promise<UpsertResult> {
  await ensureCaches(token)

  const brandId = resolveId(brandCache, req.brand_name)
  const supplierId = resolveId(supplierCache, req.supplier_name)
  const categoryId = resolveId(categoryCache, req.product_category)

  const tagIds = resolveTagIds(req.tags, req.retail_price)

  // Creates a standalone product — one parent, one variant.
  // variant_definitions carry the actual size/color for this item.
  // Variant family creation (multiple sizes under one parent) is handled by the
  // bulk import pipeline (docs/ls_cleanup_phase2_final.py), not here.
  const variant: Record<string, unknown> = {
    price_excluding_tax: req.retail_price ?? 0,
    supply_price: req.supply_price ?? 0,
    variant_definitions: buildVariantDefs(req.size_or_dimensions ?? null, req.color ?? null),
  }
  if (req.sku) variant.sku = req.sku

  if (req.barcode) {
    variant.product_codes = [{ type: 'UPC', code: req.barcode }]
  }

  const payload: Record<string, unknown> = {
    name: req.name,
    active: true,
    price_excluding_tax: req.retail_price ?? 0,
    supply_price: req.supply_price ?? 0,
    variants: [variant],
  }

  if (req.description) payload.description = req.description
  if (brandId) payload.brand_id = brandId
  if (supplierId) payload.supplier_id = supplierId
  if (categoryId) payload.product_type_id = categoryId

  const { data, status } = await lsPost(token, payload)

  if (status === 200 || status === 201) {
    // POST v2.0 returns { data: ["family-uuid"] } — a string array, not object array
    const uuids = ((data as { data?: unknown[] })?.data ?? []) as string[]
    const createdId = uuids[0] ?? null

    // Set track_inventory (v2.0 POST defaults to false) and tag_ids in one PUT.
    if (createdId) {
      const common: Record<string, unknown> = { track_inventory: true }
      if (tagIds.length > 0) common.tag_ids = tagIds
      await lsPut(token, createdId, { common })
    }

    return {
      action: 'created',
      lightspeed_id: createdId,
      sku: req.sku,
      message: `Created in Lightspeed${brandId ? '' : ' (brand not resolved)'}${supplierId ? '' : ', no supplier'}`,
    }
  }

  const errorMsg = JSON.stringify((data as { message?: string })?.message ?? data)
  return { action: 'error', lightspeed_id: null, sku: req.sku, message: `LS create failed (${status}): ${errorMsg}` }
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Method not allowed' }), {
      status: 405,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })
  }

  const token = Deno.env.get('LIGHTSPEED_TOKEN')
  if (!token) {
    return new Response(JSON.stringify({ error: 'LIGHTSPEED_TOKEN not configured' }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })
  }

  let body: UpsertRequest
  try {
    body = await req.json()
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON body' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })
  }

  if (!body.name) {
    return new Response(JSON.stringify({ error: 'name is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })
  }

  try {
    let existing: LsProduct | null = null

    // Lookup: barcode → SKU → name (prevents duplicate-name 422 on create)
    if (body.barcode) {
      existing = await searchByBarcode(token, body.barcode)
    }
    if (!existing && body.sku) {
      existing = await searchBySku(token, body.sku)
    }
    if (!existing && body.name) {
      existing = await searchByName(token, body.name)
    }

    const result: UpsertResult = existing
      ? await updateProduct(token, existing, body)
      : await createProduct(token, body)

    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })

  } catch (err) {
    console.error('ls-upsert error:', err)
    return new Response(JSON.stringify({ action: 'error', lightspeed_id: null, sku: null, message: String(err) }), {
      status: 200, // Return 200 so the caller can handle it as non-fatal
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    })
  }
})
