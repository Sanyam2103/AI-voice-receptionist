from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grooming.config import Settings
from grooming.google import GoogleCalendarGateway, get_google_credentials
from grooming.policy import ShopPolicy


def next_open_day(policy: ShopPolicy) -> date:
    candidate = datetime.now(policy.timezone).date() + timedelta(days=1)
    while policy.hours_for(candidate) is None:
        candidate += timedelta(days=1)
    return candidate


def main() -> None:
    settings = Settings.from_env()
    if not settings.google_calendar_id:
        raise SystemExit("Set GOOGLE_CALENDAR_ID in .env")
    policy = ShopPolicy.load(settings.policy_path)
    parser = argparse.ArgumentParser(description="Seed a known 60-minute calendar conflict.")
    parser.add_argument("--date", default=next_open_day(policy).isoformat())
    parser.add_argument("--time", default="10:00")
    args = parser.parse_args()
    start = datetime.fromisoformat(f"{args.date}T{args.time}").replace(
        tzinfo=policy.timezone
    )
    end = start + timedelta(minutes=60)
    credentials = get_google_credentials(
        settings.google_credentials_path,
        settings.google_token_path,
        oauth_port=settings.google_oauth_port,
    )
    calendar = GoogleCalendarGateway.from_credentials(
        credentials, settings.google_calendar_id
    )
    event = calendar.create_event(
        {
            "summary": "KNOWN TEST CONFLICT — safe to delete",
            "description": "Created by scripts/seed_conflict.py",
            "start": {"dateTime": start.isoformat(), "timeZone": str(policy.timezone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(policy.timezone)},
        }
    )
    print(f"Created conflict {event['id']} from {start.isoformat()} to {end.isoformat()}")


if __name__ == "__main__":
    main()

