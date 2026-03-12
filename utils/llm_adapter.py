import os
import json
from enum import Enum
import anthropic
import openai

class LlmProviderType(str, Enum):
    CLAUDE = "CLAUDE"
    OPENAI = "OPENAI"
    OPENROUTER = "OPENROUTER"

MODEL_MAPPING = {
    "claude-3-5-sonnet-20241022": "claude-3-5-sonnet-20240620",
    "claude-sonnet-4-20250514": "claude-3-5-sonnet-20240620",
}

def normalize_model_name(model_name: str) -> str:
    """Maps potentially invalid or preview model names to stable ones."""
    return MODEL_MAPPING.get(model_name, model_name)

class AbstractMessagesAPI:
    """An abstract representation of the Anthropic client.messages interface."""
    def create(self, model: str, messages: list, system: str = None, max_tokens: int = 4000, temperature: float = 0.0, **kwargs):
        raise NotImplementedError()

class MockContent:
    def __init__(self, text=None, tool_use=None):
        if tool_use:
            self.type = "tool_use"
            self.name = tool_use.get("name")
            self.input = tool_use.get("input")
            self.id = tool_use.get("id")
        else:
            self.type = "text"
            self.text = text

class MockResponse:
    def __init__(self, text=None, tool_use=None):
        self.content = [MockContent(text=text, tool_use=tool_use)]

class ClaudeAdapter(AbstractMessagesAPI):
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
    def create(self, model: str, messages: list, system: str = None, max_tokens: int = 4000, temperature: float = 0.0, **kwargs):
        normalized_model = normalize_model_name(model)
        return self.client.messages.create(
            model=normalized_model,
            messages=messages,
            system=system or "",
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )


class OpenAIAdapter(AbstractMessagesAPI):
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)
        
    def _handle_tool_use(self, kwargs):
        """Translates Anthropic-style tools to OpenAI-style tools."""
        anth_tools = kwargs.pop("tools", None)
        anth_tool_choice = kwargs.pop("tool_choice", None)
        
        if anth_tools:
            openai_tools = []
            for t in anth_tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {})
                    }
                })
            kwargs["tools"] = openai_tools
            
        if anth_tool_choice:
            if isinstance(anth_tool_choice, dict):
                if anth_tool_choice.get("type") == "tool":
                    kwargs["tool_choice"] = {
                        "type": "function",
                        "function": {"name": anth_tool_choice["name"]}
                    }
                elif anth_tool_choice.get("type") == "any":
                    kwargs["tool_choice"] = "required"
                elif anth_tool_choice.get("type") == "auto":
                    kwargs["tool_choice"] = "auto"
            else:
                kwargs["tool_choice"] = anth_tool_choice

    def create(self, model: str, messages: list, system: str = None, max_tokens: int = 4000, temperature: float = 0.0, **kwargs):
        normalized_model = normalize_model_name(model)
        self._handle_tool_use(kwargs)
        
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        
        # Remove any unsupported kwargs like metadata or thinking flags
        kwargs.pop("metadata", None)
        
        if "tools" in kwargs or "tool_choice" in kwargs:
            from utils.logger import setup_logger
            debug_logger = setup_logger("LLMAdapterDebug")
            debug_logger.info(f"OpenRouter/OpenAI Tools: {json.dumps(kwargs.get('tools'), indent=2)}")
            debug_logger.info(f"OpenRouter/OpenAI Tool Choice: {json.dumps(kwargs.get('tool_choice'), indent=2)}")

        resp = self.client.chat.completions.create(
            model=normalized_model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
        
        message = resp.choices[0].message
        if message.tool_calls:
            tc = message.tool_calls[0].function
            return MockResponse(tool_use={
                "name": tc.name,
                "input": json.loads(tc.arguments),
                "id": message.tool_calls[0].id
            })
            
        return MockResponse(text=message.content)

class OpenRouterAdapter(OpenAIAdapter):
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

class UnifiedClient:
    def __init__(self, provider: LlmProviderType, api_key: str):
        if provider == LlmProviderType.CLAUDE:
            self.messages = ClaudeAdapter(api_key)
        elif provider == LlmProviderType.OPENAI:
            self.messages = OpenAIAdapter(api_key)
        elif provider == LlmProviderType.OPENROUTER:
            self.messages = OpenRouterAdapter(api_key)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

def get_llm_client(ai_config: dict) -> UnifiedClient:
    provider_str = ai_config.get("type", "CLAUDE").upper()
    api_key = ai_config.get("apiKey")
    try:
        provider = LlmProviderType(provider_str)
    except ValueError:
        provider = LlmProviderType.CLAUDE
        
    if not api_key:
        from config import Config
        # Optional fallback for testing
        api_key = Config.ANTHROPIC_API_KEY
        
    return UnifiedClient(provider, api_key)
