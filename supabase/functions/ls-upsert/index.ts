import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

/**
 * ls-upsert — Lightspeed X-Series lookup-first upsert proxy.
 *
 * Searches LS by barcode (primary) then SKU (fallback).
 * If found: updates price_excluding_tax + supply_price via PUT v2.1.
 * If not found: creates standalone product via POST v2.0.
 *
 * This proxy exists because the LS personal access token cannot be
 * held in the browser — it must live in server-side secrets.
 */

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

const LS_BASE_V20 = 'https://therodeoshop.retail.lightspeed.app/api/2.0'
const LS_BASE_V21 = 'https://therodeoshop.retail.lightspeed.app/api/2.1'

// LS requires every variant to have at least one variant_definition.
// Standalones (no size/color options) use a single "One Size" definition.
const STANDALONE_VARIANT_DEF = [{ attribute_id: '8d72c173-2d55-4ef6-9813-d6bfbed613b2', value: 'One Size' }]

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

async function updateProduct(token: string, product: LsProduct, req: UpsertRequest): Promise<UpsertResult> {
  // NOTE: PUT v2.1 accepts operational fields (price, supply_price, active) but rejects ALL
  // metadata fields (supplier_id, product_type_id, brand_id, name, tags → 422 "Unknown field").
  // This is intentional and matches documented LS API limitations. If v2.1 PUT price support
  // ever breaks, action='skipped' ensures the save still completes non-fatally.
  const payload: Record<string, unknown> = { active: true }

  if (req.retail_price !== null && req.retail_price !== undefined) {
    payload.price_excluding_tax = req.retail_price
  }
  if (req.supply_price !== null && req.supply_price !== undefined) {
    payload.supply_price = req.supply_price
  }

  const { status } = await lsPut(token, product.id, payload)

  if (status === 200 || status === 204) {
    return { action: 'updated', lightspeed_id: product.id, sku: product.sku, message: 'Price updated in Lightspeed' }
  }

  // PUT rejected (likely 422) — product exists in LS but prices not updated.
  // Non-fatal: return the found ID so our DB records the correct lightspeed_product_id.
  console.warn(`ls-upsert: PUT ${product.id} returned ${status} — prices not updated but product exists`)
  return { action: 'skipped', lightspeed_id: product.id, sku: product.sku, message: `Product found in LS (id: ${product.id}) but price update returned ${status}` }
}

async function createProduct(token: string, req: UpsertRequest): Promise<UpsertResult> {
  await ensureCaches(token)

  const brandId = resolveId(brandCache, req.brand_name)
  const supplierId = resolveId(supplierCache, req.supplier_name)
  const categoryId = resolveId(categoryCache, req.product_category)

  // Build tags from gender
  const tags: string[] = []
  if (req.gender) tags.push(req.gender)

  // DESIGN INTENT: Creates a standalone product with a single "One Size" variant definition.
  // LS requires at least 1 variant_definition per variant; standalones use the Size attribute
  // with value "One Size" as a neutral placeholder. Variant family creation (grouping multiple
  // sizes/colors under one parent) belongs to the bulk import pipeline
  // (docs/ls_cleanup_phase2_final.py), not this per-product upsert. Changing this to
  // auto-create families would recreate the 5K+ orphaned-standalone debt from April cleanup.
  const variant: Record<string, unknown> = {
    sku: req.sku,
    price_excluding_tax: req.retail_price ?? 0,
    supply_price: req.supply_price ?? 0,
    variant_definitions: STANDALONE_VARIANT_DEF,
  }

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
  if (tags.length > 0) payload.tags = tags

  const { data, status } = await lsPost(token, payload)

  if (status === 200 || status === 201) {
    // POST v2.0 returns { data: ["family-uuid"] } — a string array, not object array
    const uuids = ((data as { data?: unknown[] })?.data ?? []) as string[]
    const createdId = uuids[0] ?? null
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

    // Lookup: barcode first, SKU second
    if (body.barcode) {
      existing = await searchByBarcode(token, body.barcode)
    }
    if (!existing && body.sku) {
      existing = await searchBySku(token, body.sku)
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
