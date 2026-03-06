"""
Utility functions for the RLM engine.

Handles code block parsing, output truncation, code execution processing,
final answer detection, and context normalization.
"""

import re
from typing import Optional, List, Dict, Union, Tuple


# ---------------------------------------------------------------------------
# Code block parsing
# ---------------------------------------------------------------------------

_CODE_BLOCK_PATTERN = re.compile(
    r"```repl\s*\n(.*?)```",
    re.DOTALL,
)


def find_code_blocks(response: str) -> Optional[List[str]]:
    """
    Extract all ```repl ... ``` code blocks from an LLM response.

    Returns None if no code blocks are found, otherwise a list of code strings.
    """
    matches = _CODE_BLOCK_PATTERN.findall(response)
    return matches if matches else None


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------

def truncate_output(text: str, max_chars: int = 1500) -> str:
    """
    Truncate REPL output to keep the root LLM's context window small.

    Shows a prefix and suffix with a [truncated N chars] marker in between.
    This is a key design choice from the paper — forces the LLM to rely on
    variables and sub-calls rather than polluting its context window.
    """
    if len(text) <= max_chars:
        return text

    # Show 60% prefix, 40% suffix
    prefix_len = int(max_chars * 0.6)
    suffix_len = max_chars - prefix_len
    truncated_len = len(text) - prefix_len - suffix_len

    return (
        text[:prefix_len]
        + f"\n\n... [truncated {truncated_len} chars] ...\n\n"
        + text[-suffix_len:]
    )


# ---------------------------------------------------------------------------
# Code execution processing
# ---------------------------------------------------------------------------

def process_code_execution(
    response: str,
    messages: List[Dict[str, str]],
    repl_env,
    logger=None,
) -> List[Dict[str, str]]:
    """
    Extract code blocks from an LLM response, execute them in the REPL,
    and append the results to the conversation history.

    Returns the updated messages list.
    """
    code_blocks = find_code_blocks(response)
    if not code_blocks:
        messages.append({"role": "assistant", "content": response})
        return messages

    # Add the assistant's full response (including its reasoning + code)
    messages.append({"role": "assistant", "content": response})

    # Execute each code block
    all_outputs = []
    for i, code in enumerate(code_blocks):
        if logger:
            logger.log_code_execution(code, block_index=i)

        result = repl_env.execute(code)

        output_parts = []
        if result.stdout:
            output_parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"stderr:\n{result.stderr}")

        output = "\n".join(output_parts) if output_parts else "(no output)"

        if logger:
            logger.log_repl_output(output, result.execution_time)

        all_outputs.append(output)

    # Combine and truncate all outputs
    combined_output = "\n---\n".join(all_outputs)
    truncated = truncate_output(combined_output)

    # Add truncated output as a user message (simulating environment feedback)
    messages.append({
        "role": "user",
        "content": f"REPL Output:\n{truncated}",
    })

    return messages


# ---------------------------------------------------------------------------
# Final answer detection
# ---------------------------------------------------------------------------

_FINAL_PATTERN = re.compile(r"FINAL\((.*?)\)", re.DOTALL)
_FINAL_VAR_PATTERN = re.compile(r"FINAL_VAR\((\w+)\)", re.DOTALL)


def check_for_final_answer(
    response: str,
    repl_env=None,
    logger=None,
) -> Optional[str]:
    """
    Check if the LLM response contains a FINAL() or FINAL_VAR() declaration.

    - FINAL(text) → returns text directly
    - FINAL_VAR(var_name) → looks up var_name in the REPL environment

    Returns None if no final answer is found.
    """
    # Check for FINAL_VAR first (more specific)
    var_match = _FINAL_VAR_PATTERN.search(response)
    if var_match and repl_env is not None:
        var_name = var_match.group(1).strip()
        answer = repl_env._final_var(var_name)
        if logger:
            logger.log_final_answer(f"FINAL_VAR({var_name}) → {answer[:200]}")
        return answer

    # Check for FINAL(direct answer)
    final_match = _FINAL_PATTERN.search(response)
    if final_match:
        answer = final_match.group(1).strip()
        if logger:
            logger.log_final_answer(answer[:200])
        return answer

    return None


# ---------------------------------------------------------------------------
# Context normalization
# ---------------------------------------------------------------------------

def convert_context(
    context: Union[str, List[str], List[Dict[str, str]], Dict],
) -> Tuple[Optional[Union[dict, list]], Optional[str], str, int, str]:
    """
    Normalize various input types into REPL-compatible context data.

    Returns:
        (context_json, context_str, context_type, total_length, chunk_lengths_str)
    """
    if isinstance(context, str):
        return (
            None,             # context_json
            context,          # context_str
            "string",         # context_type
            len(context),     # total_length
            str(len(context)),  # chunk_lengths
        )

    if isinstance(context, list):
        if all(isinstance(item, str) for item in context):
            # Pass as list of strings (using context_json parameter)
            lengths = [str(len(s)) for s in context]
            return (
                context,  # use context_json for lists
                None,     # context_str
                "list of strings",
                sum(len(s) for s in context),
                ", ".join(lengths),
            )

        if all(isinstance(item, dict) for item in context):
            # List of dicts — pass as JSON
            total = sum(len(str(item)) for item in context)
            lengths = [str(len(str(item))) for item in context]
            return (
                context,
                None,
                "list of documents (JSON)",
                total,
                ", ".join(lengths),
            )

    if isinstance(context, dict):
        total = len(str(context))
        return (
            context,
            None,
            "document (JSON)",
            total,
            str(total),
        )

    # Fallback: convert to string
    s = str(context)
    return (None, s, "string", len(s), str(len(s)))
