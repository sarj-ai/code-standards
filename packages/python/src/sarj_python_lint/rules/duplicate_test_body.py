"""SARJ066 — N copy-pasted test functions in one module are one `parametrize` waiting to be written.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_duplicate_test_body.py
"""

from __future__ import annotations

import ast
import copy
import re
import tokenize
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import standalone_comments, trailing_comments
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# Collapse case literals so differing inputs do not hide duplicated test structure.
_LITERAL_PLACEHOLDER = "\x00sarj-literal"

# Statements in the shared body, docstring excluded, below which "these two
# tests look alike" carries no information.
_MIN_STATEMENTS = 3

# Members of a normalized-body group before it counts as copy-paste.
_MIN_GROUP = 2

# Pytest cannot parametrize unittest-style classes, including project-specific TestCase bases.
_UNITTEST_BASE_RE = re.compile(r"Test(Case|s)?$")

# `self.<name>` calls that only exist on a `unittest.TestCase`.
_UNITTEST_SELF_ATTRS = frozenset({"subTest", "skipTest", "addCleanup", "addTypeEqualityFunc", "fail"})

_UNITTEST_ASSERT_PREFIX = "assert"

_SELF = "self"

# Longest literal echoed back in the message before it is elided.
_LITERAL_ECHO_LIMIT = 32

# Differing literals named in the message; past this the list is summarized.
_MAX_LITERALS_SHOWN = 3

# Long multiline literals are fixture documents, not case values to normalize away.
_MAX_CASE_LITERAL = 32

_PARAMETRIZE_ADVICE = (
    "Collapse them into one `@pytest.mark.parametrize(...)`, passing `ids=` so each scenario "
    "keeps the name it has today (see SARJ042)."
)

_IDENTICAL_ADVICE = (
    "There is no case table to build here: one of the two is a copy-paste that never got its "
    "edit. Make it exercise what its name claims, or delete it."
)


class DuplicateTestBody(Rule):
    id: str = "duplicate-test-body"
    code: str = "SARJ066"
    description: str = (
        "Test function duplicates another test's body in the same module — collapse them into "
        "one `@pytest.mark.parametrize` with `ids=`."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions whose normalized body already exists in the module."""
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        try:
            groups = _duplicate_groups(tree, source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        except RecursionError:
            # Deep or generated trees may exceed recursion limits during normalization.
            return []

        diags = [
            Diagnostic(
                path=path,
                line=group[1].node.lineno,
                col=group[1].node.col_offset + 1,
                code=self.code,
                message=_message(group, path),
            )
            for group in groups
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _Outline:
    """A test function fingerprinted by everything that is cheap to read."""

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef, container: str) -> None:
        super().__init__()
        self.node: ast.FunctionDef | ast.AsyncFunctionDef = node
        body = _body_without_docstring(node)
        types: list[str] = []
        statements = 0
        for stmt in body:
            for child in _walk(stmt):
                types.append(type(child).__name__)
                statements += isinstance(child, ast.stmt)
        self.statements: int = statements
        # Container, async-ness, signature and decorators are identity, not
        # body: each of them can make two identical bodies different tests.
        self.key: tuple[str, bool, tuple[str, ...], str, str] = (
            container,
            isinstance(node, ast.AsyncFunctionDef),
            _parameter_names(node),
            _decorator_shape(node),
            ",".join(types),
        )


class _Shape:
    """One test function's body reduced to a comparable normalized form."""

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef, comments: dict[int, str]) -> None:
        super().__init__()
        self.node: ast.FunctionDef | ast.AsyncFunctionDef = node
        body = _body_without_docstring(node)
        canonical = _Canonicalizer(_bound_names(body))
        self.body: str = "".join(canonical.render(stmt) for stmt in body)
        self.literals: tuple[object, ...] = tuple(canonical.literals)
        # Prose is identity, not shape: merging two tests forces one of the two
        # explanations to be deleted, and `ids=` cannot carry a paragraph.
        self.key: tuple[str, tuple[str, ...]] = (self.body, _documentation(node, comments))


class _Canonicalizer(ast.NodeVisitor):
    """Rewrite a copied subtree so only its structure survives, then dump it."""

    def __init__(self, bound: frozenset[str]) -> None:
        super().__init__()
        self._bound: frozenset[str] = bound
        self._aliases: dict[str, str] = {}
        self.literals: list[object] = []

    def render(self, stmt: ast.stmt) -> str:
        """Normalize a copy of `stmt` and return its dumped shape."""
        clone = copy.deepcopy(stmt)
        self.visit(clone)
        return ast.dump(clone)

    def visit_Constant(self, node: ast.Constant) -> None:
        value: object = node.value
        self.literals.append(value)
        node.value = _LITERAL_PLACEHOLDER
        node.kind = None

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self._bound:
            node.id = self._alias(node.id)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None and node.name in self._bound:
            node.name = self._alias(node.name)
        self.generic_visit(node)

    def _alias(self, name: str) -> str:
        return self._aliases.setdefault(name, f"v{len(self._aliases)}")


def _duplicate_groups(tree: ast.Module, source: str) -> list[list[_Shape]]:
    """Group the module's tests by body shape, discarding the groups that are not copies."""
    outlines: dict[tuple[str, bool, tuple[str, ...], str, str], list[_Outline]] = {}
    for container, in_test_case, node in _test_functions(tree):
        if in_test_case or _uses_unittest_api(node):
            continue
        outline = _Outline(node, container)
        if outline.statements < _MIN_STATEMENTS:
            continue
        outlines.setdefault(outline.key, []).append(outline)

    buckets = [bucket for bucket in outlines.values() if len(bucket) >= _MIN_GROUP]
    if not buckets:
        # The tokenize pass is only worth paying for once something might fire.
        return []
    comments = _comment_lines(source)

    found: list[list[_Shape]] = []
    for bucket in buckets:
        groups: dict[tuple[str, tuple[str, ...]], list[_Shape]] = {}
        for outline in bucket:
            shape = _Shape(outline.node, comments)
            groups.setdefault(shape.key, []).append(shape)
        found.extend(
            members
            for members in groups.values()
            if len(members) >= _MIN_GROUP and not _erases_a_fixture_document(members)
        )
    return found


def _comment_lines(source: str) -> dict[int, str]:
    """Index every `#` comment in the file by the line it sits on."""
    standalone, _ = standalone_comments(source)
    return {line: text for line, _, text in (*standalone, *trailing_comments(source))}


def _documentation(node: ast.FunctionDef | ast.AsyncFunctionDef, comments: dict[int, str]) -> tuple[str, ...]:
    """Collect the prose a function carries: its docstring and its own comments."""
    docstring = ast.get_docstring(node, clean=False) or ""
    end = node.end_lineno or node.lineno
    return (docstring, *(comments[line] for line in range(node.lineno, end + 1) if line in comments))


def _erases_a_fixture_document(members: list[_Shape]) -> bool:
    """Report whether the group is held together by erasing a multi-line fixture."""
    # `zip(*...)` loses the element type through the star-unpack, so the columns
    # are materialised with an explicit annotation rather than inlined.
    columns: list[tuple[object, ...]] = list(zip(*(member.literals for member in members), strict=True))
    return any(
        any(value != column[0] or type(value) is not type(column[0]) for value in column)
        and any(_is_fixture_document(value) for value in column)
        for column in columns
    )


def _is_fixture_document(value: object) -> bool:
    return isinstance(value, str) and "\n" in value and len(value) > _MAX_CASE_LITERAL


def _test_functions(tree: ast.Module) -> list[tuple[str, bool, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Collect the `test_*` functions pytest would collect, tagged by container."""
    classes = _class_index(tree)
    found: list[tuple[str, bool, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    pending: list[tuple[str, bool, ast.Module | ast.ClassDef]] = [("", False, tree)]
    while pending:
        container, in_test_case, node = pending.pop()
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef):
                pending.append(
                    (
                        f"{container}{stmt.name}.",
                        in_test_case or _is_test_case_class(stmt, classes, frozenset()),
                        stmt,
                    )
                )
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
                found.append((container, in_test_case, stmt))
    return found


def _class_index(tree: ast.Module) -> dict[str, ast.ClassDef]:
    """Map every class name the module defines to its definition."""
    found: dict[str, ast.ClassDef] = {}
    pending: list[ast.Module | ast.ClassDef] = [tree]
    while pending:
        for stmt in pending.pop().body:
            if isinstance(stmt, ast.ClassDef):
                found.setdefault(stmt.name, stmt)
                pending.append(stmt)
    return found


def _is_test_case_class(node: ast.ClassDef, classes: dict[str, ast.ClassDef], seen: frozenset[str]) -> bool:
    """Report whether the class reaches `unittest.TestCase` through any base."""
    if node.name in seen:
        return False
    inner = seen | {node.name}
    for base in node.bases:
        name = _base_name(base)
        local = classes.get(name)
        if local is not None:
            if _is_test_case_class(local, classes, inner):
                return True
        elif _UNITTEST_BASE_RE.search(name):
            return True
    return False


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    # A generic base such as `Generic[T]` or a parametrized mixin factory.
    if isinstance(base, ast.Subscript):
        return _base_name(base.value)
    if isinstance(base, ast.Call):
        return _base_name(base.func)
    return ""


def _uses_unittest_api(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body calls a `self.<...>` API only a TestCase provides."""
    return any(
        isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id == _SELF
        and (child.attr.startswith(_UNITTEST_ASSERT_PREFIX) or child.attr in _UNITTEST_SELF_ATTRS)
        for child in _walk(node)
    )


def _body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return body[1:]
    return body


def _bound_names(body: list[ast.stmt]) -> frozenset[str]:
    """Find every name the body binds, so those names can be renamed positionally."""
    stored = {
        child.id
        for stmt in body
        for child in _walk(stmt)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }
    handlers = {
        child.name
        for stmt in body
        for child in _walk(stmt)
        if isinstance(child, ast.ExceptHandler) and child.name is not None
    }
    return frozenset(stored | handlers)


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    # Only functions in the same container are ever compared, so `self` is
    # either present on both sides or on neither and needs no special case.
    args = node.args
    declared = (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
    return tuple(arg.arg for arg in declared if arg is not None)


def _decorator_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    # Verbatim, constants included: a different `xfail` reason, `skipif`
    # condition, `override_settings` value or `parametrize` table means the two
    # tests differ in a way the body cannot show.
    return "|".join(ast.dump(dec) for dec in node.decorator_list)


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in children(node):
        yield from _walk(child)


def _message(group: list[_Shape], path: Path) -> str:
    """Describe the duplication and point back at the original."""
    original, duplicate = group[0], group[1]
    others = len(group) - _MIN_GROUP
    also = f" (and {others} more in this module)" if others > 0 else ""
    origin = f"`{original.node.name}` ({path}:{original.node.lineno})"
    differences = _differing_literals(original.literals, duplicate.literals)
    if not differences:
        return (
            f"`{duplicate.node.name}`{also} is a verbatim copy of {origin} — same calls, same "
            f"literals, only the names differ, so the suite runs one behaviour twice and reports "
            f"two passes. {_IDENTICAL_ADVICE}"
        )
    return (
        f"`{duplicate.node.name}`{also} repeats the body of {origin} differing only in "
        f"{_render_differences(differences)} — two tests, one behaviour, and every future edit "
        f"has to be made in both. {_PARAMETRIZE_ADVICE}"
    )


def _differing_literals(original: tuple[object, ...], duplicate: tuple[object, ...]) -> list[tuple[object, object]]:
    # Equal shapes imply the same number of constants, so positional comparison
    # is well defined; the length guard is belt and braces.
    if len(original) != len(duplicate):
        return []
    return [
        (was, now) for was, now in zip(original, duplicate, strict=True) if was != now or type(was) is not type(now)
    ]


def _render_differences(differences: list[tuple[object, object]]) -> str:
    shown = ", ".join(f"{_render(was)} -> {_render(now)}" for was, now in differences[:_MAX_LITERALS_SHOWN])
    extra = len(differences) - _MAX_LITERALS_SHOWN
    return f"{shown} (and {extra} more literals)" if extra > 0 else shown


def _render(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _LITERAL_ECHO_LIMIT else f"{text[:_LITERAL_ECHO_LIMIT]}..."
