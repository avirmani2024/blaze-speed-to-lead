# Build log

What we did and why. Newest entries at the bottom.

## Milestones 1-2: pipeline without the LLM

**Why no LLM yet:** PLAN.md says to get the dumb version working end to end first. Once a lead reaches the Sheet and Discord, everything after is improvement, not risk.

### Files
- `sheets_smoke_test.py`: checks Google auth on its own, before anything else, because Sheets is the slowest piece to set up. Appends one row and prints success or the exact error.
- `app.py`: the whole pipeline (CLAUDE.md: all logic in one file).
- `leads.json`: the 10 labeled test leads from PLAN.md, written before any scoring exists so we grade the model rather than agree with it. `.example` emails and 555 phones only.
- `simulate.py`: plays Facebook's server. Strips `expected_score` before posting. Takes an optional lead number (`python simulate.py 1`).
- Not recreated (already existed): `.gitignore`, `.env.example`, `requirements.txt`.

### Decisions and why
- **Secret check is a FastAPI dependency, not code in the handler.** Dependencies run before body validation, so a request with a missing or wrong secret always gets 401, never a 422 that leaks the schema. Compared with `hmac.compare_digest` on bytes (constant time; avoids a TypeError on non-ASCII). An unset `WEBHOOK_SECRET` rejects everything rather than accepting an empty secret.
- **200 returned before any work.** `process()` runs in `BackgroundTasks`, so slow steps can't make the sender time out and resend.
- **Rule checks follow PLAN.md exactly.** 555 phones are deliberately not flagged (all test phones are 555). Blank company/message is not flagged, so lead 5 still reaches Claude later. Name/company mash matches any whole word in `asdf/test/qwerty` or a single character, so "Test Co" gets one flag; one flag alone never skips Claude.
- **2+ flags = score 1, reason "failed rule checks", Claude skipped.** Saves cost and latency on obvious junk.
- **`score_with_claude` is a stub** returning score `None`; the Discord header shows `fit ?/5` until milestone 3.
- **Each step in `process()` has its own try/except** that logs and continues, so a Sheets failure still pings Discord and vice versa. Never lose a lead.
- **Sheet writes use `RAW`** (smoke test and `save_row`). Phones stay text (`+1 317...` isn't turned into a number), and lead-supplied text such as `=HYPERLINK(...)` can never run as a spreadsheet formula.
- **Discord errors log only the exception type and HTTP status.** httpx error messages include the request URL, and the Discord webhook URL is a secret. Message is truncated to 1,990 chars (limit 2,000).
- **Secrets only via `.env` + python-dotenv.** Nothing hardcoded, printed or logged.

### Latency numbers mean two different things
- Sheet `latency_s` = time from `received_at` to **the moment the row is saved** (time-to-save).
- Discord "x.x s after submit" = time from `received_at` to **the moment the ping is built** (time-to-ping), so it is slightly larger.
- These won't match exactly. That's intended; report whichever is named in the results table.

## Setup (environment)
- **Venv:** the first `python -m venv .venv` failed under miniconda (could not copy `venvlauncher.exe`) and left a broken `.venv.venv` folder. Fixed by deleting it and running `python -m venv --copies .venv`, then `pip install -r requirements.txt`.
- **Google:** service account `sheets-writer` in project `blaze-speed-to-lead`; sheet `Blaze Leads` shared with it as Editor; header row = the 12 columns. `service_account.json` is gitignored. Sheet ID comes from the sheet's URL, not from the JSON key.
- **`.env`** is created from `.env.example` (names only, committed). Real values live only in `.env` (gitignored). `.env.example` was checked and contains no secrets.
- `sheets_smoke_test.py` passed once `GOOGLE_SHEET_ID` was saved. Its first failure was an empty ID in the saved file (editor change not saved), which Google reports as "Page Not Found"; the script now prints one line for that case instead of an HTML page.

## Milestone 2 verification
- `python simulate.py 1 9` sent Maria and asdf. Both returned 200 and produced a sheet row and a Discord ping.
- Webhook protection verified: no secret = 401, wrong secret = 401, even with a malformed body. Right secret + `number_of_doors: "many"` = 422. None of these wrote a row or ping.
- `simulate.py` changes made along the way: accepts several lead numbers (`python simulate.py 1 9`; originally it silently ignored all but the first), a `--bad` mode that sends the three must-fail requests above, and a one-line usage message for a mistyped argument (a stray `\` crashed it).
- Why `--bad` lives in `simulate.py` and not `leads.json`: the secret is a header, not lead data, and `leads.json` is the scored test set (actual-vs-expected, latency stats); requests that never reach the pipeline have no score or latency.

## Milestone 3: Claude added
- **Model:** `MODEL = "claude-haiku-5-5"` in `app.py` (a code constant, not an `.env` setting). Haiku because latency is the headline metric and the task is small. To compare against Sonnet, change that string and rerun the same 10 leads.
- **`prompt.md`:** rubric (1-5), rules to treat `<lead>` contents as data, score injection attempts 1, 2-4 sentence draft with a 15-minute call offer, no pricing promises, empty draft for score 1. Added by me beyond PLAN.md: reply in the language of the lead's message (for lead 4, Spanish).
- **`score_with_claude`:** forced tool use (`record_lead_score`), validates score is an int 1-5 and reason non-empty, forces draft empty at score 1. Any failure raises; `process()` catches it and saves the lead with blank score and reason "manual review". Errors log only exception type and HTTP status.
- **Observed so far:** Maria Lopez scored 5 (3.5 s to save) with a reason naming her door count and owner-statement pain; asdf scored 1 via rules (1 s). The other 8 leads have not been run yet.
- **`expected_score`** is an answer key written before running anything. `simulate.py` strips it, so the server and Claude never see it. Only lead 9 gets a rule-based score; leads 7 and 8 (0 doors) have one flag and go to Claude; lead 10 must be caught by Claude itself.

## Concepts clarified (so the README and Loom are accurate)
- Secret check (401) = who may send; happens first, nothing saved. Rule flags = does the content look fake; happens after the 200 reply, never rejects; 2+ flags = score 1 without calling Claude. Flagged leads are still saved (never lose a lead).
- `MASH_WORDS` is the list of fake-name words (`asdf`, `test`, `qwerty`) used by the name/company check.

## Still to do
1. Run leads 2-8 and 10; record actual vs expected and min/median/max latency.
2. No-lost-leads test with a wrong Anthropic key (expect "manual review" in sheet and Discord), then restore the key.
3. Screenshots of the sheet and a Discord ping.
4. README with results table; `git log -p` secret search; commit and push.
5. Loom and submission form.
