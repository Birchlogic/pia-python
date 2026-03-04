"""
Anthropic (Claude) LLM client for the RLM engine.
"""

import os
from typing import List, Dict, Optional

import anthropic

from rlm.base import BaseLLMClient


class AnthropicClient(BaseLLMClient):
    """LLM client wrapping the Anthropic Messages API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 16384,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key is required. Set ANTHROPIC_API_KEY or pass api_key."
            )
        self.model = model
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def completion(self, messages: List[Dict[str, str]], timeout: int = 300) -> str:
        """
        Call the Anthropic Messages API.

        Anthropic separates system messages from the conversation, so we pull
        out any system-role messages and pass them via the `system` param.
        """
        system_parts = []
        chat_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        # Anthropic requires alternating user/assistant; merge consecutive same-role
        chat_messages = self._merge_consecutive(chat_messages)

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": chat_messages,
            "timeout": timeout,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)

        response = self.client.messages.create(**kwargs)
        return response.content[0].text

    @staticmethod
    def _merge_consecutive(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Merge consecutive messages with the same role (Anthropic requirement)."""
        if not messages:
            return messages
        merged = [messages[0].copy()]
        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(msg.copy())
        return merged
