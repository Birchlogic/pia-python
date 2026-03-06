"""
REPL environment for the RLM engine.

Provides a sandboxed Python execution environment with:
- `context` variable holding the user's prompt/data
- `llm_query(prompt)` function for sub-LLM calls
- `FINAL_VAR(variable_name)` function for returning REPL variables
- Thread-safe stdout/stderr capture
- Temporary directory for file I/O
"""

import sys
import io
import os
import json
import time
import threading
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Union, Dict, List


@dataclass
class REPLResult:
    """Result of a REPL code execution."""
    stdout: str
    stderr: str
    locals: dict
    execution_time: float

    def __str__(self):
        return (
            f"REPLResult(stdout={self.stdout!r}, stderr={self.stderr!r}, "
            f"execution_time={self.execution_time:.2f}s)"
        )


class REPLEnv:
    """
    Sandboxed Python REPL environment for the RLM.

    Code is executed via exec() with restricted builtins. The environment
    persists state (variables) across executions, mimicking a notebook.
    """

    # Allowed builtins — blocks eval, exec, input, globals, locals for safety
    SAFE_BUILTINS = {
        # Core types
        "print": print, "len": len, "str": str, "int": int, "float": float,
        "list": list, "dict": dict, "set": set, "tuple": tuple, "bool": bool,
        "type": type, "isinstance": isinstance, "issubclass": issubclass,
        "bytes": bytes, "bytearray": bytearray, "memoryview": memoryview,
        "complex": complex, "frozenset": frozenset,

        # Iteration & functional
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "sorted": sorted, "reversed": reversed, "range": range,
        "iter": iter, "next": next, "any": any, "all": all,
        "slice": slice,

        # Math & conversion
        "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
        "pow": pow, "divmod": divmod,
        "chr": chr, "ord": ord, "hex": hex, "bin": bin, "oct": oct,
        "hash": hash, "id": id,

        # String
        "repr": repr, "ascii": ascii, "format": format,

        # Object introspection
        "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
        "delattr": delattr, "dir": dir, "vars": vars, "callable": callable,

        # OOP
        "super": super, "property": property,
        "staticmethod": staticmethod, "classmethod": classmethod, "object": object,

        # I/O & imports (controlled)
        "__import__": __import__,
        "open": open,

        # Exceptions
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
        "FileNotFoundError": FileNotFoundError, "OSError": OSError, "IOError": IOError,
        "RuntimeError": RuntimeError, "NameError": NameError, "ImportError": ImportError,
        "StopIteration": StopIteration, "GeneratorExit": GeneratorExit,
        "ArithmeticError": ArithmeticError, "LookupError": LookupError,
        "AssertionError": AssertionError, "NotImplementedError": NotImplementedError,
        "BaseException": BaseException, "SystemExit": SystemExit,
        "KeyboardInterrupt": KeyboardInterrupt,
        "Warning": Warning, "UserWarning": UserWarning,
        "DeprecationWarning": DeprecationWarning, "RuntimeWarning": RuntimeWarning,
        "SyntaxWarning": SyntaxWarning, "FutureWarning": FutureWarning,

        # Blocked
        "input": None, "eval": None, "exec": None,
        "compile": None, "globals": None, "locals": None,
    }

    def __init__(
        self,
        sub_llm_fn=None,
        context_json: Optional[Union[dict, list]] = None,
        context_str: Optional[str] = None,
        setup_code: Optional[str] = None,
    ):
        """
        Args:
            sub_llm_fn: A callable(prompt: str) -> str for sub-LLM queries.
            context_json: Context data as a dict/list (written to temp file, loaded as `context`).
            context_str: Context data as a plain string (written to temp file, loaded as `context`).
            setup_code: Optional Python code to run during initialization.
        """
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.mkdtemp(prefix="rlm_repl_")

        # Execution namespaces
        self.globals = {"__builtins__": dict(self.SAFE_BUILTINS)}
        self.locals = {}
        self._lock = threading.Lock()

        # Load context into the REPL
        self._load_context(context_json, context_str)

        # Inject llm_query function
        if sub_llm_fn is not None:
            self.globals["llm_query"] = sub_llm_fn

        # Inject FINAL_VAR helper
        self.globals["FINAL_VAR"] = self._final_var

        # Run optional setup code
        if setup_code:
            self.execute(setup_code)

    # ------------------------------------------------------------------
    # Context loading
    # ------------------------------------------------------------------

    def _load_context(
        self,
        context_json: Optional[Union[dict, list]],
        context_str: Optional[str],
    ):
        """Write context to temp files and load into REPL as `context` variable."""
        if context_json is not None:
            path = os.path.join(self.temp_dir, "context.json")
            with open(path, "w") as f:
                json.dump(context_json, f, indent=2)
            self.execute(
                f"import json\n"
                f"with open(r'{path}', 'r') as f:\n"
                f"    context = json.load(f)\n"
            )
        elif context_str is not None:
            path = os.path.join(self.temp_dir, "context.txt")
            with open(path, "w") as f:
                f.write(context_str)
            self.execute(
                f"with open(r'{path}', 'r') as f:\n"
                f"    context = f.read()\n"
            )

    # ------------------------------------------------------------------
    # FINAL_VAR helper
    # ------------------------------------------------------------------

    def _final_var(self, variable_name: str) -> str:
        """Return the value of a REPL variable as a string."""
        variable_name = variable_name.strip().strip('"').strip("'").strip()
        if variable_name in self.locals:
            return str(self.locals[variable_name])
        return f"Error: Variable '{variable_name}' not found in REPL environment"

    # ------------------------------------------------------------------
    # Code execution
    # ------------------------------------------------------------------

    @contextmanager
    def _capture_output(self):
        """Thread-safe context manager to capture stdout/stderr."""
        with self._lock:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                sys.stdout = stdout_buf
                sys.stderr = stderr_buf
                yield stdout_buf, stderr_buf
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

    @contextmanager
    def _temp_working_directory(self):
        """Temporarily change CWD to the REPL's temp directory."""
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            yield
        finally:
            os.chdir(old_cwd)

    def execute(self, code: str) -> REPLResult:
        """
        Execute Python code in the sandboxed REPL environment.

        Imports are executed in globals (so they persist across cells).
        Other code runs in a combined namespace. New variables are saved
        to self.locals for subsequent executions.
        """
        start_time = time.time()

        with self._capture_output() as (stdout_buf, stderr_buf):
            with self._temp_working_directory():
                try:
                    lines = code.split("\n")
                    import_lines = []
                    other_lines = []

                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith(("import ", "from ")) and not stripped.startswith("#"):
                            import_lines.append(line)
                        else:
                            other_lines.append(line)

                    # Execute imports in globals so they persist
                    if import_lines:
                        exec("\n".join(import_lines), self.globals, self.globals)

                    # Execute remaining code in combined namespace
                    if other_lines:
                        combined = {**self.globals, **self.locals}
                        exec("\n".join(other_lines), combined, combined)

                        # Save new variables to locals
                        for key, value in combined.items():
                            if key not in self.globals:
                                self.locals[key] = value

                    stdout_content = stdout_buf.getvalue()
                    stderr_content = stderr_buf.getvalue()

                except Exception as e:
                    stderr_content = stderr_buf.getvalue() + str(e)
                    stdout_content = stdout_buf.getvalue()

        execution_time = time.time() - start_time

        # Store output in locals for programmatic access
        self.locals["_stdout"] = stdout_content
        self.locals["_stderr"] = stderr_content

        return REPLResult(
            stdout=stdout_content,
            stderr=stderr_content,
            locals=self.locals.copy(),
            execution_time=execution_time,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def __del__(self):
        """Clean up temporary directory."""
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
