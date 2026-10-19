"""Plays Facebook: posts leads from leads.json to the webhook.

Usage: python simulate.py        (all leads)
       python simulate.py 1      (just lead 1)
       python simulate.py 1 9    (leads 1 and 9)
       python simulate.py --bad  (requests that must be rejected: 401, 401, 422)
"""
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

URL = "http://localhost:8000/webhook"

secret = os.environ.get("WEBHOOK_SECRET")
if not secret:
    raise SystemExit("WEBHOOK_SECRET is not set in .env")

with open("leads.json", encoding="utf-8") as f:
    leads = json.load(f)

if "--bad" in sys.argv:
    # Requests that must be rejected; none of them should reach the sheet or Discord.
    good = {k: v for k, v in leads[0].items() if k != "expected_score"}
    cases = [
        ("no secret header", good, {}, 401),
        ("wrong secret", good, {"X-Webhook-Secret": "wrong"}, 401),
        ("right secret, doors not a number", {**good, "number_of_doors": "many"},
         {"X-Webhook-Secret": secret}, 422),
    ]
    for label, body, headers, expected in cases:
        r = httpx.post(URL, json=body, headers=headers, timeout=30)
        verdict = "ok" if r.status_code == expected else "UNEXPECTED"
        print(f"{label}: {r.status_code} (expected {expected}) {verdict}")
    raise SystemExit

if len(sys.argv) > 1:
    if not all(a.isdigit() for a in sys.argv[1:]):
        raise SystemExit("usage: python simulate.py [lead numbers...] | --bad")
    nums = [int(a) for a in sys.argv[1:]]
    if any(not 1 <= n <= len(leads) for n in nums):
        raise SystemExit(f"lead numbers must be 1-{len(leads)}")
    selected = [(n, leads[n - 1]) for n in nums]
else:
    selected = list(enumerate(leads, start=1))

for n, lead in selected:
    payload = {k: v for k, v in lead.items() if k != "expected_score"}
    start = time.time()
    r = httpx.post(URL, json=payload, headers={"X-Webhook-Secret": secret}, timeout=30)
    print(f"#{n} {lead['full_name']}: {r.status_code} in {time.time() - start:.2f}s")
