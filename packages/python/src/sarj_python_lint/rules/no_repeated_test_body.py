from __future__ import annotations

import ast
from collections import Counter
import copy
from pathlib import PurePosixPath
import re
import textwrap
import tokenize
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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import standalone_comments, trailing_comments
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_TEST_PREFIX = "test"

# Collapse case literals so differing inputs do not hide duplicated test structure.
_LITERAL_PLACEHOLDER = "\x00sarj-literal"

# Statements in the shared body, docstring excluded, below which "these two
# tests look alike" carries no information.
_MIN_STATEMENTS = 3

# Members of a normalized-body group before it counts as copy-paste.
_MIN_GROUP = 2

# Small source-checker pairs often read better as individually named contracts.
# A longer uninterrupted run is a case table whose repeated shell obscures the cases.
_MIN_EMBEDDED_SOURCE_GROUP = 5
_MIN_REPEATED_SOURCE_OPERATION = 3

# Pytest cannot parametrize unittest-style classes, including project-specific TestCase bases.
_UNITTEST_BASE_RE = re.compile(r"TestCase$")

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
_LONG_SINGLE_LINE_FIXTURE_MIN_CHARS = 80
_LONG_SINGLE_LINE_FIXTURE_MIN_WORDS = 10

# Two-test coincidences need corroborating names; these words are too generic
# to establish that both tests exercise one behavior.
_WEAK_TEST_NAME_TOKENS = frozenset({"case", "key", "test", "value"})
_GENERIC_ORDINAL_TEST_RE = re.compile(r"test_?(?:[a-z]|first|one|second|three|third|two)$")

_PARAMETRIZE_ADVICE = (
    "Consider one `@pytest.mark.parametrize(...)` with descriptive `ids=` when these are cases of one contract "
    "(see SARJ042); otherwise retain and document the distinct contracts."
)

_IDENTICAL_ADVICE = (
    "There is no case table to build here: one of the two is a copy-paste that never got its "
    "edit. Make it exercise what its name claims, or delete it."
)


class _TestFunction(NamedTuple):
    container: str
    in_test_case: bool
    node: ast.FunctionDef | ast.AsyncFunctionDef


class _LiteralDifference(NamedTuple):
    original: object
    replacement: object


class NoRepeatedTestBody(Rule):
    id: str = "no-repeated-test-body"
    code: str = "SARJ066"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Substantial sibling pytest tests repeat the same structural body.",
        rationale="Copy-pasted tests drift independently and obscure the input dimension that changes behavior.",
        remediation=(
            "Parameterize literal-varying copies with descriptive `ids` when they exercise one contract; correct or "
            "remove verbatim copies that never received their intended edit."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("duplicate-test-body",),
        limitations=(
            "Only substantial sibling test bodies in one non-generated module are compared.",
            "A run of at least five two-statement embedded-source checker cases is compared because the source documents are natural parameter values.",
            "Meaningful docstring or comment differences keep tests distinct.",
            "Two-test groups with varying literals require corroborating behavior names; long scenario prose and distinct API resources remain separate contracts.",
        ),
        examples=(
            RuleExample(
                example_id="copy-pasted-tests",
                title="Copy-pasted tests hide the changing case dimension",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_permissions.py",
                        'def test_rejects_blank_role():\n    role = parse_role("")\n    result = validate(role)\n    assert result.invalid\n\ndef test_rejects_space_role():\n    role = parse_role(" ")\n    result = validate(role)\n    assert result.invalid\n\ndef test_rejects_tab_role():\n    role = parse_role("\\t")\n    result = validate(role)\n    assert result.invalid\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_permissions.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="parameterized-cases",
                title="One named case table exposes the changing inputs",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_permissions.py",
                        'import pytest\n\n@pytest.mark.parametrize("role", ["admin", "editor"], ids=["admin", "editor"])\ndef test_can_delete(role):\n    user = make_user(role)\n    allowed = can_delete(user)\n    assert allowed\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_permissions.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="verbatim-copy",
                scenario="distinct-behavior",
                title="A copied test never received its intended edit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_jobs.py",
                        "def test_starts_job():\n    job = build_job()\n    job.run()\n    assert job.done\n\ndef test_stops_job():\n    job = build_job()\n    job.run()\n    assert job.done\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_jobs.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="distinct-behaviors",
                scenario="distinct-behavior",
                title="Sibling tests preserve distinct API contracts",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_api.py",
                        'def test_delete_environment():\n    response = client.delete("/api/environments/3/")\n    result = response.json()\n    assert result["ok"]\n\ndef test_delete_schedule():\n    response = client.delete("/api/schedules/3/")\n    result = response.json()\n    assert result["ok"]\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or path.name == "conftest.py" or is_generated(path, source):
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
                message=_message(group),
                severity=Severity.WARNING,
            )
            for group in groups
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _Outline:
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
        self.embedded_source_checker: bool = _is_embedded_source_checker(node)
        # Container, async-ness, signature and decorators are identity, not
        # body: each of them can make two identical bodies different tests.
        self.key: tuple[str, bool, tuple[str, ...], str, str] = (
            container,
            isinstance(node, ast.AsyncFunctionDef),
            _signature_shape(node),
            _decorator_shape(node),
            ",".join(types),
        )


class _Shape:
    def __init__(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, comments: dict[int, str], imports: ImportIndex
    ) -> None:
        super().__init__()
        self.node: ast.FunctionDef | ast.AsyncFunctionDef = node
        body = _body_without_docstring(node)
        canonical = _Canonicalizer(_bound_names(body), imports)
        self.body: str = "".join(canonical.render(stmt) for stmt in body)
        self.literals: tuple[object, ...] = tuple(canonical.literals)
        self.embedded_source_checker: bool = _is_embedded_source_checker(node)
        self.embedded_source_signals: frozenset[str] = _embedded_source_signals(node)
        # Prose is identity, not shape: merging two tests forces one of the two
        # explanations to be deleted, and `ids=` cannot carry a paragraph.
        self.key: tuple[str, tuple[str, ...]] = (self.body, _documentation(node, comments))


class _Canonicalizer(ast.NodeVisitor):
    def __init__(self, bound: frozenset[str], imports: ImportIndex) -> None:
        super().__init__()
        self._bound: frozenset[str] = bound
        self._imports: ImportIndex = imports
        self._aliases: dict[str, str] = {}
        self._preserve_literals: int = 0
        self.literals: list[object] = []

    def render(self, stmt: ast.stmt) -> str:
        clone = copy.deepcopy(stmt)
        self.visit(clone)
        return ast.dump(clone)

    def visit_Constant(self, node: ast.Constant) -> None:
        if self._preserve_literals:
            return
        value: object = node.value
        self.literals.append(value)
        node.value = _LITERAL_PLACEHOLDER
        node.kind = None

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.visit(node.value)
        self._visit_with_literal_values(node.slice)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if key is not None:
                self._visit_with_literal_values(key)
            self.visit(value)

    def visit_Call(self, node: ast.Call) -> None:
        self.visit(node.func)
        for argument in node.args:
            self.visit(argument)
        preserves_match = _is_pytest_raises(node.func, self._imports)
        for keyword in node.keywords:
            if preserves_match and keyword.arg == "match":
                self._visit_with_literal_values(keyword.value)
            else:
                self.visit(keyword.value)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self._bound:
            node.id = self._alias(node.id)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None and node.name in self._bound:
            node.name = self._alias(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_eager(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_eager(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_eager(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_eager(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._visit_eager(node)

    def _visit_eager(self, node: ast.AST) -> None:
        for child in _eager_children(node):
            self.visit(child)

    def _alias(self, name: str) -> str:
        return self._aliases.setdefault(name, f"v{len(self._aliases)}")

    def _visit_with_literal_values(self, node: ast.AST) -> None:
        self._preserve_literals += 1
        try:
            self.visit(node)
        finally:
            self._preserve_literals -= 1


def _is_pytest_raises(node: ast.expr, imports: ImportIndex) -> bool:
    return imports.resolves(node, sources=frozenset({"pytest"}), symbol="raises")


def _duplicate_groups(tree: ast.Module, source: str) -> list[list[_Shape]]:
    imports = ImportIndex.from_tree(tree)
    test_functions = _test_functions(tree)
    positions = {
        id(node): position
        for position, (_, _, node) in enumerate(sorted(test_functions, key=lambda item: item[2].lineno))
    }
    outlines: dict[tuple[str, bool, tuple[str, ...], str, str], list[_Outline]] = {}
    for container, in_test_case, node in test_functions:
        if in_test_case or _uses_unittest_api(node):
            continue
        outline = _Outline(node, container)
        if outline.statements < _MIN_STATEMENTS and not outline.embedded_source_checker:
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
            shape = _Shape(outline.node, comments, imports)
            groups.setdefault(shape.key, []).append(shape)
        for members in groups.values():
            candidates = (
                _consecutive_embedded_source_groups(members, positions)
                if all(member.embedded_source_checker for member in members)
                else [members]
            )
            found.extend(
                candidate
                for candidate in candidates
                if len(candidate) >= _MIN_GROUP
                and not _erases_a_fixture_document(candidate)
                and not _erases_contract_identity(candidate)
                and _has_enough_duplicate_evidence(candidate)
            )
    return found


def duplicate_test_owner_ids(tree: ast.Module, source: str) -> frozenset[int]:
    try:
        groups = _duplicate_groups(tree, source)
    except tokenize.TokenError, IndentationError, SyntaxError, RecursionError:
        return frozenset()
    return frozenset(id(member.node) for group in groups for member in group)


def _consecutive_embedded_source_groups(members: list[_Shape], positions: dict[int, int]) -> list[list[_Shape]]:
    ordered = sorted(members, key=lambda member: positions[id(member.node)])
    runs: list[list[_Shape]] = []
    for member in ordered:
        if not runs or positions[id(member.node)] != positions[id(runs[-1][-1].node)] + 1:
            runs.append([])
        runs[-1].append(member)
    return [run for run in runs if len(run) >= _MIN_EMBEDDED_SOURCE_GROUP and _shares_embedded_source_signal(run)]


def _shares_embedded_source_signal(members: list[_Shape]) -> bool:
    common = members[0].embedded_source_signals
    for member in members[1:]:
        common = common.intersection(member.embedded_source_signals)
    return bool(common)


def _comment_lines(source: str) -> dict[int, str]:
    standalone, _ = standalone_comments(source)
    return {line: text for line, _, text in (*standalone, *trailing_comments(source))}


def _documentation(node: ast.FunctionDef | ast.AsyncFunctionDef, comments: dict[int, str]) -> tuple[str, ...]:
    docstring = ast.get_docstring(node, clean=False) or ""
    end = node.end_lineno or node.lineno
    return (docstring, *(comments[line] for line in range(node.lineno, end + 1) if line in comments))


def _erases_a_fixture_document(members: list[_Shape]) -> bool:
    if all(member.embedded_source_checker for member in members):
        return False
    # `zip(*...)` loses the element type through the star-unpack, so the columns
    # are materialised with an explicit annotation rather than inlined.
    columns: list[tuple[object, ...]] = list(zip(*(member.literals for member in members), strict=True))
    return any(
        any(value != column[0] or type(value) is not type(column[0]) for value in column)
        and any(_is_fixture_document(value) for value in column)
        for column in columns
    )


def _is_fixture_document(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) > _MAX_CASE_LITERAL
        and (
            "\n" in value
            or (
                len(value) >= _LONG_SINGLE_LINE_FIXTURE_MIN_CHARS
                and len(value.split()) >= _LONG_SINGLE_LINE_FIXTURE_MIN_WORDS
                and not value.lstrip()
                .upper()
                .startswith(("ALTER ", "CREATE ", "DELETE ", "INSERT ", "SELECT ", "UPDATE ", "WITH "))
            )
        )
    )


def _erases_contract_identity(members: list[_Shape]) -> bool:
    columns: list[tuple[object, ...]] = list(zip(*(member.literals for member in members), strict=True))
    return any(
        len(set(column)) > 1 and all(isinstance(value, str) and value.startswith("/") for value in column)
        for column in columns
    )


def _has_enough_duplicate_evidence(members: list[_Shape]) -> bool:
    if len(members) > _MIN_GROUP or not _differing_literals(members[0].literals, members[1].literals):
        return True
    names = [member.node.name for member in members]
    if all(_GENERIC_ORDINAL_TEST_RE.fullmatch(name) for name in names):
        return True
    token_sets = [_test_name_tokens(name) for name in names]
    shared: set[str] = token_sets[0].intersection(*token_sets[1:])
    return bool(shared - _WEAK_TEST_NAME_TOKENS)


def _test_name_tokens(name: str) -> set[str]:
    suffix = name[4:].lstrip("_") if name.startswith(_TEST_PREFIX) else name
    return {token for token in suffix.split("_") if token}


def _test_functions(tree: ast.Module) -> list[_TestFunction]:
    classes = _class_index(tree)
    found: list[_TestFunction] = []
    for statement in tree.body:
        if isinstance(statement, _FUNC_NODES) and statement.name.startswith(_TEST_PREFIX):
            found.append(_TestFunction(container="", in_test_case=False, node=statement))
        elif isinstance(statement, ast.ClassDef) and statement.name.startswith("Test"):
            in_test_case = _is_test_case_class(statement, classes, frozenset())
            found.extend(
                _TestFunction(container=f"{statement.name}.", in_test_case=in_test_case, node=member)
                for member in statement.body
                if isinstance(member, _FUNC_NODES) and member.name.startswith(_TEST_PREFIX)
            )
    return found


def _class_index(tree: ast.Module) -> dict[str, ast.ClassDef]:
    found: dict[str, ast.ClassDef] = {}
    pending: list[ast.Module | ast.ClassDef] = [tree]
    while pending:
        for stmt in pending.pop().body:
            if isinstance(stmt, ast.ClassDef):
                found.setdefault(stmt.name, stmt)
                pending.append(stmt)
    return found


def _is_test_case_class(node: ast.ClassDef, classes: dict[str, ast.ClassDef], seen: frozenset[str]) -> bool:
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
    match base:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        # A generic base such as `Generic[T]` or a parametrized mixin factory.
        case ast.Subscript(value=value):
            return _base_name(value)
        case ast.Call(func=func):
            return _base_name(func)
        case _:
            return ""


def _uses_unittest_api(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
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


def _is_embedded_source_checker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    match _body_without_docstring(node):
        case [
            ast.Assign(
                targets=[ast.Name(id=name)],
                value=ast.Constant(value=str() as source),
            ),
            ast.Assert(test=assertion),
        ] if "\n" in source:
            loads = [
                child
                for child in _walk(assertion)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name
            ]
            return len(loads) == 1 and any(
                any(load is descendant for descendant in _walk(call))
                for call in _walk(assertion)
                if isinstance(call, ast.Call) and _is_checker_call(call)
                for load in loads
            )
        case _:
            return False


def _is_checker_call(node: ast.Call) -> bool:
    match node.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name.lstrip("_").startswith(("check", "lint"))
        case _:
            return False


def _embedded_source_signals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    match _body_without_docstring(node):
        case [ast.Assign(value=ast.Constant(value=str() as source)), ast.Assert()]:
            try:
                tree = ast.parse(textwrap.dedent(source))
            except SyntaxError:
                return frozenset()
            names = [
                name for child in _walk(tree) if isinstance(child, ast.Call) for name in [_call_name(child)] if name
            ]
            return frozenset(name for name, count in Counter(names).items() if count >= _MIN_REPEATED_SOURCE_OPERATION)
        case _:
            return frozenset()


def _call_name(node: ast.Call) -> str:
    match node.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _bound_names(body: list[ast.stmt]) -> frozenset[str]:
    stored = {
        child.id
        for stmt in body
        for child in _binding_nodes(stmt)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }
    handlers = {
        child.name
        for stmt in body
        for child in _binding_nodes(stmt)
        if isinstance(child, ast.ExceptHandler) and child.name is not None
    }
    return frozenset(stored | handlers)


def _binding_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in _eager_children(node):
        yield from _binding_nodes(child)


def _eager_children(node: ast.AST) -> Iterator[ast.AST]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            yield from (
                *node.decorator_list,
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            )
        case ast.ClassDef():
            yield from (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords))
        case ast.Lambda():
            yield from (
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            )
        case ast.comprehension():
            yield from (node.iter, *node.ifs)
        case _:
            yield from children(node)


def _signature_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    return (
        ast.dump(node.args),
        ast.dump(node.returns) if node.returns is not None else "",
        *(ast.dump(param) for param in node.type_params),
    )


def _decorator_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    # Verbatim, constants included: a different `xfail` reason, `skipif`
    # condition, `override_settings` value or `parametrize` table means the two
    # tests differ in a way the body cannot show.
    return "|".join(ast.dump(dec) for dec in node.decorator_list)


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in children(node):
        yield from _walk(child)


def _message(group: list[_Shape]) -> str:
    original, duplicate = group[0], group[1]
    others = len(group) - _MIN_GROUP
    also = f" (and {others} more in this module)" if others > 0 else ""
    origin = f"`{original.node.name}` (line {original.node.lineno})"
    differences = _differing_literals(original.literals, duplicate.literals)
    if not differences:
        return (
            f"`{duplicate.node.name}`{also} is a verbatim copy of {origin} — same calls, same "
            f"literals, only the names differ, so the suite runs one behaviour twice and reports "
            f"two passes. {_IDENTICAL_ADVICE}"
        )
    return (
        f"`{duplicate.node.name}`{also} repeats the body of {origin} differing only in "
        f"{_render_differences(differences)} — the same test structure now has to be maintained in multiple places. "
        f"{_PARAMETRIZE_ADVICE}"
    )


def _differing_literals(original: tuple[object, ...], duplicate: tuple[object, ...]) -> list[_LiteralDifference]:
    # Equal shapes imply the same number of constants, so positional comparison
    # is well defined; the length guard is belt and braces.
    if len(original) != len(duplicate):
        return []
    return [
        _LiteralDifference(was, now)
        for was, now in zip(original, duplicate, strict=True)
        if was != now or type(was) is not type(now)
    ]


def _render_differences(differences: list[_LiteralDifference]) -> str:
    shown = ", ".join(f"{_render(was)} -> {_render(now)}" for was, now in differences[:_MAX_LITERALS_SHOWN])
    extra = len(differences) - _MAX_LITERALS_SHOWN
    return f"{shown} (and {extra} more literals)" if extra > 0 else shown


def _render(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _LITERAL_ECHO_LIMIT else f"{text[:_LITERAL_ECHO_LIMIT]}..."
