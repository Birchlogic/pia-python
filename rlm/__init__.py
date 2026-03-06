"""
RLM — Recursive Language Model

A task-agnostic inference paradigm for LLMs to handle arbitrarily long
contexts by programmatically examining, decomposing, and recursively
calling itself over snippets of the input.

Paper: https://arxiv.org/abs/2512.24601

Usage:
    from rlm import RLM

    rlm = RLM(backend="anthropic", verbose=True)
    result = rlm.completion(
        context="<your long context here>",
        query="What is the answer?",
    )
    print(result.response)
"""

from rlm.rlm_engine import RLM, RLMResult
from rlm.repl import REPLEnv, REPLResult

__all__ = ["RLM", "RLMResult", "REPLEnv", "REPLResult"]
__version__ = "0.1.0"
