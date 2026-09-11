from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from grooming.booking import BookingService
from grooming.chat import ChatService
from grooming.config import ROOT, Settings
from grooming.google import (
    GoogleCalendarGateway,
    GoogleSheetsGateway,
    get_google_credentials,
)
from grooming.policy import ShopPolicy
from grooming.provider import AnthropicProvider
from grooming.tools import ToolRegistry

logger = logging.getLogger(__name__)

app = FastAPI(title="Maple Street Dog Grooming Assistant")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = None
    phone: Optional[str] = Field(
        default=None,
        description="Caller ID when known (voice). Optional for text chat.",
    )


class ChatResponse(BaseModel):
    message: str
    session_id: str


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    settings = Settings.from_env()
    settings.require_runtime()
    credentials = get_google_credentials(
        settings.google_credentials_path,
        settings.google_token_path,
        oauth_port=settings.google_oauth_port,
    )
    policy = ShopPolicy.load(settings.policy_path)
    calendar = GoogleCalendarGateway.from_credentials(
        credentials, settings.google_calendar_id
    )
    contacts = GoogleSheetsGateway.from_credentials(
        credentials, settings.google_sheet_id, timezone=policy.timezone
    )
    bookings = BookingService(policy, calendar, contacts)
    tools = ToolRegistry(bookings, policy)
    provider = AnthropicProvider(
        settings.anthropic_api_key, settings.anthropic_model
    )
    return ChatService(provider, tools, policy)


@app.get("/")
def index():
    return FileResponse(Path(ROOT) / "static" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, service: ChatService = Depends(get_chat_service)):
    try:
        return service.chat(request.message, request.session_id, request.phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chat request failed")
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable; please contact the shop.",
        ) from exc

