from __future__ import annotations

import json
from datetime import date as date_type
from typing import Any, Callable, Dict, List

from .booking import BookingError, BookingService, ConflictError, HandoffRequired
from .dates import describe_moment
from .policy import ShopPolicy


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str]):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOL_DEFINITIONS = [
    _tool(
        "check_availability",
        "Return actual available appointment starts for a date and service.",
        {
            "date": {"type": "string", "description": "ISO date, YYYY-MM-DD"},
            "service": {
                "type": "string",
                "enum": ["bath", "bath_and_trim", "full_groom"],
            },
        },
        ["date", "service"],
    ),
    _tool(
        "book_appointment",
        "Book after the customer has selected a slot. Name and phone are mandatory.",
        {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "dog_name": {"type": "string"},
            "service": {
                "type": "string",
                "enum": ["bath", "bath_and_trim", "full_groom"],
            },
            "start": {"type": "string", "description": "ISO datetime from availability"},
        },
        ["name", "phone", "dog_name", "service", "start"],
    ),
    _tool(
        "find_appointments",
        "Find future assistant-managed appointments matching a customer phone number.",
        {"phone": {"type": "string"}},
        ["phone"],
    ),
    _tool(
        "reschedule_appointment",
        "Move a matching appointment after checking availability.",
        {
            "event_id": {"type": "string"},
            "phone": {"type": "string"},
            "new_start": {"type": "string", "description": "ISO datetime"},
        },
        ["event_id", "phone", "new_start"],
    ),
    _tool(
        "cancel_appointment",
        "Cancel a matching appointment.",
        {"event_id": {"type": "string"}, "phone": {"type": "string"}},
        ["event_id", "phone"],
    ),
    _tool(
        "report_running_late",
        "Record a late arrival or request staff handoff when beyond policy.",
        {
            "event_id": {"type": "string"},
            "phone": {"type": "string"},
            "minutes_late": {"type": "integer", "minimum": 0},
        },
        ["event_id", "phone", "minutes_late"],
    ),
    _tool(
        "policy_faq",
        "Look up a shop-policy fact. Never answer a shop fact without this result. "
        "The breeds topic returns groom / consult / do-not-groom lists.",
        {
            "topic": {
                "type": "string",
                "enum": [
                    "hours",
                    "services",
                    "prices",
                    "vaccines",
                    "breeds",
                    "late_policy",
                    "name",
                ],
            }
        },
        ["topic"],
    ),
    _tool(
        "request_handoff",
        "Request staff follow-up for billing, medical, aggression, complaints, unsupported requests, or tool failures.",
        {
            "phone": {"type": "string", "description": "Use empty string if unknown"},
            "reason": {"type": "string"},
            "summary": {"type": "string"},
        },
        ["phone", "reason", "summary"],
    ),
]


class ToolRegistry:
    def __init__(self, bookings: BookingService, policy: ShopPolicy):
        self.bookings = bookings
        self.policy = policy
        self.handlers: Dict[str, Callable[..., Any]] = {
            "check_availability": self._availability,
            "book_appointment": bookings.book,
            "find_appointments": lambda phone: bookings.find_appointments(phone),
            "reschedule_appointment": bookings.reschedule,
            "cancel_appointment": bookings.cancel,
            "report_running_late": bookings.running_late,
            "policy_faq": self._faq,
            "request_handoff": bookings.handoff,
        }

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        handler = self.handlers.get(name)
        if handler is None:
            return json.dumps(
                {"status": "handoff", "error": "Unknown tool. Staff help is required."}
            )
        try:
            return json.dumps({"status": "ok", "result": handler(**arguments)})
        except ConflictError as exc:
            return json.dumps({"status": "conflict", "error": str(exc)})
        except HandoffRequired as exc:
            return json.dumps({"status": "handoff", "error": str(exc)})
        except BookingError as exc:
            return json.dumps({"status": "error", "error": str(exc)})
        except Exception:
            return json.dumps(
                {
                    "status": "handoff",
                    "error": "The booking tools failed. Do not claim success; arrange staff follow-up.",
                }
            )

    def _availability(self, date: str, service: str) -> Dict[str, Any]:
        slots = self.bookings.availability(date, service)
        day = date_type.fromisoformat(date)
        return {
            "date": date,
            "weekday": f"{day:%A}",
            "open": self.policy.hours_for(day) is not None,
            "slots": [
                {"start": slot, "label": describe_moment(slot)} for slot in slots
            ],
        }

    def _faq(self, topic: str) -> Any:
        answer = self.policy.faq(topic)
        if answer is None:
            raise HandoffRequired("That fact is not present in the shop policy.")
        return answer

