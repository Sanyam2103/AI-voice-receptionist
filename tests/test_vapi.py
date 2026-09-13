from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import app, get_chat_service
from grooming.booking import BookingService
from grooming.policy import ShopPolicy
from grooming.tools import ToolRegistry
from grooming.vapi import handle_vapi_request, parse_tool_calls, webhook_url
from tests.fakes import FakeCalendar, FakeContacts

ROOT = Path(__file__).resolve().parents[1]


def _registry(contacts=None) -> ToolRegistry:
    policy = ShopPolicy.load(ROOT / "shop_policy.json")
    return ToolRegistry(
        BookingService(policy, FakeCalendar(), contacts or FakeContacts()),
        policy,
    )


def test_webhook_url_normalizes_host_and_full_paths():
    expected = "https://foo.trycloudflare.com/api/vapi/webhook"
    assert webhook_url("foo.trycloudflare.com") == expected
    assert webhook_url("https://foo.trycloudflare.com") == expected
    assert webhook_url("https://foo.trycloudflare.com/") == expected
    assert webhook_url("https://foo.trycloudflare.com/api/vapi/webhook") == expected


def test_parses_tool_call_list_and_openai_nested_arguments():
    listed = parse_tool_calls(
        {
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "call_1",
                        "name": "policy_faq",
                        "arguments": {"topic": "hours"},
                    }
                ],
            }
        }
    )
    assert listed == [
        {"id": "call_1", "name": "policy_faq", "arguments": {"topic": "hours"}}
    ]

    nested = parse_tool_calls(
        {
            "message": {
                "type": "tool-calls",
                "toolCalls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "policy_faq",
                            "arguments": '{"topic": "prices"}',
                        },
                    }
                ],
            }
        }
    )
    assert nested[0]["arguments"] == {"topic": "prices"}


def test_tool_calls_run_registry_and_fill_phone_from_caller_id():
    contacts = FakeContacts()
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"customer": {"number": "+14155550190"}},
            "toolCallList": [
                {
                    "id": "toolu_faq",
                    "name": "policy_faq",
                    "arguments": {"topic": "name"},
                },
                {
                    "id": "toolu_find",
                    "name": "find_appointments",
                    "parameters": {},
                },
            ],
        }
    }
    response = handle_vapi_request(_registry(contacts), payload)
    faq = json.loads(response["results"][0]["result"])
    find = json.loads(response["results"][1]["result"])
    assert response["results"][0]["toolCallId"] == "toolu_faq"
    assert faq["status"] == "ok"
    assert "Maple Street" in json.dumps(faq["result"])
    assert find["status"] == "ok"
    assert contacts.calls[0]["phone"] == "4155550190"


def test_non_tool_events_return_empty_ack():
    assert handle_vapi_request(_registry(), {"message": {"type": "status-update"}}) == {}


def test_webhook_endpoint_returns_vapi_results():
    class FakeVoice:
        def __init__(self):
            self.tools = _registry()

    app.dependency_overrides[get_chat_service] = lambda: FakeVoice()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/vapi/webhook",
            json={
                "message": {
                    "type": "tool-calls",
                    "toolCallList": [
                        {
                            "id": "call_hours",
                            "name": "policy_faq",
                            "arguments": {"topic": "hours"},
                        }
                    ],
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["results"][0]["toolCallId"] == "call_hours"
        result = json.loads(body["results"][0]["result"])
        assert result["status"] == "ok"
        assert "tue" in json.dumps(result["result"]).lower()
    finally:
        app.dependency_overrides.clear()
