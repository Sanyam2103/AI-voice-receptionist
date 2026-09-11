from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import DEFAULT_OAUTH_PORT

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
CONTACT_HEADERS = [
    "phone",
    "name",
    "dog_name",
    "last_intent",
    "last_summary",
    "last_contacted_at",
    "needs_followup",
    "followup_reason",
]
LAST_COLUMN = chr(ord("A") + len(CONTACT_HEADERS) - 1)


def normalize_phone(value: str) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def oauth_client_type(credentials_path: Path) -> str:
    """Return 'installed' (Desktop) or 'web' (Web application) from client JSON."""
    with credentials_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if "installed" in payload:
        return "installed"
    if "web" in payload:
        return "web"
    raise ValueError(
        "credentials.json must be a Desktop app (installed) or Web application "
        "OAuth client. Service accounts are not supported."
    )


def get_google_credentials(
    credentials_path: Path,
    token_path: Path,
    oauth_port: int = DEFAULT_OAUTH_PORT,
) -> Credentials:
    """Load user OAuth credentials, refreshing or running consent, then cache token.json.

    Desktop and Web client JSON both use a local loopback server. Web clients must
    list http://localhost:<GOOGLE_OAUTH_PORT>/ as an authorized redirect URI.
    """
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and not credentials.has_scopes(SCOPES):
        credentials = None
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google OAuth client credentials not found: {credentials_path}"
                )
            oauth_client_type(credentials_path)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            credentials = flow.run_local_server(
                host="localhost",
                port=oauth_port,
                redirect_uri_trailing_slash=True,
            )
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


class GoogleCalendarGateway:
    def __init__(self, service: Any, calendar_id: str):
        if not calendar_id:
            raise ValueError("GOOGLE_CALENDAR_ID is required")
        self.service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_credentials(cls, credentials: Credentials, calendar_id: str):
        return cls(build("calendar", "v3", credentials=credentials), calendar_id)

    def list_events(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        result = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])

    def event_bounds(self, event: Dict[str, Any], timezone) -> tuple[datetime, datetime]:
        if "dateTime" in event["start"]:
            start = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))
            return start.astimezone(timezone), end.astimezone(timezone)
        start_day = datetime.fromisoformat(event["start"]["date"]).date()
        end_day = datetime.fromisoformat(event["end"]["date"]).date()
        return (
            datetime.combine(start_day, time.min, timezone),
            datetime.combine(end_day, time.min, timezone),
        )

    def get_event(self, event_id: str) -> Dict[str, Any]:
        return (
            self.service.events()
            .get(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )

    def find_customer_events(
        self, phone: str, start: datetime, end: datetime
    ) -> List[Dict[str, Any]]:
        target = normalize_phone(phone)
        return [
            event
            for event in self.list_events(start, end)
            if event.get("extendedProperties", {}).get("private", {}).get("customer_phone")
            == target
        ]

    def create_event(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=body)
            .execute()
        )

    def update_event(self, event_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return (
            self.service.events()
            .update(calendarId=self.calendar_id, eventId=event_id, body=body)
            .execute()
        )

    def delete_event(self, event_id: str) -> None:
        (
            self.service.events()
            .delete(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )


class GoogleSheetsGateway:
    def __init__(self, service: Any, spreadsheet_id: str, timezone=None):
        if not spreadsheet_id:
            raise ValueError("GOOGLE_SHEET_ID is required")
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.timezone = timezone

    @classmethod
    def from_credentials(
        cls, credentials: Credentials, spreadsheet_id: str, timezone=None
    ):
        return cls(
            build("sheets", "v4", credentials=credentials), spreadsheet_id, timezone
        )

    def upsert_contact(self, phone: str, **fields: Any) -> Dict[str, str]:
        phone_digits = normalize_phone(phone)
        if not phone_digits:
            raise ValueError("phone is required")
        title = self._ensure_contacts_tab()
        rows = self._read_rows(title)
        row_number = None
        existing: List[str] = []
        for index, row in enumerate(rows[1:], start=2):
            padded = self._pad(row)
            if normalize_phone(padded[0]) == phone_digits:
                row_number, existing = index, padded
                break
        clock = datetime.now(self.timezone) if self.timezone else datetime.now().astimezone()
        now = clock.isoformat()
        values = self._merge_row(phone_digits, existing, fields, now)
        resource = self.service.spreadsheets().values()
        if row_number:
            resource.update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{title}'!A{row_number}:{LAST_COLUMN}{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [values]},
            ).execute()
        else:
            resource.append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{title}'!A:{LAST_COLUMN}",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            ).execute()
        return dict(zip(CONTACT_HEADERS, values))

    def _ensure_contacts_tab(self) -> str:
        metadata = (
            self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        title = next(
            (
                sheet["properties"]["title"]
                for sheet in metadata.get("sheets", [])
                if sheet["properties"]["title"].strip().lower() == "contacts"
            ),
            None,
        )
        if title is None:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": "Contacts"}}}]},
            ).execute()
            title = "Contacts"
        rows = self._read_rows(title)
        if not rows or self._pad(rows[0]) != CONTACT_HEADERS:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{title}'!A1:{LAST_COLUMN}1",
                valueInputOption="USER_ENTERED",
                body={"values": [CONTACT_HEADERS]},
            ).execute()
        return title

    def _read_rows(self, title: str) -> List[List[str]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"'{title}'!A:{LAST_COLUMN}")
            .execute()
        )
        return result.get("values", [])

    @staticmethod
    def _pad(row: List[str]) -> List[str]:
        return (list(row) + [""] * len(CONTACT_HEADERS))[: len(CONTACT_HEADERS)]

    def _merge_row(
        self, phone: str, existing: List[str], fields: Dict[str, Any], now: str
    ) -> List[str]:
        base = self._pad(existing)
        result: List[str] = []
        for index, header in enumerate(CONTACT_HEADERS):
            if header == "phone":
                value: Any = phone
            elif header == "last_contacted_at":
                value = fields.get(header) or now
            elif header in fields and fields[header] is not None:
                value = fields[header]
            else:
                value = base[index]
            if isinstance(value, bool):
                value = str(value).lower()
            result.append(str(value))
        return result

