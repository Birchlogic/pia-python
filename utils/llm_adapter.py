import os
import json
from enum import Enum
from typing import List, Optional, Union
import anthropic
import openai

from pydantic import BaseModel, Field

class LlmProviderType(str, Enum):
    CLAUDE = "CLAUDE"
    OPENAI = "OPENAI"
    OPENROUTER = "OPENROUTER"

class AIConfig(BaseModel):
    type: LlmProviderType = Field(default=LlmProviderType.CLAUDE)
    model: Optional[str] = None
    apiKey: Optional[str] = None
    
    class Config:
        use_enum_values = True

def normalize_model_name(model_name: str) -> str:
    """Passes through the model name as is, now that strict adherence is required."""
    return model_name

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
        self.provider = "CLAUDE"
        self.client = anthropic.Anthropic(api_key=api_key, timeout=600.0)
    def create(self, model: str, messages: list, system: str = None, max_tokens: int = 4000, temperature: float = 0.0, **kwargs):
        normalized_model = normalize_model_name(model)
        from utils.logger import setup_logger
        debug_logger = setup_logger("LLMAdapterDebug")
        debug_logger.info(f"{self.provider} model: {normalized_model}")

        debug_logger.info(f"{self.provider} Request - Model: {normalized_model}, Messages: {len(messages)}, System: {'Yes' if system else 'No'}")
        
        try:
            resp = self.client.messages.create(
                model=normalized_model,
                messages=messages,
                system=system or "",
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            # Anthropic responses have 'stop_reason'
            debug_logger.info(f"{self.provider} Response received. Stop Reason: {getattr(resp, 'stop_reason', 'N/A')}")
            return resp
        except Exception as e:
            logger = setup_logger("LLMAdapter")
            logger.error(f"{self.provider} API Error: {str(e)}")
            raise e


class OpenAIAdapter(AbstractMessagesAPI):
    def __init__(self, api_key: str, provider: str = "OPENAI"):
        self.provider = provider
        self.client = openai.OpenAI(api_key=api_key, timeout=600.0)
        
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
        
        from utils.logger import setup_logger
        debug_logger = setup_logger("LLMAdapterDebug")
        
        if "tools" in kwargs or "tool_choice" in kwargs:
            debug_logger.info(f"{self.provider} Tools: {json.dumps(kwargs.get('tools'), indent=2)}")
            debug_logger.info(f"{self.provider} Tool Choice: {json.dumps(kwargs.get('tool_choice'), indent=2)}")

        debug_logger.info(f"{self.provider} Request - Model: {normalized_model}, Messages: {len(full_messages)}")
        
        try:
            resp = self.client.chat.completions.create(
                model=normalized_model,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            
            finish_reason = resp.choices[0].finish_reason
            debug_logger.info(f"{self.provider} Finish Reason: {finish_reason}")
        except Exception as e:
            logger = setup_logger("LLMAdapter")
            # Log full error body for 500 errors if available
            error_body = "N/A"
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                error_body = e.response.text
            elif hasattr(e, 'body'):
                error_body = str(e.body)
            elif hasattr(e, 'message'):
                error_body = str(e.message)
                
            logger.error(f"{self.provider} API Error: {str(e)} - Body: {error_body}")
            raise e
        
        message = resp.choices[0].message
        if message.tool_calls:
            tc = message.tool_calls[0].function
            debug_logger.info(f"Arguments length: {len(tc.arguments)}")
            try:
                tool_input = json.loads(tc.arguments)
            except json.JSONDecodeError as e:
                logger = setup_logger("LLMAdapter")
                logger.error(f"Failed to parse tool arguments (finish_reason: {finish_reason}): {tc.arguments}")
                # Try to clean up the JSON string if it has common LLM artifacts
                cleaned = tc.arguments.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
                try:
                    tool_input = json.loads(cleaned)
                except:
                    raise e

            return MockResponse(tool_use={
                "name": tc.name,
                "input": tool_input,
                "id": message.tool_calls[0].id
            })
            
        return MockResponse(text=message.content)

class OpenRouterAdapter(OpenAIAdapter):
    def __init__(self, api_key: str):
        super().__init__(api_key, provider="OPENROUTER")
        self.client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=600.0
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

def get_llm_client(ai_config: Union[dict, AIConfig]) -> UnifiedClient:
    if isinstance(ai_config, dict):
        # Allow missing fields to use defaults
        config_obj = AIConfig(**ai_config)
    else:
        config_obj = ai_config
        
    provider = config_obj.type
    api_key = config_obj.apiKey
        
    from utils.logger import setup_logger
    debug_logger = setup_logger("LLMAdapterDebug")
    debug_logger.info(f"Initializing UnifiedClient for provider: {provider}, model: {config_obj.model}")
        
    if not api_key:
        debug_logger.warning("No API key provided in ai_config")
        
    return UnifiedClient(provider, api_key)
