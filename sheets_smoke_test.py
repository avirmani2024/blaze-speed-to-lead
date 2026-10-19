"""Google auth check: appends one test row to the sheet."""
import os
import time

import gspread
from dotenv import load_dotenv

load_dotenv()

try:
    gc = gspread.service_account(filename=os.environ["GOOGLE_SA_FILE"])
    ws = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
    ws.append_row(
        ["smoke test", time.strftime("%Y-%m-%d %H:%M:%S")], value_input_option="RAW"
    )
    print("SUCCESS: test row appended to the sheet.")
except Exception as e:
    msg = str(e)
    if "<html" in msg.lower():
        msg = "Google returned an HTML 'Page Not Found' page (check GOOGLE_SHEET_ID in .env)"
    print(f"FAILED: {type(e).__name__}: {msg[:300]}")
    raise SystemExit(1)
