# Maple Street Dog Grooming Assistant

Phase 1 customer chat assistant built with FastAPI, the direct Anthropic Python SDK,
Google Calendar, and Google Sheets. The shop's hours, service durations, prices, and
other FAQ facts come only from `shop_policy.json`. Times are in IST
(`Asia/Kolkata`). Prices are in INR.

## What it does

- Answers policy-backed FAQs without inventing missing facts.
- Finds availability from shop hours, service duration, and live Calendar events.
- Books only after collecting a customer name and phone, and checks conflicts again
  immediately before every Calendar write.
- Finds, reschedules, and cancels assistant-managed appointments by phone number.
- Records running-late notices; notices beyond 15 minutes require staff follow-up.
- Upserts a Contacts row as soon as a phone is known (voice caller ID, a number
  typed in chat, or a tool argument). Appointment mutations still update that row.
- Hands billing/charge complaints, medical issues, aggression, unsupported services,
  and tool failures to staff.
- Keeps chat sessions in process memory (they reset when the server restarts).

## Prerequisites

- Python 3.10 or newer
- An Anthropic API key
- A Google Cloud OAuth **Desktop app** or **Web application** client for the
  shop user's account (not a service account)
- Google Calendar API and Google Sheets API enabled in that Google Cloud project
- A target Google Calendar and Google Sheet accessible by the consenting user

This project uses user OAuth on a local loopback server. Do not create or use a
service account.

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy your existing OAuth client JSON to `credentials.json` in this directory
   (Desktop `installed` or Web `web` clients are both supported). It is ignored
   by Git.

3. Copy `.env.example` to `.env` and set:

   - `ANTHROPIC_API_KEY`
   - `ANTHROPIC_MODEL` if a different Claude model is desired
   - `GOOGLE_CALENDAR_ID` (`primary` is valid)
   - `GOOGLE_SHEET_ID` from the spreadsheet URL
   - `GOOGLE_OAUTH_PORT` if you cannot use `8080` (default is `8080`)

   For a **Web application** client, add this authorized redirect URI in Google
   Cloud Console so it matches the local consent server exactly:

   `http://localhost:8080/`

   Desktop clients typically allow any localhost port; this project still uses
   `8080` unless you override `GOOGLE_OAUTH_PORT`.

4. Authorize and verify Google:

   ```bash
   python scripts/google_ping.py
   ```

   A browser consent flow opens the first time at `http://localhost:8080/` and
   caches user credentials in `token.json`, which is also ignored by Git. If an
   older token was created with narrower scopes, remove `token.json` and run the
   command again.

5. Start the app:

   ```bash
   uvicorn app:app --reload
   ```

   Open <http://127.0.0.1:8000>. The health check is at `/health`; chat requests use
   `POST /api/chat` with `{"message": "...", "session_id": null, "phone": null}`.
   For voice, send the caller ID as `phone` on every turn so Contacts is upserted
   even before a booking. Text chat can omit `phone`; a 10-digit number in the
   message is also recorded.

The app creates a `Contacts` tab if needed and maintains these columns:
`phone`, `name`, `dog_name`, `last_intent`, `last_summary`,
`last_contacted_at`, `needs_followup`, and `followup_reason`.

## Conflict smoke test

Create an obvious 60-minute event on the next open day at 10:00:

```bash
python scripts/seed_conflict.py
```

Or choose an open date and time:

```bash
python scripts/seed_conflict.py --date 2026-09-14 --time 14:00
```

`--time` is shop-local IST on an open day. Default is `10:00`, which is opening time.
```

The event is named `KNOWN TEST CONFLICT — safe to delete`. Ask the assistant for
availability around that time, verify the overlap is excluded, then delete the event.

## Automated tests

```bash
pytest -q
```

Tests use in-memory fakes and a scripted Claude provider. They do not call Anthropic
or Google.

## Safety and consistency notes

Calendar events created by the assistant store customer matching data in private
extended properties. Existing unrelated events still block availability but cannot be
changed by the assistant. If a Contacts write fails after a Calendar mutation, the
service attempts to roll back the Calendar change and requires staff handoff rather
than claiming success.

Keep `shop_policy.json` accurate: it is the sole source of shop-policy facts.

