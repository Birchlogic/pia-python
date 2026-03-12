"""
OpenRouter LLM client for the RLM engine.
"""

import os
from typing import List, Dict, Optional

from rlm.base import BaseLLMClient


class OpenRouterClient(BaseLLMClient):
    """LLM client wrapping the OpenRouter API (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "anthropic/claude-3-5-sonnet",
        max_tokens: int = 16384,
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. Set OPENROUTER_API_KEY or pass api_key."
            )
        self.model = model
        self.max_tokens = max_tokens

        # Lazy import so the package is optional
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package is required for OpenRouterClient. "
                "Install it with: pip install openai"
            )
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )

    def completion(self, messages: List[Dict[str, str]], timeout: int = 300) -> str:
        """Call the OpenRouter API."""
        extra_headers = {
            "HTTP-Referer": "https://birchlogic.pia", # Optional
            "X-Title": "Birchlogic PIA", # Optional
        }
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=messages,
            timeout=timeout,
            extra_headers=extra_headers
        )
        return response.choices[0].message.content
