"""
Optional colorful logging for the RLM engine using rich.

Gracefully degrades to plain print() if rich is not installed.
"""

from typing import Optional, List, Dict


class RLMLogger:
    """
    Logger for RLM execution. Uses `rich` for colorful console output
    if available, otherwise falls back to plain print.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._console = None
        self._rich_available = False

        if enabled:
            try:
                from rich.console import Console
                from rich.panel import Panel
                from rich.syntax import Syntax
                from rich.markdown import Markdown
                self._console = Console()
                self._rich_available = True
            except ImportError:
                pass

    def _print(self, *args, **kwargs):
        if not self.enabled:
            return
        if self._console:
            self._console.print(*args, **kwargs)
        else:
            print(*args)

    def log_query_start(self, query: str):
        if not self.enabled:
            return
        if self._rich_available:
            from rich.panel import Panel
            self._console.print(Panel(
                f"[bold cyan]{query}[/bold cyan]",
                title="🔄 RLM Query",
                border_style="cyan",
            ))
        else:
            print(f"\n{'='*60}\n🔄 RLM Query: {query}\n{'='*60}")

    def log_iteration(self, iteration: int, max_iterations: int):
        if not self.enabled:
            return
        self._print(
            f"\n[bold yellow]━━━ Iteration {iteration + 1}/{max_iterations} ━━━[/bold yellow]"
            if self._rich_available
            else f"\n--- Iteration {iteration + 1}/{max_iterations} ---"
        )

    def log_model_response(self, response: str, has_code: bool = False):
        if not self.enabled:
            return
        truncated = response[:500] + "..." if len(response) > 500 else response
        icon = "💻" if has_code else "💬"
        if self._rich_available:
            from rich.panel import Panel
            self._console.print(Panel(
                truncated,
                title=f"{icon} Root LLM Response",
                border_style="green" if has_code else "blue",
            ))
        else:
            print(f"\n{icon} Root LLM Response:\n{truncated}")

    def log_code_execution(self, code: str, block_index: int = 0):
        if not self.enabled:
            return
        if self._rich_available:
            from rich.syntax import Syntax
            from rich.panel import Panel
            syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
            self._console.print(Panel(
                syntax,
                title=f"⚡ Executing Code Block {block_index + 1}",
                border_style="yellow",
            ))
        else:
            print(f"\n⚡ Executing Code Block {block_index + 1}:\n{code}")

    def log_repl_output(self, output: str, execution_time: float = 0):
        if not self.enabled:
            return
        truncated = output[:300] + "..." if len(output) > 300 else output
        if self._rich_available:
            from rich.panel import Panel
            self._console.print(Panel(
                truncated,
                title=f"📤 REPL Output ({execution_time:.2f}s)",
                border_style="magenta",
            ))
        else:
            print(f"\n📤 REPL Output ({execution_time:.2f}s):\n{truncated}")

    def log_sub_llm_call(self, prompt_preview: str):
        if not self.enabled:
            return
        truncated = prompt_preview[:200] + "..." if len(prompt_preview) > 200 else prompt_preview
        self._print(
            f"[dim]🔗 Sub-LLM call: {truncated}[/dim]"
            if self._rich_available
            else f"🔗 Sub-LLM call: {truncated}"
        )

    def log_final_answer(self, answer: str):
        if not self.enabled:
            return
        if self._rich_available:
            from rich.panel import Panel
            self._console.print(Panel(
                f"[bold green]{answer}[/bold green]",
                title="✅ Final Answer",
                border_style="green",
                padding=(1, 2),
            ))
        else:
            print(f"\n{'='*60}\n✅ Final Answer: {answer}\n{'='*60}")

    def log_forced_final(self):
        if not self.enabled:
            return
        self._print(
            "[bold red]⚠️  Max iterations reached — forcing final answer[/bold red]"
            if self._rich_available
            else "⚠️  Max iterations reached — forcing final answer"
        )
