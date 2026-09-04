from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PARAMETRIZE = "parametrize"

_PARAM = "param"


class _UnnameableTable(NamedTuple):
    decorator: ast.Call
    case_count: int


# Node kinds pytest cannot render into a readable test id.
_OPAQUE_NODES = (ast.Dict, ast.Set, ast.DictComp, ast.SetComp, ast.ListComp, ast.GeneratorExp)

# Constructors whose result pytest's `_idval` always renders: the scalar types
# it stringifies, plus `type` and `re.compile`, whose results carry a `__name__`
# / a `.pattern` that pytest reads instead.
_NAMEABLE_CONSTRUCTORS = frozenset({"str", "bytes", "int", "float", "bool", "complex", "type"})
_STRING_TRANSFORMS = frozenset({"encode", "format"})
_PYTEST_MARK_SOURCES = frozenset({"pytest.mark"})
_PYTEST_SOURCES = frozenset({"pytest"})
_RE_SOURCES = frozenset({"re"})
_TEXTWRAP_SOURCES = frozenset({"textwrap"})

_VALUES_ARG_INDEX = 1

_DECORATED_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class OpaqueParametrizeCaseNeedsId(Rule):
    id: str = "opaque-parametrize-case-needs-id"
    code: str = "SARJ042"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Opaque static pytest parameter cases rely on argument-name-and-index fallback IDs.",
        rationale="Fallback IDs such as `payload0` are hard to diagnose and silently change when the table is reordered.",
        remediation=(
            "Give each opaque row a semantic `pytest.param(..., id=...)`, or use a semantic callable `ids=` when one "
            "mapping applies to the entire table."
        ),
        category=RuleCategory.TESTING,
        aliases=("parametrize-case-needs-id",),
        limitations=(
            "Only import-proven pytest parametrization over static list or tuple tables in maintained test files is analyzed.",
            "Cases with a pytest-readable scalar column or a statically non-None explicit ID are allowed.",
            "Dynamic and callable IDs and repository-level pytest_make_parametrize_id hooks are not evaluated.",
        ),
        examples=(
            RuleExample(
                example_id="opaque-cases-without-ids",
                title="Dictionary cases receive generated names",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_handler.py",
                        'import pytest\n\n@pytest.mark.parametrize("payload", [{}, {"status": "invalid"}])\ndef test_handler(payload):\n    assert handle(payload)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_handler.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="opaque-cases-with-ids",
                title="Dictionary cases have stable names",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_handler.py",
                        'import pytest\n\n@pytest.mark.parametrize(\n    "payload",\n    [\n        pytest.param({}, id="empty-payload"),\n        pytest.param({"status": "invalid"}, id="invalid-status"),\n    ],\n)\ndef test_handler(payload):\n    assert handle(payload)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_handler.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        imports = _module_import_index(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_message(count),
                severity=Severity.WARNING,
            )
            for node, count in _tables_with_unnameable_cases(tree, imports)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _message(count: int) -> str:
    subject = "case relies" if count == 1 else "cases rely"
    return (
        f"{count} {subject} on pytest's argument-name-and-index fallback (for example, `payload0`), which renumbers "
        'when rows are reordered. Add semantic `pytest.param(..., id="...")` values or a semantic callable `ids=`.'
    )


def _tables_with_unnameable_cases(tree: ast.Module, imports: ImportIndex) -> list[_UnnameableTable]:
    # One diagnostic per table, not per case: a single `ids=` on the decorator
    # resolves every case at once, so per-case reporting would be N copies of
    # one fix and would bury a large table's other diagnostics.
    hits: list[_UnnameableTable] = []
    for node in _decorator_calls(tree):
        if not _is_parametrize(node.func, imports):
            continue
        argnames = _argument(node, 0, "argnames")
        values = _argument(node, _VALUES_ARG_INDEX, "argvalues")
        if argnames is None or values is None:
            continue
        if not isinstance(values, (ast.List, ast.Tuple)):
            continue
        width = _parametrize_width(argnames)
        if width is None:
            continue
        explicit_ids = _explicit_decorator_ids(node, len(values.elts))
        if explicit_ids is None:
            continue
        count = sum(
            1
            for case, has_explicit_id in zip(values.elts, explicit_ids, strict=True)
            if not has_explicit_id and _is_unnameable(case, width, imports)
        )
        if count:
            hits.append(_UnnameableTable(node, count))
    return hits


def _decorator_calls(tree: ast.Module) -> list[ast.Call]:
    return [dec for node in nodes(tree, *_DECORATED_NODES) for dec in node.decorator_list if isinstance(dec, ast.Call)]


def _is_parametrize(func: ast.expr, imports: ImportIndex) -> bool:
    return imports.resolves(func, sources=_PYTEST_MARK_SOURCES, symbol=_PARAMETRIZE)


def _argument(node: ast.Call, position: int, name: str) -> ast.expr | None:
    if len(node.args) > position:
        return None if _has_keyword(node, name) else node.args[position]
    return next((keyword.value for keyword in node.keywords if keyword.arg == name), None)


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in node.keywords)


def _explicit_decorator_ids(node: ast.Call, case_count: int) -> tuple[bool, ...] | None:
    ids = _argument(node, 3, "ids")
    if ids is None or _is_none(ids):
        return (False,) * case_count
    if not isinstance(ids, (ast.List, ast.Tuple)) or len(ids.elts) != case_count:
        return None
    return tuple(not _is_none(item) for item in ids.elts)


def _parametrize_width(argnames: ast.expr) -> int | None:
    if isinstance(argnames, ast.Constant) and isinstance(argnames.value, str):
        names = [stripped_name for name in argnames.value.split(",") if (stripped_name := name.strip())]
        return len(names) or None
    if isinstance(argnames, (ast.List, ast.Tuple)):
        if not argnames.elts or not all(
            isinstance(elt, ast.Constant) and isinstance(elt.value, str) for elt in argnames.elts
        ):
            return None
        return len(argnames.elts)
    return None


def _is_unnameable(case: ast.expr, width: int, imports: ImportIndex) -> bool:
    if isinstance(case, ast.Call) and _is_param_wrapper(case.func, imports):
        # An explicitly named case is fine however opaque its payload is.
        case_id = next((keyword.value for keyword in case.keywords if keyword.arg == "id"), None)
        if case_id is not None and not _is_none(case_id):
            return False
        if not case.args:
            return False
        if width == 1:
            return len(case.args) == 1 and _is_opaque_value(case.args[0], single_value=True, imports=imports)
        return all(_is_opaque_value(arg, single_value=True, imports=imports) for arg in case.args)
    if width == 1:
        return _is_opaque_value(case, single_value=True, imports=imports)
    if not isinstance(case, (ast.Tuple, ast.List)):
        return False
    return bool(case.elts) and all(_is_opaque_value(elt, single_value=True, imports=imports) for elt in case.elts)


def _is_param_wrapper(func: ast.expr, imports: ImportIndex) -> bool:
    return imports.resolves(func, sources=_PYTEST_SOURCES, symbol=_PARAM)


def _is_opaque_value(value: ast.expr, *, single_value: bool, imports: ImportIndex) -> bool:
    # A multi-column case is a tuple. pytest joins the per-column ids with `-`,
    # so one nameable column is enough to tell the case apart — only an
    # all-opaque case falls back to argument-name-and-index components.
    if single_value and isinstance(value, (ast.Tuple, ast.List)):
        return True
    if isinstance(value, ast.Constant) and value.value is Ellipsis:
        return True
    if isinstance(value, ast.Call):
        return not _is_nameable_call(value, imports)
    return isinstance(value, _OPAQUE_NODES)


def _is_nameable_call(call: ast.Call, imports: ImportIndex) -> bool:
    # `float('nan')` -> `nan`, `type(None)` -> `NoneType`: pytest renders the
    # value these produce, so the case names itself after all.
    if isinstance(call.func, ast.Name) and call.func.id in _NAMEABLE_CONSTRUCTORS:
        return imports.builtin_is_unshadowed(call.func.id)
    if imports.resolves(call.func, sources=_RE_SOURCES, symbol="compile"):
        return True
    if imports.resolves(call.func, sources=_TEXTWRAP_SOURCES, symbol="dedent"):
        return True
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in _STRING_TRANSFORMS
        and _is_static_string_value(call.func.value, imports)
    )


def _is_static_string_value(node: ast.expr, imports: ImportIndex) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))) or (
        isinstance(node, ast.Call) and _is_nameable_call(node, imports)
    )


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _module_import_index(tree: ast.Module) -> ImportIndex:
    body: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == "pytest":
            regular_names = [alias for alias in statement.names if alias.name != "mark"]
            if regular_names:
                body.append(ast.ImportFrom(module=statement.module, names=regular_names, level=statement.level))
            body.extend(
                ast.Import(names=[ast.alias(name="pytest.mark", asname=alias.asname or alias.name)])
                for alias in statement.names
                if alias.name == "mark"
            )
            continue
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            body.append(statement)
            continue
        body.extend(
            ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=ast.Constant(None))
            for name in _statement_bound_names(statement)
        )
    return ImportIndex.from_tree(ast.Module(body=body, type_ignores=[]))


def _statement_bound_names(statement: ast.stmt) -> frozenset[str]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return frozenset({statement.name})
    return frozenset(
        node.id
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    )
