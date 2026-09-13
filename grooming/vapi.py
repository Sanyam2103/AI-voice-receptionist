from __future__ import annotations

import inspect
import json
from typing import Any, Callable, Dict, List, Mapping
from urllib.parse import urlparse

from .chat import ChatService
from .tools import TOOL_DEFINITIONS, ToolRegistry

TOOL_CALL_TYPES = {"tool-calls", "tool.calls"}
WEBHOOK_PATH = "/api/vapi/webhook"


def webhook_url(host_or_url: str) -> str:
    """Normalize a tunnel host or URL to the FastAPI Vapi webhook."""
    raw = (host_or_url or "").strip()
    if not raw:
        raise ValueError("tunnel URL is empty")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"invalid tunnel URL: {host_or_url}")
    return f"{parsed.scheme}://{parsed.netloc}{WEBHOOK_PATH}"


def vapi_function_specs() -> List[Dict[str, Any]]:
    """Dashboard/API tool bodies. Set each tool's server.url to the tunnel webhook."""
    specs = []
    for definition in TOOL_DEFINITIONS:
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "parameters": definition["input_schema"],
                },
                "server": {"url": "https://YOUR-TUNNEL/api/vapi/webhook"},
            }
        )
    return specs


def handle_vapi_request(tools: ToolRegistry, payload: Mapping[str, Any]) -> Dict[str, Any]:
    message = _message(payload)
    calls = parse_tool_calls(payload)
    if message.get("type") not in TOOL_CALL_TYPES and not calls:
        return {}

    caller = caller_phone(message)
    if caller:
        try:
            tools.bookings.touch_contact(
                caller, intent="inbound", summary="voice call"
            )
        except Exception:
            pass

    results = []
    for call in calls:
        arguments = dict(call["arguments"])
        if caller and not str(arguments.get("phone") or "").strip():
            arguments["phone"] = caller
        handler = tools.handlers.get(call["name"])
        result = tools.execute(call["name"], _filter_kwargs(handler, arguments))
        results.append({"toolCallId": call["id"], "result": result})
    return {"results": results}


def parse_tool_calls(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    message = _message(payload)
    raw_calls = (
        message.get("toolCallList")
        or message.get("toolCalls")
        or message.get("tool_call_list")
        or []
    )
    parsed = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        normalized = _normalize_call(call)
        if normalized["id"] and normalized["name"]:
            parsed.append(normalized)
    return parsed


def caller_phone(message: Mapping[str, Any]) -> str:
    call = message.get("call") if isinstance(message.get("call"), dict) else {}
    sources = [call.get("customer"), message.get("customer")]
    raw = None
    for customer in sources:
        if isinstance(customer, dict) and customer.get("number"):
            raw = customer["number"]
            break
    return ChatService._canonical_phone(raw if isinstance(raw, str) else None)


def _message(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    message = payload.get("message")
    return message if isinstance(message, dict) else payload


def _normalize_call(call: Mapping[str, Any]) -> Dict[str, Any]:
    nested = call.get("function")
    if isinstance(nested, dict):
        name = nested.get("name") or call.get("name")
        arguments = (
            nested.get("arguments")
            or nested.get("parameters")
            or call.get("arguments")
            or {}
        )
        call_id = call.get("id")
    else:
        name = call.get("name")
        arguments = (
            call.get("arguments")
            or call.get("parameters")
            or call.get("input")
            or {}
        )
        call_id = call.get("id")
        tool_call = call.get("toolCall")
        if isinstance(tool_call, dict):
            call_id = call_id or tool_call.get("id")
            function = tool_call.get("function")
            if isinstance(function, dict):
                name = name or function.get("name")
                arguments = (
                    arguments
                    or function.get("parameters")
                    or function.get("arguments")
                    or {}
                )

    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(arguments, dict):
        arguments = {}
    return {"id": str(call_id or ""), "name": str(name or ""), "arguments": arguments}


def _filter_kwargs(
    handler: Callable[..., Any] | None, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    if handler is None:
        return arguments
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return arguments
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return arguments
    allowed = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in arguments.items() if key in allowed}
