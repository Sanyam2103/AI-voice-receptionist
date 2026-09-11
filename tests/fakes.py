from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List


class FakeCalendar:
    def __init__(self, events: List[Dict[str, Any]] | None = None):
        self.events = {event["id"]: deepcopy(event) for event in (events or [])}
        self.list_calls = 0
        self.deleted: List[str] = []

    def list_events(self, start, end):
        self.list_calls += 1
        return [
            deepcopy(event)
            for event in self.events.values()
            if event.get("status") != "cancelled"
            and self.event_bounds(event, start.tzinfo)[0] < end
            and self.event_bounds(event, start.tzinfo)[1] > start
        ]

    @staticmethod
    def event_bounds(event, timezone):
        return (
            datetime.fromisoformat(event["start"]["dateTime"]).astimezone(timezone),
            datetime.fromisoformat(event["end"]["dateTime"]).astimezone(timezone),
        )

    def create_event(self, body):
        event = deepcopy(body)
        event["id"] = f"event-{len(self.events) + 1}"
        self.events[event["id"]] = event
        return deepcopy(event)

    def get_event(self, event_id):
        return deepcopy(self.events[event_id])

    def update_event(self, event_id, body):
        event = deepcopy(body)
        event["id"] = event_id
        self.events[event_id] = event
        return deepcopy(event)

    def delete_event(self, event_id):
        self.deleted.append(event_id)
        del self.events[event_id]

    def find_customer_events(self, phone, start, end):
        return [
            event
            for event in self.list_events(start, end)
            if event.get("extendedProperties", {}).get("private", {}).get(
                "customer_phone"
            )
            == phone
        ]


class FakeContacts:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    def upsert_contact(self, phone, **fields):
        if self.fail:
            raise RuntimeError("sheet unavailable")
        row = {"phone": phone, **fields}
        self.calls.append(row)
        return row


def event(
    event_id: str,
    start: str,
    end: str,
    phone: str = "4155550190",
    service: str = "bath",
):
    return {
        "id": event_id,
        "summary": "Fido — bath",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "extendedProperties": {
            "private": {
                "customer_phone": phone,
                "customer_name": "Sara",
                "dog_name": "Fido",
                "service": service,
            }
        },
    }

