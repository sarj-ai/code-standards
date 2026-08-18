from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


class _RegexImports(NamedTuple):
    modules: frozenset[str]
    compile_functions: frozenset[str]


def _is_regex_call(node: ast.AST, *, compiled_names: frozenset[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr not in {"search", "match", "fullmatch", "finditer"}:
            return False
        if isinstance(func.value, ast.Name) and func.value.id in {
            "re",
            "regex",
            "pattern",
            "compiled_pattern",
            *compiled_names,
        }:
            return True
        if isinstance(func.value, ast.Attribute) and func.value.attr in {"pattern", "regex", "_pattern"}:
            return True
    return False


def _is_simple_truthy_test(test_node: ast.AST, var_name: str) -> bool:
    if isinstance(test_node, ast.Name) and test_node.id == var_name:
        return True
    if (
        isinstance(test_node, ast.Compare)
        and isinstance(test_node.left, ast.Name)
        and test_node.left.id == var_name
        and len(test_node.ops) == 1
        and isinstance(test_node.ops[0], ast.IsNot)
    ):
        right = test_node.comparators[0]
        if isinstance(right, ast.Constant) and right.value is None:
            return True
    return False


def _is_name_used_after(stmts: list[ast.stmt], start_idx: int, name: str) -> bool:
    class UsageVisitor(ast.NodeVisitor):
        used: bool = False

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == name:
                self.used = True
            self.generic_visit(node)

    visitor = UsageVisitor()
    for st in stmts[start_idx:]:
        visitor.visit(st)
        if visitor.used:
            return True
    return False


class PreferWalrusRegexMatch(Rule):
    id: str = "prefer-walrus-regex-match"
    code: str = "SARJ081"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Bind a regex result in the `if` condition that immediately tests it.",
        rationale="A named expression keeps the match operation and its condition together while preserving access to the result.",
        remediation="Move the regex call into the following condition as `if (match := pattern.search(text)):`.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a simple assignment immediately followed by a truthy or `is not None` check is analyzed.",
            "The assignment is retained when the result is used after the conditional or the regex receiver cannot be resolved.",
        ),
        examples=(
            RuleExample(
                example_id="assigned-regex-result",
                title="Regex result is assigned before its condition",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "import re\n\n"
                        "def first_number(text: str) -> str | None:\n"
                        '    match = re.search(r"\\d+", text)\n'
                        "    if match:\n"
                        "        return match.group(0)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="conditional-regex-binding",
                title="Regex result is bound in its condition",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "import re\n\n"
                        "def first_number(text: str) -> str | None:\n"
                        '    if match := re.search(r"\\d+", text):\n'
                        "        return match.group(0)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        if not any(
            isinstance(call.func, ast.Attribute) and call.func.attr in {"search", "match", "fullmatch", "finditer"}
            for call in nodes(tree, ast.Call)
        ):
            return []
        regex_imports = _regex_imports(tree)
        module_compiled = _compiled_bindings(
            tree.body,
            regex_imports.modules,
            regex_imports.compile_functions,
        )

        for node in walk(tree):
            raw_body = getattr(node, "body", None)
            if not isinstance(raw_body, list):
                continue
            body: list[ast.stmt] = [st for st in raw_body if isinstance(st, ast.stmt)]  # pyright: ignore[reportUnknownVariableType]
            shadowed: frozenset[str] = (
                _owner_bindings(node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                else frozenset()
            )
            compiled_names = (module_compiled - shadowed) | _compiled_bindings(
                body,
                regex_imports.modules,
                regex_imports.compile_functions,
            )

            for i in range(len(body) - 1):
                s1 = body[i]
                s2 = body[i + 1]

                if not (isinstance(s1, ast.Assign) and len(s1.targets) == 1 and isinstance(s1.targets[0], ast.Name)):
                    continue
                var_name = s1.targets[0].id

                if not _is_regex_call(s1.value, compiled_names=compiled_names) or not isinstance(s2, ast.If):
                    continue

                if not _is_simple_truthy_test(s2.test, var_name) or _is_name_used_after(body, i + 2, var_name):
                    continue

                if not is_suppressed(source_lines, s1.lineno, self.code):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=s1.lineno,
                            col=s1.col_offset + 1,
                            code=self.code,
                            message=(
                                f"Regex match pre-assignment `{var_name} = ...` before `if` — "
                                f"combine into `if ({var_name} := ...):`."
                            ),
                        )
                    )

        return sorted(diags, key=lambda d: (d.line, d.col))


def _regex_imports(tree: ast.Module) -> _RegexImports:
    modules: set[str] = set()
    functions: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.Import(names=names):
                modules.update(alias.asname or "re" for alias in names if alias.name == "re")
            case ast.ImportFrom(module="re", level=0, names=names):
                functions.update(alias.asname or alias.name for alias in names if alias.name == "compile")
            case _:
                continue
    return _RegexImports(frozenset(modules), frozenset(functions))


def _compiled_bindings(
    body: list[ast.stmt],
    regex_modules: frozenset[str],
    compile_functions: frozenset[str],
) -> frozenset[str]:
    assignments: dict[str, list[ast.expr]] = {}
    for statement in body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ) if _is_compile_call(value, regex_modules, compile_functions):
                assignments.setdefault(name, []).append(value)
            case _:
                continue
    if not assignments:
        return frozenset()
    binding_counts = _scope_binding_counts(body)
    return frozenset(name for name, values in assignments.items() if binding_counts.get(name) == 1 and len(values) == 1)


def _owner_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> frozenset[str]:
    names = set(_scope_binding_counts(node.body))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        names.update(argument.arg for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs))
        if args.vararg is not None:
            names.add(args.vararg.arg)
        if args.kwarg is not None:
            names.add(args.kwarg.arg)
    return frozenset(names)


def _scope_binding_counts(body: list[ast.stmt]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def record(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                record(node.name)
                continue
            case ast.Lambda():
                continue
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                record(name)
            case ast.alias(name=name, asname=asname):
                record(asname or name.split(".", maxsplit=1)[0])
            case ast.ExceptHandler() | ast.MatchAs() | ast.MatchStar():
                if node.name is not None:
                    record(node.name)
            case ast.MatchMapping(rest=str() as name):
                record(name)
            case _:
                pass
        stack.extend(ast.iter_child_nodes(node))
    return counts


def _is_compile_call(
    value: ast.expr,
    regex_modules: frozenset[str],
    compile_functions: frozenset[str],
) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id in compile_functions
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "compile"
        and isinstance(func.value, ast.Name)
        and func.value.id in regex_modules
    )
