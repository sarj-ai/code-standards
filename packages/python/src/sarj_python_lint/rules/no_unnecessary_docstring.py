from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_semantics import scope_bound_names
from sarj_python_lint.rules._ast_index import parent_map, walk as walk_ast
from sarj_python_lint.rules._docstrings import docstring_expression
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_DOCTEST_PROMPT = ">>>"
_METADATA_MODULES = frozenset({"functools", "dataclasses", "builtins", "abc", "typing", "typing_extensions"})
_METADATA_CALLABLE_NAMES = frozenset(
    {"wraps", "lru_cache", "cache", "dataclass", "classmethod", "staticmethod", "abstractmethod", "override"}
)
_METADATA_NAMESPACE_MEMBERS = frozenset({"__dict__", "__getattribute__", "__setattr__", "__delattr__"})
_METADATA_READONLY_ATTRIBUTES = frozenset({"__name__", "__qualname__", "__module__", "__doc__"})
_BARE_METADATA_DECORATORS = frozenset(
    {"builtins.classmethod", "builtins.staticmethod", "functools.cache", "functools.lru_cache"}
)
_TRANSPARENT_METADATA_MODIFIERS = frozenset({"abc.abstractmethod", "typing.override", "typing_extensions.override"})
_DATACLASS_OPTIONS = (
    "init",
    "repr",
    "eq",
    "order",
    "unsafe_hash",
    "frozen",
    "match_args",
    "kw_only",
    "slots",
    "weakref_slot",
)

_LIVEKIT_TOOL_DECORATORS = frozenset(
    {
        "livekit.agents.function_tool",
        "livekit.agents.llm.function_tool",
    }
)
_OPENAI_TOOL_DECORATORS = frozenset({"agents.function_tool"})
_PYDANTIC_DOC_DECORATORS = frozenset({"pydantic.computed_field"})
_FASTAPI_CONSTRUCTORS = frozenset({"fastapi.APIRouter", "fastapi.FastAPI"})
_FASTAPI_ROUTE_METHODS = frozenset({"api_route", "delete", "get", "head", "options", "patch", "post", "put", "trace"})
_TYPER_CONSTRUCTORS = frozenset({"typer.Typer"})
_TYPER_DOC_METHODS = frozenset({"callback", "command"})
_CLICK_DOC_DECORATORS = frozenset({"click.command", "click.group"})
_CLICK_GROUP_CONSTRUCTORS = frozenset({"click.Group"})
_CLICK_GROUP_METHODS = frozenset({"command", "group"})
_KNOWN_DECORATORS = frozenset(
    {
        "builtins.property",
        "functools.cached_property",
        "pytest.fixture",
        "pytest.yield_fixture",
        "pytest_asyncio.fixture",
        "pytest_asyncio.plugin.fixture",
        "strawberry.type",
    }
)
_KNOWN_SCHEMA_BASES = frozenset(
    {
        "enum.Enum",
        "enum.Flag",
        "enum.IntEnum",
        "enum.IntFlag",
        "enum.StrEnum",
        "pydantic.BaseModel",
        "pydantic.RootModel",
        "pydantic_settings.BaseSettings",
    }
)
_SUPPRESSION_RE = re.compile(
    r"#\s*sarj-noqa:\s*(?P<codes>SARJ\d+(?:\s*,\s*SARJ\d+)*)\s*(?:—|--)\s*\S",
    re.IGNORECASE,
)


class _ModuleEnvironment(NamedTuple):
    imports: dict[str, str]
    shadowed: frozenset[str]


@final
class NoUnnecessaryDocstring(ProjectRule):
    id: str = "no-unnecessary-docstring"
    code: str = "SARJ420"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary=(
            "No docstring consumer detected — delete it; make author-controlled names, types, and structure explain "
            "the code."
        ),
        rationale=(
            "A docstring with no detected consumer makes code depend on prose for ordinary meaning and creates a "
            "second maintenance surface that agents expand and maintainers must review."
        ),
        remediation=(
            "Delete the docstring. If author-controlled code is unclear without it, clarify names, types, and structure "
            "or extract a small named helper. Keep a genuinely hidden invariant as one concise local comment. When "
            "external tooling consumes __doc__, use an exact SARJ420 suppression that names the consumer."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes require a second native error-level exact-name-restatement finding on an unescaped private nested synchronous nongenerator function. All references must be direct calls; public APIs, classes/modules, behavioral prose, escapes and metadata consumers remain review-only. Known frame and metadata capabilities, their import aliases and metadata field access prevent fixes.",
            "Containing callables must also be ordinary synchronous nongenerators with proven inert execution; unknown callouts, properties, overloads, reachable frame-exporting exceptions, and helper references crossing additional function, class, lambda, or comprehension scopes prevent fixes.",
            (
                "Generated files, doctests, syntax-required stub bodies, schema classes, framework decorators, explicit "
                "__doc__/help/getdoc consumers, canonical metadata-copy decorators, and local sarj-noqa suppressions are excluded."
            ),
            (
                "The rule is intentionally default-deny: public API documentation without mechanically visible "
                "consumption needs an auditable SARJ420 suppression."
            ),
            (
                "Dynamic Click or Typer decorator options are conservatively treated as possible help consumers; "
                "explicit non-None help leaves the docstring eligible."
            ),
            (
                "Source-proven direct decorators returning a wraps-decorated wrapper consume only their input doc; "
                "factory and wrapper implementation prose remain eligible. Unknown assigned/updated options, shadowed "
                "bindings, lazy outer factories, opaque wrapper headers, and unresolved imports do not prove metadata consumption."
            ),
        ),
        examples=(
            RuleExample(
                example_id="safe-private-autofix-subset",
                title="Unescaped private helper keeps its behavioral contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "def outer(value):\n"
                            "    def _normalize(item):\n"
                            '        """Normalize."""\n'
                            "        return item\n"
                            "    return _normalize(value)\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "def outer(value):\n"
                            "    def _normalize(item):\n"
                            "        return item\n"
                            "    return _normalize(value)\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
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
            RuleExample(
                example_id="wraps-without-doc-copy",
                scenario="metadata-copy",
                title="A wrapper excluding __doc__ does not consume input prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/metadata.py",
                        'from functools import wraps\n\ndef original() -> int:\n    """This prose is not copied."""\n    return 1\n\n@wraps(original, assigned=())\ndef wrapped() -> int:\n    return original()\n',
                    ),
                ),
                focus_path=PurePosixPath("app/metadata.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="canonical-metadata-consumers",
                scenario="metadata-copy",
                title="Standard-library decorators mechanically read or copy docstrings",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/metadata.py",
                        'from dataclasses import dataclass\nfrom functools import lru_cache\n\n@dataclass(frozen=True, slots=True)\nclass Options:\n    """Read by dataclass metadata generation."""\n    limit: int\n\n@lru_cache(maxsize=1)\ndef options() -> Options:\n    """Copied onto the cache wrapper."""\n    return Options(limit=10)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/metadata.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        if not any(
            docstring_expression(owner) is not None for owner in _docstring_owners(tree, node_index=context.node_index)
        ):
            return []
        metadata = _metadata_context_bindings(context, tree)
        owner_keys = _owner_keys(tree)
        explicit_consumers = _explicit_docstring_consumers(
            tree, owner_keys, metadata=metadata, node_index=context.node_index
        )
        shadowed = _module_bound_names(tree)
        imports = _import_bindings(tree, shadowed)
        consumed_owner_ids = (
            _fastapi_docstring_consumers(tree, imports)
            | _typer_docstring_consumers(tree, imports)
            | _click_group_docstring_consumers(tree, imports)
            | _schema_docstring_consumers(tree, imports, node_index=context.node_index)
            | _project_schema_docstring_consumers(context.session.project, path, tree, node_index=context.node_index)
            | _metadata_docstring_consumers(context, metadata)
            | explicit_consumers.copied_owner_ids
        )
        source_lines = context.source_lines
        diagnostics: list[Diagnostic] = []
        for owner in _docstring_owners(tree, node_index=context.node_index):
            expression = docstring_expression(owner)
            if expression is None:
                continue
            docstring = ast.get_docstring(owner, clean=False)
            if docstring is None or _DOCTEST_PROMPT in docstring:
                continue
            owner_line = 1 if isinstance(owner, ast.Module) else owner.lineno
            owner_imports, owner_shadowed = _module_environment_before(tree, owner_line)
            if (
                _is_syntax_required(owner)
                or id(owner) in consumed_owner_ids
                or _framework_consumes_docstring(owner, owner_imports, owner_shadowed)
            ):
                continue
            if owner_keys[id(owner)] in explicit_consumers.names:
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
                    severity=Severity.ERROR,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _docstring_owners(
    tree: ast.Module, *, node_index: NodeIndex | None = None
) -> Iterable[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    yield tree
    yield from (
        node
        for node in walk_ast(tree, index=node_index)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _is_syntax_required(owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not isinstance(owner, ast.Module) and len(owner.body) == 1


def _owner_keys(tree: ast.Module) -> dict[int, str]:
    keys = {id(tree): "__doc__"}
    pending: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    while pending:
        node, prefix = pending.pop()
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = (*prefix, node.name)
            keys[id(node)] = ".".join(prefix)
        pending.extend((child, prefix) for child in reversed(tuple(ast.iter_child_nodes(node))))
    return keys


def _suppressed_on_docstring(source_lines: list[str], expression: ast.Expr, code: str) -> bool:
    end_line = expression.end_lineno or expression.lineno
    if end_line < 1 or end_line > len(source_lines):
        return False
    match = _SUPPRESSION_RE.search(source_lines[end_line - 1])
    return match is not None and code in {item.strip().upper() for item in match.group("codes").split(",")}


@dataclass(frozen=True, slots=True)
class _ExplicitDocstringConsumers:
    names: frozenset[str]
    copied_owner_ids: frozenset[int]


def _explicit_docstring_consumers(
    tree: ast.Module, owner_keys: dict[int, str], *, metadata: _MetadataBindings, node_index: NodeIndex | None = None
) -> _ExplicitDocstringConsumers:
    owners = frozenset(owner_keys.values())
    consumed: set[str] = set()
    copied_owner_ids: set[int] = set()
    owner_index = _owner_index(owners)
    aliases = _module_aliases(tree, owners, owner_index)
    metadata_owners = _MetadataOwners(
        owner_keys,
        aliases,
        owner_index,
        metadata,
        _metadata_declaration_occurrences(tree, owner_keys, node_index=node_index),
    )
    inspect_names: set[str] = set()
    getdoc_names: set[str] = set()
    shadowed = _module_bound_names(tree)
    imports = _import_bindings(tree, shadowed)
    if _bare_module_docstring_consumed(tree, node_index=node_index):
        consumed.add("__doc__")
    builtin_help_available = _doc_consumer_imports(tree, shadowed, inspect_names, getdoc_names)

    def collect_call_consumers(node: ast.Call) -> None:
        function = _dotted_name(node.func)
        is_getdoc = function in ({f"{name}.getdoc" for name in inspect_names} | getdoc_names)
        is_help = function == "help" and builtin_help_available
        if (is_getdoc or is_help) and (key := _resolve_owner(node.args[0], owners, aliases, owner_index)):
            consumed.add(key)
        resolved_function = _resolve_imported_name(node.func, imports)
        if (
            resolved_function in _LIVEKIT_TOOL_DECORATORS
            and _livekit_uses_docstring(node)
            and (key := _resolve_owner(node.args[0], owners, aliases, owner_index))
        ):
            consumed.add(key)

    for node in walk_ast(tree, index=node_index):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr == "__doc__":
            if key := _resolve_owner(node.value, owners, aliases, owner_index):
                consumed.add(key)
        elif isinstance(node, ast.Call):
            if node.args:
                collect_call_consumers(node)
            if copied_owner := _metadata_explicit_owner(node, metadata_owners):
                copied_owner_ids.add(id(copied_owner))

    copied_owner_ids.update(
        id(owner) for owner in _metadata_wrapped_owners(tree, metadata_owners, node_index=node_index)
    )
    return _ExplicitDocstringConsumers(names=frozenset(consumed), copied_owner_ids=frozenset(copied_owner_ids))


def _metadata_wrapped_owners(
    tree: ast.Module, owners: _MetadataOwners, *, node_index: NodeIndex | None
) -> frozenset[_MetadataOwner]:
    consumed: set[_MetadataOwner] = set()
    for owner in walk_ast(tree, index=node_index):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in owner.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            wrapped = _wraps_doc_argument(decorator, owners.bindings)
            if (
                wrapped is not None
                and (key := _metadata_copy_owner(wrapped, owners))
                and _metadata_wraps_header_preserved(owner, key, owners)
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


def _bare_module_docstring_consumed(tree: ast.Module, *, node_index: NodeIndex | None = None) -> bool:
    parents = parent_map(tree, index=node_index)
    for node in walk_ast(tree, index=node_index):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "__doc__"):
            continue
        current: ast.AST = node
        inside_function = False
        while (parent := parents.get(current)) is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                inside_function = True
                if _function_binds_docstring_name(parent):
                    break
            elif isinstance(parent, ast.ClassDef) and not inside_function:
                break
            current = parent
        else:
            return True
    return False


def _function_binds_docstring_name(owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> bool:
    arguments = (
        *owner.args.posonlyargs,
        *owner.args.args,
        *owner.args.kwonlyargs,
    )
    if any(argument.arg == "__doc__" for argument in arguments):
        return True
    if owner.args.vararg is not None and owner.args.vararg.arg == "__doc__":
        return True
    if owner.args.kwarg is not None and owner.args.kwarg.arg == "__doc__":
        return True
    body = owner.body if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) else [owner.body]
    if any(
        isinstance(node, ast.Global) and "__doc__" in node.names for statement in body for node in walk_ast(statement)
    ):
        return False

    def binds(node: ast.AST) -> bool:
        match node:
            case ast.Name(id="__doc__", ctx=ast.Store()):
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                return node.name == "__doc__"
            case ast.Lambda():
                return False
            case _:
                return any(binds(child) for child in ast.iter_child_nodes(node))

    return any(binds(statement) for statement in body)


def _framework_consumes_docstring(
    owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    shadowed: frozenset[str],
) -> bool:
    if isinstance(owner, ast.Module):
        return False
    for decorator in owner.decorator_list:
        if _decorator_consumes_docstring(decorator, imports, shadowed):
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
        _collect_import_binding(statement, shadowed, bindings)
    return bindings


def _module_environment_before(tree: ast.Module, line: int) -> _ModuleEnvironment:
    imports: dict[str, str] = {}
    shadowed: set[str] = set()
    for statement in tree.body:
        if statement.lineno >= line:
            break
        _update_module_environment(statement, imports, shadowed)
    return _ModuleEnvironment(imports, frozenset(shadowed))


def _decorator_consumes_docstring(decorator: ast.expr, imports: dict[str, str], shadowed: frozenset[str]) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = _dotted_name(target)
    head = None if dotted is None else dotted.partition(".")[0]
    name = _resolve_imported_name(target, imports) if head in imports else None
    if name in _LIVEKIT_TOOL_DECORATORS and (not isinstance(decorator, ast.Call) or _livekit_uses_docstring(decorator)):
        return True
    if name in _OPENAI_TOOL_DECORATORS and (
        not isinstance(decorator, ast.Call) or _keyword_is_not_literal_false(decorator, "use_docstring_info")
    ):
        return True
    if name in _PYDANTIC_DOC_DECORATORS and (
        not isinstance(decorator, ast.Call) or _keyword_is_missing_or_none(decorator, "description")
    ):
        return True
    if name in _CLICK_DOC_DECORATORS and (not isinstance(decorator, ast.Call) or _doc_help_is_implicit(decorator)):
        return True
    if name in _KNOWN_DECORATORS:
        return True
    return bool(dotted == "property" and "property" not in shadowed)


def _keyword_is_not_literal_false(call: ast.Call, name: str) -> bool:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    return not (isinstance(value, ast.Constant) and value.value is False)


def _keyword_is_missing_or_none(call: ast.Call, name: str) -> bool:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def _doc_help_is_implicit(call: ast.Call) -> bool:
    return _keyword_is_missing_or_none(call, "help")


def _livekit_uses_docstring(call: ast.Call) -> bool:
    return not any(
        keyword.arg == "raw_schema" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
        for keyword in call.keywords
    )


def _fastapi_docstring_consumers(tree: ast.Module, imports: dict[str, str]) -> frozenset[int]:
    consumed: set[int] = set()

    def visit(body: list[ast.stmt], inherited: dict[str, bool]) -> None:
        bindings = dict(inherited)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if any(_is_fastapi_route(decorator, bindings) for decorator in statement.decorator_list):
                    consumed.add(id(statement))
                nested = dict(bindings)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _receiver_parameter_bindings(statement, nested, imports, _FASTAPI_CONSTRUCTORS)
                visit(statement.body, nested)
                bindings[statement.name] = False
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                value = statement.value
                is_receiver = _is_fastapi_receiver_value(value, bindings, imports)
                _bind_receiver_targets(targets, bindings, is_receiver=is_receiver)

    visit(tree.body, {})
    return frozenset(consumed)


def _typer_docstring_consumers(tree: ast.Module, imports: dict[str, str]) -> frozenset[int]:
    consumed: set[int] = set()

    def visit(body: list[ast.stmt], inherited: dict[str, bool]) -> None:
        bindings = dict(inherited)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if any(_is_typer_callback(decorator, bindings) for decorator in statement.decorator_list):
                    consumed.add(id(statement))
                nested = dict(bindings)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _receiver_parameter_bindings(statement, nested, imports, _TYPER_CONSTRUCTORS)
                visit(statement.body, nested)
                bindings[statement.name] = False
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                value = statement.value
                is_receiver = _is_typer_receiver_value(value, bindings, imports)
                _bind_receiver_targets(targets, bindings, is_receiver=is_receiver)

    visit(tree.body, {})
    return frozenset(consumed)


def _click_group_docstring_consumers(tree: ast.Module, imports: dict[str, str]) -> frozenset[int]:
    consumed: set[int] = set()

    def visit_declaration(
        statement: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, bindings: dict[str, bool]
    ) -> None:
        group_decorator = next(
            (decorator for decorator in statement.decorator_list if _is_click_group_decorator(decorator, imports)),
            None,
        )
        if any(_is_click_group_callback(decorator, bindings) for decorator in statement.decorator_list):
            consumed.add(id(statement))
        visit(statement.body, bindings)
        bindings[statement.name] = group_decorator is not None

    def visit(body: list[ast.stmt], inherited: dict[str, bool]) -> None:
        bindings = dict(inherited)
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit_declaration(statement, bindings)
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                value = statement.value
                is_receiver = _is_click_group_receiver_value(value, bindings, imports)
                for target in targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = is_receiver

    visit(tree.body, {})
    return frozenset(consumed)


def _schema_docstring_consumers(
    tree: ast.Module, imports: dict[str, str], *, node_index: NodeIndex | None = None
) -> frozenset[int]:
    classes = {
        statement.name: statement
        for statement in walk_ast(tree, index=node_index)
        if isinstance(statement, ast.ClassDef)
    }
    consumed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, class_node in classes.items():
            if name in consumed:
                continue
            base_names = {
                _resolve_imported_name(base.value if isinstance(base, ast.Subscript) else base, imports)
                for base in class_node.bases
            }
            if not base_names.isdisjoint(_KNOWN_SCHEMA_BASES | consumed):
                consumed.add(name)
                changed = True
    return frozenset(id(classes[name]) for name in consumed)


def _project_schema_docstring_consumers(
    indexes: ProjectIndexSet | None, path: Path, tree: ast.Module, *, node_index: NodeIndex | None = None
) -> frozenset[int]:
    if indexes is None or (unit := indexes.unit(path)) is None:
        return frozenset()
    return frozenset(
        id(owner)
        for owner in walk_ast(tree, index=node_index)
        if isinstance(owner, ast.ClassDef) and indexes.class_inherits_from(unit, owner.name, _KNOWN_SCHEMA_BASES)
    )


def _is_fastapi_receiver_value(node: ast.AST | None, bindings: dict[str, bool], imports: dict[str, str]) -> bool:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, False) or _resolve_imported_name(node, imports) in _FASTAPI_CONSTRUCTORS
    return isinstance(node, ast.Call) and (
        _resolve_imported_name(node.func, imports) in _FASTAPI_CONSTRUCTORS
        or (isinstance(node.func, ast.Name) and bindings.get(node.func.id, False))
    )


def _is_fastapi_route(decorator: ast.expr, bindings: dict[str, bool]) -> bool:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return False
    receiver = decorator.func.value
    if (
        not isinstance(receiver, ast.Name)
        or not bindings.get(receiver.id)
        or decorator.func.attr not in _FASTAPI_ROUTE_METHODS
    ):
        return False
    description = next((keyword.value for keyword in decorator.keywords if keyword.arg == "description"), None)
    return description is None or (isinstance(description, ast.Constant) and not description.value)


def _is_typer_receiver_value(node: ast.AST | None, bindings: dict[str, bool], imports: dict[str, str]) -> bool:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, False) or _resolve_imported_name(node, imports) in _TYPER_CONSTRUCTORS
    return isinstance(node, ast.Call) and (
        _resolve_imported_name(node.func, imports) in _TYPER_CONSTRUCTORS
        or (isinstance(node.func, ast.Name) and bindings.get(node.func.id, False))
    )


def _is_typer_callback(decorator: ast.expr, bindings: dict[str, bool]) -> bool:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return False
    receiver = decorator.func.value
    return (
        isinstance(receiver, ast.Name)
        and bindings.get(receiver.id, False)
        and decorator.func.attr in _TYPER_DOC_METHODS
        and _doc_help_is_implicit(decorator)
    )


def _is_click_group_decorator(decorator: ast.expr, imports: dict[str, str]) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _resolve_imported_name(target, imports) == "click.group"


def _is_click_group_receiver_value(node: ast.AST | None, bindings: dict[str, bool], imports: dict[str, str]) -> bool:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, False) or _resolve_imported_name(node, imports) in _CLICK_GROUP_CONSTRUCTORS
    return isinstance(node, ast.Call) and (
        _resolve_imported_name(node.func, imports) in _CLICK_GROUP_CONSTRUCTORS
        or (isinstance(node.func, ast.Name) and bindings.get(node.func.id, False))
    )


def _is_click_group_callback(decorator: ast.expr, bindings: dict[str, bool]) -> bool:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return False
    receiver = decorator.func.value
    return (
        isinstance(receiver, ast.Name)
        and bindings.get(receiver.id, False)
        and decorator.func.attr in _CLICK_GROUP_METHODS
        and _doc_help_is_implicit(decorator)
    )


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


def _doc_consumer_imports(
    tree: ast.Module, shadowed: frozenset[str], inspect_names: set[str], getdoc_names: set[str]
) -> bool:
    builtin_help_available = True
    for statement in tree.body:
        match statement:
            case ast.Import(names=names):
                _collect_inspect_modules(names, shadowed, inspect_names)
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
    return builtin_help_available


def _collect_import_binding(statement: ast.stmt, shadowed: frozenset[str], bindings: dict[str, str]) -> None:
    match statement:
        case ast.Import(names=names):
            for item in names:
                local_name = item.asname or item.name.partition(".")[0]
                if local_name not in shadowed:
                    bindings[local_name] = item.name if item.asname else local_name
        case ast.ImportFrom(module=str() as module, names=names, level=0):
            for item in names:
                local_name = item.asname or item.name
                if local_name not in shadowed:
                    bindings[local_name] = f"{module}.{item.name}"
        case _:
            return


def _update_module_environment(statement: ast.stmt, imports: dict[str, str], shadowed: set[str]) -> None:
    match statement:
        case ast.Import(names=names):
            for item in names:
                local_name = item.asname or item.name.partition(".")[0]
                imports[local_name] = item.name if item.asname else local_name
                shadowed.discard(local_name)
        case ast.ImportFrom(module=str() as module, names=names, level=0):
            for item in names:
                local_name = item.asname or item.name
                imports[local_name] = f"{module}.{item.name}"
                shadowed.discard(local_name)
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            imports.pop(statement.name, None)
            shadowed.add(statement.name)
        case ast.Assign(targets=targets):
            for target in targets:
                if isinstance(target, ast.Name):
                    imports.pop(target.id, None)
                    shadowed.add(target.id)
        case ast.AnnAssign(target=ast.Name(id=name)):
            imports.pop(name, None)
            shadowed.add(name)
        case _:
            return


def _receiver_parameter_bindings(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
    nested: dict[str, bool],
    imports: dict[str, str],
    constructors: frozenset[str],
) -> None:
    for argument in (*statement.args.posonlyargs, *statement.args.args, *statement.args.kwonlyargs):
        nested[argument.arg] = (
            argument.annotation is not None and _resolve_imported_name(argument.annotation, imports) in constructors
        )
    if statement.args.vararg is not None:
        nested[statement.args.vararg.arg] = False
    if statement.args.kwarg is not None:
        nested[statement.args.kwarg.arg] = False


def _collect_inspect_modules(names: list[ast.alias], shadowed: frozenset[str], inspect_names: set[str]) -> None:
    for item in names:
        if item.name == "inspect" and (item.asname or item.name) not in shadowed:
            inspect_names.add(item.asname or item.name)


def _bind_receiver_targets(targets: Sequence[ast.expr], bindings: dict[str, bool], *, is_receiver: bool) -> None:
    for target in targets:
        if isinstance(target, ast.Name):
            bindings[target.id] = is_receiver


type _MetadataOwner = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


class _MetadataOwners(NamedTuple):
    keys: dict[int, str]
    aliases: dict[str, str]
    short_names: dict[str, tuple[str, ...]]
    bindings: _MetadataBindings
    declarations: dict[str, tuple[_MetadataOwner, ...]]


class _MetadataProject(NamedTuple):
    tree: ast.Module
    bindings: _MetadataBindings
    indexes: ProjectIndexSet | None
    unit: SourceUnit | None
    facts: dict[ast.Module, _MetadataBindings]
    factories: dict[ast.AST, bool]


class _MetadataBindings(NamedTuple):
    imports: ImportIndex
    parents: Mapping[ast.AST, ast.AST]
    scope_names: dict[ast.AST, frozenset[str]]
    class_names: dict[ast.AST, frozenset[str]]
    counts: dict[str, int]
    opaque_modules: frozenset[str]


def _metadata_context_bindings(context: PythonFileContext, tree: ast.Module) -> _MetadataBindings:
    indexes = context.session.project
    local_modules = frozenset(
        name for name in _METADATA_MODULES if indexes is not None and indexes.source_unit(name) is not None
    )
    return _metadata_bindings(tree, node_index=context.node_index, local_modules=local_modules)


def _metadata_bindings(
    tree: ast.Module, *, node_index: NodeIndex | None = None, local_modules: frozenset[str] = frozenset()
) -> _MetadataBindings:
    imports = ImportIndex.from_tree(tree, module_scope_only=True)
    parents = parent_map(tree, index=node_index)
    counts: dict[str, int] = {}
    for statement in tree.body:
        for name in _metadata_bound_names((statement,)):
            counts[name] = counts.get(name, 0) + 1
    for node in walk_ast(tree, index=node_index):
        if isinstance(node, ast.Global):
            for name in node.names:
                counts[name] = counts.get(name, 0) + 1
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and (name := _metadata_dotted_name(node)) is not None
        ):
            counts[name] = counts.get(name, 0) + 1
    return _MetadataBindings(
        imports,
        parents,
        {},
        {},
        counts,
        local_modules | _metadata_namespace_exposed(tree, imports, parents, node_index=node_index),
    )


def _metadata_root(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _metadata_namespace_exposed(
    tree: ast.Module,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
    *,
    node_index: NodeIndex | None,
) -> frozenset[str]:
    opaque: set[str] = set()
    scope = _MetadataBindings(imports, parents, {}, {}, {}, frozenset())
    for node in walk_ast(tree, index=node_index):
        if isinstance(node, ast.Global):
            opaque.update(_metadata_global_modules(node, imports))
        root = _metadata_root(node)
        binding = imports.bindings.get(root) if root is not None else None
        if binding is None or binding.module not in _METADATA_MODULES:
            continue
        if root is None or _metadata_shadowed(node, root, scope):
            continue
        if _metadata_reference_escapes(node, parents.get(node), binding.symbol):
            opaque.add(binding.module)
    return frozenset(opaque)


def _metadata_reference_escapes(node: ast.AST, parent: ast.AST | None, symbol: str | None) -> bool:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return True
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return True
    if isinstance(node, ast.Attribute) and node.attr in _METADATA_CALLABLE_NAMES and symbol is None:
        return not _metadata_callable_reference(node, parent)
    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
        return False
    if symbol in _METADATA_NAMESPACE_MEMBERS:
        return True
    if isinstance(parent, ast.Attribute) and isinstance(parent.ctx, ast.Load):
        return parent.attr.startswith("__") and parent.attr not in _METADATA_READONLY_ATTRIBUTES
    return symbol is None or (symbol in _METADATA_CALLABLE_NAMES and not _metadata_callable_reference(node, parent))


def _metadata_callable_reference(node: ast.AST, parent: ast.AST | None) -> bool:
    if isinstance(parent, ast.Call) and parent.func is node:
        return True
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node in parent.decorator_list:
        return True
    return (
        isinstance(parent, ast.Attribute)
        and isinstance(parent.ctx, ast.Load)
        and parent.attr in _METADATA_READONLY_ATTRIBUTES
    )


type _MetadataComprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
type _MetadataScope = (
    ast.Module
    | ast.FunctionDef
    | ast.AsyncFunctionDef
    | ast.ClassDef
    | ast.TypeAlias
    | ast.Lambda
    | _MetadataComprehension
)


class _MetadataFrame(NamedTuple):
    scope: _MetadataScope
    names: frozenset[str]
    declarations: bool
    completed_class: bool = False


def _metadata_shadowed(node: ast.AST, name: str, bindings: _MetadataBindings) -> bool:
    return any(
        name in frame.names
        for frame in _metadata_scope_frames(node, name, bindings)
        if not isinstance(frame.scope, ast.Module)
    )


def _metadata_scope_frames(node: ast.AST, name: str, bindings: _MetadataBindings) -> Iterable[_MetadataFrame]:
    class_namespace = True
    deferred_class = False
    globals_only = False
    for reference in _metadata_enclosing_scopes(node, bindings):
        parent = reference.scope
        child = reference.child
        deferred_class |= reference.variable_annotation
        if reference.variable_annotation and isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            yield _MetadataFrame(parent, frozenset({name}), declarations=False)
            return
        annotation_frame = _metadata_annotation_frame(reference, bindings, class_namespace=class_namespace)
        if annotation_frame is not None:
            yield annotation_frame
        frame = (
            _MetadataFrame(parent, frozenset(), declarations=False)
            if globals_only and not isinstance(parent, ast.Module)
            else _metadata_frame(
                parent,
                child,
                node,
                bindings,
                outside_body=reference.outside_body,
                class_namespace=class_namespace,
                deferred_class=deferred_class,
            )
        )
        if frame.names:
            yield frame
        if _metadata_class_global_fallback(parent, child, name, frame.names, bindings, class_namespace=class_namespace):
            globals_only = True
        deferred_class |= _metadata_deferred_header(parent, child, outside_body=reference.outside_body)
        if _metadata_enters_nested_scope(parent, child, outside_body=reference.outside_body):
            class_namespace = False


class _MetadataScopeReference(NamedTuple):
    scope: _MetadataScope
    child: ast.AST
    outside_body: bool
    variable_annotation: bool


def _metadata_enclosing_scopes(node: ast.AST, bindings: _MetadataBindings) -> Iterable[_MetadataScopeReference]:
    enclosing_expressions: set[ast.AST] = set()
    child = node
    variable_annotation = False
    while (parent := bindings.parents.get(child)) is not None:
        if isinstance(parent, ast.AnnAssign) and child is parent.annotation:
            variable_annotation = True
        outer_scope = _metadata_expression_outer_scope(child, parent, bindings.parents)
        if outer_scope is not None:
            enclosing_expressions.add(outer_scope)
        if isinstance(
            parent,
            (
                ast.Module,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.TypeAlias,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            yield _MetadataScopeReference(parent, child, parent in enclosing_expressions, variable_annotation)
            variable_annotation = False
        child = parent


def _metadata_annotation_frame(
    reference: _MetadataScopeReference, bindings: _MetadataBindings, *, class_namespace: bool
) -> _MetadataFrame | None:
    if not class_namespace or not _metadata_deferred_header(
        reference.scope, reference.child, outside_body=reference.outside_body
    ):
        return None
    annotation_class = _metadata_annotation_class(reference.scope, bindings)
    if annotation_class is None:
        return None
    return _MetadataFrame(
        annotation_class,
        _metadata_bound_names(annotation_class.body),
        declarations=True,
        completed_class=True,
    )


def _metadata_enters_nested_scope(scope: _MetadataScope, child: ast.AST, *, outside_body: bool) -> bool:
    match scope:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return child in scope.body
        case ast.Lambda():
            return child is scope.body
        case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
            return not outside_body
        case _:
            return False


def _metadata_expression_outer_scope(
    child: ast.AST, parent: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> ast.AST | None:
    if isinstance(parent, ast.arguments) and child in _metadata_callable_defaults(parent):
        return parents.get(parent)
    if isinstance(parent, ast.comprehension) and child is parent.iter:
        scope = parents.get(parent)
        if (
            isinstance(scope, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
            and parent is scope.generators[0]
        ):
            return scope
    return None


def _metadata_deferred_header(scope: _MetadataScope, child: ast.AST, *, outside_body: bool) -> bool:
    match scope:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return not outside_body and child not in scope.body and child not in scope.decorator_list
        case ast.ClassDef():
            return child in scope.type_params
        case ast.TypeAlias():
            return True
        case _:
            return False


def _metadata_annotation_class(scope: _MetadataScope, bindings: _MetadataBindings) -> ast.ClassDef | None:
    node: ast.AST = scope
    while (parent := bindings.parents.get(node)) is not None:
        if isinstance(parent, ast.ClassDef):
            return parent
        if isinstance(
            parent,
            (
                ast.Module,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return None
        node = parent
    return None


def _metadata_frame(
    scope: _MetadataScope,
    child: ast.AST,
    reference: ast.AST,
    bindings: _MetadataBindings,
    *,
    outside_body: bool,
    class_namespace: bool,
    deferred_class: bool,
) -> _MetadataFrame:
    match scope:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            if outside_body or child in scope.decorator_list:
                return _MetadataFrame(scope, frozenset(), declarations=False)
            if child not in scope.body:
                return _MetadataFrame(scope, _metadata_type_parameter_names(scope), declarations=False)
        case ast.ClassDef():
            if child in scope.decorator_list:
                return _MetadataFrame(scope, frozenset(), declarations=False)
            if not class_namespace or child in scope.bases or child in scope.keywords or child in scope.type_params:
                return _MetadataFrame(scope, _metadata_type_parameter_names(scope), declarations=False)
            if deferred_class:
                return _MetadataFrame(
                    scope, _metadata_scope_names(scope, bindings), declarations=True, completed_class=True
                )
            names = _metadata_class_names(scope, child, bindings)
            if isinstance(reference, ast.Name) and isinstance(reference.ctx, (ast.Store, ast.Del)):
                names |= {reference.id}
            return _MetadataFrame(scope, names, declarations=True)
        case ast.TypeAlias():
            return _MetadataFrame(scope, _metadata_type_parameter_names(scope), declarations=False)
        case _:
            if outside_body:
                return _MetadataFrame(scope, frozenset(), declarations=False)
    return _MetadataFrame(
        scope,
        _metadata_scope_names(scope, bindings),
        isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)),
    )


def _metadata_class_global_fallback(
    scope: _MetadataScope,
    child: ast.AST,
    name: str,
    names: frozenset[str],
    bindings: _MetadataBindings,
    *,
    class_namespace: bool,
) -> bool:
    # A later class-local declaration makes LOAD_NAME fall back to globals,
    # rather than capture a same-named enclosing function cell.
    return (
        isinstance(scope, ast.ClassDef)
        and class_namespace
        and child in scope.body
        and name in _metadata_scope_names(scope, bindings)
        and name not in names
    )


def _metadata_class_names(scope: ast.ClassDef, statement: ast.AST, bindings: _MetadataBindings) -> frozenset[str]:
    names = bindings.class_names.get(statement)
    if names is None:
        names = (
            _metadata_bound_names(_metadata_class_prefix(scope, statement, bindings))
            | _metadata_current_bindings(statement)
            | (_metadata_type_parameter_names(scope) - _metadata_bound_names(scope.body))
        )
        bindings.class_names[statement] = names
    return names


def _metadata_class_prefix(scope: ast.ClassDef, node: ast.AST, bindings: _MetadataBindings) -> tuple[ast.stmt, ...]:
    while (parent := bindings.parents.get(node)) is not None and parent is not scope:
        node = parent
    for position, statement in enumerate(scope.body):
        if statement is node:
            return tuple(scope.body[:position])
    return ()


def _metadata_current_bindings(statement: ast.AST) -> frozenset[str]:
    # Definition headers and assignment RHS expressions execute before their
    # declaration/target is installed. Unknown assignment expressions there
    # still invalidate provenance conservatively.
    match statement:
        case ast.Assign(value=value) | ast.AnnAssign(value=value):
            return _metadata_bound_names((value,)) if value is not None else frozenset()
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return _metadata_bound_names(_metadata_binding_children(statement))
        case _:
            return _metadata_bound_names((statement,))


def _metadata_type_parameter_names(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.TypeAlias,
) -> frozenset[str]:
    if isinstance(scope, ast.Module):
        return frozenset()
    return frozenset(
        parameter.name
        for parameter in scope.type_params
        if isinstance(parameter, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple))
    )


def _metadata_scope_names(scope: _MetadataScope, bindings: _MetadataBindings) -> frozenset[str]:
    names = bindings.scope_names.get(scope)
    if names is not None:
        return names
    match scope:
        case ast.TypeAlias():
            names = _metadata_type_parameter_names(scope)
        case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
            names = frozenset(
                node.id
                for generator in scope.generators
                for node in walk_ast(generator.target)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            )
        case ast.Lambda():
            names = _metadata_bound_names((scope.body,))
        case _:
            names = _metadata_bound_names(scope.body) | _metadata_type_parameter_names(scope)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        names |= _metadata_parameter_names(scope.args)
    bindings.scope_names[scope] = names
    return names


def _metadata_parameter_names(arguments: ast.arguments) -> frozenset[str]:
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    names = {parameter.arg for parameter in parameters}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return frozenset(names)


def _metadata_bound_names(nodes: Iterable[ast.AST]) -> frozenset[str]:
    names: set[str] = set()
    pending = list(nodes)
    while pending:
        node = pending.pop()
        match node:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                names.add(name)
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                names.add(name)
            case ast.Import():
                names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
            case ast.ImportFrom():
                names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
            case _:
                pass
        pending.extend(_metadata_binding_children(node))
    return frozenset(names)


def _metadata_binding_children(node: ast.AST) -> Iterable[ast.AST]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return (*node.decorator_list, *_metadata_callable_defaults(node.args))
        case ast.Lambda():
            return _metadata_callable_defaults(node.args)
        case ast.ClassDef():
            return (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords))
        case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
            return _metadata_comprehension_expressions(node)
        case _:
            return ast.iter_child_nodes(node)


def _metadata_callable_defaults(arguments: ast.arguments) -> tuple[ast.expr, ...]:
    return (*arguments.defaults, *(value for value in arguments.kw_defaults if value is not None))


def _metadata_comprehension_expressions(node: _MetadataComprehension) -> tuple[ast.expr, ...]:
    expressions = [child for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)]
    for generator in node.generators:
        expressions.append(generator.iter)
        expressions.extend(generator.ifs)
    return tuple(expressions)


def _metadata_symbol(node: ast.expr, bindings: _MetadataBindings) -> str | None:
    root = _metadata_root(node)
    if root is None or _metadata_shadowed(node, root, bindings):
        return None
    if (
        isinstance(node, ast.Name)
        and node.id in {"classmethod", "staticmethod"}
        and bindings.imports.builtin_is_unshadowed(node.id)
    ):
        return (
            None if "builtins" in bindings.opaque_modules or bindings.counts.get(node.id, 0) else f"builtins.{node.id}"
        )
    qualified = bindings.imports.resolved_qualified_name(node)
    if qualified is None or qualified.rpartition(".")[0] in bindings.opaque_modules:
        return None
    return qualified


def _wraps_doc_argument(call: ast.Call, bindings: _MetadataBindings) -> ast.expr | None:
    if _metadata_symbol(call.func, bindings) != "functools.wraps":
        return None
    options = _metadata_call_options(call, ("wrapped", "assigned", "updated"))
    if options is None:
        return None
    updated = options.get("updated")
    if (
        updated is not None
        and _metadata_literal_fields(updated) is None
        and _metadata_symbol(updated, bindings) != "functools.WRAPPER_UPDATES"
    ):
        return None
    wrapped = options.get("wrapped")
    assigned = options.get("assigned")
    if assigned is None:
        return wrapped
    fields = _metadata_literal_fields(assigned)
    if fields is not None:
        return wrapped if "__doc__" in fields else None
    return wrapped if _metadata_symbol(assigned, bindings) == "functools.WRAPPER_ASSIGNMENTS" else None


def _metadata_literal_fields(node: ast.expr) -> frozenset[str] | None:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    names: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.add(element.value)
    return frozenset(names)


def _metadata_call_options(call: ast.Call, names: tuple[str, ...]) -> dict[str, ast.expr] | None:
    if len(call.args) > len(names) or any(isinstance(argument, ast.Starred) for argument in call.args):
        return None
    options = dict(zip(names, call.args, strict=False))
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in names or keyword.arg in options:
            return None
        options[keyword.arg] = keyword.value
    return options


def _metadata_docstring_consumers(context: PythonFileContext, bindings: _MetadataBindings) -> frozenset[int]:
    indexes = context.session.project
    unit = indexes.unit(context.path) if indexes is not None else None
    if unit is not None and unit.source != context.source:
        unit = None
    tree = context.tree
    if tree is None:
        return frozenset()
    project = _MetadataProject(tree, bindings, indexes, unit, {tree: bindings}, {})
    consumed: set[int] = set()
    for owner in walk_ast(tree, index=context.node_index):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for decorator in reversed(owner.decorator_list):
            if _metadata_transparent_decorator(decorator, bindings):
                continue
            if _metadata_standard_decorator(owner, decorator, bindings) or _metadata_source_decorator(
                owner, decorator, project
            ):
                consumed.add(id(owner))
            break
    return frozenset(consumed)


def _metadata_source_decorator(
    owner: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    decorator: ast.expr,
    project: _MetadataProject,
) -> bool:
    if isinstance(owner, ast.ClassDef) or isinstance(decorator, ast.Call):
        return False
    definition = _metadata_factory(decorator, project.tree, project.bindings, project.indexes, project.unit)
    if definition is None:
        return False
    tree, factory = definition
    if tree not in project.facts:
        project.facts[tree] = _metadata_bindings(tree, local_modules=project.bindings.opaque_modules)
    if factory not in project.factories:
        project.factories[factory] = _factory_copies_input_doc(factory, project.facts[tree])
    return project.factories[factory]


def _factory_copies_input_doc(factory: ast.FunctionDef | ast.AsyncFunctionDef, bindings: _MetadataBindings) -> bool:
    parameters = (*factory.args.posonlyargs, *factory.args.args)
    if (
        factory.decorator_list
        or len(parameters) != 1
        or factory.args.vararg
        or factory.args.kwarg
        or factory.args.kwonlyargs
    ):
        return False
    if bindings.counts.get(factory.name) != 1 or not factory.body or _metadata_factory_mutated(factory.name, bindings):
        return False
    result = factory.body[-1]
    if not isinstance(result, ast.Return) or not isinstance(result.value, ast.Name):
        return False
    wrapper = next(
        (
            node
            for node in factory.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == result.value.id
        ),
        None,
    )
    if wrapper is None or len(wrapper.decorator_list) != 1 or not isinstance(wrapper.decorator_list[0], ast.Call):
        return False
    parameter = parameters[0].arg
    counts: dict[str, int] = {}
    for statement in factory.body:
        for name in scope_bound_names([statement]):
            counts[name] = counts.get(name, 0) + 1
    if parameter in counts or counts.get(wrapper.name) != 1:
        return False
    if not _metadata_eager_factory_return(factory, result) or not _metadata_factory_input_doc_preserved(
        factory, wrapper, parameter, bindings
    ):
        return False
    wrapped = _wraps_doc_argument(wrapper.decorator_list[0], bindings)
    return isinstance(wrapped, ast.Name) and wrapped.id == parameter


def _metadata_eager_factory_return(factory: ast.FunctionDef | ast.AsyncFunctionDef, result: ast.Return) -> bool:
    if isinstance(factory, ast.AsyncFunctionDef):
        return False
    pending: list[ast.AST] = list(factory.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.Yield, ast.YieldFrom)) or (isinstance(node, ast.Return) and node is not result):
            return False
        pending.extend(ast.iter_child_nodes(node))
    return True


def _metadata_factory(
    target: ast.expr,
    tree: ast.Module,
    bindings: _MetadataBindings,
    indexes: ProjectIndexSet | None,
    unit: SourceUnit | None,
) -> tuple[ast.Module, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    root = _metadata_root(target)
    if root is None or _metadata_shadowed(target, root, bindings) or bindings.counts.get(root) != 1:
        return None
    name = _metadata_dotted_name(target)
    if name is None or _metadata_factory_mutated(name, bindings):
        return None
    if isinstance(target, ast.Name) and (local := _metadata_direct_function(tree, target.id)) is not None:
        return tree, local
    if indexes is None or unit is None or root not in unit.imports or root not in _metadata_direct_imports(tree):
        return None
    symbol = indexes.resolve(unit, target)
    source = indexes.source_unit(symbol.module) if symbol is not None else None
    if source is None or source.tree is None or symbol is None:
        return None
    definition = _metadata_direct_function(source.tree, symbol.name)
    return (source.tree, definition) if definition is not None else None


def _metadata_direct_imports(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            names.update(alias.asname or alias.name.partition(".")[0] for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in statement.names)
    return frozenset(names)


def _metadata_direct_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _metadata_transparent_decorator(decorator: ast.expr, bindings: _MetadataBindings) -> bool:
    return (
        not isinstance(decorator, ast.Call) and _metadata_symbol(decorator, bindings) in _TRANSPARENT_METADATA_MODIFIERS
    )


def _metadata_copy_owner(node: ast.expr, owners: _MetadataOwners) -> _MetadataOwner | None:
    declaration = _metadata_owner_reference(node, owners)
    if declaration is None or not _metadata_input_reaches_consumer(declaration, owners.bindings):
        return None
    return declaration


def _metadata_input_reaches_consumer(
    owner: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, bindings: _MetadataBindings
) -> bool:
    for decorator in reversed(owner.decorator_list):
        if _metadata_transparent_decorator(decorator, bindings):
            continue
        return _metadata_standard_decorator(owner, decorator, bindings)
    return True


def _metadata_dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join((node.id, *reversed(parts))) if isinstance(node, ast.Name) else None


def _metadata_owner_reference(
    node: ast.expr,
    owners: _MetadataOwners,
    *,
    skipped_scope: ast.AST | None = None,
) -> _MetadataOwner | None:
    bindings = owners.bindings
    name = _metadata_dotted_name(node)
    if name is None:
        return None
    root, separator, tail = name.partition(".")
    parts = name.split(".")
    if any(bindings.counts.get(".".join(parts[:size]), 0) for size in range(2, len(parts) + 1)):
        return None
    for frame in _metadata_scope_frames(node, root, bindings):
        if frame.scope is skipped_scope or root not in frame.names:
            continue
        if frame.declarations:
            return _metadata_bound_owner(node, root, tail if separator else "", frame, owners)
        return None
    return None


def _metadata_bound_owner(
    node: ast.expr,
    root: str,
    tail: str,
    frame: _MetadataFrame,
    owners: _MetadataOwners,
) -> _MetadataOwner | None:
    bindings = owners.bindings
    scope = frame.scope
    if isinstance(scope, ast.ClassDef):
        if frame.completed_class:
            declaration = _metadata_last_declaration(scope.body, root)
            return _metadata_declaration_tail(declaration, tail, owners) if declaration is not None else None
        return _metadata_class_bound_owner(node, root, tail, scope, owners)
    if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    counts = (
        bindings.counts.get(root, 0)
        if isinstance(scope, ast.Module)
        else sum(root in _metadata_bound_names((statement,)) for statement in scope.body)
    )
    definitions = [
        statement
        for statement in scope.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and statement.name == root
    ]
    if counts == 1 and len(definitions) == 1:
        return _metadata_declaration_tail(definitions[0], tail, owners)
    if isinstance(scope, ast.Module) and counts == 1 and root in owners.aliases:
        return _metadata_resolved_alias_owner(node, scope, owners)
    return None


def _metadata_resolved_alias_owner(node: ast.expr, scope: ast.Module, owners: _MetadataOwners) -> _MetadataOwner | None:
    capture = _metadata_alias_capture(node, scope, owners)
    if capture is None:
        return None
    resolved, position = capture
    first, _, tail = resolved.partition(".")
    if owners.bindings.counts.get(first) != 1:
        return None
    matches = owners.declarations.get(first, ())
    if len(matches) != 1 or not _metadata_capture_path_preserved(resolved, position, scope, owners.bindings):
        return None
    if position is not None and matches[0] not in scope.body[:position]:
        return None
    return _metadata_declaration_tail(matches[0], tail, owners)


def _metadata_alias_capture(
    node: ast.expr, scope: ast.Module, owners: _MetadataOwners
) -> tuple[str, int | None] | None:
    name = _metadata_dotted_name(node)
    before = len(scope.body)
    captured: int | None = None
    while name is not None and (root := name.partition(".")[0]) in owners.aliases:
        if owners.bindings.counts.get(root) != 1:
            return None
        assignment = _metadata_alias_assignment(scope, root)
        if assignment is None:
            return None
        position, value = assignment
        if position >= before:
            return None
        _, separator, tail = name.partition(".")
        if not separator:
            captured = position
        value_name = _metadata_dotted_name(value)
        name = f"{value_name}.{tail}" if value_name is not None and separator else value_name
        before = position
    return (name, captured) if name is not None else None


def _metadata_alias_assignment(scope: ast.Module, name: str) -> tuple[int, ast.expr] | None:
    for position, statement in enumerate(scope.body):
        match statement:
            case ast.Assign(targets=targets, value=value):
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                if len(names) == len(targets) and name in names:
                    return position, value
            case ast.AnnAssign(target=ast.Name(id=target), value=ast.expr() as value) if target == name:
                return position, value
            case _:
                pass
    return None


def _metadata_capture_path_preserved(
    name: str, capture: int | None, scope: ast.Module, bindings: _MetadataBindings
) -> bool:
    parts = name.split(".")
    changed = {prefix for size in range(2, len(parts) + 1) if bindings.counts.get(prefix := ".".join(parts[:size]), 0)}
    if not changed:
        return True
    if capture is None:
        return False
    for node, parent in bindings.parents.items():
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, (ast.Store, ast.Del)):
            continue
        if _metadata_dotted_name(node) not in changed:
            continue
        if not _metadata_direct_later_mutation(node, parent, scope, capture):
            return False
    return True


def _metadata_direct_later_mutation(node: ast.Attribute, parent: ast.AST, scope: ast.Module, capture: int) -> bool:
    match parent:
        case ast.Assign(targets=[target]) | ast.AnnAssign(target=target) | ast.AugAssign(target=target):
            direct = target is node
        case ast.Delete(targets=[target]):
            direct = target is node
        case _:
            return False
    return direct and parent in scope.body[capture + 1 :]


def _metadata_class_bound_owner(
    node: ast.expr, root: str, tail: str, scope: ast.ClassDef, owners: _MetadataOwners
) -> _MetadataOwner | None:
    statement: ast.AST = node
    while (parent := owners.bindings.parents.get(statement)) is not None and parent is not scope:
        statement = parent
    if root in _metadata_current_bindings(statement):
        return None
    declaration = _metadata_last_declaration(_metadata_class_prefix(scope, statement, owners.bindings), root)
    return _metadata_declaration_tail(declaration, tail, owners) if declaration is not None else None


def _metadata_declaration_tail(
    declaration: _MetadataOwner, tail: str, owners: _MetadataOwners
) -> _MetadataOwner | None:
    for name in tail.split(".") if tail else ():
        if not isinstance(declaration, ast.ClassDef) or not _metadata_input_reaches_consumer(
            declaration, owners.bindings
        ):
            return None
        member = _metadata_last_declaration(declaration.body, name)
        if member is None:
            return None
        declaration = member
    return declaration


def _metadata_last_declaration(statements: Sequence[ast.stmt], name: str) -> _MetadataOwner | None:
    last: ast.stmt | None = None
    for statement in statements:
        if name in _metadata_bound_names((statement,)):
            last = statement
    return (
        last if isinstance(last, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and last.name == name else None
    )


def _metadata_declaration_occurrences(
    tree: ast.Module, owner_keys: dict[int, str], *, node_index: NodeIndex | None
) -> dict[str, tuple[_MetadataOwner, ...]]:
    declarations: dict[str, tuple[_MetadataOwner, ...]] = {}
    for node in walk_ast(tree, index=node_index):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            key = owner_keys[id(node)]
            declarations[key] = (*declarations.get(key, ()), node)
    return declarations


def _metadata_standard_decorator(
    owner: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    decorator: ast.expr,
    bindings: _MetadataBindings,
) -> bool:
    if isinstance(owner, ast.ClassDef):
        return _dataclass_reads_doc(decorator, bindings)
    if isinstance(decorator, ast.Call):
        return _lru_cache_copies_doc(decorator, bindings)
    return _metadata_symbol(decorator, bindings) in _BARE_METADATA_DECORATORS


def _dataclass_reads_doc(decorator: ast.expr, bindings: _MetadataBindings) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if _metadata_symbol(target, bindings) != "dataclasses.dataclass":
        return False
    if not isinstance(decorator, ast.Call):
        return True
    if decorator.args:
        return False
    options = _metadata_call_options(decorator, _DATACLASS_OPTIONS)
    return options is not None and all(
        isinstance(value, ast.Constant) and isinstance(value.value, bool) for value in options.values()
    )


def _lru_cache_copies_doc(decorator: ast.expr, bindings: _MetadataBindings) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if _metadata_symbol(target, bindings) != "functools.lru_cache":
        return False
    if not isinstance(decorator, ast.Call):
        return True
    options = _metadata_call_options(decorator, ("maxsize", "typed"))
    if options is None or not _metadata_cache_size(options.get("maxsize")):
        return False
    typed = options.get("typed")
    return typed is None or (isinstance(typed, ast.Constant) and isinstance(typed.value, bool))


def _metadata_cache_size(value: ast.expr | None) -> bool:
    if value is None:
        return True
    if isinstance(value, ast.Constant):
        return value.value is None or isinstance(value.value, int)
    return (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, (ast.UAdd, ast.USub))
        and isinstance(value.operand, ast.Constant)
        and isinstance(value.operand.value, int)
    )


def _metadata_explicit_owner(call: ast.Call, owners: _MetadataOwners) -> _MetadataOwner | None:
    argument = _metadata_explicit_argument(call, owners.bindings)
    if argument is None:
        return None
    declaration = _metadata_copy_owner(argument, owners)
    if _metadata_symbol(call.func, owners.bindings) == "dataclasses.dataclass" and not isinstance(
        declaration, ast.ClassDef
    ):
        return None
    return declaration


def _metadata_explicit_argument(call: ast.Call, bindings: _MetadataBindings) -> ast.expr | None:
    match _metadata_symbol(call.func, bindings):
        case "builtins.classmethod" | "builtins.staticmethod":
            return (
                call.args[0]
                if len(call.args) == 1 and not call.keywords and not isinstance(call.args[0], ast.Starred)
                else None
            )
        case "functools.cache":
            options = _metadata_call_options(call, ("user_function",))
            return options.get("user_function") if options is not None else None
        case "functools.lru_cache":
            options = _metadata_call_options(call, ("maxsize", "typed"))
            if options is None:
                return None
            typed = options.get("typed")
            return (
                options.get("maxsize")
                if typed is None or (isinstance(typed, ast.Constant) and isinstance(typed.value, bool))
                else None
            )
        case "dataclasses.dataclass":
            return _metadata_dataclass_input(call)
        case _:
            return None


def _metadata_factory_mutated(name: str, bindings: _MetadataBindings) -> bool:
    parts = name.split(".")
    return any(bindings.counts.get(".".join(parts[:size]), 0) for size in range(2, len(parts) + 1)) or any(
        target.startswith(f"{name}.") for target in bindings.counts
    )


def _metadata_global_modules(node: ast.Global, imports: ImportIndex) -> frozenset[str]:
    return frozenset(
        imports.bindings[name].module
        for name in node.names
        if name in imports.bindings and imports.bindings[name].module in _METADATA_MODULES
    )


def _metadata_dataclass_input(call: ast.Call) -> ast.expr | None:
    if len(call.args) != 1:
        return None
    options = _metadata_call_options(call, ("cls", *_DATACLASS_OPTIONS))
    if options is not None and all(
        name == "cls" or (isinstance(value, ast.Constant) and isinstance(value.value, bool))
        for name, value in options.items()
    ):
        return call.args[0]
    return None


def _metadata_factory_input_doc_preserved(
    factory: ast.FunctionDef | ast.AsyncFunctionDef,
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    bindings: _MetadataBindings,
) -> bool:
    evaluated = list(_metadata_evaluated_header(wrapper))
    for statement in factory.body:
        if statement is wrapper:
            break
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return False
        evaluated.append(statement)
    return all(_metadata_parameter_doc_preserved(node, parameter, bindings) for node in evaluated)


def _metadata_parameter_doc_preserved(scope: ast.AST, parameter: str, bindings: _MetadataBindings) -> bool:
    for node in walk_ast(scope):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == parameter
            and not _metadata_readonly_owner_reference(node, bindings.parents.get(node))
        ):
            return False
    return True


def _metadata_readonly_owner_reference(node: ast.expr, parent: ast.AST | None) -> bool:
    if (
        not isinstance(parent, ast.Attribute)
        or parent.value is not node
        or parent.attr not in _METADATA_READONLY_ATTRIBUTES
    ):
        return False
    return parent.attr != "__doc__" or isinstance(parent.ctx, ast.Load)


def _metadata_wraps_header_preserved(
    wrapper: ast.FunctionDef | ast.AsyncFunctionDef,
    key: _MetadataOwner,
    owners: _MetadataOwners,
) -> bool:
    for header in _metadata_evaluated_header(wrapper):
        for node in walk_ast(header):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            if _metadata_owner_reference(node, owners, skipped_scope=wrapper) is not key:
                continue
            if not _metadata_readonly_owner_reference(node, owners.bindings.parents.get(node)):
                return False
    return True


def _metadata_evaluated_header(owner: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.AST, ...]:
    evaluated: list[ast.AST] = [owner.args, *owner.type_params]
    if owner.returns is not None:
        evaluated.append(owner.returns)
    return tuple(evaluated)
