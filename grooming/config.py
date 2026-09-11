from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


DEFAULT_OAUTH_PORT = 8080


def parse_oauth_port(value: str | None) -> int:
    raw = (value or "").strip() or str(DEFAULT_OAUTH_PORT)
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError("GOOGLE_OAUTH_PORT must be an integer") from exc
    if port < 0 or port > 65535:
        raise ValueError("GOOGLE_OAUTH_PORT must be between 0 and 65535")
    return port


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    google_calendar_id: str
    google_sheet_id: str
    google_credentials_path: Path
    google_token_path: Path
    policy_path: Path
    google_oauth_port: int = DEFAULT_OAUTH_PORT

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", ""),
            google_sheet_id=os.getenv("GOOGLE_SHEET_ID", ""),
            google_credentials_path=Path(
                os.getenv("GOOGLE_CREDENTIALS_PATH", str(ROOT / "credentials.json"))
            ),
            google_token_path=Path(
                os.getenv("GOOGLE_TOKEN_PATH", str(ROOT / "token.json"))
            ),
            policy_path=Path(os.getenv("SHOP_POLICY_PATH", str(ROOT / "shop_policy.json"))),
            google_oauth_port=parse_oauth_port(os.getenv("GOOGLE_OAUTH_PORT")),
        )

    def require_runtime(self) -> None:
        missing = [
            name
            for name, value in (
                ("ANTHROPIC_API_KEY", self.anthropic_api_key),
                ("GOOGLE_CALENDAR_ID", self.google_calendar_id),
                ("GOOGLE_SHEET_ID", self.google_sheet_id),
            )
            if not value
        ]
        if missing:
            raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

