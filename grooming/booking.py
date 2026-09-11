from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List

from .dates import describe_moment
from .google import normalize_phone
from .policy import ShopPolicy


class BookingError(Exception):
    pass


class ConflictError(BookingError):
    pass


class HandoffRequired(BookingError):
    pass


class BookingService:
    def __init__(
        self,
        policy: ShopPolicy,
        calendar: Any,
        contacts: Any,
        now: Callable[[], datetime] | None = None,
    ):
        self.policy = policy
        self.calendar = calendar
        self.contacts = contacts
        self.now = now or (lambda: datetime.now(self.policy.timezone))

    def availability(self, day: str, service: str) -> List[str]:
        target_day = date.fromisoformat(day)
        hours = self.policy.hours_for(target_day)
        duration = timedelta(minutes=self.policy.duration_minutes(service))
        if hours is None:
            return []
        opening, closing = hours
        events = self.calendar.list_events(opening, closing)
        slots: List[str] = []
        candidate = opening
        current = self.now().astimezone(self.policy.timezone)
        while candidate + duration <= closing:
            if candidate >= current and not self._has_conflict(candidate, candidate + duration, events):
                slots.append(candidate.isoformat())
            candidate += timedelta(minutes=self.policy.slot_minutes)
        return slots

    def book(
        self,
        *,
        name: str,
        phone: str,
        dog_name: str,
        service: str,
        start: str,
    ) -> Dict[str, Any]:
        self._require_identity(name, phone)
        begin, end = self._validate_slot(start, service)
        # Correctness boundary: fetch the calendar again immediately before writing.
        if self._has_conflict(begin, end, self.calendar.list_events(begin, end)):
            raise ConflictError("That time is no longer available. Please choose another slot.")
        body = self._event_body(name, phone, dog_name, service, begin, end)
        event = self.calendar.create_event(body)
        try:
            self._log(
                phone,
                name=name,
                dog_name=dog_name,
                intent="book",
                summary=f"Booked {service} for {begin.isoformat()} (event {event['id']})",
            )
        except Exception as exc:
            try:
                self.calendar.delete_event(event["id"])
            finally:
                raise HandoffRequired(
                    "Booking could not be safely completed because contact logging failed."
                ) from exc
        return self._public_event(event)

    def find_appointments(self, phone: str) -> List[Dict[str, Any]]:
        digits = normalize_phone(phone)
        if not digits:
            raise BookingError("A phone number is required.")
        current = self.now().astimezone(self.policy.timezone)
        events = self.calendar.find_customer_events(
            digits, current - timedelta(days=1), current + timedelta(days=365)
        )
        return [self._public_event(event) for event in events]

    def reschedule(
        self, *, event_id: str, phone: str, new_start: str
    ) -> Dict[str, Any]:
        event = self._owned_event(event_id, phone)
        private = event.get("extendedProperties", {}).get("private", {})
        service = private.get("service")
        if not service:
            raise HandoffRequired("The appointment is missing its service details.")
        begin, end = self._validate_slot(new_start, service)
        events = [
            item
            for item in self.calendar.list_events(begin, end)
            if item.get("id") != event_id
        ]
        if self._has_conflict(begin, end, events):
            raise ConflictError("That time is no longer available. Please choose another slot.")
        old_event = dict(event)
        updated_body = self._writable_event(event)
        updated_body["start"] = {"dateTime": begin.isoformat(), "timeZone": str(self.policy.timezone)}
        updated_body["end"] = {"dateTime": end.isoformat(), "timeZone": str(self.policy.timezone)}
        updated = self.calendar.update_event(event_id, updated_body)
        try:
            self._log(
                phone,
                name=private.get("customer_name", ""),
                dog_name=private.get("dog_name", ""),
                intent="reschedule",
                summary=f"Rescheduled {event_id} to {begin.isoformat()}",
            )
        except Exception as exc:
            try:
                self.calendar.update_event(event_id, self._writable_event(old_event))
            finally:
                raise HandoffRequired(
                    "Reschedule could not be safely completed because contact logging failed."
                ) from exc
        return self._public_event(updated)

    def cancel(self, *, event_id: str, phone: str) -> Dict[str, Any]:
        event = self._owned_event(event_id, phone)
        private = event.get("extendedProperties", {}).get("private", {})
        self.calendar.delete_event(event_id)
        try:
            self._log(
                phone,
                name=private.get("customer_name", ""),
                dog_name=private.get("dog_name", ""),
                intent="cancel",
                summary=f"Cancelled appointment {event_id}",
            )
        except Exception as exc:
            try:
                self.calendar.create_event(self._writable_event(event))
            finally:
                raise HandoffRequired(
                    "Cancellation could not be safely completed because contact logging failed."
                ) from exc
        return {"status": "cancelled", "event_id": event_id}

    def running_late(
        self, *, event_id: str, phone: str, minutes_late: int
    ) -> Dict[str, Any]:
        if minutes_late < 0:
            raise BookingError("Minutes late cannot be negative.")
        event = self._owned_event(event_id, phone)
        if minutes_late > self.policy.late_policy_minutes:
            self._followup(
                phone,
                "running_late",
                f"Customer expects to be {minutes_late} minutes late for {event_id}",
                "Late beyond shop policy",
            )
            raise HandoffRequired(
                f"Arrivals over {self.policy.late_policy_minutes} minutes late require staff help."
            )
        private = event.get("extendedProperties", {}).get("private", {})
        old_event = dict(event)
        body = self._writable_event(event)
        note = f"Customer reported running {minutes_late} minutes late."
        body["description"] = "\n".join(filter(None, [body.get("description", ""), note]))
        updated = self.calendar.update_event(event_id, body)
        try:
            self._log(
                phone,
                name=private.get("customer_name", ""),
                dog_name=private.get("dog_name", ""),
                intent="running_late",
                summary=f"{minutes_late} minutes late for {event_id}",
            )
        except Exception as exc:
            try:
                self.calendar.update_event(event_id, self._writable_event(old_event))
            finally:
                raise HandoffRequired(
                    "The late notice could not be safely recorded."
                ) from exc
        return {"status": "noted", "event": self._public_event(updated)}

    def handoff(self, phone: str, reason: str, summary: str) -> Dict[str, Any]:
        if normalize_phone(phone):
            self._followup(phone, "handoff", summary, reason)
        return {
            "status": "handoff",
            "reason": reason,
            "message": "A staff member needs to help with this request.",
        }

    def touch_contact(
        self, phone: str, *, intent: str = "inbound", summary: str = ""
    ) -> str:
        """Best-effort Contacts upsert once a phone is known. Empty/invalid is a no-op."""
        digits = normalize_phone(phone)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            return ""
        self.contacts.upsert_contact(
            digits,
            last_intent=intent,
            last_summary=summary,
            needs_followup=False,
            followup_reason="",
        )
        return digits

    def _validate_slot(self, start: str, service: str) -> tuple[datetime, datetime]:
        duration = timedelta(minutes=self.policy.duration_minutes(service))
        begin = datetime.fromisoformat(start)
        if begin.tzinfo is None:
            begin = begin.replace(tzinfo=self.policy.timezone)
        begin = begin.astimezone(self.policy.timezone)
        hours = self.policy.hours_for(begin.date())
        if hours is None:
            raise BookingError("The shop is closed that day.")
        opening, closing = hours
        if begin < self.now().astimezone(self.policy.timezone):
            raise BookingError("Appointments must be in the future.")
        if begin < opening or begin + duration > closing:
            raise BookingError("The appointment would fall outside shop hours.")
        minutes_from_open = int((begin - opening).total_seconds() // 60)
        if minutes_from_open % self.policy.slot_minutes:
            raise BookingError(
                f"Appointments must start on a {self.policy.slot_minutes}-minute boundary."
            )
        return begin, begin + duration

    def _owned_event(self, event_id: str, phone: str) -> Dict[str, Any]:
        digits = normalize_phone(phone)
        if not digits:
            raise BookingError("A phone number is required.")
        event = self.calendar.get_event(event_id)
        owner = event.get("extendedProperties", {}).get("private", {}).get("customer_phone")
        if owner != digits:
            raise BookingError("That appointment does not match this phone number.")
        return event

    def _has_conflict(
        self, start: datetime, end: datetime, events: List[Dict[str, Any]]
    ) -> bool:
        for event in events:
            if event.get("status") == "cancelled":
                continue
            event_start, event_end = self.calendar.event_bounds(
                event, self.policy.timezone
            )
            if event_start < end and event_end > start:
                return True
        return False

    def _event_body(
        self,
        name: str,
        phone: str,
        dog_name: str,
        service: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        return {
            "summary": f"{dog_name} — {service.replace('_', ' ')}",
            "description": f"Customer: {name}\nPhone: {phone}",
            "start": {"dateTime": start.isoformat(), "timeZone": str(self.policy.timezone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(self.policy.timezone)},
            "extendedProperties": {
                "private": {
                    "managed_by": "maple_street_assistant",
                    "customer_name": name,
                    "customer_phone": normalize_phone(phone),
                    "dog_name": dog_name,
                    "service": service,
                }
            },
        }

    @staticmethod
    def _writable_event(event: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "summary",
            "description",
            "location",
            "start",
            "end",
            "extendedProperties",
            "attendees",
            "reminders",
            "colorId",
            "transparency",
            "visibility",
        }
        return {key: value for key, value in event.items() if key in allowed}

    @staticmethod
    def _public_event(event: Dict[str, Any]) -> Dict[str, Any]:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
            "date"
        )
        return {
            "event_id": event.get("id"),
            "summary": event.get("summary"),
            "start": start,
            "start_label": describe_moment(start),
            "end": event.get("end", {}).get("dateTime")
            or event.get("end", {}).get("date"),
        }

    def _log(
        self, phone: str, *, name: str, dog_name: str, intent: str, summary: str
    ) -> None:
        self.contacts.upsert_contact(
            phone,
            name=name,
            dog_name=dog_name,
            last_intent=intent,
            last_summary=summary,
            needs_followup=False,
            followup_reason="",
        )

    def _followup(self, phone: str, intent: str, summary: str, reason: str) -> None:
        try:
            self.contacts.upsert_contact(
                phone,
                last_intent=intent,
                last_summary=summary,
                needs_followup=True,
                followup_reason=reason,
            )
        except Exception as exc:
            raise HandoffRequired(
                "Staff follow-up is required, but contact logging also failed."
            ) from exc

    @staticmethod
    def _require_identity(name: str, phone: str) -> None:
        if not name.strip() or not normalize_phone(phone):
            raise BookingError("Both customer name and phone number are required to book.")

