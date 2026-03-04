"""
OpenAI LLM client for the RLM engine.
"""

import os
from typing import List, Dict, Optional

from rlm.base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    """LLM client wrapping the OpenAI Chat Completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        max_tokens: int = 16384,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY or pass api_key."
            )
        self.model = model
        self.max_tokens = max_tokens

        # Lazy import so the package is optional
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package is required for OpenAIClient. "
                "Install it with: pip install openai"
            )
        self.client = openai.OpenAI(api_key=self.api_key)

    def completion(self, messages: List[Dict[str, str]], timeout: int = 300) -> str:
        """Call the OpenAI Chat Completions API."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=messages,
            timeout=timeout,
        )
        return response.choices[0].message.content
