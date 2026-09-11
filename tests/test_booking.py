from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from grooming.booking import BookingError, BookingService, ConflictError, HandoffRequired
from grooming.policy import ShopPolicy
from tests.fakes import FakeCalendar, FakeContacts, event

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-09-10T12:00:00+05:30")


def service(events=None, contacts=None):
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    calendar = FakeCalendar(events)
    contacts = contacts or FakeContacts()
    return BookingService(policy, calendar, contacts, now=lambda: NOW), calendar, contacts


def test_availability_uses_duration_hours_and_calendar_events():
    busy = event(
        "busy",
        "2026-09-11T11:00:00+05:30",
        "2026-09-11T12:00:00+05:30",
    )
    bookings, _, _ = service([busy])
    slots = bookings.availability("2026-09-11", "full_groom")

    assert "2026-09-11T10:00:00+05:30" not in slots
    assert "2026-09-11T10:30:00+05:30" not in slots
    assert "2026-09-11T11:00:00+05:30" not in slots
    assert "2026-09-11T11:30:00+05:30" not in slots
    assert "2026-09-11T12:00:00+05:30" in slots
    assert "2026-09-11T18:00:00+05:30" not in slots


def test_closed_day_has_no_availability():
    bookings, _, _ = service()
    assert bookings.availability("2026-09-12", "bath") == []  # Saturday
    assert bookings.availability("2026-09-13", "bath") == []  # Sunday


@pytest.mark.parametrize(
    ("name", "phone"),
    [("", "4155550190"), ("Sara", ""), (" ", "not-a-phone")],
)
def test_booking_never_writes_without_name_and_phone(name, phone):
    bookings, calendar, _ = service()
    with pytest.raises(BookingError):
        bookings.book(
            name=name,
            phone=phone,
            dog_name="Fido",
            service="bath",
            start="2026-09-11T13:00:00+05:30",
        )
    assert calendar.events == {}


def test_booking_rechecks_conflicts_immediately_before_write():
    busy = event(
        "busy",
        "2026-09-11T13:00:00+05:30",
        "2026-09-11T13:30:00+05:30",
    )
    bookings, calendar, _ = service([busy])
    with pytest.raises(ConflictError):
        bookings.book(
            name="Sara",
            phone="415-555-0190",
            dog_name="Fido",
            service="bath",
            start="2026-09-11T13:00:00+05:30",
        )
    assert calendar.list_calls == 1
    assert set(calendar.events) == {"busy"}


def test_successful_booking_is_logged_to_contacts():
    bookings, calendar, contacts = service()
    result = bookings.book(
        name="Sara",
        phone="415-555-0190",
        dog_name="Fido",
        service="bath",
        start="2026-09-11T13:00:00+05:30",
    )
    assert result["event_id"] in calendar.events
    assert contacts.calls[-1]["last_intent"] == "book"
    assert contacts.calls[-1]["needs_followup"] is False


def test_booking_rolls_back_when_contact_log_fails():
    contacts = FakeContacts(fail=True)
    bookings, calendar, _ = service(contacts=contacts)
    with pytest.raises(HandoffRequired):
        bookings.book(
            name="Sara",
            phone="415-555-0190",
            dog_name="Fido",
            service="bath",
            start="2026-09-11T13:00:00+05:30",
        )
    assert calendar.events == {}


def test_reschedule_rechecks_and_logs():
    existing = event(
        "mine",
        "2026-09-11T13:00:00+05:30",
        "2026-09-11T13:30:00+05:30",
    )
    bookings, calendar, contacts = service([existing])
    result = bookings.reschedule(
        event_id="mine",
        phone="415-555-0190",
        new_start="2026-09-14T14:00:00+05:30",
    )
    assert result["start"] == "2026-09-14T14:00:00+05:30"
    assert calendar.list_calls == 1
    assert contacts.calls[-1]["last_intent"] == "reschedule"


def test_cancellation_requires_matching_phone_and_logs():
    existing = event(
        "mine",
        "2026-09-11T13:00:00+05:30",
        "2026-09-11T13:30:00+05:30",
    )
    bookings, calendar, contacts = service([existing])
    with pytest.raises(BookingError):
        bookings.cancel(event_id="mine", phone="2125550000")
    result = bookings.cancel(event_id="mine", phone="4155550190")
    assert result == {"status": "cancelled", "event_id": "mine"}
    assert "mine" not in calendar.events
    assert contacts.calls[-1]["last_intent"] == "cancel"


def test_running_late_beyond_policy_hands_off_and_marks_followup():
    existing = event(
        "mine",
        "2026-09-11T13:00:00+05:30",
        "2026-09-11T13:30:00+05:30",
    )
    bookings, _, contacts = service([existing])
    with pytest.raises(HandoffRequired):
        bookings.running_late(
            event_id="mine", phone="4155550190", minutes_late=20
        )
    assert contacts.calls[-1]["needs_followup"] is True
    assert contacts.calls[-1]["last_intent"] == "running_late"


def test_touch_contact_upserts_valid_phone_and_ignores_junk():
    bookings, _, contacts = service()
    assert bookings.touch_contact("not a number") == ""
    assert contacts.calls == []
    assert bookings.touch_contact("415-555-0190", summary="asked hours") == "4155550190"
    assert contacts.calls[-1]["phone"] == "4155550190"
    assert contacts.calls[-1]["last_intent"] == "inbound"
    assert contacts.calls[-1]["last_summary"] == "asked hours"

