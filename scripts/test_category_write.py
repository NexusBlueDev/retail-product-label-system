#!/usr/bin/env python3
"""Test script: find the correct LS API field/endpoint for writing product_type_id."""
import json, urllib.request, urllib.error
from pathlib import Path

LS_TOKEN = None
for line in Path('.env.local').read_text().splitlines():
    if line.startswith('LIGHTSPEED_TOKEN='):
        LS_TOKEN = line.split('=',1)[1].strip()

BASE_URL = "https://therodeoshop.retail.lightspeed.app"
PRODUCT_ID = "b8175994-1c9f-4d9a-801d-d0e5d317687a"  # Color Intensifier & Shampoo
TYPE_ID = "b8bcea50-2154-45d1-99f5-a241fcaa5598"  # Horse/Rodeo-Health, Care, Grooming-Groom Tools

def ls_req(method, path, body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {LS_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode()
        try:
            return e.code, json.loads(body_txt)
        except:
            return e.code, {'raw': body_txt[:300]}

print("=== Testing different formats for product_type assignment ===\n")

# Get current state
status, r = ls_req('GET', f'/api/2.0/products/{PRODUCT_ID}')
data = r.get('data', r)
print(f"GET v2.0 — name: {data.get('name')!r}, product_type_id: {data.get('product_type_id')!r}")

# Test 1: v2.0 PATCH with only product_type_id
status, r = ls_req('PATCH', f'/api/2.0/products/{PRODUCT_ID}', {"product_type_id": TYPE_ID})
data = r.get('data', r)
print(f"\nPATCH v2.0 product_type_id — status={status}, product_type_id: {data.get('product_type_id')!r}, type: {data.get('type')!r}")

# Test 2: v2.0 PUT with product_type nested as 'type'
status, r = ls_req('PUT', f'/api/2.0/products/{PRODUCT_ID}', {
    "type": {"id": TYPE_ID, "name": "Horse/Rodeo-Health, Care, Grooming-Groom Tools"}
})
data = r.get('data', r)
print(f"\nPUT v2.0 type object — status={status}, product_type_id: {data.get('product_type_id')!r}")

# Verify with fresh GET
status, r = ls_req('GET', f'/api/2.0/products/{PRODUCT_ID}')
data = r.get('data', r)
print(f"\nFresh GET — product_type_id: {data.get('product_type_id')!r}, type: {data.get('type')!r}")

# Test 3: Check if there's a product_type relationship endpoint
for method, path in [
    ('GET', f'/api/2.0/products/{PRODUCT_ID}/product_types'),
    ('POST', f'/api/2.0/products/{PRODUCT_ID}/product_type'),
    ('PUT', f'/api/2.0/products/{PRODUCT_ID}/type'),
]:
    body = {"id": TYPE_ID} if method != 'GET' else None
    status, r = ls_req(method, path, body)
    if status != 404:
        print(f"\n{method} {path} — status={status}: {str(r)[:200]}")
    else:
        print(f"\n{method} {path} — 404 (no route)")
