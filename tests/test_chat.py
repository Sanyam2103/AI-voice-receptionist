from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from grooming.booking import BookingService
from grooming.chat import ChatService
from grooming.policy import ShopPolicy
from grooming.provider import AnthropicProvider
from grooming.tools import ToolRegistry
from tests.fakes import FakeCalendar, FakeContacts

ROOT = Path(__file__).resolve().parents[1]


class ScriptedProvider:
    def __init__(self):
        self.calls = 0
        self.messages = None

    def create_message(self, **kwargs):
        self.calls += 1
        self.messages = deepcopy(kwargs["messages"])
        if self.calls == 1:
            return SimpleNamespace(
                content=[
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "policy_faq",
                        "input": {"topic": "vaccines"},
                    }
                ]
            )
        return SimpleNamespace(
            content=[{"type": "text", "text": "Rabies is required."}]
        )


def build_chat(provider, contacts=None):
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    contacts = contacts or FakeContacts()
    bookings = BookingService(policy, FakeCalendar(), contacts)
    return ChatService(provider, ToolRegistry(bookings, policy), policy), contacts


def test_chat_runs_anthropic_tool_loop_and_keeps_session():
    provider = ScriptedProvider()
    chat, _ = build_chat(provider)
    first = chat.chat("What vaccines do you require?")
    assert first["message"] == "Rabies is required."
    assert first["session_id"]
    tool_result = provider.messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "Anti-rabies" in tool_result["content"]

    second = chat.chat("Thanks", first["session_id"])
    assert second["session_id"] == first["session_id"]


def test_tool_failures_return_handoff_without_exception_details():
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    contacts = FakeContacts(fail=True)
    registry = ToolRegistry(
        BookingService(policy, FakeCalendar(), contacts), policy
    )
    output = json.loads(
        registry.execute(
            "request_handoff",
            {"phone": "4155550190", "reason": "medical", "summary": "question"},
        )
    )
    assert output["status"] == "handoff"
    assert "logging" in output["error"]


def test_policy_faq_breeds_includes_groom_consult_and_do_not_groom():
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    registry = ToolRegistry(
        BookingService(policy, FakeCalendar(), FakeContacts()), policy
    )
    output = json.loads(registry.execute("policy_faq", {"topic": "breeds"}))
    assert output["status"] == "ok"
    breeds = output["result"]
    assert "husky" in breeds["breeds_need_consult"]
    assert "wolf hybrid" in breeds["breeds_we_dont"]
    assert "poodle" in breeds["breeds_we_groom"]
    assert set(breeds) == {
        "breeds_we_groom",
        "breeds_need_consult",
        "breeds_we_dont",
    }


class TextOnlyProvider:
    def create_message(self, **kwargs):
        self.system = kwargs["system"]
        return SimpleNamespace(content=[{"type": "text", "text": "Mon–Fri 10 to 7."}])


def test_known_caller_phone_upserts_contact_without_a_booking_tool():
    provider = TextOnlyProvider()
    chat, contacts = build_chat(provider)
    first = chat.chat("What are your hours?", phone="415-555-0190")
    second = chat.chat("Thanks", first["session_id"], phone="415-555-0190")
    assert len(contacts.calls) == 1
    assert contacts.calls[0]["phone"] == "4155550190"
    assert contacts.calls[0]["last_intent"] == "inbound"
    assert "4155550190" in provider.system
    assert second["session_id"] == first["session_id"]


def test_phone_typed_in_chat_is_logged_without_caller_id():
    chat, contacts = build_chat(TextOnlyProvider())
    chat.chat("Hi, my number is 415-555-0190 and I have 2 dogs.")
    assert contacts.calls[0]["phone"] == "4155550190"


def test_faq_without_phone_does_not_write_contacts():
    chat, contacts = build_chat(TextOnlyProvider())
    chat.chat("What vaccines do you require?")
    assert contacts.calls == []


def test_system_prompt_maps_every_date_to_its_real_weekday():
    provider = TextOnlyProvider()
    chat, _ = build_chat(provider)
    chat.chat("Can I book on Tuesday?")
    lines = [
        line for line in provider.system.splitlines() if re.match(r"- \d{4}-", line)
    ]
    assert len(lines) == chat.CALENDAR_DAYS
    for line in lines:
        day, weekday = re.match(r"- (\S+) is a (\w+)", line).groups()
        expected = date.fromisoformat(day)
        assert weekday == expected.strftime("%A")
        closed = expected.weekday() >= 5
        assert ("CLOSED" in line) is closed


def test_availability_results_label_the_weekday():
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    registry = ToolRegistry(
        BookingService(policy, FakeCalendar(), FakeContacts()), policy
    )
    saturday = json.loads(
        registry.execute("check_availability", {"date": "2026-09-12", "service": "bath"})
    )["result"]
    assert saturday == {
        "date": "2026-09-12",
        "weekday": "Saturday",
        "open": False,
        "slots": [],
    }


def test_provider_is_thin_direct_sdk_wrapper():
    fake_messages = SimpleNamespace(create=lambda **kwargs: kwargs)
    fake_client = SimpleNamespace(messages=fake_messages)
    provider = AnthropicProvider("", "test-model", client=fake_client)
    result = provider.create_message(
        system="rules", messages=[{"role": "user", "content": "hi"}], tools=[]
    )
    assert result["model"] == "test-model"
    assert result["temperature"] == 0
    assert result["messages"][0]["content"] == "hi"

