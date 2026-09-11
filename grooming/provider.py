from __future__ import annotations

from typing import Any, Dict, List

from anthropic import Anthropic


class AnthropicProvider:
    """Thin boundary around the direct Anthropic SDK."""

    def __init__(self, api_key: str, model: str, client: Any = None):
        if not api_key and client is None:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self.client = client or Anthropic(api_key=api_key)
        self.model = model

    def create_message(
        self, *, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Any:
        return self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            temperature=0,
            system=system,
            messages=messages,
            tools=tools,
        )

