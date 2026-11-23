from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    DiagnosticSeverity,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_names import terminal_name as _leaf_name
from sarj_python_lint.rules._inherited_contract import inherited_contract


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
    from sarj_python_lint.rules._imports import ImportIndex


_MIN_FIELDS = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})
_TUPLE_SOURCES = frozenset({"builtins"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_BUILTIN_CONTAINERS = frozenset({"dict", "frozenset", "list", "set", "tuple", "type"})
_CONTAINER_SOURCES = frozenset({"collections", "collections.abc", "types", "typing", "typing_extensions"})
_CONTAINER_SYMBOLS = frozenset(
    {
        "AbstractSet",
        "Annotated",
        "AsyncGenerator",
        "AsyncIterable",
        "AsyncIterator",
        "Awaitable",
        "Callable",
        "ChainMap",
        "ClassVar",
        "Collection",
        "Container",
        "Coroutine",
        "Counter",
        "DefaultDict",
        "Deque",
        "Dict",
        "Final",
        "FrozenSet",
        "Generator",
        "ItemsView",
        "Iterable",
        "Iterator",
        "KeysView",
        "List",
        "Mapping",
        "MappingProxyType",
        "MutableMapping",
        "MutableSequence",
        "MutableSet",
        "NotRequired",
        "Optional",
        "OrderedDict",
        "ReadOnly",
        "Required",
        "Reversible",
        "Sequence",
        "Set",
        "Type",
        "Union",
        "ValuesView",
        "defaultdict",
        "deque",
    }
)

_MSG = (
    "function returns a fixed positional tuple record — return a dataclass or validation model; "
    "use typing.NamedTuple only when tuple protocol compatibility is required."
)


@final
class PreferNamedtupleOverTupleReturn(Rule):
    id: str = "no-positional-tuple-record"
    code: str = "SARJ026"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Fixed tuple return records should use named fields instead of positional slots.",
        rationale=(
            "A fixed tuple return makes callers remember positions and lets adjacent values be silently swapped. "
            "Named records preserve field meaning across public, private, decorated, method, and test boundaries."
        ),
        remediation=(
            "Return a frozen dataclass or validation model. Use `typing.NamedTuple` only when an exact tuple protocol is required."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("prefer-namedtuple-over-tuple-return",),
        limitations=(
            "Generated files and documentation examples are excluded.",
            "Provenance-resolved builtin or typing fixed tuple return annotations with at least two slots are reported, including stable local aliases, quoted annotations, Annotated wrappers and optional unions in test helpers and fixtures; variadic tuples remain valid collections.",
            "Existing direct tuple records remain errors; newly resolved typing_extensions providers, local aliases, application types named Unpack and optional-union records start as warnings for adoption review.",
            "Public methods on classes with explicit bases, dunder methods and `@override` methods are excluded as inherited contracts. Private helpers on subclasses remain eligible unless a base class in the same module declares the same name.",
            "Fixed tuples nested in proven container, union, Callable and local-alias type arguments of parameters, returns and annotated variables or fields are warnings. Arguments of other generics (for example array shape parameters) and returns of functions passed as `key=` callables are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="positional-public-return",
                title="Public function returns a positional record",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "def load_profile() -> tuple[str, int, bool]:\n    return 'Ada', 42, True\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-public-return",
                title="Public function returns a tuple-compatible named record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "from typing import NamedTuple\n\n"
                        "class Profile(NamedTuple):\n"
                        "    name: str\n"
                        "    age: int\n"
                        "    active: bool\n\n"
                        "def load_profile() -> Profile:\n"
                        "    return Profile(name='Ada', age=42, active=True)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        tree = context.tree
        if context.generated or _is_documentation_path(path) or tree is None or context.has_wildcard_import:
            return []
        semantics = context.annotation_semantics
        sort_keys = _sort_key_functions(tree)
        findings = [
            *(
                finding
                for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
                for finding in _function_findings(node, context.parents.get(node), tree, semantics, sort_keys)
            ),
            *(
                finding
                for node in context.nodes(ast.AnnAssign)
                for finding in _nested_findings(node.annotation, semantics)
            ),
        ]
        return sorted(
            (
                Diagnostic(
                    path=path,
                    line=finding.node.lineno,
                    col=finding.node.col_offset + 1,
                    code=self.code,
                    message=finding.message,
                    severity=finding.severity,
                )
                for finding in findings
                if not context.suppressions.is_suppressed(finding.node.lineno, self.code)
            ),
            key=lambda item: (item.line, item.col),
        )


@dataclass(frozen=True, slots=True)
class _Finding:
    node: ast.stmt | ast.expr
    message: str
    severity: DiagnosticSeverity


def _function_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.AST | None,
    tree: ast.Module,
    semantics: AnnotationSemantics,
    sort_keys: frozenset[str],
) -> Iterator[_Finding]:
    imports = semantics.imports
    private_method = isinstance(owner, ast.ClassDef) and bool(owner.bases) and _private_helper(node, owner, tree)
    if _is_dunder(node.name) or (inherited_contract(owner) and not private_method) or _declares_override(node, imports):
        return
    arguments = node.args
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg):
        if argument is not None:
            yield from _nested_findings(argument.annotation, semantics)
    if node.returns is None or node.name in sort_keys:
        return
    if not any(_is_public_record_tuple(member, imports) for member in semantics.transparent_members(node.returns)):
        yield from _nested_findings(node.returns, semantics)
        return
    legacy = not private_method and _is_public_record_tuple(node.returns, imports, legacy=True)
    yield _Finding(node, _MSG, Severity.ERROR if legacy else Severity.WARNING)


def _nested_findings(annotation: ast.expr | None, semantics: AnnotationSemantics) -> Iterator[_Finding]:
    if annotation is not None and (record := _nested_record(annotation, semantics)) is not None:
        yield _Finding(annotation, _nested_message(record), Severity.WARNING)


def _private_helper(node: ast.FunctionDef | ast.AsyncFunctionDef, owner: ast.ClassDef, tree: ast.Module) -> bool:
    if not node.name.startswith("_") or _is_dunder(node.name):
        return False
    bases = {base.id for base in owner.bases if isinstance(base, ast.Name)}
    return not any(
        isinstance(statement, ast.ClassDef)
        and statement.name in bases
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == node.name
            for member in statement.body
        )
        for statement in tree.body
    )


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _nested_record(annotation: ast.expr, semantics: AnnotationSemantics) -> ast.Subscript | None:
    pending: list[tuple[ast.expr, frozenset[str]]] = [(annotation, frozenset())]
    while pending:
        node, seen = pending.pop()
        parsed = semantics.parse(node)
        if isinstance(parsed, ast.Name) and parsed.id in semantics.aliases:
            if parsed.id not in seen:
                pending.append((semantics.aliases[parsed.id], seen | {parsed.id}))
        elif isinstance(parsed, ast.Subscript) and _is_public_record_tuple(parsed, semantics.imports):
            return parsed
        elif parsed is not None:
            pending.extend((child, seen) for child in reversed(_type_arguments(parsed, semantics.imports)))
    return None


def _type_arguments(node: ast.expr, imports: ImportIndex) -> list[ast.expr]:
    match node:
        case ast.Subscript(value=target) if not _is_container(target, imports):
            return []
        case ast.Subscript(slice=ast.Tuple(elts=elements) | ast.List(elts=elements)):
            return elements
        case ast.Subscript(slice=element):
            return [element]
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return [left, right]
        case ast.List(elts=elements) | ast.Tuple(elts=elements):
            return elements
        case _:
            return []


def _is_container(target: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(target, ast.Name) and target.id in _BUILTIN_CONTAINERS and imports.builtin_is_unshadowed(target.id):
        return True
    return imports.resolved_symbol(target, sources=_CONTAINER_SOURCES) in _CONTAINER_SYMBOLS


def _declares_override(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    return any(
        imports.resolves(decorator, sources=_TYPING_SOURCES, symbol="override") for decorator in node.decorator_list
    )


def _sort_key_functions(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        keyword.value.id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "key" and isinstance(keyword.value, ast.Name)
    )


def _nested_message(record: ast.Subscript) -> str:
    return (
        f"`{ast.unparse(record)}` is a positional record — name its fields with a frozen dataclass or validation "
        "model, or use `tuple[T, ...]` for a homogeneous sequence (typing.NamedTuple only when tuple protocol "
        "compatibility is required)."
    )


def _is_documentation_path(path: Path) -> bool:
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


def _is_public_record_tuple(annotation: ast.expr, imports: ImportIndex, *, legacy: bool = False) -> bool:
    typing_sources = frozenset({"typing"}) if legacy else _TYPING_SOURCES
    annotation = _unwrap_return_annotation(annotation, imports, typing_sources)
    if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.slice, ast.Tuple):
        return False
    target = annotation.value
    is_tuple = (
        (isinstance(target, ast.Name) and target.id == "tuple" and imports.builtin_is_unshadowed("tuple"))
        or imports.resolves(target, sources=_TUPLE_SOURCES, symbol="tuple")
        or imports.resolves(target, sources=typing_sources, symbol="Tuple")
    )
    if not is_tuple:
        return False
    fields = annotation.slice.elts
    return len(fields) >= _MIN_FIELDS and not any(_is_variadic_field(field, imports, legacy=legacy) for field in fields)


def _unwrap_return_annotation(annotation: ast.expr, imports: ImportIndex, typing_sources: frozenset[str]) -> ast.expr:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = parse_or_none(Path("annotation.py"), f"value: {annotation.value}")
        if parsed is not None and isinstance(parsed.body[0], ast.AnnAssign):
            return parsed.body[0].annotation
    if (
        isinstance(annotation, ast.Subscript)
        and imports.resolves(annotation.value, sources=typing_sources, symbol="Annotated")
        and isinstance(annotation.slice, ast.Tuple)
        and annotation.slice.elts
    ):
        return _unwrap_return_annotation(annotation.slice.elts[0], imports, typing_sources)
    return annotation


def _is_variadic_field(node: ast.expr, imports: ImportIndex, *, legacy: bool) -> bool:
    return (
        isinstance(node, ast.Starred)
        or (
            isinstance(node, ast.Subscript)
            and (
                imports.resolves(node.value, sources=frozenset({"typing", "typing_extensions"}), symbol="Unpack")
                or (legacy and _leaf_name(node.value) == "Unpack")
            )
        )
        or (isinstance(node, ast.Constant) and node.value is Ellipsis)
    )
