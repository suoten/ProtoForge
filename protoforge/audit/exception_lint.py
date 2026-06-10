"""Layer 3: Exception Handling Pattern Scanner.

Scans Python source files for dangerous exception handling patterns:
  - `except Exception` followed by `return None`, `return []`, `return False`, `return 0`, `return {}`
  - Bare `except:` clauses
  - `except Exception` without re-raise or logging

These patterns silently swallow errors and make debugging extremely difficult.
The recommended alternatives are:
  - Re-raise the exception (possibly wrapped)
  - Return a Result/Either type
  - At minimum, log the exception before returning a default

Usage:
    python -m protoforge.audit.exception_lint [path ...]
    python -m protoforge.audit.exception_lint --diff  # scan only changed files
"""

import ast
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExceptionLintViolation:
    """A single exception handling violation."""

    file_path: str
    line_number: int
    violation_type: str  # "swallow_return" | "bare_except" | "no_log_no_reraise"
    detail: str
    severity: str = "warning"  # "error" | "warning" | "info"


@dataclass
class ExceptionLintResult:
    """Result of an exception lint scan."""

    violations: list[ExceptionLintViolation] = field(default_factory=list)
    files_scanned: int = 0
    total_except_blocks: int = 0

    @property
    def ok(self) -> bool:
        return len([v for v in self.violations if v.severity == "error"]) == 0

    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.severity == "error"])

    @property
    def warning_count(self) -> int:
        return len([v for v in self.violations if v.severity == "warning"])

    def summary(self) -> str:
        lines = [
            f"Exception Lint: scanned {self.files_scanned} files, "
            f"found {self.total_except_blocks} except blocks, "
            f"{self.error_count} errors, {self.warning_count} warnings",
        ]
        if not self.violations:
            lines.append("No violations found.")
        else:
            # Group by file
            by_file: dict[str, list[ExceptionLintViolation]] = {}
            for v in self.violations:
                by_file.setdefault(v.file_path, []).append(v)
            for fpath, violations in sorted(by_file.items()):
                lines.append(f"\n  {fpath}:")
                for v in sorted(violations, key=lambda x: x.line_number):
                    lines.append(f"    L{v.line_number}: [{v.severity}] {v.violation_type}: {v.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AST-based scanner
# ---------------------------------------------------------------------------

# Patterns that indicate a "swallowed" exception (returning a default value)
_SWALLOW_RETURN_VALUES = {
    "None", "[]", "False", "0", "{}", "set()", "''", '""',
}

# Functions/methods where returning a default is acceptable
_KNOWN_SAFE_FUNCTIONS = {
    "_safe_json_loads",  # explicitly designed to return default on parse failure
    "__str__",  # str representation should never raise
    "__repr__",
}


class ExceptionLintVisitor(ast.NodeVisitor):
    """AST visitor that scans for dangerous exception handling patterns."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.violations: list[ExceptionLintViolation] = []
        self.total_except_blocks = 0
        self._current_function: Optional[str] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_function = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = old_function

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.total_except_blocks += 1

        # Check for bare except (no exception type)
        if node.type is None:
            self.violations.append(ExceptionLintViolation(
                file_path=self.file_path,
                line_number=node.lineno,
                violation_type="bare_except",
                detail="Bare 'except:' catches everything including KeyboardInterrupt/SystemExit. "
                       "Use 'except Exception:' at minimum.",
                severity="error",
            ))
            self.generic_visit(node)
            return

        # Check if it's catching Exception broadly
        is_broad_exception = False
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            is_broad_exception = True
        elif isinstance(node.type, ast.Attribute) and node.type.attr == "Exception":
            is_broad_exception = True
        elif isinstance(node.type, ast.Tuple):
            # Check if Exception is in the tuple
            for elt in node.type.elts:
                if isinstance(elt, ast.Name) and elt.id == "Exception":
                    is_broad_exception = True
                    break

        if not is_broad_exception:
            self.generic_visit(node)
            return

        # Analyze the body of the except block
        body = node.body
        has_reraise = False
        has_logging = False
        has_return_default = False
        return_value_detail = ""

        for stmt in body:
            # Check for re-raise
            if isinstance(stmt, ast.Raise):
                if stmt.exc is None:
                    # bare raise - re-raising the caught exception
                    has_reraise = True
                else:
                    # raise SomeException(...) - wrapping and re-raising
                    has_reraise = True

            # Check for logging
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                # Check if it's a logger call
                if isinstance(call.func, ast.Attribute):
                    func_name = call.func.attr
                    if func_name in ("debug", "info", "warning", "error", "critical", "exception", "log"):
                        # Check if it's on a logger object
                        has_logging = True
                # Check for print() as a form of logging (less ideal but not silent)
                if isinstance(call.func, ast.Name) and call.func.id == "print":
                    has_logging = True

            # Check for return with default value
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    has_return_default = True
                    return_value_detail = "return None"
                elif isinstance(stmt.value, ast.Constant):
                    val = repr(stmt.value.value)
                    if val in _SWALLOW_RETURN_VALUES or stmt.value.value in (None, False, 0, "", []):
                        has_return_default = True
                        return_value_detail = f"return {val}"
                elif isinstance(stmt.value, (ast.List, ast.Tuple)) and len(stmt.value.elts) == 0:
                    has_return_default = True
                    return_value_detail = "return []"
                elif isinstance(stmt.value, ast.Dict) and len(stmt.value.keys) == 0:
                    has_return_default = True
                    return_value_detail = "return {}"
                elif isinstance(stmt.value, ast.Set) and len(stmt.value.elts) == 0:
                    has_return_default = True
                    return_value_detail = "return set()"
                elif isinstance(stmt.value, ast.Name) and stmt.value.id in ("None", "False"):
                    has_return_default = True
                    return_value_detail = f"return {stmt.value.id}"

        # Skip known safe functions
        if self._current_function in _KNOWN_SAFE_FUNCTIONS:
            self.generic_visit(node)
            return

        # Report violations
        if has_return_default and not has_reraise:
            if has_logging:
                # Logged but swallowed - less severe, downgrade to warning
                self.violations.append(ExceptionLintViolation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    violation_type="swallow_return_logged",
                    detail=f"'except Exception' followed by '{return_value_detail}' swallows the error (logged). "
                           f"Consider re-raising or returning a Result type for better error propagation.",
                    severity="warning",
                ))
            else:
                self.violations.append(ExceptionLintViolation(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    violation_type="swallow_return",
                    detail=f"'except Exception' followed by '{return_value_detail}' swallows the error. "
                           f"Either re-raise, log+raise, or return a Result type.",
                    severity="error",
                ))
        elif not has_reraise and not has_logging:
            self.violations.append(ExceptionLintViolation(
                file_path=self.file_path,
                line_number=node.lineno,
                violation_type="no_log_no_reraise",
                detail="'except Exception' without re-raise or logging. "
                       "Error is silently ignored. Add logging or re-raise.",
                severity="warning",
            ))

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------


def scan_file(file_path: Path) -> tuple[list[ExceptionLintViolation], int]:
    """Scan a single Python file for exception handling violations."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return [], 0
    except Exception as e:
        logger.debug("Failed to parse %s: %s", file_path, e)
        return [], 0

    visitor = ExceptionLintVisitor(str(file_path))
    visitor.visit(tree)
    return visitor.violations, visitor.total_except_blocks


def scan_directory(
    root_path: Path,
    exclude_dirs: Optional[set[str]] = None,
) -> ExceptionLintResult:
    """Scan all Python files in a directory for exception handling violations."""
    if exclude_dirs is None:
        exclude_dirs = {
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "migrations", "dist", "build", ".tox", ".mypy_cache",
            ".ruff_cache", ".pytest_cache",
        }

    result = ExceptionLintResult()

    for py_file in root_path.rglob("*.py"):
        # Skip excluded directories
        parts = py_file.relative_to(root_path).parts
        if any(part in exclude_dirs for part in parts):
            continue

        violations, except_count = scan_file(py_file)
        result.violations.extend(violations)
        result.total_except_blocks += except_count
        result.files_scanned += 1

    return result


def scan_paths(paths: list[Path]) -> ExceptionLintResult:
    """Scan specific paths (files or directories)."""
    result = ExceptionLintResult()

    for path in paths:
        if path.is_file() and path.suffix == ".py":
            violations, except_count = scan_file(path)
            result.violations.extend(violations)
            result.total_except_blocks += except_count
            result.files_scanned += 1
        elif path.is_dir():
            sub_result = scan_directory(path)
            result.violations.extend(sub_result.violations)
            result.total_except_blocks += sub_result.total_except_blocks
            result.files_scanned += sub_result.files_scanned

    return result


# ---------------------------------------------------------------------------
# Regex-based quick scan (for files that can't be AST-parsed)
# ---------------------------------------------------------------------------

# Pattern: except Exception followed by return with a default value
_SWALLOW_PATTERN = re.compile(
    r"except\s+Exception\b[^:]*:\s*\n"
    r"(?:[ \t]+[^\n]*\n)*?"  # skip some lines
    r"[ \t]+return\s+(None|False|0|\[\]|\{\}|set\(\)|\'\'|\"\"|)\s*",
    re.MULTILINE,
)


def quick_scan_file(file_path: Path) -> list[ExceptionLintViolation]:
    """Quick regex-based scan for common swallow patterns.

    Less accurate than AST scan but catches patterns in files
    that might not parse correctly.
    """
    violations = []
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return violations

    for match in _SWALLOW_PATTERN.finditer(content):
        line_num = content[:match.start()].count("\n") + 1
        return_val = match.group(1) or "None"
        violations.append(ExceptionLintViolation(
            file_path=str(file_path),
            line_number=line_num,
            violation_type="swallow_return",
            detail=f"Regex match: 'except Exception' followed by 'return {return_val}'",
            severity="info",
        ))

    return violations


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ProtoForge Exception Lint - Layer 3",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["protoforge"],
        help="Paths to scan (default: protoforge/)",
    )
    parser.add_argument(
        "--severity",
        choices=["error", "warning", "info"],
        default="warning",
        help="Minimum severity to report (default: warning)",
    )
    parser.add_argument(
        "--max-violations",
        type=int,
        default=100,
        help="Maximum number of violations to report (default: 100)",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths]
    result = scan_paths(paths)

    # Filter by severity
    severity_order = {"error": 0, "warning": 1, "info": 2}
    min_severity = severity_order[args.severity]
    result.violations = [
        v for v in result.violations
        if severity_order.get(v.severity, 2) <= min_severity
    ]

    # Limit output
    if len(result.violations) > args.max_violations:
        result.violations = result.violations[:args.max_violations]

    print("\n=== ProtoForge Exception Lint (Layer 3) ===\n")
    print(result.summary())

    if result.error_count > 0:
        print("\nRecommended fixes:")
        print("  1. Replace 'except Exception: return None' with 'except Exception: logger.error(...); raise'")
        print("  2. Or use a Result type: return Err(exception)")
        print("  3. At minimum, add logging before returning a default value")

    return 1 if result.error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
