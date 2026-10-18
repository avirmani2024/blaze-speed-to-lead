# Blaze speed-to-lead (Option B take-home)

2-hour build for a Blaze growth engineering internship. Blaze is an AI CFO for property managers. Their Facebook leads wait a median of 22 hours for first contact, and 44% are junk.

This pipeline receives a fake Facebook lead on a webhook, rule-checks it, has Claude score it 1–5 with a one-line reason and a draft first reply, appends it to a Google Sheet, and pings me on Discord in under 60 seconds.

The full plan with the reasoning is in `PLAN.md`. This file is the short version.

## Hard rules

- **Fake leads only.** Use `.example` email domains and 555 phone numbers.
- **Messages go only to me** (my private Discord channel). Never send anything to a lead.
- **No secrets in the repo.** `.env` and `service_account.json` are gitignored. Commit `.env.example` with names only.
- **Keep it small.** Eight files, all logic in `app.py`. Something small that works beats something big that doesn't.
- **No frontend.** The Sheet and Discord are the interface. FastAPI's `/docs` page is the clickable demo.

## Stack

- Python, FastAPI + uvicorn, Pydantic
- `gspread` with a Google service account
- `anthropic` SDK, model `claude-haiku-5-5`, structured output via forced tool use (`record_lead_score`)
- `httpx` for the Discord webhook and for `simulate.py`
- `python-dotenv` for secrets

## Files

```
app.py            FastAPI webhook + pipeline
prompt.md         scoring rubric + reply rules (system prompt, loaded by app.py)
simulate.py       posts each lead in leads.json to the webhook, prints latency
leads.json        10 fake leads, each with expected_score (stripped before posting)
requirements.txt  fastapi uvicorn gspread anthropic httpx python-dotenv
.env.example      ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL, GOOGLE_SHEET_ID, GOOGLE_SA_FILE, WEBHOOK_SECRET
.gitignore        .env, service_account.json, __pycache__/, .venv/
README.md         what it does, how to run, sample output, results table
```

## Pipeline in app.py

1. `POST /webhook` takes a Pydantic `Lead`: `full_name`, `email`, `phone`, `company_name`, `number_of_doors` (int), `message`.
2. Check the `X-Webhook-Secret` header against `WEBHOOK_SECRET` with `hmac.compare_digest`. Missing or wrong → 401, do nothing else.
3. Stamp `received_at`, add the lead to `BackgroundTasks`, return 200 `{"status": "received"}` immediately.
4. Background `process(lead)`:
   1. `rule_checks(lead)` returns a list of flags: bad email (no `@` or no dot after it), phone under 10 digits / one repeated digit / `1234567890`, doors not 1–50,000, keyboard-mash name or company (`asdf`, `test`, `qwerty`, single character). Two or more flags → score 1, reason "failed rule checks", empty draft, skip Claude.
   2. `score_with_claude(lead, flags)`: system prompt from `prompt.md`, lead JSON inside `<lead>` tags, `tool_choice` forced to `record_lead_score` with `score` (int 1–5), `reason` (one line), `draft_reply` (2–4 sentences, empty if score 1). Validate the score range.
   3. `save_row(...)` appends one row to the sheet.
   4. `ping_discord(...)` posts the message (keep under 2,000 chars) with elapsed seconds since `received_at`.

Each step in step 4 has its own `try/except`. Never lose a lead: if Claude fails, save with blank score and reason "manual review"; if Sheets fails, still ping Discord. Log errors to stdout.

## Sheet columns

`received_at, name, email, phone, company, doors, message, rule_flags, score, reason, draft, latency_s`

## Discord message format

```
NEW LEAD  fit 5/5  (x.x s after submit)
Maria Lopez · Oakline Property Group · 240 doors
maria@oaklinepm.example · +1 317 555 0142
Why: <reason>

Draft reply:
<draft>
```

## Build order (check each milestone before moving on)

1. Setup: `.gitignore` first, venv, install. Sheets smoke test writes a row; a test POST shows in Discord.
2. Pipeline without AI: webhook + secret + background task + rule checks + sheet + Discord. `python simulate.py` gives one row and one ping.
3. Add Claude: `prompt.md`, tool schema, fallback. Maria scores 4–5; "asdf" scores 1.
4. Test set: run all 10 leads; record actual vs expected and min/median/max latency. Lead 10 (prompt injection) must score 1.
5. README with results table and screenshots. Check `git log -p` for secrets before pushing.
