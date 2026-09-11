from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grooming.config import Settings
from grooming.google import (
    GoogleCalendarGateway,
    GoogleSheetsGateway,
    get_google_credentials,
)
from grooming.policy import ShopPolicy


def main() -> None:
    settings = Settings.from_env()
    if not settings.google_calendar_id or not settings.google_sheet_id:
        raise SystemExit("Set GOOGLE_CALENDAR_ID and GOOGLE_SHEET_ID in .env")
    credentials = get_google_credentials(
        settings.google_credentials_path,
        settings.google_token_path,
        oauth_port=settings.google_oauth_port,
    )
    policy = ShopPolicy.load(settings.policy_path)
    calendar = GoogleCalendarGateway.from_credentials(
        credentials, settings.google_calendar_id
    )
    sheets = GoogleSheetsGateway.from_credentials(credentials, settings.google_sheet_id)
    now = datetime.now(policy.timezone)
    events = calendar.list_events(now, now + timedelta(days=7))
    sheets.service.spreadsheets().get(
        spreadsheetId=settings.google_sheet_id
    ).execute()
    print(f"Google connection OK: {len(events)} calendar event(s) in next 7 days; sheet readable")


if __name__ == "__main__":
    main()

