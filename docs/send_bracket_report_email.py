"""
send_bracket_report_email.py
============================
Sends Corrinne the bracket/paren product name report via Microsoft Graph API.

Attachments:
  - docs/ls_bracket_names.csv         (all 4,374 bracket-name variants)
  - docs/ls_bracket_match_pairs.csv   (225 automated match pairs)

Also notes that UPC fix is running and will follow up with error log.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

NEXUSBLUE_WEBSITE = Path.home() / "dev" / "nexusblue-website"
ENV_FILE = NEXUSBLUE_WEBSITE / ".env.local"
DOCS = Path("docs")

SENDER = "bill@nexusblue.io"
TO = "corrinne.torpey@nexusblue.io"
CC = "bill@nexusblue.io"

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


def load_env() -> dict:
    creds = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    return creds


def get_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = GRAPH_TOKEN_URL.format(tenant_id=tenant_id)
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


import urllib.parse


def attach(path: Path) -> dict:
    content = path.read_bytes()
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": path.name,
        "contentType": "text/csv",
        "contentBytes": base64.b64encode(content).decode(),
    }


def send_email(token: str, subject: str, body_html: str, attachments: list):
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": TO}}],
            "ccRecipients": [{"emailAddress": {"address": CC}}],
            "attachments": attachments,
        },
        "saveToSentItems": True,
    }
    url = GRAPH_SEND_URL.format(sender=SENDER)
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"Email sent — HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"HTTP {e.code}: {body[:500]}")
        raise


def main():
    creds = load_env()
    tenant_id = creds["MICROSOFT_TENANT_ID"]
    client_id = creds["MICROSOFT_CLIENT_ID"]
    client_secret = creds["MICROSOFT_CLIENT_SECRET"]

    print("Getting Graph token...", flush=True)
    token = get_graph_token(tenant_id, client_id, client_secret)

    # Count stats for email body
    all_csv = DOCS / "ls_bracket_names.csv"
    pairs_csv = DOCS / "ls_bracket_match_pairs.csv"

    total_lines = sum(1 for _ in open(all_csv)) - 1  # subtract header
    pairs_lines = sum(1 for _ in open(pairs_csv)) - 1

    subject = "Lightspeed — Bracket/Paren Product Names Report + UPC Fix Status"

    body = f"""<p>Hi Corrinne,</p>

<p>Two updates:</p>

<h3>1. UPC Fix — In Progress</h3>
<p>The UPC corrections are currently running across all 3,627 variants from your reviewed sheet.
Here's what the script is doing:</p>
<ul>
  <li><strong>3,575 variants</strong> — using the corrected UPC from your NEW UPC column</li>
  <li><strong>36 variants</strong> — auto-corrected: Excel formatted the NEW UPC column as
      a decimal (retail price + UPC merged together, e.g. <em>63.9952356641444</em>).
      For these, we applied the standard leading-zero fix (prepend "0" to the 11-digit UPC).</li>
  <li><strong>16 variants</strong> — UPC cleared (the "other issues" rows with no NEW UPC provided)</li>
</ul>
<p>Some variants are hitting a "UPC already exists" error — this means the corrected 12-digit UPC
is already assigned to another product (likely a duplicate import). I'll send you a separate error
log once the run completes so you can research those.</p>

<h3>2. Bracket/Paren Product Names — Report Attached</h3>
<p>I've run the query you requested. There are <strong>{total_lines:,} total variants</strong>
with <code>[</code>, <code>]</code>, <code>(</code>, or <code>)</code> in their product name.
Here's the breakdown:</p>
<ul>
  <li><strong>~3,632</strong> — genuine "SKU in name" cases (e.g., <em>Cinch T-Shirt [W-MIN-MSK7901003-LIL-LIL-XS]</em>)</li>
  <li><strong>~283</strong> — fill weight descriptors in name (e.g., <em>(300 fill)</em>) — likely intentional</li>
  <li><strong>~447</strong> — other descriptive text in parens (e.g., <em>(Big &amp; Tall Sizes)</em>, <em>(Infant/Toddler)</em>) — likely intentional</li>
  <li><strong>~12</strong> — trophy buckle dimensions (e.g., <em>(4.5"x3.75")</em>) — intentional</li>
</ul>

<p>I've attached two files:</p>
<ol>
  <li><strong>ls_bracket_names.csv</strong> — All {total_lines:,} variants (same columns as the UPC audit sheet + Family ID and embedded SKU columns)</li>
  <li><strong>ls_bracket_match_pairs.csv</strong> — {pairs_lines} automated match pairs where I found a likely clean family counterpart (matched by style code + color + size)</li>
</ol>

<h3>On the Merge/Delete Workflow</h3>
<p>Here's how I understand the process you described, and where I need your input:</p>

<p><strong>The plan:</strong> For each bracket-name variant, find its counterpart in a proper product family
(matched by SKU, color, size, length, width, UPC), merge any unique data from the bracket variant into
the family variant, then delete the bracket-name variant.</p>

<p><strong>The challenge:</strong> I found automated matches for only {pairs_lines} of the ~3,632 SKU-in-name variants.
The rest either don't have a clean family counterpart yet, or the SKU formats differ enough that I can't
confirm the match programmatically.</p>

<p><strong>What would help:</strong></p>
<ul>
  <li>If the bracket-name items are all from a specific Lightspeed import batch, do you have that import file? The original import data would let me match by style + UPC more precisely.</li>
  <li>For the {pairs_lines} matches I found, would you like to review the match pairs sheet and confirm before I run the merge? Each row shows the bracket variant on the left and the proposed clean variant on the right with color/size.</li>
  <li>Should the bracket-name variants be treated as standalone imports (no family) that need to be <em>moved into</em> the correct family? Or are they exact duplicates of family variants that should just be deleted?</li>
</ul>

<p>Let me know how you'd like to proceed and I'll put together the merge script once we have a confirmed match set.</p>

<p>Thanks,<br>Bill</p>"""

    attachments = [
        attach(all_csv),
        attach(pairs_csv),
    ]

    print("Sending email...", flush=True)
    send_email(token, subject, body, attachments)


if __name__ == "__main__":
    main()
