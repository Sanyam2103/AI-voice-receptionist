from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from grooming.config import ROOT
from grooming.tools import TOOL_DEFINITIONS
from grooming.vapi import webhook_url

VAPI_API = "https://api.vapi.ai"
USER_AGENT = "maple-street-grooming/1.0"
SHOP_TOOL_NAMES = {definition["name"] for definition in TOOL_DEFINITIONS}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Set every Maple Street Function tool's Server URL to this "
            "machine's public webhook. Use after Cloudflare prints a new host."
        )
    )
    parser.add_argument(
        "tunnel",
        help="Tunnel host or URL, e.g. https://foo.trycloudflare.com",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned PATCHes without calling Vapi",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Update every tool in the Vapi org, not only shop tool names",
    )
    args = parser.parse_args()
    target = webhook_url(args.tunnel)
    token = _api_key()
    tools = list(_iter_tools(_get_json("/tool?limit=100", token)))
    selected = [
        tool
        for tool in tools
        if args.all or _tool_name(tool) in SHOP_TOOL_NAMES
    ]
    if not selected:
        found = ", ".join(_tool_name(tool) or tool.get("id", "?") for tool in tools)
        raise SystemExit(
            "No matching tools. Names in Vapi must match "
            + ", ".join(sorted(SHOP_TOOL_NAMES))
            + (f". Found: {found}" if found else ".")
        )
    missing = sorted(
        SHOP_TOOL_NAMES - {_tool_name(tool) for tool in selected}
    )
    if missing and not args.all:
        print("Warning: not in Vapi yet: " + ", ".join(missing), file=sys.stderr)

    print(f"Webhook: {target}")
    for tool in selected:
        name = _tool_name(tool)
        tool_id = tool.get("id")
        current = ((tool.get("server") or {}).get("url") or "")
        print(f"{name} ({tool_id}): {current or '(empty)'} -> {target}")
        if args.dry_run:
            continue
        _patch_json(f"/tool/{tool_id}", token, {"server": {"url": target}})
    if args.dry_run:
        print("Dry run; nothing sent.")


def _api_key() -> str:
    load_dotenv(ROOT / ".env")
    token = os.getenv("VAPI_API_KEY", "").strip()
    if not token:
        raise SystemExit("Set VAPI_API_KEY in .env (Vapi Dashboard → Organization → API Keys).")
    return token


def _iter_tools(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise SystemExit(f"Unexpected GET /tool body: {payload!r}")


def _tool_name(tool: Dict[str, Any]) -> str:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(function.get("name") or tool.get("name") or "")


def _get_json(path: str, token: str) -> Any:
    return _request("GET", path, token)


def _patch_json(path: str, token: str, body: Dict[str, Any]) -> Any:
    return _request("PATCH", path, token, body)


def _request(method: str, path: str, token: str, body: Dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        VAPI_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            # Cloudflare fronts api.vapi.ai and rejects the default Python-urllib agent.
            "User-Agent": USER_AGENT,
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Vapi {method} {path} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Could not reach Vapi: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


if __name__ == "__main__":
    main()
