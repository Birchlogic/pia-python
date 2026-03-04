"""
RLM Engine — Core Recursive Language Model implementation.

Implements Algorithm 1 from the paper (arxiv 2512.24601):
1. Initialize REPL with context as a variable + llm_query function
2. Build system prompt with only constant-size metadata about context
3. Loop: root LLM generates code → execute in REPL → truncate output → append
4. Stop when FINAL() or FINAL_VAR() is detected
"""

from dataclasses import dataclass, field
from typing import Optional, Union, List, Dict, Any

from rlm.base import BaseLLMClient
from rlm.repl import REPLEnv
from rlm.prompts import build_system_prompt, next_action_prompt, DEFAULT_QUERY
from rlm.utils import (
    find_code_blocks,
    process_code_execution,
    check_for_final_answer,
    convert_context,
)
from rlm.logger import RLMLogger


@dataclass
class RLMResult:
    """Result of an RLM completion."""
    response: str
    iterations: int
    messages: List[Dict[str, str]] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


class RLM:
    """
    Recursive Language Model — drop-in replacement for llm.completion().

    Usage:
        from rlm import RLM

        rlm = RLM(backend="anthropic", verbose=True)
        result = rlm.completion(context="...", query="Find the answer")
        print(result.response)
    """

    BACKENDS = {"anthropic", "openai"}

    def __init__(
        self,
        backend: str = "anthropic",
        model: Optional[str] = None,
        recursive_model: Optional[str] = None,
        api_key: Optional[str] = None,
        max_iterations: int = 20,
        max_recursion_depth: int = 1,
        verbose: bool = False,
        max_output_chars: int = 1500,
    ):
        """
        Args:
            backend: LLM provider — "anthropic" or "openai".
            model: Model name for the root LLM. Defaults per backend.
            recursive_model: Model for sub-LLM calls. Defaults to `model`.
            api_key: API key. Falls back to environment variables.
            max_iterations: Max root LLM iterations before forcing an answer.
            max_recursion_depth: Max recursion depth (currently depth-1 sub-calls).
            verbose: Enable colorful logging.
            max_output_chars: Max chars of REPL output shown to root LLM.
        """
        if backend not in self.BACKENDS:
            raise ValueError(f"Unknown backend '{backend}'. Choose from: {self.BACKENDS}")

        self.backend = backend
        self.max_iterations = max_iterations
        self.max_recursion_depth = max_recursion_depth
        self.max_output_chars = max_output_chars
        self.logger = RLMLogger(enabled=verbose)

        # Create root LLM client
        self.root_llm = self._create_client(backend, model, api_key)

        # Create sub-LLM client (used inside REPL for llm_query calls)
        sub_model = recursive_model or model
        self.sub_llm = self._create_client(backend, sub_model, api_key)

    def _create_client(
        self,
        backend: str,
        model: Optional[str],
        api_key: Optional[str],
    ) -> BaseLLMClient:
        """Instantiate an LLM client for the given backend."""
        if backend == "anthropic":
            from rlm.clients.anthropic_client import AnthropicClient
            kwargs = {"api_key": api_key}
            if model:
                kwargs["model"] = model
            return AnthropicClient(**kwargs)
        elif backend == "openai":
            from rlm.clients.openai_client import OpenAIClient
            kwargs = {"api_key": api_key}
            if model:
                kwargs["model"] = model
            return OpenAIClient(**kwargs)
        else:
            raise ValueError(f"Unknown backend: {backend}")

    def _sub_llm_query(self, prompt: str) -> str:
        """
        Sub-LLM query function injected into the REPL as `llm_query`.

        This is the key enabler of symbolic recursion — REPL code can
        programmatically call the LLM on arbitrary slices of the context.
        """
        self.logger.log_sub_llm_call(prompt[:200])

        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list):
            messages = prompt
        else:
            messages = [{"role": "user", "content": str(prompt)}]

        try:
            return self.sub_llm.completion(messages, timeout=300)
        except Exception as e:
            return f"Error making sub-LLM query: {str(e)}"

    def completion(
        self,
        context: Union[str, List[str], List[Dict[str, str]], Dict],
        query: Optional[str] = None,
    ) -> RLMResult:
        """
        Run the RLM completion loop (Algorithm 1 from the paper).

        Args:
            context: The (potentially very long) context to process.
                     Can be a string, list of strings, list of dicts, or dict.
            query: The user's question about the context.

        Returns:
            An RLMResult with the response and metadata.
        """
        if query is None:
            query = DEFAULT_QUERY

        self.logger.log_query_start(query)

        # --- Step 1: Convert context to REPL-compatible format ---
        context_json, context_str, context_type, total_length, chunk_lengths = (
            convert_context(context)
        )

        # --- Step 2: Build system prompt with metadata (NOT the full context) ---
        messages = build_system_prompt(
            context_type=context_type,
            context_total_length=total_length,
            context_lengths=chunk_lengths,
        )

        # --- Step 3: Initialize REPL with context + llm_query ---
        repl_env = REPLEnv(
            sub_llm_fn=self._sub_llm_query,
            context_json=context_json,
            context_str=context_str,
        )

        # --- Step 4: Main RLM loop ---
        for iteration in range(self.max_iterations):
            self.logger.log_iteration(iteration, self.max_iterations)

            # Append the per-iteration action prompt
            action_prompt = next_action_prompt(query, iteration)
            current_messages = messages + [action_prompt]

            # Query root LLM
            response = self.root_llm.completion(current_messages)

            # Check for code blocks
            code_blocks = find_code_blocks(response)
            has_code = code_blocks is not None
            self.logger.log_model_response(response, has_code=has_code)

            # Process code execution or plain response
            if has_code:
                messages = process_code_execution(
                    response, messages, repl_env, self.logger,
                )
            else:
                messages.append({
                    "role": "assistant",
                    "content": response,
                })

            # Check for final answer
            final_answer = check_for_final_answer(response, repl_env, self.logger)
            if final_answer:
                self.logger.log_final_answer(final_answer)
                return RLMResult(
                    response=final_answer,
                    iterations=iteration + 1,
                    messages=messages,
                )

        # --- Step 5: Force final answer if max iterations reached ---
        self.logger.log_forced_final()
        messages.append(next_action_prompt(query, iteration, final_answer=True))
        forced_response = self.root_llm.completion(messages)
        self.logger.log_final_answer(forced_response)

        return RLMResult(
            response=forced_response,
            iterations=self.max_iterations,
            messages=messages,
        )

    def reset(self):
        """Reset the engine state (for re-use)."""
        pass  # Engine is stateless between completions
