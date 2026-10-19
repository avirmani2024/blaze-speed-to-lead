# Blaze speed-to-lead

A fake Facebook lead arrives on a webhook. The pipeline rule-checks it, has Claude score it 1-5 with a one-line reason and a draft first reply, appends it to a Google Sheet, and pings a private Discord channel, all within a few seconds.

Blaze's Facebook leads wait a median of 22 hours for first contact, and 44% are junk. This build cuts "lead submits to Blaze sees a scored lead with a ready reply" from hours to seconds.

**What it does not change:** a person still reads the ping and sends the reply. The pipeline cuts time-to-awareness and does the prep work (triage and a draft). Nothing is ever sent to a lead; messages go only to my private Discord channel, and every test lead is fake (`.example` emails, 555 phones).

## How it works

```
simulate.py --POST + X-Webhook-Secret--> app.py (FastAPI, port 8000)
  1. check secret      wrong/missing -> 401, nothing else happens
  2. validate + reply  200 {"status": "received"} immediately; rest runs in the background
  3. rule checks       bad email / fake phone / bad door count / keyboard-mash name
  4. score             2+ flags -> score 1, Claude skipped; otherwise Claude Haiku
                       scores 1-5 and drafts a reply (forced tool use -> structured JSON)
  5. save              one row appended to the Google Sheet
  6. Discord           score, seconds since submit, contact, reason and draft
```

- The webhook replies before doing any work, so a slow step can never make the sender time out and resend.
- Each of steps 3-6 has its own `try/except`. If Claude fails, the lead is saved with a blank score and reason "manual review". If Sheets fails, Discord still pings. No lead is lost.
- Rule flags never reject a lead; they are saved in the `rule_flags` column. Only a bad secret (401) or a malformed body (422) is rejected.
- Lead fields go to Claude inside `<lead>` tags and `prompt.md` tells it to treat them as data, never instructions.

| File | Role |
| --- | --- |
| `app.py` | Webhook and the whole pipeline |
| `prompt.md` | Scoring rubric and reply rules (Claude's system prompt) |
| `simulate.py` | Plays Facebook: posts leads from `leads.json` |
| `leads.json` | 10 fake leads, each with an `expected_score` answer key (stripped before posting) |
| `sheets_smoke_test.py` | One-off Google auth check |
| `BUILD_LOG.md` | What was done and why |
| `PIPELINE_GUIDE.pdf` | The whole process, file by file |

## Run it

1. `python -m venv --copies .venv`, activate it, then `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and fill in the values (never commit `.env`):
   `ANTHROPIC_API_KEY`, `DISCORD_WEBHOOK_URL`, `GOOGLE_SHEET_ID`, `GOOGLE_SA_FILE`, `WEBHOOK_SECRET`.
   Generate the secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Google: create a service account, download its key as `service_account.json` into the project folder, create a sheet with the header row below, and share it with the service account's email as Editor. Check with `python sheets_smoke_test.py`.
4. Start the server: `python -m uvicorn app:app --port 8000`
5. In a second terminal:
   - `python simulate.py` sends all 10 leads, or `python simulate.py 1 9` sends just those.
   - `python simulate.py --bad` sends requests that must be rejected (expect 401, 401, 422).
   - The clickable demo is `http://localhost:8000/docs`.

Sheet header row: `received_at, name, email, phone, company, doors, message, rule_flags, score, reason, draft, latency_s`

## Results

Model: `claude-haiku-5-5`. Ten fake leads with expected scores written before the first run. Latency is `latency_s` from the sheet: seconds from receipt to the row being saved.

| # | Lead | Doors | Expected | Actual | Latency (s) |
| --- | --- | --- | --- | --- | --- |
| 1 | Maria Lopez, Oakline Property Group | 240 | 5 | 5 | 2.4 |
| 2 | Sam Ortiz, BrightKey Property Management | 1,200 | 5 | 5 | 2.5 |
| 3 | Dev Patel, Patel Residential Mgmt | 60 | 4 | 4 | 2.3 |
| 4 | Priya Nair, Northgate Property Mgmt (Spanish message) | 85 | 4 | 4 | 2.4 |
| 5 | Chris Moe (no company, no message) | 150 | 3 | 3 | 2.3 |
| 6 | Tom Reed, Reed Rentals | 4 | 2 | 2 | 2.6 |
| 7 | Jenna Wu, Summit Realty | 0 | 2 | 2 | 2.4 |
| 8 | Lena Fisch, Fisch HVAC Services | 0 | 1 | **2** | 2.5 |
| 9 | asdf (rules catch it, no Claude call) | 9,999 | 1 | 1 | 0.9 |
| 10 | Alex Kim, Test Co (prompt injection) | 12 | 1 | 1 | 2.1 |

- **Accuracy:** 9 of 10 exact; all 10 within one point of expected. Leads 9 and 10 both scored 1.
- **Latency (time to save):** min 0.9 s, median 2.4 s, max 2.6 s, against the 60 s target. Lead 9 is fastest because it skips Claude. This is not time-to-Discord, which is a little longer; the ping shows its own figure.
- **The miss:** lead 8, an HVAC vendor asking to partner, scored 2 ("adjacent at best") instead of 1. The rubric lists "vendor pitch" as 1 and "realtor/landlord" as 2, so the line between them is a judgment call that the prompt does not settle.
- **Injection (lead 10):** scored 1 with an empty draft; Claude's reason says it treated the message as an attempt to manipulate scoring.
- **Webhook protection:** a request with no secret or a wrong secret returns 401, and one with the right secret but a bad body (`number_of_doors: "many"`) returns 422. None of them wrote a row or a ping.

Small test set: 10 hand-written leads show the pipeline behaves as designed, not how accurate it would be on real leads. The door thresholds in the rubric (25 and 100) are assumptions, not Blaze's real cutoffs.

## Realism notes

- A real Meta Lead Ads webhook doesn't send these fields. It sends a `leadgen_id`, and the server fetches the answers from the Graph API. This build simulates the fetched result.
- In production the shared-secret header would be replaced by verifying Meta's `X-Hub-Signature-256` HMAC signature.
- The server runs on a laptop here; production needs an always-on host, retries, dedupe for repeat submissions, and an alert when any step fails.
