"""
Abstract base class for LLM clients used by the RLM engine.
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class BaseLLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    def completion(self, messages: List[Dict[str, str]], timeout: int = 300) -> str:
        """
        Send a list of chat messages and return the assistant's response text.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            timeout: Request timeout in seconds.

        Returns:
            The assistant's response as a plain string.
        """
        ...
