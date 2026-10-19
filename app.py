"""Blaze speed-to-lead: webhook + pipeline (milestones 1-2, no LLM yet)."""
import hmac
import json
import os
import re
import time
from pathlib import Path

import anthropic
import gspread
import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Blaze speed-to-lead")

MASH_WORDS = {"asdf", "test", "qwerty"}
SHEET_COLUMNS = [
    "received_at", "name", "email", "phone", "company", "doors",
    "message", "rule_flags", "score", "reason", "draft", "latency_s",
]


class Lead(BaseModel):
    full_name: str
    email: str
    phone: str
    company_name: str = ""
    number_of_doors: int
    message: str = ""


def check_secret(x_webhook_secret: str | None = Header(default=None)) -> None:
    # Runs before body validation, so a bad secret is always 401.
    expected = os.environ.get("WEBHOOK_SECRET", "")
    if not expected or not x_webhook_secret or not hmac.compare_digest(
        x_webhook_secret.encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/webhook", dependencies=[Depends(check_secret)])
def webhook(lead: Lead, background_tasks: BackgroundTasks):
    received_at = time.time()
    background_tasks.add_task(process, lead, received_at)
    return {"status": "received"}


def _is_mash(value: str) -> bool:
    v = value.strip().lower()
    if not v:
        return False  # blank is handled elsewhere (lead 5 must still reach Claude)
    return len(v) == 1 or any(w in MASH_WORDS for w in re.split(r"\W+", v))


def rule_checks(lead: Lead) -> list[str]:
    flags = []
    email = lead.email.strip()
    if "@" not in email or "." not in email.rsplit("@", 1)[1]:
        flags.append("bad_email")
    digits = re.sub(r"\D", "", lead.phone)
    if len(digits) < 10 or len(set(digits)) == 1 or digits == "1234567890":
        flags.append("bad_phone")
    if not 1 <= lead.number_of_doors <= 50000:
        flags.append("bad_doors")
    if _is_mash(lead.full_name):
        flags.append("mash_name")
    if _is_mash(lead.company_name):
        flags.append("mash_company")
    return flags


MODEL = "claude-haiku-5-5"
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
TOOL = {
    "name": "record_lead_score",
    "description": "Record the fit score and first-reply draft for one lead.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "reason": {"type": "string", "description": "One line, under 20 words"},
            "draft_reply": {"type": "string", "description": "2-4 sentences; empty if score is 1"},
        },
        "required": ["score", "reason", "draft_reply"],
    },
}


def score_with_claude(lead: Lead, flags: list[str]) -> dict:
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=30, max_retries=1
    )
    lead_json = json.dumps(lead.model_dump(), ensure_ascii=False, indent=2)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_lead_score"},
        messages=[{
            "role": "user",
            "content": f"<lead>\n{lead_json}\n</lead>\nRule flags: {flags}",
        }],
    )
    data = next(b.input for b in resp.content if b.type == "tool_use")
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError(f"score out of range: {score!r}")
    reason = " ".join(str(data.get("reason", "")).split())
    if not reason:
        raise ValueError("empty reason")
    draft = "" if score == 1 else str(data.get("draft_reply", "")).strip()
    return {"score": score, "reason": reason, "draft_reply": draft}


def save_row(lead: Lead, received_at: float, flags: list[str], result: dict) -> None:
    gc = gspread.service_account(filename=os.environ["GOOGLE_SA_FILE"])
    ws = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
    score = result["score"]
    row = [
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(received_at)),
        lead.full_name, lead.email, lead.phone, lead.company_name,
        lead.number_of_doors, lead.message, ", ".join(flags),
        "" if score is None else score,
        result["reason"], result["draft_reply"],
        round(time.time() - received_at, 1),
    ]
    # RAW: phones stay text and fields can never run as formulas.
    ws.append_row(row, value_input_option="RAW")


def format_discord(lead: Lead, received_at: float, result: dict) -> str:
    score = result["score"]
    fit = "?" if score is None else score
    elapsed = time.time() - received_at
    msg = (
        f"NEW LEAD  fit {fit}/5  ({elapsed:.1f} s after submit)\n"
        f"{lead.full_name} · {lead.company_name} · {lead.number_of_doors} doors\n"
        f"{lead.email} · {lead.phone}\n"
        f"Why: {result['reason']}\n\n"
        f"Draft reply:\n{result['draft_reply']}"
    )
    return msg[:1990]


def ping_discord(lead: Lead, received_at: float, result: dict) -> None:
    r = httpx.post(
        os.environ["DISCORD_WEBHOOK_URL"],
        json={"content": format_discord(lead, received_at, result)},
        timeout=10,
    )
    r.raise_for_status()


def process(lead: Lead, received_at: float) -> None:
    flags: list[str] = []
    result = {"score": None, "reason": "manual review", "draft_reply": ""}

    try:
        flags = rule_checks(lead)
        if len(flags) >= 2:
            result = {"score": 1, "reason": "failed rule checks", "draft_reply": ""}
        else:
            result = score_with_claude(lead, flags)
    except Exception as e:
        # Type and status only: keep API error bodies (and anything key-like) out of logs.
        status = getattr(e, "status_code", "")
        print(f"[scoring] {type(e).__name__} {status}", flush=True)

    try:
        save_row(lead, received_at, flags, result)
    except Exception as e:
        print(f"[sheets] {type(e).__name__}: {e}", flush=True)

    try:
        ping_discord(lead, received_at, result)
    except Exception as e:
        # Never log str(e): httpx errors include the webhook URL, which is a secret.
        status = getattr(getattr(e, "response", None), "status_code", "")
        print(f"[discord] {type(e).__name__} {status}", flush=True)
