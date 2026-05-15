"""
send_upc_fix_results_email.py
==============================
Sends Corrinne the UPC fix error log after ls_upc_fix.py completes.

Run after ls_upc_fix.py has finished:
  python3 docs/send_upc_fix_results_email.py
"""

import base64
import csv
import json
import urllib.error
import urllib.parse
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


def attach_csv(path: Path) -> dict:
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
    log_csv = DOCS / "ls_upc_fix_log.csv"
    errors_csv = DOCS / "ls_upc_fix_errors.csv"

    if not log_csv.exists():
        print("Error: ls_upc_fix_log.csv not found — has the script finished?")
        return

    log_rows = list(csv.DictReader(open(log_csv)))
    ok_rows = [r for r in log_rows if r["status"] == "OK"]
    error_rows = [r for r in log_rows if r["status"] == "ERROR"]
    auto_rows = [r for r in log_rows if r["action"] == "AUTO_CORRECTED"]
    clear_rows = [r for r in log_rows if r["action"] == "CLEAR"]

    creds = load_env()
    token = get_graph_token(creds["MICROSOFT_TENANT_ID"], creds["MICROSOFT_CLIENT_ID"],
                            creds["MICROSOFT_CLIENT_SECRET"])

    subject = "Lightspeed UPC Fix — Complete (error log attached)"

    body = f"""<p>Hi Corrinne,</p>

<p>The UPC correction run has completed. Here's the summary:</p>

<table border="1" cellpadding="6" cellspacing="0">
  <tr><td><strong>Total variants processed</strong></td><td>{len(log_rows):,}</td></tr>
  <tr><td><strong>Successfully updated</strong></td><td>{len(ok_rows):,}</td></tr>
  <tr><td><strong>Errors (UPC already exists on another product)</strong></td><td>{len(error_rows):,}</td></tr>
  <tr><td><strong>Auto-corrected (Excel formatting issue)</strong></td><td>{len(auto_rows):,}</td></tr>
  <tr><td><strong>UPC cleared (the 16 "other issues" rows)</strong></td><td>{len(clear_rows):,}</td></tr>
</table>

<h3>About the Errors ({len(error_rows):,} variants)</h3>
<p>These variants received a "UPC already exists" error from Lightspeed — the corrected 12-digit UPC
is already assigned to a different product. This typically means:</p>
<ul>
  <li>The product was imported twice — once with the 11-digit (truncated) UPC and once with the full 12-digit UPC on a separate variant</li>
  <li>Or the full 12-digit UPC was correctly set on the product family variant, and the 11-digit code was an extra standalone import</li>
</ul>
<p>The attached error log (<strong>ls_upc_fix_errors.csv</strong>) lists all {len(error_rows):,} variants with their
old UPC, the UPC that conflicted, and the ID of the existing product holding that UPC.
Please review and let me know how you'd like to proceed — these may be duplicates that should be deleted.</p>

<p>Thanks,<br>Bill</p>"""

    attachments = [attach_csv(errors_csv)]
    print("Sending UPC fix results email...", flush=True)
    send_email(token, subject, body, attachments)


if __name__ == "__main__":
    main()
