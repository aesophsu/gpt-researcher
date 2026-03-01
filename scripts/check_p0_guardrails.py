#!/usr/bin/env python3
"""Static guardrails for P0 regressions."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
SERVER_DIR = BACKEND_DIR / "server"
APP_FILE = SERVER_DIR / "app.py"

RULE_MUTABLE_DEFAULT = "P0_MUTABLE_DEFAULT"
RULE_ENV_WRITE = "P0_ENV_WRITE"
RULE_DUP_MOUNT = "P0_DUP_MOUNT"

# Explicit carve-out for deprecated helper kept for backward compatibility.
ENV_WRITE_ALLOWLIST: set[tuple[str, str]] = {
    ("backend/server/server_utils.py", "update_environment_variables"),
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def parse_file(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def is_mutable_default(node: ast.AST | None) -> bool:
    return isinstance(node, (ast.List, ast.Dict, ast.Set))


def check_mutable_defaults(issues: list[str]) -> None:
    for file in BACKEND_DIR.rglob("*.py"):
        tree = parse_file(file)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            pos_defaults = node.args.defaults or []
            pos_args = node.args.args[-len(pos_defaults) :] if pos_defaults else []
            for arg_node, default_node in zip(pos_args, pos_defaults):
                if is_mutable_default(default_node):
                    issues.append(
                        f"[{RULE_MUTABLE_DEFAULT}] {rel(file)}:{default_node.lineno} "
                        f"{node.name}('{arg_node.arg}') uses mutable default"
                    )

            for kw_arg, kw_default in zip(node.args.kwonlyargs, node.args.kw_defaults or []):
                if is_mutable_default(kw_default):
                    issues.append(
                        f"[{RULE_MUTABLE_DEFAULT}] {rel(file)}:{kw_default.lineno} "
                        f"{node.name}('{kw_arg.arg}') uses mutable kw-only default"
                    )


def is_os_environ_subscript(node: ast.AST) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    value = node.value
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "environ"
        and isinstance(value.value, ast.Name)
        and value.value.id == "os"
    )


def check_env_writes(issues: list[str]) -> None:
    for file in SERVER_DIR.rglob("*.py"):
        tree = parse_file(file)
        function_stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            def visit_Assign(self, node: ast.Assign) -> None:
                current_fn = function_stack[-1] if function_stack else "<module>"
                for target in node.targets:
                    if is_os_environ_subscript(target):
                        key = (rel(file), current_fn)
                        if key not in ENV_WRITE_ALLOWLIST:
                            issues.append(
                                f"[{RULE_ENV_WRITE}] {rel(file)}:{node.lineno} "
                                f"os.environ write detected in {current_fn}"
                            )
                self.generic_visit(node)

            def visit_AugAssign(self, node: ast.AugAssign) -> None:
                current_fn = function_stack[-1] if function_stack else "<module>"
                if is_os_environ_subscript(node.target):
                    key = (rel(file), current_fn)
                    if key not in ENV_WRITE_ALLOWLIST:
                        issues.append(
                            f"[{RULE_ENV_WRITE}] {rel(file)}:{node.lineno} "
                            f"os.environ write detected in {current_fn}"
                        )
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                current_fn = function_stack[-1] if function_stack else "<module>"
                if is_os_environ_subscript(node.target):
                    key = (rel(file), current_fn)
                    if key not in ENV_WRITE_ALLOWLIST:
                        issues.append(
                            f"[{RULE_ENV_WRITE}] {rel(file)}:{node.lineno} "
                            f"os.environ write detected in {current_fn}"
                        )
                self.generic_visit(node)

        Visitor().visit(tree)


def check_duplicate_mounts(issues: list[str]) -> None:
    if not APP_FILE.exists():
        issues.append(f"[{RULE_DUP_MOUNT}] backend/server/app.py:1 file not found")
        return

    tree = parse_file(APP_FILE)
    seen: dict[str, int] = {}
    duplicates: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "mount"):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
            continue
        path_value = first_arg.value
        if path_value in seen:
            duplicates.append((path_value, node.lineno))
        else:
            seen[path_value] = node.lineno

    for path_value, line in duplicates:
        issues.append(
            f"[{RULE_DUP_MOUNT}] {rel(APP_FILE)}:{line} duplicate app.mount path '{path_value}'"
        )


def main() -> int:
    issues: list[str] = []
    check_mutable_defaults(issues)
    check_env_writes(issues)
    check_duplicate_mounts(issues)

    if issues:
        for issue in sorted(issues):
            print(issue)
        return 1

    print("P0 guardrails passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
