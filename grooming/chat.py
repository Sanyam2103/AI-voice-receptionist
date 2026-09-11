from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

from .dates import describe_day
from .google import normalize_phone
from .policy import ShopPolicy
from .tools import TOOL_DEFINITIONS, ToolRegistry


class InMemorySessions:
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> tuple[str, Dict[str, Any]]:
        with self._lock:
            identifier = session_id or str(uuid4())
            return identifier, self._sessions.setdefault(
                identifier,
                {"messages": [], "phone": None, "contact_logged": False},
            )


class ChatService:
    def __init__(
        self,
        provider: Any,
        tools: ToolRegistry,
        policy: ShopPolicy,
        sessions: InMemorySessions | None = None,
    ):
        self.provider = provider
        self.tools = tools
        self.policy = policy
        self.sessions = sessions or InMemorySessions()

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        phone: str | None = None,
    ) -> Dict[str, str]:
        if not message.strip():
            raise ValueError("message cannot be empty")
        identifier, state = self.sessions.get_or_create(session_id)
        history: List[Dict[str, Any]] = state["messages"]
        self._remember_phone(state, phone or self._phone_from_text(message), message)

        history.append({"role": "user", "content": message})

        for _ in range(8):
            response = self.provider.create_message(
                system=self._system_prompt(state.get("phone")),
                messages=history,
                tools=TOOL_DEFINITIONS,
            )
            blocks = [self._block_dict(block) for block in response.content]
            history.append({"role": "assistant", "content": blocks})
            uses = [block for block in blocks if block.get("type") == "tool_use"]
            if not uses:
                text = "\n".join(
                    block.get("text", "")
                    for block in blocks
                    if block.get("type") == "text"
                ).strip()
                return {
                    "session_id": identifier,
                    "message": text
                    or "I’m sorry, but I need a staff member to help with that.",
                }
            results = []
            for use in uses:
                arguments = use.get("input", {}) or {}
                self._remember_phone(state, arguments.get("phone"), message)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": self.tools.execute(use["name"], arguments),
                    }
                )
            history.append({"role": "user", "content": results})

        return {
            "session_id": identifier,
            "message": "I couldn’t safely complete that request. A staff member needs to help.",
        }

    def _remember_phone(self, state: Dict[str, Any], raw: str | None, summary: str) -> None:
        digits = self._canonical_phone(raw)
        if not digits:
            return
        state["phone"] = digits
        if state.get("contact_logged"):
            return
        try:
            self.tools.bookings.touch_contact(
                digits, intent="inbound", summary=summary.strip()[:300]
            )
            state["contact_logged"] = True
        except Exception:
            state["contact_logged"] = False

    CALENDAR_DAYS = 21

    def _date_context(self) -> str:
        today = datetime.now(self.policy.timezone).date()
        lines = []
        for offset in range(self.CALENDAR_DAYS):
            day = today + timedelta(days=offset)
            hours = self.policy.hours_for(day)
            status = (
                f"open {hours[0]:%H:%M}-{hours[1]:%H:%M}" if hours else "CLOSED"
            )
            marker = {0: " (today)", 1: " (tomorrow)"}.get(offset, "")
            lines.append(
                f"- {day.isoformat()} is a {day:%A}{marker}: {status}"
            )
        return "\n".join(lines)

    def _system_prompt(self, caller_phone: str | None = None) -> str:
        moment = datetime.now(self.policy.timezone)
        now = f"{describe_day(moment.date())} at {moment:%H:%M} ({moment.isoformat()})"
        known_phone = (
            f"- The caller phone is already known: {caller_phone}. Use it for tools; "
            "do not ask them to repeat it.\n"
            if caller_phone
            else ""
        )
        collect_phone = (
            "- Before booking, collect customer name, dog name, service, and a selected offered time. "
            "Phone is already known.\n"
            if caller_phone
            else "- Before booking, collect customer name, phone, dog name, service, and a selected offered time.\n"
        )
        return f"""You are the customer assistant for {self.policy.data['name']}.
Current shop-local datetime: {now}.
All appointment times are in IST (Asia/Kolkata, UTC+05:30). Quote times in IST.

This calendar is the only correct mapping between dates and weekdays:
{self._date_context()}

Date rules:
- Never work out a weekday or date yourself. When the customer says a weekday name,
  "today", "tomorrow", or "next week", read the exact ISO date off the calendar above
  and pass that to the tools.
- If the wanted date is not in the calendar above, or the weekday and date the customer
  gave disagree, ask them to confirm the exact date before using any tool.
- Always name the weekday and date together when you offer or confirm a time, for
  example "Tuesday, 15 Sep at 14:00", so a wrong date is caught before booking.
- Confirm the weekday and date with the customer before book_appointment or
  reschedule_appointment. Tool results include a label; if it disagrees with what the
  customer asked for, say so and fix it instead of continuing.

Correctness rules:
{known_phone}- Use tools for every shop fact and appointment action. Never invent facts.
- Availability comes only from check_availability. Never imply a slot is free otherwise.
{collect_phone}- Never call book_appointment without both name and phone.
- For reschedule, cancellation, or late arrival, verify the appointment using phone and event ID.
- State that a mutation succeeded only when its tool returns status "ok".
- If a result says conflict, offer to check alternatives.
- Billing/charge complaints, medical questions or exceptions, aggression, unsupported special
  cuts, and every tool failure must use request_handoff. Do not provide medical advice.
- If policy_faq lacks a fact, say you do not know and hand off.
- Keep responses concise and do not expose internal tool details.

The JSON policy is the sole source of shop facts:
{json.dumps(self.policy.data, sort_keys=True)}
"""

    @staticmethod
    def _canonical_phone(value: str | None) -> str:
        digits = normalize_phone(value or "")
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits if len(digits) == 10 else ""

    @staticmethod
    def _phone_from_text(text: str) -> str:
        for match in re.finditer(
            r"(?:\+?91|\+?1)?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text
        ):
            digits = ChatService._canonical_phone(match.group(0))
            if digits:
                return digits
        return ""

    @staticmethod
    def _block_dict(block: Any) -> Dict[str, Any]:
        if isinstance(block, dict):
            return block
        if hasattr(block, "model_dump"):
            return block.model_dump()
        output = {"type": getattr(block, "type", "")}
        for key in ("id", "name", "input", "text"):
            if hasattr(block, key):
                output[key] = getattr(block, key)
        return output

