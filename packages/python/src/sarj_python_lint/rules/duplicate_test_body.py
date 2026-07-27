"""SARJ058: N copy-pasted test functions in one module are one `parametrize` waiting to be written.

`test_admin_can_delete` and `test_editor_can_delete` whose bodies are the same
three lines with `"admin"` swapped for `"editor"` are not two tests. They are one
test run twice, and the duplication has a running cost: the suite reports two
passing tests where one behaviour is covered, so the test count overstates the
coverage; and every future edit — a renamed fixture, an extra assertion, a
changed helper signature — has to be made N times, which is exactly the edit
people make N-1 times.

`@pytest.mark.parametrize("role", ["admin", "editor"], ids=["admin", "editor"])`
collapses them into one body with N cases, and (unlike the hand copy) a new case
is one list entry rather than a new function.

This is the copy-paste sibling of **SARJ041 `test-loops-over-literal-cases`**,
and the two are exact mirror images. SARJ041 fires when a *single* test hides N
cases inside a `for` loop over a literal table — too few test functions. This
rule fires when N *separate test functions* hold the same body — too many. Both
diagnostics ask for the same fix, `@pytest.mark.parametrize`, from opposite
sides. Where SARJ041 works inside one function, this rule is a whole-module
grouping. The `ids=` advice in the message is the bridge to **SARJ042
`parametrize-case-needs-id`**: collapsing named scenarios into a table loses the
scenario names unless `ids=` carries them over, and a nameless case table is
SARJ042's problem.

Fires when ALL of these hold:

* the file is a test file (`is_test_path`), and is not generated,
* the tests are **pytest-style**, not `unittest.TestCase` methods,
* two or more `test_*` functions **in the same container** — the module body, or
  the same class — normalize to the same body shape,
* the shared body is **substantive**: at least 3 statements counted over the
  whole body subtree, docstring excluded. Two-statement tests
  (`x = f(); assert x`) are similar by nature, and grouping them measures
  nothing,
* the functions agree on everything that is not the body: same `async`-ness,
  same parameter list, and byte-identical decorators.

Body shapes are compared by hashing into a dict, never by comparing functions
pairwise, and in two stages: a cheap per-function outline (one traversal, no
copying) buckets the candidates, and the expensive normalization runs only
inside a bucket that already has two members. On the worst real test module
measured that is the difference between 53 and 19 ms/1k LOC, for identical
findings. There is no cap on module size and nothing is ever truncated. The
normalization erases exactly two things:

* **every constant** collapses to one placeholder, so the literal that differs
  between the copies (`"admin"` vs `"editor"`, `200` vs `404`) does not defeat
  the match. The original values are kept in order, which is what lets the
  message name what actually differs,
* **every name bound inside the body** (assignment, `for`, `with ... as`,
  `except ... as`, walrus, comprehension target) is renamed to `v0, v1, …` in
  first-appearance order, so `user = ...` and `u = ...` are the same shape.

Everything else is kept verbatim, and that is the load-bearing half of the
design: attribute names, keyword-argument names, operators, and any name the
body does *not* bind — module-level constants, imported helpers, enum members,
exception classes, the function under test — all stay. `assert normalize_phone(x)`
and `assert normalize_email(x)` are different shapes; `assert f(x) == CANONICAL`
and `assert f(x) == LEGACY` are different shapes. Only a difference that a
`parametrize` argument could actually carry is erased.

Corpus evidence. Measured over five populations — bulbul (3,472 substantive test
functions), noura-be (2,307), django (13,499), fastapi (2,076), celery (2,692) —
holding the group threshold at 2:

    bulbul 61 (1.8% of its tests)   noura-be 33 (1.4%)   django 0
    fastapi 387 (18.6%)             celery 40 (1.5%)

Before the `unittest.TestCase` guard the same run fired 983 times; that one
guard removed all 462 of the difference (458 in django, 4 in celery). A 21-hit
manual sample spread across all five corpora then classified 21 true positives
and 0 false positives, and it turned up five *byte-for-byte* duplicate tests
that are latent bugs rather than mere noise:

* `bulbul/python/agent/tests/test_agent_tools.py:2785` —
  `test_handles_none_activity_without_error` never sets up an activity, so it is
  literally `test_sets_session_stt` under a different name and asserts nothing
  about the None-activity path it is named for,
* `bulbul/python/bulbul/tests/store/test_custom_scenario_store.py:461` —
  `test_superadmin_can_delete_any_scenario` is `test_delete_scenario` verbatim,
  with no superadmin actor anywhere in it,
* `bulbul/python/agent/tests/test_custom_api_tool.py:876` — `test_roundtrip_list`
  repeats `test_list_of_strings_roundtrip` with the locals renamed, which is the
  case the local-name canonicalization exists to catch,
* `fastapi/tests/test_compat.py:118` — the "pipe union" variant of
  `test_serialize_sequence_value_with_optional_list` uses the same
  `list[str] | None` annotation as the test it is supposed to contrast with,
* `celery/t/unit/backends/test_base.py:1419` —
  `test_chord_part_return_propagate_default` is identical to
  `..._propagate_set`, so one of the two configures nothing.

fastapi is a genuine outlier at 18.6% rather than a rule defect: its suite is
one-endpoint-per-test by construction (`tests/test_path.py` alone holds a
31-member group of `client.get(path)` / `assert status` / `assert json` bodies),
and every cluster read there was a real, collapsible table.

Deliberately NOT flagged:

* **`unittest.TestCase` methods.** pytest documents that
  `@pytest.mark.parametrize` cannot be applied to a `unittest.TestCase`
  subclass, so the fix this rule asks for is not available there and the
  diagnostic would be unactionable. The unittest answer — a table plus
  `with self.subTest(...)` — is a different transformation, and SARJ041 already
  treats `subTest` as an acceptable substitute for parametrize. This is the
  single largest guard by volume: it takes django's suite from **458 findings
  to 0**, every one of the 458 being a `TestCase` method where the advice would
  have been wrong — among them
  `django/tests/migrations/test_writer.py:346` (`test_serialize_multiline_strings`
  against `test_serialize_strings`, six literals apart and genuinely two
  scenarios), `django/tests/test_utils/tests.py:1264` and
  `django/tests/staticfiles_tests/test_storage.py:124`. Detected two ways,
  because django's suite needs both: a base class
  named like a test case (`TestCase`, `SimpleTestCase`, `TransactionTestCase`,
  and suite-local intermediates such as `ChoiceWidgetTest` in
  `django/tests/forms_tests/widget_tests/test_select.py:10`), or a body calling
  a TestCase-only `self.` API (`self.assertEqual`, `self.subTest`,
  `self.skipTest`) — which catches the mixin classes that carry test methods
  without inheriting a TestCase at all, such as django's `TestHashedFiles` in
  `staticfiles_tests/test_storage.py`,
* **functions in different classes**, even in the same module and with the same
  body. `class SQLiteTests(TestCase)` and `class PostgresTests(TestCase)` with
  the same three-line body are a deliberate parity pair whose behaviour comes
  from `setUp`, the class-level attributes, and the base class — none of which
  is visible in the body. django's backend suites are built entirely this way,
  and grouping across classes made them the single largest false-positive
  cluster. The container (module, or a specific class) is part of the identity,
* **functions whose decorators differ in any way**, compared verbatim with
  constants intact. Two bodies can be identical while
  `@pytest.mark.xfail(reason="ipv6 not supported")` versus
  `@pytest.mark.xfail(reason="ipv4 only")`, `@pytest.mark.skipif(sys.platform ==
  "win32")` versus a different condition, or `@override_settings(USE_TZ=True)`
  versus `USE_TZ=False` makes them genuinely different tests. The decorator *is*
  the parameter in those suites, and it is already spelled declaratively, so
  there is nothing to collapse,
* **a sync/async parity pair**. `def test_get` and `async def test_get_async`
  exercising the same assertions cover two different code paths in the library
  under test; a `parametrize` cannot merge them because pytest dispatches them
  differently. `async`-ness is part of the identity,
* **functions taking different parameters.** Fixtures are behaviour: `def
  test_x(client)` and `def test_x(async_client)` with the same body run against
  different systems. The parameter names are part of the identity,
* **short bodies.** A two-statement test is not evidence of copy-paste — call,
  assert, done, and any two tests of the same helper look alike. The 3-statement
  floor is what keeps the rule from firing on every well-factored unit suite,
* **generated test modules** (`is_generated_source`) — a generator emitting N
  near-identical cases is the generator's business, and the fix would be
  overwritten on the next regeneration,
* the **first** member of a group. The diagnostic goes on the copies and points
  back at the original, so a group of four reports three findings, not four.
"""

from __future__ import annotations

import ast
import copy
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# Every literal collapses to this, so the differing case value does not defeat
# the shape match. A string keeps `ast.dump` output deterministic (an `object()`
# sentinel would render its memory address).
_LITERAL_PLACEHOLDER = "\x00sarj-literal"

# Statements in the shared body, docstring excluded, below which "these two
# tests look alike" carries no information.
_MIN_STATEMENTS = 3

# Members of a normalized-body group before it counts as copy-paste. Two is the
# honest threshold: one function copied once is already a maintenance burden,
# and the guards (container, decorators, signature, size) carry the precision.
_MIN_GROUP = 2

# A class whose base reads like a test-case base is a `unittest.TestCase`, and
# pytest refuses to apply `parametrize` to those. Matches django's `TestCase` /
# `SimpleTestCase` / `TransactionTestCase`, plain `unittest.TestCase`, and the
# suite-local intermediate bases those projects build (`ChoiceWidgetTest`,
# `AdminViewBasicTest`). A pytest-style class has no base at all, or a base that
# is not named for a test case.
_UNITTEST_BASE_RE = re.compile(r"Test(Case|s)?$")

# `self.<name>` calls that only exist on a `unittest.TestCase`. This is the
# fallback for a mixin class carrying test methods without a TestCase base —
# django's `TestHashedFiles` is mixed into a `CollectionTestCase` elsewhere.
_UNITTEST_SELF_ATTRS = frozenset({"subTest", "skipTest", "addCleanup", "addTypeEqualityFunc", "fail"})

_UNITTEST_ASSERT_PREFIX = "assert"

_SELF = "self"

# Longest literal echoed back in the message before it is elided.
_LITERAL_ECHO_LIMIT = 32

# Differing literals named in the message; past this the list is summarized.
_MAX_LITERALS_SHOWN = 3


class DuplicateTestBody(Rule):
    """Copy-pasted test functions differing only in literals — parametrize them."""

    id: str = "duplicate-test-body"
    code: str = "SARJ058"
    description: str = (
        "Test function duplicates another test's body in the same module — collapse them into "
        "one `@pytest.mark.parametrize` with `ids=`."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions whose normalized body already exists in the module.

        Returns:
            One diagnostic per copy (never the original), sorted by position.

        """
        if not is_test_path(path) or is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=duplicate.node.lineno,
                col=duplicate.node.col_offset + 1,
                code=self.code,
                message=_message(duplicate, original, path),
            )
            for original, duplicate in _duplicate_pairs(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _Outline:
    """A test function fingerprinted by everything that is cheap to read.

    One traversal, no copying and no `ast.dump` of the body: the identity fields
    (container, async-ness, signature, decorators) plus the sequence of node
    types the body contains. Two functions with different outlines can never
    normalize to the same body, so the expensive `_Shape` pass only ever runs on
    the functions whose outlines already collide — which in a normal module is
    almost none of them.
    """

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
    """One test function's body reduced to a comparable normalized form.

    `body` is equal for two functions of the same outline exactly when a
    `parametrize` could merge them; `literals` holds each erased constant in
    traversal order, so two members of the same group have literal lists of the
    same length and positional comparison names what differs.
    """

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        super().__init__()
        self.node: ast.FunctionDef | ast.AsyncFunctionDef = node
        body = _body_without_docstring(node)
        canonical = _Canonicalizer(_bound_names(body))
        self.body: str = "".join(canonical.render(stmt) for stmt in body)
        self.literals: tuple[object, ...] = tuple(canonical.literals)


class _Canonicalizer(ast.NodeVisitor):
    """Rewrite a copied subtree so only its structure survives, then dump it.

    Works on a deep copy: `parse_or_none` hands every rule the *same* module
    object, so mutating a node in place would corrupt the tree for the rules
    that run after this one.
    """

    def __init__(self, bound: frozenset[str]) -> None:
        super().__init__()
        self._bound: frozenset[str] = bound
        self._aliases: dict[str, str] = {}
        self.literals: list[object] = []

    def render(self, stmt: ast.stmt) -> str:
        """Normalize a copy of `stmt` and return its dumped shape.

        Returns:
            The `ast.dump` of the statement with literals and local names erased.

        """
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
            node.id = self._aliases.setdefault(node.id, f"v{len(self._aliases)}")


def _duplicate_pairs(tree: ast.Module) -> list[tuple[_Shape, _Shape]]:
    """Group the module's tests by body shape and pair each copy with its original.

    Returns:
        `(original, copy)` for every member of a group after the first.

    """
    outlines: dict[tuple[str, bool, tuple[str, ...], str, str], list[_Outline]] = {}
    for container, in_test_case, node in _test_functions(tree):
        if in_test_case or _uses_unittest_api(node):
            continue
        outline = _Outline(node, container)
        if outline.statements < _MIN_STATEMENTS:
            continue
        outlines.setdefault(outline.key, []).append(outline)

    pairs: list[tuple[_Shape, _Shape]] = []
    for bucket in outlines.values():
        if len(bucket) < _MIN_GROUP:
            continue
        groups: dict[str, list[_Shape]] = {}
        for outline in bucket:
            shape = _Shape(outline.node)
            groups.setdefault(shape.body, []).append(shape)
        pairs.extend(
            (members[0], duplicate)
            for members in groups.values()
            if len(members) >= _MIN_GROUP
            for duplicate in members[1:]
        )
    return pairs


def _test_functions(tree: ast.Module) -> list[tuple[str, bool, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Collect the `test_*` functions pytest would collect, tagged by container.

    Only module-level functions and class methods are collected — a `test_*`
    nested inside another function is a callback, not a test. The container tag
    is `""` for the module body and the dotted class path otherwise, which is
    what keeps two backend-parity classes from being compared against each other.

    Returns:
        `(container, inside a unittest.TestCase, function)` triples.

    """
    found: list[tuple[str, bool, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    pending: list[tuple[str, bool, ast.Module | ast.ClassDef]] = [("", False, tree)]
    while pending:
        container, in_test_case, node = pending.pop()
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef):
                pending.append((f"{container}{stmt.name}.", in_test_case or _is_test_case_class(stmt), stmt))
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
                found.append((container, in_test_case, stmt))
    return found


def _is_test_case_class(node: ast.ClassDef) -> bool:
    return any(_UNITTEST_BASE_RE.search(_base_name(base)) for base in node.bases)


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
    """Report whether the body calls a `self.<...>` API only a TestCase provides.

    Returns:
        True for `self.assertX(...)`, `self.subTest(...)`, `self.fail(...)`, and
        the other TestCase-only helpers.

    """
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
    """Find every name the body binds, so those names can be renamed positionally.

    Parameters are deliberately absent: they are only ever loaded in the body,
    and their names are part of the function's identity rather than its shape.

    Returns:
        The identifiers bound by assignment, `for`, `with`/`except ... as`,
        walrus, or a comprehension target.

    """
    return frozenset(
        child.id
        for stmt in body
        for child in _walk(stmt)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    )


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
    for child in ast.iter_child_nodes(node):
        yield from _walk(child)


def _message(duplicate: _Shape, original: _Shape, path: Path) -> str:
    """Describe the duplication and point back at the original.

    Returns:
        The diagnostic text, naming the differing literals when there are any.

    """
    differences = _differing_literals(original.literals, duplicate.literals)
    if differences:
        detail = f"differing only in {_render_differences(differences)}"
    else:
        detail = "with a byte-for-byte identical body"
    return (
        f"`{duplicate.node.name}` repeats the body of `{original.node.name}` ({path}:{original.node.lineno}) "
        f"{detail} — two tests, one behaviour, and every future edit has to be made in both. "
        "Collapse them into one `@pytest.mark.parametrize(...)`, passing `ids=` so each scenario "
        "keeps the name it has today (see SARJ042)."
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
