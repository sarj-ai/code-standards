from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._docstrings import docstring_expression
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_DOCTEST_PROMPT = ">>>"
_KNOWN_DECORATORS = frozenset(
    {
        "agents.function_tool",
        "builtins.property",
        "functools.cached_property",
        "pytest.fixture",
        "pytest.yield_fixture",
        "strawberry.type",
    }
)
_KNOWN_SCHEMA_BASES = frozenset({"pydantic.BaseModel", "pydantic.RootModel", "pydantic_settings.BaseSettings"})
_SUPPRESSION_RE = re.compile(
    r"#\s*sarj-noqa:\s*(?P<codes>SARJ\d+(?:\s*,\s*SARJ\d+)*)\s*(?:—|--)\s*\S",
    re.IGNORECASE,
)


@final
class NoUnnecessaryDocstring(Rule):
    id: str = "no-unnecessary-docstring"
    code: str = "SARJ420"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Keep docstrings only when a machine or framework consumes them.",
        rationale=(
            "Human-only docstrings duplicate names, signatures, and nearby code while creating a second prose surface "
            "that agents expand and maintainers must review."
        ),
        remediation=(
            "Delete the docstring; move a genuinely hidden local invariant to one concise comment, or suppress SARJ420 "
            "when an external documentation consumer cannot be detected mechanically."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Generated files, doctests, syntax-required stub bodies, schema classes, framework decorators, explicit "
                "__doc__/help/getdoc consumers, and local sarj-noqa suppressions are excluded."
            ),
            (
                "The rule is intentionally default-deny: public API documentation without mechanically visible "
                "consumption needs an auditable SARJ420 suppression."
            ),
        ),
        examples=(
            RuleExample(
                example_id="human-only-docstrings",
                title="Human-only module, class, and function prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        '"""Service entry points."""\n\nclass Service:\n    """Coordinates requests."""\n\n    def run(self) -> None:\n        """Run the service."""\n        return None\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=3,
                public=True,
            ),
            RuleExample(
                example_id="framework-docstring",
                title="Framework consumes the function docstring",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/tools.py",
                        'from agents import function_tool\n\n@function_tool\ndef lookup_account(account_id: str) -> str:\n    """Look up an account for the model."""\n    return account_id\n',
                    ),
                ),
                focus_path=PurePosixPath("app/tools.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        owner_keys = _owner_keys(tree)
        explicitly_consumed = _explicit_docstring_consumers(tree, frozenset(owner_keys.values()))
        shadowed = _module_bound_names(tree)
        imports = _import_bindings(tree, shadowed)
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for owner in _docstring_owners(tree):
            expression = docstring_expression(owner)
            if expression is None:
                continue
            docstring = ast.get_docstring(owner, clean=False)
            if docstring is None or _DOCTEST_PROMPT in docstring:
                continue
            if _is_syntax_required(owner) or _framework_consumes_docstring(owner, imports, shadowed):
                continue
            if owner_keys[id(owner)] in explicitly_consumed:
                continue
            if _suppressed_on_docstring(source_lines, expression, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=expression.lineno,
                    col=expression.col_offset + 1,
                    code=self.code,
                    message=self.description,
                    severity=Severity.WARNING,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _docstring_owners(tree: ast.Module) -> Iterable[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    yield tree
    yield from (
        node for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _is_syntax_required(owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not isinstance(owner, ast.Module) and len(owner.body) == 1


def _owner_keys(tree: ast.Module) -> dict[int, str]:
    keys = {id(tree): "__doc__"}

    def visit(body: list[ast.stmt], prefix: tuple[str, ...]) -> None:
        for statement in body:
            if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = (*prefix, statement.name)
                keys[id(statement)] = ".".join(qualified)
                visit(statement.body, qualified)

    visit(tree.body, ())
    return keys


def _suppressed_on_docstring(source_lines: list[str], expression: ast.Expr, code: str) -> bool:
    end_line = expression.end_lineno or expression.lineno
    if end_line < 1 or end_line > len(source_lines):
        return False
    match = _SUPPRESSION_RE.search(source_lines[end_line - 1])
    return match is not None and code in {item.strip().upper() for item in match.group("codes").split(",")}


def _explicit_docstring_consumers(tree: ast.Module, owners: frozenset[str]) -> frozenset[str]:
    consumed: set[str] = set()
    owner_index = _owner_index(owners)
    aliases = _module_aliases(tree, owners, owner_index)
    module_level = _module_level_node_ids(tree)
    inspect_names: set[str] = set()
    getdoc_names: set[str] = set()
    shadowed = _module_bound_names(tree)
    builtin_help_available = True
    for statement in tree.body:
        match statement:
            case ast.Import(names=names):
                for item in names:
                    if item.name == "inspect" and (item.asname or item.name) not in shadowed:
                        inspect_names.add(item.asname or item.name)
            case ast.ImportFrom(module="inspect", names=names):
                for item in names:
                    if item.name == "getdoc" and (item.asname or item.name) not in shadowed:
                        getdoc_names.add(item.asname or item.name)
            case ast.FunctionDef(name="help") | ast.AsyncFunctionDef(name="help") | ast.ClassDef(name="help"):
                builtin_help_available = False
            case ast.Assign(targets=targets) if any(
                isinstance(target, ast.Name) and target.id == "help" for target in targets
            ):
                builtin_help_available = False
            case _:
                pass
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "__doc__"
            and id(node) in module_level
        ):
            consumed.add("__doc__")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr == "__doc__":
            if key := _resolve_owner(node.value, owners, aliases, owner_index):
                consumed.add(key)
        elif isinstance(node, ast.Call) and node.args:
            function = _dotted_name(node.func)
            is_getdoc = function in ({f"{name}.getdoc" for name in inspect_names} | getdoc_names)
            is_help = function == "help" and builtin_help_available and id(node) in module_level
            if (is_getdoc or is_help) and (key := _resolve_owner(node.args[0], owners, aliases, owner_index)):
                consumed.add(key)
    imports = _import_bindings(tree, shadowed)
    for owner in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        for decorator in owner.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            function = _resolve_imported_name(decorator.func, imports)
            if function == "functools.wraps" and (
                key := _resolve_owner(decorator.args[0], owners, aliases, owner_index)
            ):
                consumed.add(key)
    return frozenset(consumed)


def _dotted_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            prefix = _dotted_name(value)
            return None if prefix is None else f"{prefix}.{attribute}"
        case _:
            return None


def _resolve_owner(
    node: ast.AST,
    owners: frozenset[str],
    aliases: dict[str, str],
    owner_index: dict[str, tuple[str, ...]],
) -> str | None:
    name = _dotted_name(node)
    if name is None:
        return None
    seen: set[str] = set()
    while name in aliases and name not in seen:
        seen.add(name)
        name = aliases[name]
    if name in owners:
        return name
    matches = owner_index.get(name, ())
    return matches[0] if len(matches) == 1 else None


def _module_aliases(
    tree: ast.Module, owners: frozenset[str], owner_index: dict[str, tuple[str, ...]]
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    invalid: set[str] = set()
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value = statement.value
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id in aliases or target.id in invalid or value is None:
                aliases.pop(target.id, None)
                invalid.add(target.id)
                continue
            if _is_current_module_expression(value):
                aliases[target.id] = "__doc__"
            elif (resolved := _resolve_owner(value, owners, aliases, owner_index)) is not None:
                aliases[target.id] = resolved
    return aliases


def _is_current_module_expression(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and _dotted_name(node.value) == "sys.modules"
        and isinstance(node.slice, ast.Name)
        and node.slice.id == "__name__"
    )


def _owner_index(owners: frozenset[str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for owner in owners:
        grouped.setdefault(owner.rpartition(".")[2], []).append(owner)
    return {name: tuple(values) for name, values in grouped.items()}


def _module_level_node_ids(tree: ast.Module) -> frozenset[int]:
    return frozenset(
        id(node)
        for statement in tree.body
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in ast.walk(statement)
    )


def _framework_consumes_docstring(
    owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    shadowed: frozenset[str],
) -> bool:
    if isinstance(owner, ast.Module):
        return False
    for decorator in owner.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = _resolve_imported_name(target, imports)
        if name in _KNOWN_DECORATORS:
            return True
        if name == "property" and "property" not in shadowed:
            return True
    if not isinstance(owner, ast.ClassDef):
        return False
    return any(
        _resolve_imported_name(base.value if isinstance(base, ast.Subscript) else base, imports) in _KNOWN_SCHEMA_BASES
        for base in owner.bases
    )


def _import_bindings(tree: ast.Module, shadowed: frozenset[str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for statement in tree.body:
        match statement:
            case ast.Import(names=names):
                for item in names:
                    local_name = item.asname or item.name.partition(".")[0]
                    if local_name not in shadowed:
                        bindings[local_name] = item.name
            case ast.ImportFrom(module=str() as module, names=names):
                for item in names:
                    local_name = item.asname or item.name
                    if local_name not in shadowed:
                        bindings[local_name] = f"{module}.{item.name}"
            case _:
                continue
    return bindings


def _module_bound_names(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(statement.name)
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)):
                names.add(name)
            case _:
                continue
    return frozenset(names)


def _resolve_imported_name(node: ast.AST, imports: dict[str, str]) -> str | None:
    dotted = _dotted_name(node)
    if dotted is None:
        return None
    head, separator, tail = dotted.partition(".")
    resolved = imports.get(head)
    if resolved is None:
        return dotted
    return f"{resolved}.{tail}" if separator else resolved
