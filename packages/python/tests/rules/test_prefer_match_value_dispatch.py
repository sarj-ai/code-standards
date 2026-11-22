import ast
import json
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules.prefer_match_value_dispatch import PreferMatchValueDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/dispatch.py") -> list[Diagnostic]:
    return PreferMatchValueDispatch().check(Path(path), source)


def _ladder(first: str = "value == 'a'", second: str = "value == 'b'") -> str:
    return f"if {first}:\n    result = first()\nelif {second}:\n    result = second()\nelse:\n    result = fallback()\n"


def _finite_wildcard(body: str) -> str:
    return (
        "from __future__ import annotations\nfrom typing import Literal, assert_never\n"
        "def f(value: Literal['a', 'b']):\n    match value:\n"
        "        case 'a':\n            return 1\n        case _:\n"
        + "".join("            " + line + "\n" for line in body.splitlines())
    )


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    "guard",
    [
        pytest.param("if value == 'a':\n    return 1", id="equality-return"),
        pytest.param("if value in ('a',):\n    return 1", id="membership-return"),
        pytest.param("if value not in ('b', 'c'):\n    return 1", id="negative-membership-return"),
        pytest.param("if value != 'a':\n    pass\nelse:\n    return 1", id="else-return"),
        pytest.param("if value == 'a':\n    raise ValueError()", id="equality-raise"),
        pytest.param("if value != 'b' and value != 'c':\n    return 1", id="compound-and-return"),
        pytest.param("assert value != 'a'", id="assertion"),
    ],
)
def test_prior_terminal_guard_narrows_match_domain(guard: str, *, extra_value: bool) -> None:
    domain = "'a', 'b', 'c'" if extra_value else "'a', 'b'"
    source = (
        f"from typing import Literal\ndef f(value: Literal[{domain}]):\n"
        + "".join("    " + line + "\n" for line in guard.splitlines())
        + "    match value:\n        case 'b':\n            return 2\n        case _:\n            return 3\n"
    )
    assert len(_check(source)) == int(extra_value)


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    "guard",
    [
        pytest.param("if value in ('b', 'c'):", id="enclosing-membership"),
        pytest.param("if value == 'a':\n    return 1\nelse:", id="enclosing-else"),
    ],
)
def test_enclosing_guard_narrows_match_domain(guard: str, *, extra_value: bool) -> None:
    domain = "'a', 'b', 'c'" if extra_value else "'a', 'b'"
    source = (
        f"from typing import Literal\ndef f(value: Literal[{domain}]):\n"
        + "".join("    " + line + "\n" for line in guard.splitlines())
        + "        match value:\n            case 'b':\n                return 2\n"
        "            case _:\n                return 3\n    return 1\n"
    )
    assert len(_check(source)) == int(extra_value)


def test_nonterminal_guard_keeps_match_domain() -> None:
    source = _finite_wildcard("return 2").replace(
        "    match value:", "    if value == 'a':\n        pass\n    match value:"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
def test_compound_or_terminal_guard_narrows_match_domain(*, extra_value: bool) -> None:
    domain = "'a', 'b', 'c', 'd'" if extra_value else "'a', 'b', 'c'"
    source = (
        f"from typing import Literal\ndef f(value: Literal[{domain}]):\n"
        "    if value == 'a' or value == 'b':\n        return 1\n"
        "    match value:\n        case 'c':\n            return 2\n        case _:\n            return 3\n"
    )
    assert len(_check(source)) == int(extra_value)


@pytest.mark.parametrize("enclosing", [False, True], ids=["preceding-terminal", "enclosing"])
def test_unknown_subject_guard_abstains(*, enclosing: bool) -> None:
    if enclosing:
        body = (
            "    if value.startswith('b'):\n        match value:\n"
            "            case 'b':\n                return 2\n            case _:\n                return 3\n    return 1\n"
        )
    else:
        body = (
            "    if value.startswith('a'):\n        return 1\n"
            "    match value:\n        case 'b':\n            return 2\n        case _:\n            return 3\n"
        )
    assert _check("from typing import Literal\ndef f(value: Literal['a', 'b']):\n" + body) == []


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("if ready():\n    return 1", id="unrelated-terminal"),
        pytest.param("if value.startswith('a'):\n    pass", id="subject-nonterminal"),
        pytest.param("if ready(lambda value: value.startswith('a')):\n    return 1", id="shadowed-lambda-subject"),
    ],
)
def test_guards_without_subject_narrowing_keep_domain(prefix: str) -> None:
    source = _finite_wildcard("return 2").replace(
        "    match value:", "".join("    " + line + "\n" for line in prefix.splitlines()) + "    match value:"
    )
    assert len(_check(source)) == 1


def _wildcard_case(body: str, first: str = "yield 1") -> str:
    return (
        'from typing import Literal, assert_never\n\ndef f(value: Literal["a", "b"]):\n    match value:\n'
        f'        case "a":\n            {first}\n        case _:\n'
        + "".join(("            " + line if line else "") + "\n" for line in body.splitlines())
    )


def _guarded_match(prefix: str, *, extra_value: bool, loop: bool = False) -> str:
    domain = "'a', 'b', 'c'" if "'c'" in prefix else "'a', 'b'"
    domain += ", 'z'" if extra_value else ""
    indent = "        " if loop else "    "
    match_block = "match value:\n    case 'b':\n        return 2\n    case _:\n        return 3\n"
    return (
        "import sys\nfrom typing import Literal, assert_never\n"
        f"def f(value: Literal[{domain}], items=(), ctx=None):\n"
        + ("    for _ in items:\n" if loop else "")
        + "".join(indent + line + "\n" for line in prefix.splitlines())
        + "".join(indent + line + "\n" for line in match_block.splitlines())
    )


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    ("prefix", "loop"),
    [
        pytest.param("if value == 'a':\n    continue", True, id="continue"),
        pytest.param("if value == 'a':\n    break", True, id="break"),
        pytest.param("if value == 'a':\n    assert False", False, id="assert-false"),
        pytest.param("if value == 'a':\n    assert_never(value)", False, id="assert-never"),
        pytest.param("if value == 'a':\n    sys.exit(1)", False, id="process-exit"),
        pytest.param(
            "if value == 'a':\n    if ctx:\n        return 1\n    else:\n        return 0", False, id="nested-exits"
        ),
        pytest.param("if ctx:\n    return 0\nelif value == 'a':\n    return 1", False, id="elif-after-unrelated"),
        pytest.param("if value == 'c':\n    return 0\nelif value == 'a':\n    return 1", False, id="elif-chain"),
        pytest.param(
            "if value == 'a':\n    return 1\nelif ctx:\n    pass\nelse:\n    pass", False, id="elif-fallthrough"
        ),
    ],
)
def test_modelled_exits_narrow_match_domain(prefix: str, *, loop: bool, extra_value: bool) -> None:
    assert len(_check(_guarded_match(prefix, extra_value=extra_value, loop=loop))) == int(extra_value)


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    ("prefix", "loop"),
    [
        pytest.param("with ctx:\n    if value == 'a':\n        return 1", False, id="with"),
        pytest.param("try:\n    if value == 'a':\n        return 1\nfinally:\n    pass", False, id="try-finally"),
        pytest.param("try:\n    if value == 'a':\n        return 1\nexcept OSError:\n    pass", False, id="try-except"),
        pytest.param(
            "match value:\n    case 'a':\n        return 1\n    case 'b':\n        pass", False, id="preceding-match"
        ),
        pytest.param("for _ in items:\n    if value == 'a':\n        return 1", False, id="loop-guard"),
        pytest.param("if value.startswith('a'):\n    continue", True, id="unknown-continue"),
        pytest.param("if ctx:\n    return 0\nelif value.startswith('a'):\n    return 1", False, id="unknown-elif"),
    ],
)
def test_unmodelled_subject_exits_abstain(prefix: str, *, loop: bool, extra_value: bool) -> None:
    assert _check(_guarded_match(prefix, extra_value=extra_value, loop=loop)) == []


_INNER_EXPLICIT_MATCH = (
    "match value:\n    case 'a':\n        return 1\n    case 'b':\n        return 2\n    case _:\n        return 3\n"
)


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    "enclosing",
    [
        pytest.param("while value != 'c':\n", id="while"),
        pytest.param("match value:\n    case 'a' | 'b':\n", id="match-case"),
        pytest.param("match value:\n    case other if other != 'c':\n", id="guarded-case"),
        pytest.param("match flag:\n    case 1 if value != 'c':\n", id="other-subject-guard"),
    ],
)
def test_enclosing_subject_loops_and_cases_abstain(enclosing: str, *, extra_value: bool) -> None:
    domain = "'a', 'b', 'c', 'd'" if extra_value else "'a', 'b', 'c'"
    depth = len(enclosing.splitlines())
    source = (
        f"from typing import Literal\ndef f(value: Literal[{domain}], flag: int):\n"
        + "".join("    " + line + "\n" for line in enclosing.splitlines())
        + "".join("    " * (depth + 1) + line + "\n" for line in _INNER_EXPLICIT_MATCH.splitlines())
        + "    return 0\n"
    )
    ast.parse(source)
    inner = depth + 3
    assert inner not in [diagnostic.line for diagnostic in _check(source)]


@pytest.mark.parametrize("extra_value", [False, True], ids=["exhausted-domain", "remaining-value"])
@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("value == 'a' and sys.exit(1)", id="and-exit"),
        pytest.param("value != 'a' or sys.exit(1)", id="or-exit"),
        pytest.param("if value == 'a':\n    with ctx:\n        return 1", id="narrowed-with-exit"),
        pytest.param(
            "if value == 'a':\n    try:\n        return 1\n    finally:\n        pass", id="narrowed-try-exit"
        ),
        pytest.param("if value == 'a':\n    while True:\n        return 1", id="narrowed-loop-exit"),
    ],
)
def test_subject_dependent_unmodelled_exits_abstain(prefix: str, *, extra_value: bool) -> None:
    assert _check(_guarded_match(prefix, extra_value=extra_value)) == []


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("def label():\n    if value == 'a':\n        return 'raw'\n    return 'x'", id="nested-def"),
        pytest.param(
            "for item in items:\n    if value == 'a':\n        continue\n    print(item)", id="loop-local-continue"
        ),
        pytest.param("while ctx:\n    if value == 'a':\n        break", id="loop-local-break"),
        pytest.param("if ctx:\n    with ctx:\n        return 1", id="unrelated-nested-exit"),
    ],
)
def test_non_escaping_or_unrelated_prefixes_keep_domain(prefix: str) -> None:
    assert len(_check(_guarded_match(prefix, extra_value=False))) == 1


def test_try_else_dispatch_sees_try_body_guards() -> None:
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b'], load):\n    try:\n"
        "        if value == 'a':\n            return 1\n        load()\n    except OSError:\n        return 0\n"
        "    else:\n        match value:\n            case 'b':\n                return 2\n            case _:\n"
        "                return 3\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("if ctx:\n    continue", id="unrelated-continue"),
        pytest.param("if value == 'a':\n    print(value)", id="returning-call"),
    ],
)
def test_nonexiting_or_unrelated_loop_guards_keep_domain(prefix: str) -> None:
    assert len(_check(_guarded_match(prefix, extra_value=False, loop="continue" in prefix))) == 1


def test_deep_branch_comparison_does_not_recurse() -> None:
    operands = " + ".join(["item"] * 2000)
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b'], item):\n"
        f"    if value == 'a':\n        return {operands}\n    return 1\n"
    )
    assert [diagnostic.line for diagnostic in _check(source)] == [3]


def test_finite_dispatch_helpers_import_no_rule_modules() -> None:
    probe = (
        "import sys\nimport sarj_python_lint.rules._finite_literal_dispatch\n"
        "print(sorted(name for name in sys.modules if name.startswith('sarj_python_lint.rules.')"
        " and not name.rsplit('.', 1)[1].startswith('_')))"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        pytest.param(6, 1, id="supported-negation-depth"),
        pytest.param(8, 0, id="guard-depth-abstention"),
    ],
)
def test_guard_refinement_depth_is_bounded(depth: int, expected: int) -> None:
    condition = "not (" * depth + "value == 'a'" + ")" * depth
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b', 'c']):\n"
        f"    if {condition}:\n        return 1\n"
        "    match value:\n        case 'b':\n            return 2\n        case _:\n            return 3\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        pytest.param("value == 'a'", 0, id="unreachable-selected-arm"),
        pytest.param("value in ('a', 'b')", 1, id="reachable-selected-and-implicit-values"),
    ],
)
def test_prior_terminal_guard_refines_returning_partition(selector: str, expected: int) -> None:
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b', 'c']):\n"
        "    if value == 'a':\n        return 1\n"
        f"    if {selector}:\n        return 2\n    return 3\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("rejected = assert_never(value)", id="assignment"),
        pytest.param("str(assert_never(value))", id="nested-call"),
        pytest.param("if assert_never(value):\n    pass", id="if-test"),
    ],
)
def test_rejecting_prefix_precedes_suspension_inside_later_raise(prefix: str) -> None:
    assert _check(_finite_wildcard(prefix + "\nraise ValueError((yield 2))")) == []


@pytest.mark.parametrize(
    "operand",
    [
        pytest.param("assert_never(value)", id="direct-rejection"),
        pytest.param("str(assert_never(value))", id="nested-rejection"),
        pytest.param("(assert_never(value) if True else 0)", id="conditional-rejection"),
    ],
)
def test_yield_prefix_precedes_uncertain_suspension_inside_later_raise(operand: str) -> None:
    assert len(_check(_finite_wildcard(f"yield 2\nraise ValueError({operand}, (yield 3))"))) == 1


@pytest.mark.parametrize(
    ("decorator", "receiver"),
    [
        pytest.param("", "self, ", id="instance-method"),
        pytest.param("    @staticmethod\n", "", id="static-method"),
        pytest.param("    @classmethod\n", "cls, ", id="class-method"),
    ],
)
@pytest.mark.parametrize("productive", [False, True], ids=["global-rejection", "global-producer"])
def test_method_rejection_lookup_skips_class_namespace(decorator: str, receiver: str, *, productive: bool) -> None:
    imports = "from typing import Literal\n"
    binding = "    from typing import assert_never\n"
    if productive:
        imports += "def assert_never(value):\n    return 2\n"
    else:
        imports += "from typing import assert_never\n"
        binding = "    assert_never = None\n"
    source = (
        imports + "class Handler:\n" + binding + decorator + f"    def f({receiver}value: Literal['a', 'b']):\n"
        "        match value:\n            case 'a':\n                return 1\n"
        "            case _:\n                return assert_never(value)\n"
    )
    assert len(_check(source)) == int(productive)


@pytest.mark.parametrize("productive", [False, True], ids=["global-typing-module", "global-fake-module"])
def test_method_module_lookup_skips_class_namespace(*, productive: bool) -> None:
    imports = "from typing import Literal\n"
    if productive:
        imports += "class Namespace:\n    def assert_never(self, value):\n        return 2\nt = Namespace()\n"
        binding = "    import typing as t\n"
    else:
        imports += "import typing as t\n"
        binding = "    t = None\n"
    source = (
        imports + "class Handler:\n" + binding + "    def f(self, value: Literal['a', 'b']):\n        match value:\n"
        "            case 'a':\n                return 1\n            case _:\n                return t.assert_never(value)\n"
    )
    assert len(_check(source)) == int(productive)


_FORMAT_ALIAS = "from typing import Literal\nFormat = Literal['pcm', 'wav', 'mp3', 'flac']\n"
_FORMAT_PARTITION = (
    "def encode(value: Format):\n    if value in ('pcm', 'wav'):\n"
    "        return direct(value)\n    return compressed(value)\n"
)


class _PyrightDiagnostic(BaseModel):
    rule: str | None = None


class _PyrightReport(BaseModel):
    general_diagnostics: list[_PyrightDiagnostic] = Field(alias="generalDiagnostics")


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("return 2", id="return"),
        pytest.param("yield 2", id="yield"),
        pytest.param("yield 2\nraise ValueError()", id="yield-raise"),
    ],
)
@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("rejected = assert_never(value)", id="assignment"),
        pytest.param("rejected: object = assert_never(value)", id="annotated-assignment"),
        pytest.param("rejected = 0\nrejected += assert_never(value)", id="augmented-assignment"),
        pytest.param("def inner(argument=assert_never(value)):\n    return argument", id="function-default"),
        pytest.param(
            "async def inner(argument=assert_never(value)):\n    return argument", id="async-function-default"
        ),
        pytest.param("@assert_never(value)\ndef inner():\n    return 0", id="function-decorator"),
        pytest.param("str(assert_never(value))", id="wrapped-expression"),
        pytest.param("if assert_never(value):\n    pass", id="if-test"),
        pytest.param("if assert_never(value):\n    return 3", id="if-test-return"),
    ],
)
def test_rejecting_statement_prefix_precedes_later_publication(prefix: str, suffix: str) -> None:
    assert _check(_finite_wildcard(prefix + "\n" + suffix)) == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("if assert_never(value):\n    return 2", 0, id="rejecting-if-without-later-sink"),
        pytest.param("rejected = str(value)\nyield 2\nraise ValueError()", 1, id="ordinary-assignment"),
        pytest.param("if bool(value):\n    pass\nyield 2\nraise ValueError()", 1, id="ordinary-if-test"),
        pytest.param("yield 2\nstr(assert_never(value))", 1, id="publication-before-wrapped-rejection"),
        pytest.param(
            "yield 2\nstr(assert_never(value))\nraise ValueError()", 1, id="publication-before-rejection-and-raise"
        ),
        pytest.param("return 2\nstr(assert_never(value))", 1, id="return-before-unreachable-rejection"),
        pytest.param("yield 2\nrejected = assert_never(value)", 1, id="publication-before-assignment-rejection"),
        pytest.param("rejected = ((yield 2), assert_never(value))", 1, id="assignment-operand-publishes-first"),
        pytest.param("str(((yield 2), assert_never(value)))", 1, id="wrapped-expression-operand-publishes-first"),
        pytest.param("rejected: assert_never(value) = 0\nyield 2", 1, id="deferred-local-annotation"),
        pytest.param(
            "def inner(argument: assert_never(value)):\n    return argument\nyield 2",
            1,
            id="deferred-function-parameter-annotation",
        ),
        pytest.param(
            "def inner() -> assert_never(value):\n    return 0\nyield 2",
            1,
            id="deferred-function-return-annotation",
        ),
        pytest.param("type Result = assert_never(value)\nyield 2", 1, id="deferred-type-alias"),
    ],
)
def test_statement_prefix_proof_preserves_productive_and_deferred_paths(body: str, expected: int) -> None:
    assert len(_check(_finite_wildcard(body))) == expected


def test_assignment_to_a_shadowed_rejection_function_remains_productive() -> None:
    source = _finite_wildcard("rejected = assert_never(value)\nyield 2").replace(
        "def f(", "def assert_never(value):\n    return 0\ndef f("
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "alias",
    [
        _FORMAT_ALIAS,
        "from typing_extensions import Literal as Choice\nFormat = Choice['pcm', 'wav', 'mp3', 'flac']\n",
        "import typing as t\nFormat = t.Literal['pcm', 'wav', 'mp3', 'flac']\n",
        "from typing import Literal, TypeAlias\nFormat: TypeAlias = Literal['pcm', 'wav', 'mp3', 'flac']\n",
        "from typing import Literal\ntype Format = Literal['pcm', 'wav', 'mp3', 'flac']\n",
    ],
)
def test_finite_literal_partition_warns_without_autofix(alias: str) -> None:
    source = alias + _FORMAT_PARTITION
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity.value == "warning"
    assert "enumerate every value" in diagnostics[0].message
    assert fix_source(Path("app/formats.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == source


@pytest.mark.parametrize("explicit_else", [False, True], ids=["following-return", "explicit-else"])
@pytest.mark.parametrize("selector", ["value == 'a'", "value in ('a',)"], ids=["equality", "membership"])
def test_finite_partition_cannot_authorize_a_legacy_fix(selector: str, *, explicit_else: bool) -> None:
    source = (
        "from typing import Literal\nKind = Literal['a', 'b']\ndef outer():\n"
        f"    def _label(value: Kind):\n        if {selector}:\n            return 1\n"
        + ("        else:\n            return 2\n" if explicit_else else "        return 2\n")
        + "    return _label('a') + _label('b')\n"
    )
    findings = _check(source, "app/service.py")
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"
    assert fix_source(Path("app/service.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == source


def test_two_test_legacy_literal_ladder_keeps_safe_fix() -> None:
    source = (
        "def label():\n    def _label(value):\n        if value == 'one':\n            return 1\n"
        "        elif value == 'two':\n            return 2\n        else:\n            return 0\n"
        "    return _label('one')\n"
    )
    expected = (
        "def label():\n    def _label(value):\n        match value:\n            case 'one':\n                return 1\n"
        "            case 'two':\n                return 2\n            case _:\n                return 0\n"
        "    return _label('one')\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == expected


@pytest.mark.parametrize("location", ["match", "selected-if", "else-if"])
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        pytest.param("()", 0, id="empty-tuple"),
        pytest.param("[]", 0, id="empty-list"),
        pytest.param("{}", 0, id="empty-dict"),
        pytest.param("not [1]", 0, id="negated-nonempty-list"),
        pytest.param("-0", 0, id="negative-integer-zero"),
        pytest.param("+0", 0, id="positive-integer-zero"),
        pytest.param("-0.0", 0, id="negative-float-zero"),
        pytest.param("0 == 1", 0, id="false-constant-equality"),
        pytest.param("1 != 1", 0, id="false-constant-inequality"),
        pytest.param("'a' == b'a'", 0, id="different-primitive-equality"),
        pytest.param("0 == 0", 1, id="true-constant-equality"),
        pytest.param("1 != 0", 1, id="true-constant-inequality"),
        pytest.param("0 == False", 1, id="integer-boolean-equality"),
        pytest.param("ready == True", 1, id="dynamic-comparison-remains-productive"),
        pytest.param("ready", 1, id="productive-boolean"),
        pytest.param("True", 1, id="productive-true"),
        pytest.param("[1]", 1, id="productive-nonempty-list"),
        pytest.param("not [*items]", 1, id="unknown-list-expansion-can-be-empty"),
        pytest.param("not {**mapping}", 1, id="unknown-dict-expansion-can-be-empty"),
    ],
)
def test_finite_rejection_uses_literal_truth_without_losing_productive_controls(
    tmp_path: Path, location: str, expression: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    bodies = {
        "match": (
            "    match value:\n        case 'a':\n            return 1\n"
            f"        case _:\n            assert {expression}\n            return 2\n"
        ),
        "selected-if": f"    if value == 'a':\n        assert {expression}\n        return 1\n    return 2\n",
        "else-if": (
            f"    if value == 'a':\n        return 1\n    else:\n        assert {expression}\n        return 2\n"
        ),
    }
    source = (
        "from typing import Literal\nKind = Literal['a', 'b']\n"
        "def f(value: Kind, ready: bool, items: tuple[int, ...], mapping: dict[str, int]):\n" + bodies[location]
    )
    path = tmp_path / "dispatch.py"
    path.write_text(source)
    findings = analyze([PreferMatchValueDispatch.id, "prefer-match-assert-never"], [path], jobs=1)
    assert sum(finding.code == "SARJ439" for finding in findings) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("assert ()\n", 0, id="empty-assertion-without-suffix"),
        pytest.param("if []:\n    return 2\nraise ValueError()\n", 0, id="empty-condition"),
        pytest.param("if [1]:\n    return 2\nraise ValueError()\n", 1, id="nonempty-condition"),
        pytest.param("if 0 == 1:\n    return 2\nraise ValueError()\n", 0, id="false-comparison-condition"),
        pytest.param("if 0 == 0:\n    return 2\nraise ValueError()\n", 1, id="true-comparison-condition"),
        pytest.param(
            "if ready:\n    raise ValueError()\n    return 2\nraise TypeError()\n", 0, id="return-after-raise"
        ),
        pytest.param(
            "if ready:\n    assert_never(value)\n    return 2\nraise ValueError()\n",
            0,
            id="return-after-import-proven-rejection",
        ),
        pytest.param(
            "if ready:\n    if other:\n        raise ValueError()\n    else:\n        raise TypeError()\n"
            "    return 2\nraise RuntimeError()\n",
            0,
            id="return-after-both-nested-arms-reject",
        ),
        pytest.param(
            "if ready:\n    return 2\n    assert_never(value)\nraise ValueError()\n",
            1,
            id="return-before-import-proven-rejection",
        ),
        pytest.param(
            "if ready:\n    return 2\n    raise ValueError()\nraise TypeError()\n", 1, id="return-before-raise"
        ),
        pytest.param("if -1:\n    raise ValueError()\nelse:\n    return 2\n", 0, id="signed-true-condition"),
    ],
)
def test_only_reachable_returns_escape_finite_rejection(body: str, expected: int) -> None:
    source = (
        "from typing import Literal, assert_never\ndef f(value: Literal['a', 'b'], ready: bool, other: bool):\n"
        "    match value:\n        case 'a':\n            return 1\n        case _:\n"
        + "".join("            " + line + "\n" for line in body.splitlines())
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            _wildcard_case("raise ValueError([assert_never(value) for item in (0,)], (yield 2))\n"),
            0,
            id="eager-list-reject-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((yield 2), [assert_never(value) for item in (0,)])\n"),
            1,
            id="eager-list-yield-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError({assert_never(value) for item in (0,)}, (yield 2))\n"),
            0,
            id="eager-set-reject-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((yield 2), {assert_never(value) for item in (0,)})\n"),
            1,
            id="eager-set-yield-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError({item: assert_never(value) for item in (0,)}, (yield 2))\n"),
            0,
            id="eager-dict-reject-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((yield 2), {item: assert_never(value) for item in (0,)})\n"),
            1,
            id="eager-dict-yield-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((item for item in assert_never(value)), (yield 2))\n"),
            0,
            id="eager-generator-first-iterable-reject-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((yield 2), (item for item in assert_never(value)))\n"),
            1,
            id="eager-generator-first-iterable-yield-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((assert_never(value) for item in (0,)), (yield 2))\n"),
            1,
            id="deferred-generator-body",
        ),
        pytest.param(
            _wildcard_case("raise ValueError([assert_never(value) for item in ()], (yield 2))\n"),
            1,
            id="empty-comprehension",
        ),
        pytest.param(
            _wildcard_case("raise ValueError([assert_never(value) for item in (0,) if False], (yield 2))\n"),
            1,
            id="false-filter-comprehension",
        ),
        pytest.param(
            _wildcard_case("yield assert_never(value)\n"),
            0,
            id="yield-own-reject",
        ),
        pytest.param(
            _wildcard_case("yield assert_never(value)\nraise ValueError()\n"),
            0,
            id="yield-own-reject-sink",
        ),
        pytest.param(
            _wildcard_case("yield ((yield 2), assert_never(value))\nraise ValueError()\n"),
            1,
            id="yield-inner-publication-first",
        ),
        pytest.param(
            _wildcard_case("yield from assert_never(value)\n"),
            0,
            id="yield-from-own-reject",
        ),
        pytest.param(
            _wildcard_case("yield from assert_never(value)\nraise ValueError()\n"),
            0,
            id="yield-from-own-reject-sink",
        ),
        pytest.param(
            _wildcard_case("yield from ((yield 2), assert_never(value))\nraise ValueError()\n"),
            1,
            id="yield-from-inner-publication-first",
        ),
        pytest.param(
            _wildcard_case("if assert_never(value):\n    return 2\nraise ValueError()\n", first="return 1"),
            0,
            id="return-rejecting-if-test",
        ),
        pytest.param(
            _wildcard_case("if True:\n    return 2\nraise ValueError()\n", first="return 1"),
            1,
            id="return-true-if-test",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            '    if value == "a":\n'
            "        return 1\n"
            "    return str(assert_never(value))\n",
            0,
            id="return-nested-call-reject",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            '    if value == "a":\n'
            "        return 1\n"
            "    return str(value)\n",
            1,
            id="return-nested-call-productive",
        ),
        pytest.param(
            _wildcard_case("return (assert_never(value), 2)\nraise ValueError()\n", first="return 1"),
            0,
            id="return-tuple-reject",
        ),
        pytest.param(
            _wildcard_case("return (2, 3)\nraise ValueError()\n", first="return 1"),
            1,
            id="return-tuple-productive",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            "    for item in (0,):\n"
            "        match value:\n"
            '            case "a":\n'
            "                return 1\n"
            "            case _:\n"
            "                if assert_never(value):\n"
            "                    break\n"
            "                raise ValueError()\n"
            "    return 2\n",
            0,
            id="break-rejecting-if-test",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            "    for item in (0,):\n"
            "        match value:\n"
            '            case "a":\n'
            "                return 1\n"
            "            case _:\n"
            "                if True:\n"
            "                    break\n"
            "                raise ValueError()\n"
            "    return 2\n",
            1,
            id="break-true-if-test",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            "    for item in (0,):\n"
            "        match value:\n"
            '            case "a":\n'
            "                return 1\n"
            "            case _:\n"
            "                if assert_never(value):\n"
            "                    continue\n"
            "                raise ValueError()\n"
            "    return 2\n",
            0,
            id="continue-rejecting-if-test",
        ),
        pytest.param(
            "from typing import Literal, assert_never\n"
            "\n"
            'def f(value: Literal["a", "b"]):\n'
            "    for item in (0,):\n"
            "        match value:\n"
            '            case "a":\n'
            "                return 1\n"
            "            case _:\n"
            "                if True:\n"
            "                    continue\n"
            "                raise ValueError()\n"
            "    return 2\n",
            1,
            id="continue-true-if-test",
        ),
        pytest.param(
            _wildcard_case("str(assert_never(value))\nreturn 2\n", first="return 1"),
            0,
            id="prefix-nested-call-reject",
        ),
        pytest.param(
            _wildcard_case("str(value)\nreturn 2\n", first="return 1"),
            1,
            id="prefix-nested-call-productive",
        ),
        pytest.param(
            _wildcard_case("assert assert_never(value)\nreturn 2\n", first="return 1"),
            0,
            id="prefix-assert-call-reject",
        ),
        pytest.param(
            _wildcard_case("assert True\nreturn 2\n", first="return 1"),
            1,
            id="prefix-assert-true-productive",
        ),
    ],
)
def test_eager_rejection_precedes_observable_escape(source: str, expected: int) -> None:
    findings = _check(source)
    assert len(findings) == expected
    assert all(finding.severity.value == "warning" for finding in findings)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            _wildcard_case("raise ValueError((lambda: assert_never(value))(), (yield 2))\n"),
            0,
            id="lambda-called-reject-first",
        ),
        pytest.param(
            _wildcard_case("yield (lambda: assert_never(value))()\n"),
            0,
            id="lambda-own-value-reject",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((lambda: (yield assert_never(value)))(), (yield 2))\n"),
            1,
            id="lambda-generator-body-deferred",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((lambda ignored: assert_never(value))((yield 2)))\n"),
            1,
            id="lambda-call-argument-yield-first",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((lambda: 0)(), (yield 2))\n"),
            1,
            id="lambda-ordinary-call-productive",
        ),
        pytest.param(
            _wildcard_case("raise ValueError([item for item in (yield 2)])\n"),
            1,
            id="list-first-iterable-publishes",
        ),
        pytest.param(
            _wildcard_case("raise ValueError({item for item in (yield 2)})\n"),
            1,
            id="set-first-iterable-publishes",
        ),
        pytest.param(
            _wildcard_case("raise ValueError({item: item for item in (yield 2)})\n"),
            1,
            id="dict-first-iterable-publishes",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((item for item in (yield 2)))\n"),
            1,
            id="generator-first-iterable-publishes",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((lambda: (assert_never(value) if True else (yield 3)))(), (yield 2))\n"),
            1,
            id="invoked-lambda-with-unreachable-yield-is-generator",
        ),
        pytest.param(
            _wildcard_case("raise ValueError((item for assert_never in assert_never(value)), (yield 2))\n"),
            0,
            id="generator-first-iterable-uses-outer-assert-never",
        ),
    ],
)
def test_comprehension_and_lambda_execution_scope(source: str, expected: int) -> None:
    findings = _check(source)
    assert len(findings) == expected
    assert all(finding.severity.value == "warning" for finding in findings)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            "raise ValueError(assert_never(value), (yield 2))", 0, id="evaluation-order-positional-call-rejection-first"
        ),
        pytest.param(
            "raise ValueError((yield 2), assert_never(value))", 1, id="evaluation-order-positional-call-yield-first"
        ),
        pytest.param(
            "raise ValueError(str(assert_never(value)), (yield 2))",
            0,
            id="evaluation-order-nested-call-rejection-first",
        ),
        pytest.param(
            "raise ValueError((yield 2), str(assert_never(value)))", 1, id="evaluation-order-nested-call-yield-first"
        ),
        pytest.param(
            "raise ValueError(left=assert_never(value), right=(yield 2))",
            0,
            id="evaluation-order-keyword-call-rejection-first",
        ),
        pytest.param(
            "raise ValueError(left=(yield 2), right=assert_never(value))",
            1,
            id="evaluation-order-keyword-call-yield-first",
        ),
        pytest.param(
            "raise assert_never(value)((yield 2))", 0, id="evaluation-order-callee-before-arguments-rejection-first"
        ),
        pytest.param(
            "raise (yield 2)(assert_never(value))", 1, id="evaluation-order-callee-before-arguments-yield-first"
        ),
        pytest.param(
            "raise ValueError((assert_never(value), (yield 2)))", 0, id="evaluation-order-tuple-rejection-first"
        ),
        pytest.param("raise ValueError(((yield 2), assert_never(value)))", 1, id="evaluation-order-tuple-yield-first"),
        pytest.param(
            "raise ValueError([assert_never(value), (yield 2)])", 0, id="evaluation-order-list-rejection-first"
        ),
        pytest.param("raise ValueError([(yield 2), assert_never(value)])", 1, id="evaluation-order-list-yield-first"),
        pytest.param(
            "raise ValueError({assert_never(value): (yield 2)})", 0, id="evaluation-order-dict-rejection-first"
        ),
        pytest.param("raise ValueError({(yield 2): assert_never(value)})", 1, id="evaluation-order-dict-yield-first"),
        pytest.param(
            "raise ValueError(assert_never(value) + (yield 2))", 0, id="evaluation-order-binary-rejection-first"
        ),
        pytest.param("raise ValueError((yield 2) + assert_never(value))", 1, id="evaluation-order-binary-yield-first"),
        pytest.param(
            "raise ValueError(assert_never(value) == (yield 2))", 0, id="evaluation-order-comparison-rejection-first"
        ),
        pytest.param(
            "raise ValueError((yield 2) == assert_never(value))", 1, id="evaluation-order-comparison-yield-first"
        ),
        pytest.param(
            "raise ValueError(assert_never(value) or (yield 2))", 0, id="evaluation-order-boolean-rejection-first"
        ),
        pytest.param(
            "raise ValueError((yield 2) or assert_never(value))", 1, id="evaluation-order-boolean-yield-first"
        ),
        pytest.param(
            "raise ValueError((yield 2) if assert_never(value) else 0)",
            0,
            id="evaluation-order-conditional-test-rejection-first",
        ),
        pytest.param(
            "raise ValueError(assert_never(value) if (yield 2) else 0)",
            1,
            id="evaluation-order-conditional-test-yield-first",
        ),
        pytest.param(
            "raise ValueError(assert_never(value)[(yield 2)])", 0, id="evaluation-order-subscription-rejection-first"
        ),
        pytest.param(
            "raise ValueError((yield 2)[assert_never(value)])", 1, id="evaluation-order-subscription-yield-first"
        ),
        pytest.param("raise assert_never(value) from (yield 2)", 0, id="evaluation-order-raise-cause-rejection-first"),
        pytest.param("raise ValueError() from (yield 2)", 1, id="evaluation-order-raise-cause-yield-first"),
        pytest.param(
            "raise ValueError(lambda x=assert_never(value), y=(yield 2): x)",
            0,
            id="evaluation-order-lambda-defaults-rejection-first",
        ),
        pytest.param(
            "raise ValueError(lambda x=(yield 2), y=assert_never(value): x)",
            1,
            id="evaluation-order-lambda-defaults-yield-first",
        ),
        pytest.param(
            "raise ValueError(lambda x=assert_never(value), *, y=(yield 2): x)",
            0,
            id="evaluation-order-lambda-keyword-defaults-rejection-first",
        ),
        pytest.param(
            "raise ValueError(lambda x=(yield 2), *, y=assert_never(value): x)",
            1,
            id="evaluation-order-lambda-keyword-defaults-yield-first",
        ),
        pytest.param(
            "raise ValueError((lambda: assert_never(value)), (yield 2))",
            1,
            id="evaluation-order-unexecuted-lambda-body",
        ),
        pytest.param(
            "raise ValueError((False and assert_never(value)), (yield 2))",
            1,
            id="evaluation-order-short-circuited-prefix",
        ),
        pytest.param("yield 2\nraise ValueError()", 1, id="evaluation-order-known-productive-control"),
        pytest.param(
            "if assert_never(value):\n    yield 2\nraise ValueError()", 0, id="ancestor-order-if-test-rejection-first"
        ),
        pytest.param(
            "if (yield 2):\n    assert_never(value)\nraise ValueError()", 1, id="ancestor-order-if-test-yield-first"
        ),
        pytest.param(
            "try:\n    @assert_never(value)\n    def inner(argument=(yield 2)):\n        return argument\nfinally:\n    raise ValueError()",
            0,
            id="ancestor-order-function-decorator-rejection-first",
        ),
        pytest.param(
            "try:\n    @(lambda function: function)\n    def inner(argument=(yield 2)):\n        return argument\nfinally:\n    raise ValueError()",
            1,
            id="ancestor-order-function-decorator-yield-first",
        ),
        pytest.param(
            "target = {}\ntarget[(yield 2)] = assert_never(value)\nraise ValueError()",
            0,
            id="ancestor-order-assignment-rejection-first",
        ),
        pytest.param(
            "target = {}\ntarget[assert_never(value)] = (yield 2)\nraise ValueError()",
            1,
            id="ancestor-order-assignment-yield-first",
        ),
        pytest.param(
            "assert_never(value)[0] += (yield 2)\nraise ValueError()",
            0,
            id="ancestor-order-augmented-assignment-rejection-first",
        ),
        pytest.param(
            "target = [0]\ntarget[(yield 2)] += assert_never(value)\nraise ValueError()",
            1,
            id="ancestor-order-augmented-assignment-yield-first",
        ),
        pytest.param(
            "target = {}\ntarget[(yield 2)]: int = assert_never(value)\nraise ValueError()",
            0,
            id="ancestor-order-annotated-assignment-rejection-first",
        ),
        pytest.param(
            "target = {}\ntarget[assert_never(value)]: int = (yield 2)\nraise ValueError()",
            1,
            id="ancestor-order-annotated-assignment-yield-first",
        ),
        pytest.param("raise ValueError((yield 2))", 1, id="exception-value-yields"),
        pytest.param("raise ValueError() from (yield 2)", 1, id="exception-cause-yields"),
        pytest.param("raise ValueError((yield from (2,)))", 1, id="exception-value-delegates"),
        pytest.param("raise ValueError((yield from ()))", 0, id="empty-exception-delegate"),
        pytest.param("assert False, (yield 2)", 1, id="false-assert-message-yields"),
        pytest.param("assert False, (yield from ())", 0, id="empty-assert-message-delegate"),
        pytest.param("return assert_never((yield 2))", 1, id="rejection-argument-yields"),
        pytest.param("try:\n    yield 2\nfinally:\n    raise ValueError()", 1, id="yield-before-finalizer"),
        pytest.param("try:\n    yield from (2,)\nfinally:\n    raise ValueError()", 1, id="delegate-before-finalizer"),
        pytest.param(
            "if (yield 2):\n    raise ValueError()\nelse:\n    raise TypeError()", 1, id="rejecting-test-yields"
        ),
        pytest.param("yield 2\nraise ValueError()", 1, id="yield-before-separate-raise"),
        pytest.param("raise ValueError()\nyield 2", 0, id="yield-after-raise-unreachable"),
        pytest.param("def inner():\n    yield 2\nraise ValueError(inner())", 0, id="nested-generator-not-published"),
        pytest.param("try:\n    return 2\nfinally:\n    raise ValueError()", 0, id="return-overridden"),
        pytest.param("try:\n    yield from ()\nfinally:\n    raise ValueError()", 0, id="empty-protected-delegate"),
        pytest.param("assert True, (yield 2)\nraise ValueError()", 0, id="assert-message-unreachable"),
        pytest.param("raise ValueError() if True else (yield 2)", 0, id="conditional-yield-unreachable"),
        pytest.param("raise (yield 2) if True else ValueError()", 1, id="conditional-yield-reachable"),
        pytest.param("assert (yield 2) and False", 1, id="assert-test-yields"),
        pytest.param("assert False and (yield 2)", 0, id="short-circuited-yield"),
        pytest.param(
            "try:\n    pass\nexcept (yield 2):\n    pass\nfinally:\n    raise ValueError()",
            0,
            id="unentered-handler",
        ),
        pytest.param(
            "try:\n    raise ValueError()\nexcept TypeError:\n    pass\nelse:\n    yield 2\n"
            "finally:\n    raise RuntimeError()",
            0,
            id="unreachable-try-else",
        ),
        pytest.param(
            "try:\n    match 'x':\n        case 'y':\n            yield 2\nfinally:\n    raise ValueError()",
            0,
            id="unselected-nested-case",
        ),
        pytest.param(
            "try:\n    pass\nfinally:\n    yield 2\n    raise ValueError()", 1, id="finalizer-yields-before-rejecting"
        ),
    ],
)
def test_rejecting_sinks_preserve_only_reachable_generator_values(body: str, expected: int) -> None:
    source = (
        "from typing import Literal, assert_never\ndef f(value: Literal['a', 'b']):\n"
        "    match value:\n        case 'a':\n            yield 1\n        case _:\n"
        + "".join("            " + line + "\n" for line in body.splitlines())
    )
    findings = _check(source)
    assert len(findings) == expected
    for finding in findings:
        assert finding.severity.value == "warning"
        assert finding.line == 3
        assert finding.col == 5


def test_shadowed_rejection_call_keeps_a_reachable_productive_suffix() -> None:
    source = (
        "from typing import Literal\ndef assert_never(value):\n    return value\n"
        "def f(value: Literal['a', 'b'], ready: bool):\n    match value:\n"
        "        case 'a':\n            return 1\n        case _:\n"
        "            if ready:\n                assert_never(value)\n                return 2\n"
        "            raise ValueError()\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("depth", "expected"),
    [pytest.param(1, 1, id="shallow-productive-path"), pytest.param(9, 0, id="beyond-proof-bound-abstains")],
)
def test_escape_proof_preserves_the_existing_depth_bound(depth: int, expected: int) -> None:
    statements = [f"{'    ' * level}if ready:" for level in range(depth)]
    statements.append(f"{'    ' * depth}return 2")
    body = "\n".join(statements)
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b'], ready: bool):\n"
        "    match value:\n        case 'a':\n            return 1\n        case _:\n"
        + "".join("            " + line + "\n" for line in body.splitlines())
        + "            raise ValueError()\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("delegate", "expected"),
    [
        pytest.param("()", 0, id="empty-tuple"),
        pytest.param("[]", 0, id="empty-list"),
        pytest.param("{}", 0, id="empty-dict"),
        pytest.param("''", 0, id="empty-string"),
        pytest.param("b''", 0, id="empty-bytes"),
        pytest.param("(2,)", 1, id="nonempty-tuple"),
        pytest.param("items", 1, id="unknown-delegate-can-yield"),
    ],
)
def test_empty_yield_delegation_does_not_escape_rejection(delegate: str, expected: int) -> None:
    source = (
        "from typing import Literal\ndef f(value: Literal['a', 'b'], items: tuple[int, ...]):\n"
        "    match value:\n        case 'a':\n            yield 1\n        case _:\n"
        f"            yield from {delegate}\n            raise ValueError()\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("bindings", "expected"),
    [pytest.param(7, 1, id="last-supported-binding"), pytest.param(8, 0, id="first-abstaining-binding")],
)
def test_alias_binding_cutoff_is_explicit(bindings: int, expected: int) -> None:
    source = (
        "from typing import Literal\nA0 = Literal['a', 'b']\n"
        + "".join(f"A{index} = A{index - 1}\n" for index in range(1, bindings))
        + f"def f(value: A{bindings - 1}):\n    if value == 'a':\n        return 1\n    return 2\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("domain", "dispatch", "expected"),
    [
        pytest.param("1, 2, 3", "if value in (1, 2):\n    return 1\nreturn 2", 1, id="integer-membership"),
        pytest.param("-1, 0, 1", "if value == -1:\n    return 1\nreturn 2", 1, id="negative-integer-equality"),
        pytest.param("0, +1, 2", "if value == +1:\n    return 1\nreturn 2", 1, id="signed-positive-integer"),
        pytest.param(
            "1, 2",
            "match value:\n    case 1:\n        return 1\n    case _:\n        return 2",
            1,
            id="integer-wildcard",
        ),
        pytest.param(
            "-1, 0",
            "match value:\n    case -1:\n        return 1\n    case 0:\n        return 2",
            0,
            id="explicit-negative-cases",
        ),
        pytest.param("'a', 1", "if value == 1:\n    return 1\nreturn 2", 1, id="mixed-string-and-integer"),
        pytest.param("True, False", "if value == True:\n    return 1\nreturn 2", 0, id="boolean-domain-abstains"),
        pytest.param("1, True", "if value == 1:\n    return 1\nreturn 2", 0, id="boolean-integer-domain-collision"),
        pytest.param("1, 2", "if value == True:\n    return 1\nreturn 2", 0, id="boolean-selector-abstains"),
    ],
)
def test_integer_literal_partitions_keep_boolean_equality_ambiguity_outside_scope(
    domain: str, dispatch: str, expected: int
) -> None:
    source = f"from typing import Literal\ndef f(value: Literal[{domain}]):\n" + "".join(
        "    " + line + "\n" for line in dispatch.splitlines()
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize("local_shadow", [False, True], ids=["module-import", "local-shadow"])
def test_imported_relative_literal_alias_is_resolved_without_execution(tmp_path: Path, *, local_shadow: bool) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nrequires-python='>=3.10'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "formats.py").write_text(_FORMAT_ALIAS + "raise RuntimeError('must not execute')\n")
    source = "from .formats import Format\n" + _FORMAT_PARTITION
    if local_shadow:
        source = "Format = str\n" + _FORMAT_PARTITION.replace(
            "    if value", "    from .formats import Format\n    if value"
        )
    path = package / "encode.py"
    path.write_text(source)
    diagnostics = _check(source, str(path))
    assert len(diagnostics) == (0 if local_shadow else 1)
    assert all(diagnostic.code == "SARJ439" for diagnostic in diagnostics)


@pytest.mark.parametrize("local_alias", [False, True], ids=["imported-alias", "local-alias"])
def test_type_checking_import_resolves_and_conditional_local_alias_abstains(
    tmp_path: Path, *, local_alias: bool
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nrequires-python='>=3.10'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "formats.py").write_text(_FORMAT_ALIAS)
    declaration = (
        "    from typing import Literal\n    Format = Literal['pcm', 'wav', 'mp3', 'flac']\n"
        if local_alias
        else "    from .formats import Format\n"
    )
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n" + declaration + _FORMAT_PARTITION
    path = package / "encode.py"
    path.write_text(source)
    assert [diagnostic.code for diagnostic in _check(source, str(path))] == ([] if local_alias else ["SARJ439"])


@pytest.mark.parametrize(
    "partition",
    [
        pytest.param("if ready:\n    return 0\nelif value in ('pcm', 'wav'):\n    return 1\nreturn 2", id="elif"),
        pytest.param("if value not in ('mp3', 'flac'):\n    return 1\nreturn 2", id="negated-membership"),
        pytest.param("if value != 'pcm':\n    return 1\nreturn 2", id="inequality"),
        pytest.param("if 'pcm' == value:\n    return 1\nreturn 2", id="reversed"),
        pytest.param("if value == 'pcm' or value == 'wav':\n    return 1\nreturn 2", id="or-selector"),
    ],
)
def test_documented_partition_shapes_outside_scope_abstain(partition: str) -> None:
    source = (
        _FORMAT_ALIAS
        + "def encode(value: Format, ready: bool):\n"
        + "".join("    " + line + "\n" for line in partition.splitlines())
    )
    assert _check(source) == []


def test_terminal_sibling_literal_branches_are_not_partially_rewritten() -> None:
    source = (
        "from typing import Literal\ndef outer():\n    def _label(value: Literal['a', 'b', 'c', 'd']):\n"
        "        if value == 'a':\n            return 1\n        if value == 'b':\n            return 2\n"
        "        if value == 'c':\n            return 3\n        return 4\n"
        "    return _label('a') + _label('b') + _label('c') + _label('d')\n"
    )
    assert _check(source, "app/service.py")
    assert fix_source(Path("app/service.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == source


@pytest.mark.parametrize("provider", ["typing", "typing_extensions"], ids=["stdlib", "extensions"])
@pytest.mark.parametrize("imported_alias", [False, True], ids=["direct", "first-party-alias"])
def test_project_local_literal_providers_abstain_without_execution(
    tmp_path: Path, provider: str, *, imported_alias: bool
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    (tmp_path / f"{provider}.py").write_text(
        "class Literal:\n    @classmethod\n    def __class_getitem__(cls, items):\n        return str\n"
        "raise RuntimeError('provider must not execute')\n"
    )
    alias = _FORMAT_ALIAS.replace("from typing import Literal", f"from {provider} import Literal")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "formats.py").write_text(alias)
    source = ("from .formats import Format\n" if imported_alias else alias) + _FORMAT_PARTITION
    path = package / "encode.py"
    path.write_text(source)
    assert analyze([PreferMatchValueDispatch.id], [path]) == []


def test_project_local_assert_never_is_not_a_rejecting_sink(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    (tmp_path / "typing_extensions.py").write_text(
        "def assert_never(value):\n    return 2\nraise RuntimeError('provider must not execute')\n"
    )
    source = (
        "from typing_extensions import assert_never\n"
        + _FORMAT_ALIAS
        + "def encode(value: Format):\n    match value:\n        case 'pcm' | 'wav':\n"
        "            return direct(value)\n        case _:\n            return assert_never(value)\n"
    )
    path = tmp_path / "encode.py"
    path.write_text(source)
    findings = analyze([PreferMatchValueDispatch.id], [path])
    assert [(finding.code, finding.severity.value) for finding in findings] == [("SARJ439", "warning")]


@pytest.mark.parametrize(
    "body",
    [
        _FORMAT_PARTITION.replace("compressed(value)", "assert_never(value)"),
        (
            "def encode(value: Format):\n    if value in ('pcm', 'wav'):\n        return direct(value)\n"
            "    else:\n        logger.warning('unsupported')\n        return assert_never(value)\n"
        ),
        _FORMAT_PARTITION.replace("direct(value)", "assert_never(value)"),
    ],
    ids=["following-rejection", "else-logging-rejection", "selected-arm-rejection"],
)
def test_rejecting_if_partitions_remain_owned_by_typechecking(body: str) -> None:
    assert _check("from typing import assert_never\n" + _FORMAT_ALIAS + body) == []


@pytest.mark.parametrize("branch", ["body", "else"], ids=["conditional-body", "conditional-else"])
def test_nested_conditional_partition_retains_lexical_parameter(branch: str) -> None:
    partition = "\n".join("    " + line for line in _FORMAT_PARTITION.splitlines()[1:]) + "\n"
    prefix = "def encode(value: Format, ready):\n    if ready:\n"
    if branch == "else":
        prefix += "        return None\n    else:\n"
    findings = _check(_FORMAT_ALIAS + prefix + partition)
    assert [(finding.code, finding.severity.value) for finding in findings] == [("SARJ439", "warning")]


def test_source_owner_budget_abstains_after_seven_imported_domains(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    pieces: list[str] = []
    for index in range(8):
        (package / f"formats_{index}.py").write_text(_FORMAT_ALIAS)
        pieces.append(
            f"from .formats_{index} import Format as Format{index}\n"
            + _FORMAT_PARTITION.replace("encode(", f"encode_{index}(").replace(": Format", f": Format{index}")
        )
    source = "\n".join(pieces)
    path = package / "encode.py"
    path.write_text(source)
    findings = analyze([PreferMatchValueDispatch.id], [path])
    expected_lines = [index for index, line in enumerate(source.splitlines(), start=1) if "if value in" in line]
    assert [finding.line for finding in findings] == expected_lines[:7]


@pytest.mark.parametrize(
    "source",
    [
        _FORMAT_PARTITION.replace(": Format", ": str"),
        _FORMAT_PARTITION.replace(": Format", ""),
        "from external import Format\n" + _FORMAT_PARTITION,
        "from external import Literal\nFormat = Literal['pcm', 'wav', 'mp3', 'flac']\n" + _FORMAT_PARTITION,
        _FORMAT_ALIAS + "Format = str\n" + _FORMAT_PARTITION,
        _FORMAT_ALIAS + _FORMAT_PARTITION.replace("    if value", "    value = 'pcm'\n    if value"),
        _FORMAT_ALIAS
        + _FORMAT_PARTITION.replace("if value in ('pcm', 'wav'):", "if value in ('pcm', 'wav') and ready:"),
        _FORMAT_ALIAS + _FORMAT_PARTITION.replace("('pcm', 'wav')", "supported_formats"),
        _FORMAT_ALIAS + _FORMAT_PARTITION.replace("compressed(value)", "direct(value)"),
        _FORMAT_ALIAS + _FORMAT_PARTITION.replace("def encode(value: Format):", "def encode[Format](value: Format):"),
        _FORMAT_ALIAS + _FORMAT_PARTITION.replace(": Format", ": Format | str"),
        "from typing import Literal\nFormat = str\n"
        + _FORMAT_PARTITION.replace(
            "    if value", "    type Format = Literal['pcm', 'wav', 'mp3', 'flac']\n    if value"
        ),
        "from external import Literal\n"
        + _FORMAT_PARTITION.replace(": Format", ": Literal['pcm', 'wav', 'mp3', 'flac']").replace(
            "    if value", "    from typing import Literal\n    if value"
        ),
        "# @generated\n" + _FORMAT_ALIAS + _FORMAT_PARTITION,
        "def broken(:\n",
    ],
    ids=[
        "open-string",
        "untyped",
        "external-alias",
        "external-literal-provider",
        "rebound-alias",
        "rebound-subject",
        "guarded-membership",
        "dynamic-membership",
        "identical-branches",
        "shadowing-type-parameter",
        "open-union",
        "local-type-alias-shadow",
        "local-literal-provider-shadow",
        "generated-source",
        "malformed-source",
    ],
)
def test_unproven_or_non_dispatch_partitions_abstain(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            return compressed(value)",
            1,
            id="productive-wildcard-hides-values",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case 'mp3' | 'flac':\n            return compressed(value)",
            0,
            id="every-value-explicit",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            assert_never(value)",
            0,
            id="assert-never-wildcard",
        ),
        pytest.param(
            "case str():\n            return direct(value)\n        case _:\n            return compressed(value)",
            0,
            id="class-pattern-abstains",
        ),
        pytest.param("case _:\n            return direct(value)", 0, id="wildcard-only"),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            logger.warning('unsupported')\n            assert_never(value)",
            0,
            id="logging-before-assert-never",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            logger.warning('unsupported')\n            return assert_never(value)",
            0,
            id="return-assert-never-with-logging",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            assert_never(value)\n            logger.warning('unreachable')",
            0,
            id="assert-never-before-unreachable-suffix",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if ready:\n                return compressed(value)\n            assert_never(value)",
            1,
            id="productive-return-before-assert-never",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _ as remainder:\n"
            "            return compressed(remainder)",
            1,
            id="captured-wildcard-remains-productive",
        ),
        pytest.param(
            "case ('pcm' | 'wav') as selected:\n            return direct(selected)\n        case _:\n"
            "            return compressed(value)",
            1,
            id="captured-literal-cases-retain-known-values",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if ready:\n                raise ValueError('unsupported')\n"
            "            else:\n                raise TypeError('unsupported')",
            0,
            id="both-conditional-arms-reject",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            assert False",
            0,
            id="literal-false-assertion-rejects",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            assert False\n            return compressed(value)",
            0,
            id="literal-false-assertion-precedes-unreachable-return",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            assert True\n            return compressed(value)",
            1,
            id="nonrejecting-assertion-preserves-productive-return",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if ready:\n                raise ValueError('unsupported')\n"
            "            else:\n                return compressed(value)",
            1,
            id="conditional-productive-alternative",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            try:\n                return compressed(value)\n"
            "            finally:\n                raise ValueError('unsupported')",
            0,
            id="finally-rejection-overrides-return",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            try:\n                raise ValueError('unsupported')\n"
            "            finally:\n                return compressed(value)",
            1,
            id="finally-productive-return-overrides-rejection",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            class Rejected:\n                raise ValueError('unsupported')",
            0,
            id="uncertain-class-body-abstains",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if False:\n                return compressed(value)\n"
            "            raise ValueError('unsupported')",
            0,
            id="unreachable-return-does-not-escape-rejection",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if True:\n                raise ValueError('unsupported')\n"
            "            else:\n                return compressed(value)",
            0,
            id="unreachable-alternative-does-not-imply-productivity",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            if True:\n                return compressed(value)\n"
            "            else:\n                raise ValueError('unsupported')",
            1,
            id="reachable-productive-arm-is-preserved",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n"
            "            try:\n                return compressed(value)\n"
            "            finally:\n                class Rejected:\n                    raise ValueError('unsupported')\n"
            "            raise TypeError('unsupported')",
            0,
            id="unclassified-finalizer-does-not-prove-escape",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            raise ValueError('unsupported')",
            0,
            id="raising-wildcard-rejects",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            logger.warning('unsupported')\n            raise ValueError('unsupported')",
            0,
            id="logging-prefix-before-raise-rejects",
        ),
        pytest.param(
            "case 'pcm' | 'wav':\n            return direct(value)\n        case _:\n            if ready:\n                return compressed(value)\n            raise ValueError('unsupported')",
            1,
            id="conditional-productive-wildcard-warns",
        ),
    ],
)
def test_finite_match_must_not_hide_known_values_in_wildcard(body: str, expected: int) -> None:
    source = (
        "from typing import assert_never\n"
        + _FORMAT_ALIAS
        + "def encode(value: Format):\n    match value:\n        "
        + body
        + "\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize("control", ["break", "continue"])
@pytest.mark.parametrize("local_loop", [False, True], ids=["outer-loop", "local-loop"])
def test_catchall_loop_control_distinguishes_rejection_from_escape(control: str, *, local_loop: bool) -> None:
    catchall = (
        f"            for item in range(2):\n                if item:\n                    {control}\n"
        if local_loop
        else f"            if ready:\n                {control}\n"
    )
    source = (
        _FORMAT_ALIAS + "def encode(value: Format):\n    for attempt in range(2):\n        match value:\n"
        "            case 'pcm' | 'wav':\n                return direct(value)\n            case _:\n"
        + "\n".join("    " + line for line in catchall.splitlines())
        + "\n                raise ValueError('unsupported')\n"
    )
    assert len(_check(source)) == (0 if local_loop else 1)


def test_finite_partition_respects_exact_suppression_and_old_python(tmp_path: Path) -> None:
    suppressed = _FORMAT_ALIAS + _FORMAT_PARTITION.replace(
        "if value in ('pcm', 'wav'):", "if value in ('pcm', 'wav'):  # sarj-noqa: SARJ439 -- retained protocol dispatch"
    )
    assert _check(suppressed) == []
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.9'\n")
    source = _FORMAT_ALIAS + _FORMAT_PARTITION
    path = tmp_path / "encode.py"
    path.write_text(source)
    assert _check(source, str(path)) == []


def test_typed_equality_ladder_keeps_one_existing_blocking_diagnostic(tmp_path: Path) -> None:
    source = (
        "from typing import Literal\nFormat = Literal['a', 'b', 'c']\n"
        "def encode(value: Format):\n    if value == 'a':\n        return 1\n"
        "    elif value == 'b':\n        return 2\n    else:\n        return 3\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    path = tmp_path / "example.py"
    path.write_text(source)
    findings = analyze(["prefer-match-value-dispatch", "prefer-match-assert-never"], [path])
    assert [(finding.line, finding.code, finding.severity.value) for finding in findings] == [(4, "SARJ439", "error")]


@pytest.mark.parametrize("suppressed", [False, True], ids=["one-owner", "exact-owner-suppression"])
def test_typed_terminal_siblings_keep_one_dispatch_owner(tmp_path: Path, *, suppressed: bool) -> None:
    source = (
        "from typing import Literal\nFormat = Literal['a', 'b', 'c', 'd']\n"
        "def encode(value: Format):\n    if value == 'a':\n        return 1\n"
        "    if value == 'b':\n        return 2\n    if value == 'c':\n        return 3\n    return 4\n"
    )
    if suppressed:
        source = source.replace(
            "if value == 'a':", "if value == 'a':  # sarj-noqa: SARJ439 -- reviewed terminal dispatch"
        )
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python='>=3.10'\n")
    path = tmp_path / "example.py"
    path.write_text(source)
    findings = analyze([PreferMatchValueDispatch.id, "prefer-match-assert-never"], [path])
    assert [(finding.line, finding.code, finding.severity.value) for finding in findings] == (
        [] if suppressed else [(4, "SARJ439", "warning")]
    )


@pytest.mark.parametrize(
    ("use_match", "add_format"),
    [(False, False), (False, True), (True, False), (True, True)],
    ids=["if-original", "if-new-format", "match-original", "match-new-format"],
)
def test_upstream_exhaustiveness_detects_new_format_only_after_explicit_match(
    tmp_path: Path, *, use_match: bool, add_format: bool
) -> None:
    formats = "'pcm', 'wav', 'mp3', 'flac'" + (", 'ogg'" if add_format else "")
    source = f"from typing import Literal\nFormat = Literal[{formats}]\ndef encode(value: Format) -> int:\n"
    source += (
        "    match value:\n        case 'pcm' | 'wav':\n            return 1\n        case 'mp3' | 'flac':\n            return 2\n"
        if use_match
        else "    if value in ('pcm', 'wav'):\n        return 1\n    return 2\n"
    )
    path = tmp_path / "example.py"
    path.write_text(source)
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "typeCheckingMode": "basic",
                "reportMatchNotExhaustive": "error",
                "pythonVersion": "3.11",
            }
        )
    )
    completed = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--outputjson", str(path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    diagnostics = _PyrightReport.model_validate_json(completed.stdout).general_diagnostics
    missing_case = any(item.rule == "reportMatchNotExhaustive" for item in diagnostics)
    assert missing_case is (use_match and add_format)
    assert completed.returncode == (1 if use_match and add_format else 0), completed.stdout + completed.stderr


_EXAMPLES = PreferMatchValueDispatch.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_documentation_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


def test_two_tests_and_fallback_are_a_warning() -> None:
    diagnostics = _check(_ladder())
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ439"
    assert diagnostics[0].severity.value == "warning"
    assert diagnostics[0].line == 1
    assert diagnostics[0].col == 1
    assert "attribute evaluation" in diagnostics[0].message


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("path.name == 'a'", "path.name == 'b'"),
        ("request.path.name == 'a'", "request.path.name == 'b'"),
        ("value == -1", "value == +2"),
        ("value == b'a'", "value == b'b'"),
        ("value == 1.5", "value == 2.5"),
    ],
)
def test_supported_values_and_subjects(first: str, second: str) -> None:
    assert len(_check(_ladder(first, second))) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("value == 'a'", "value == 'a'"),
        ("value == 1", "value == 1.0"),
        ("value == -0", "value == 0"),
        ("value == True", "value == False"),
        ("value == -True", "value == 1"),
        ("value == None", "value == 'b'"),
        ("get_value() == 'a'", "get_value() == 'b'"),
        ("get_value().name == 'a'", "get_value().name == 'b'"),
        ("value[0] == 'a'", "value[0] == 'b'"),
        ("value == 'a'", "other == 'b'"),
        ("value == 'a'", "'b' == value"),
        ("'a' == value", "'b' == value"),
        ("value != 'a'", "value == 'b'"),
        ("value is None", "value == 'b'"),
        ("value == 'a' and ready", "value == 'b'"),
        ("value == 'a'", "value == make_case()"),
        ("value == 'a'", "value == UNKNOWN"),
        ("value == 'a'", "value == constants.B"),
        ("value == 'a' == other", "value == 'b'"),
    ],
)
def test_unsafe_or_unrelated_tests_are_excluded(first: str, second: str) -> None:
    assert _check(_ladder(first, second)) == []


def test_resolves_literal_module_constants() -> None:
    assert len(_check("FIRST: str = 'a'\nSECOND = 'b'\n" + _ladder("value == FIRST", "value == SECOND"))) == 1


@pytest.mark.parametrize(
    "binding",
    [
        "FIRST = 'c'",
        "FIRST += 'c'",
        "del FIRST",
        "import FIRST",
        "from other import FIRST",
        "from other import *",
        "def other(FIRST): pass",
        "def other[FIRST](): pass",
        "def FIRST(): pass",
        "class FIRST: pass",
        "for FIRST in items: pass",
        "with context() as FIRST: pass",
        "if ready: FIRST = 'c'",
        "if (FIRST := 'c'): pass",
        "def other():\n    global FIRST",
        "try:\n    run()\nexcept Error as FIRST:\n    pass",
        "match data:\n    case FIRST:\n        pass",
        "match data:\n    case [*FIRST]:\n        pass",
        "match data:\n    case {'a': entry, **FIRST}:\n        pass",
    ],
)
def test_ambiguous_constant_bindings_are_excluded(binding: str) -> None:
    source = "FIRST = 'a'\nSECOND = 'b'\n" + binding + "\n" + _ladder("value == FIRST", "value == SECOND")
    assert _check(source) == []


def test_duplicate_named_values_are_excluded() -> None:
    assert _check("FIRST = 'a'\nSECOND = 'a'\n" + _ladder("value == FIRST", "value == SECOND")) == []


def test_identical_bodies_defer_to_ruff_sim114() -> None:
    assert _check(_ladder().replace("result = second()", "result = first()")) == []


def test_annotated_path_sample_is_advisory() -> None:
    source = """
from pathlib import Path
_ESLINT_SUPPRESSIONS = 'eslint.json'
_RATCHET_SUPPRESSIONS = 'ratchet.json'
def migrate(path: Path, original, eslint, codes):
    if path.name == _ESLINT_SUPPRESSIONS:
        migrated = _rewrite_eslint_suppressions(original, eslint)
    elif path.name == _RATCHET_SUPPRESSIONS:
        migrated = _rewrite_ratchet_suppressions(original, codes)
    else:
        migrated = _rewrite(path, original, eslint, codes)
    return migrated
"""
    assert len(_check(source)) == 1


def test_missing_fallback_is_excluded() -> None:
    assert _check("if value == 'a':\n    first()\nelif value == 'b':\n    second()\n") == []


def test_single_test_is_excluded() -> None:
    assert _check("if value == 'a':\n    first()\nelse:\n    fallback()\n") == []


def test_else_nested_if_is_not_elif() -> None:
    assert (
        _check(
            "if value == 'a':\n    first()\nelse:\n    if value == 'b':\n        second()\n    else:\n        fallback()\n"
        )
        == []
    )


def test_reports_maximal_chain_once() -> None:
    source = _ladder().replace("else:\n", "elif value == 'c':\n    third()\nelse:\n")
    assert len(_check(source)) == 1


def test_does_not_report_eligible_suffix_of_mixed_chain() -> None:
    source = "if ready:\n    prepare()\nel" + _ladder()
    assert _check(source) == []


def test_multiline_test_is_supported() -> None:
    assert len(_check(_ladder().replace("elif value == 'b':", "elif (\n    value == 'b'\n):"))) == 1


@pytest.mark.parametrize("source", ["if:", "# Generated file; do not edit\n" + _ladder()])
def test_invalid_and_generated_sources_are_excluded(source: str) -> None:
    assert _check(source) == []


def _siblings(first: str = "suffix in {'.yaml', '.yml'}", last: str = "suffix == '.jsonc' and valid") -> str:
    return (
        f"def parse(suffix, valid):\n    if {first}:\n        return 1\n"
        f"    if suffix == '.toml':\n        return 2\n    if {last}:\n        return 3\n    return None\n"
    )


@pytest.mark.parametrize("container", ["{'.yaml', '.yml'}", "('.yaml', '.yml')", "['.yaml', '.yml']"])
def test_grouped_terminal_dispatch(container: str) -> None:
    assert len(_check(_siblings(f"suffix in {container}"))) == 1


def test_grouped_ladder_dispatch() -> None:
    source = (
        _siblings()
        .replace("    if suffix ==", "    elif suffix ==")
        .replace("    return None", "    else:\n        return None")
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "first",
    [
        "suffix in ()",
        "suffix in ('.yaml',)",
        "suffix in OPTIONS",
        "suffix in (*OPTIONS, '.yml')",
        "suffix in {True, None}",
        "suffix in {'.yaml', '.toml'}",
        "suffix in {'.yaml', '.yaml'}",
        "suffix == '.yaml' or suffix == '.yml'",
        "other in {'.yaml', '.yml'}",
        "suffix in ('a', 'b', 'c', 'd', 'e', 'f', 'g')",
        "ready and suffix == '.yaml'",
    ],
)
def test_grouped_dispatch_near_misses(first: str) -> None:
    assert _check(_siblings(first)) == []


@pytest.mark.parametrize(
    "last", ["valid and suffix == '.jsonc'", "suffix == '.jsonc' or valid", "suffix == '.jsonc' and (valid := check())"]
)
def test_unsafe_final_guards(last: str) -> None:
    assert _check(_siblings(last=last)) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("return 1", "run()"),
        ("return 2", "return 1"),
        ("    return None\n", ""),
        ("    if suffix == '.toml':", "    suffix = update()\n    if suffix == '.toml':"),
        ("suffix", "path.suffix"),
    ],
)
def test_terminal_dispatch_boundaries(old: str, new: str) -> None:
    assert _check(_siblings().replace(old, new)) == []


def test_mixed_predicates_with_identical_returns_are_not_dispatch() -> None:
    assert (
        _check(
            "def stop(stripped, suffix, line, indent):\n    if not stripped or (suffix in {'.yaml', '.yml'} and stripped in {'---', '...'}):\n        return True\n    if suffix == '.toml' and valid(stripped):\n        return True\n    if comment(line) is None and len(line) < indent:\n        return True\n    return False\n"
        )
        == []
    )


def test_terminal_dispatch_keeps_try_except_body() -> None:
    source = _siblings().replace(
        "        return 1",
        "        try:\n            validate()\n        except ValueError:\n            return None\n        return 1",
    )
    assert len(_check(source)) == 1


def test_mixed_sibling_sequence_has_no_eligible_suffix() -> None:
    assert _check(_siblings().replace("    if suffix in", "    if ready:\n        return 0\n    if suffix in")) == []


def test_membership_and_pattern_matching_are_not_safe_automatic_rewrites() -> None:
    class UnhashableEqual(str):  # ruff: ignore[subclass-builtin] - Exercise native str hash/equality overrides.
        __slots__ = ()

        def __hash__(self) -> int:
            raise TypeError

        def __eq__(self, other: object) -> bool:
            return other == ".yaml"

    def make_value() -> str:
        return UnhashableEqual()

    value = make_value()
    with pytest.raises(TypeError):
        assert value in {".yaml", ".yml"}
    match value:
        case ".yaml" | ".yml":
            matched = True
        case _:
            matched = False
    assert matched


def test_set_membership_invokes_hash_but_literal_pattern_does_not() -> None:
    calls: list[str] = []

    class HashObserved(str):  # ruff: ignore[subclass-builtin] - Exercise native str hash/equality overrides.
        __slots__ = ()

        def __hash__(self) -> int:
            calls.append("hash")
            return hash(".yaml")

        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            return other == ".yaml"

    def make_value() -> str:
        return HashObserved()

    value = make_value()
    assert value in {".yaml", ".yml"}
    assert "hash" in calls
    calls.clear()
    match value:
        case ".yaml" | ".yml":
            matched = True
        case _:
            matched = False
    assert matched
    assert calls == ["eq"]


def test_two_separate_terminal_sequences_have_one_finding_each() -> None:
    assert len(_check(_siblings() + _siblings().replace("def parse", "def other"))) == 2


def test_expanded_mixed_ladder_has_no_eligible_suffix() -> None:
    source = (
        _siblings()
        .replace("    if suffix ==", "    elif suffix ==")
        .replace("    return None", "    else:\n        return None")
    )
    source = source.replace("    if suffix in", "    if ready:\n        return 0\n    elif suffix in")
    assert _check(source) == []


def test_exact_parser_dispatch_shape() -> None:
    source = """
def literal_lines(path, source, lines):
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            list(yaml.compose_all(source))
        except yaml.YAMLError:
            return None
        return _config_literal_lines(path, lines)
    if suffix == ".toml":
        try:
            tomllib.loads(source)
        except tomllib.TOMLDecodeError:
            return None
        return _config_literal_lines(path, lines)
    if suffix == ".jsonc" and _structured_config_document(suffix, source) is not None:
        return set()
    return None
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_terminal_raise_dispatch() -> None:
    assert (
        len(_check(_siblings().replace("return 1", "raise FirstError").replace("return None", "raise Unsupported")))
        == 1
    )


def test_two_terminal_siblings_remain_below_expansion_threshold() -> None:
    assert (
        _check(
            "def parse(value):\n    if value == 'a':\n        return 1\n    if value == 'b':\n        return 2\n    return None\n"
        )
        == []
    )


def test_warning_rule_fixes_only_proven_parameter_dispatch() -> None:
    assert PreferMatchValueDispatch.documentation is not None
    assert PreferMatchValueDispatch.documentation.autofix.value == "safe"
    source = _siblings()
    assert fix_source(Path("app/dispatch.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == source


def test_with_suppressed_raise_is_not_a_terminal_branch() -> None:
    source = _siblings().replace("        return 1", "        with suppress(Exception):\n            raise FirstError")
    assert _check(source) == []


def test_three_plain_equality_terminal_siblings_are_supported() -> None:
    assert len(_check(_siblings("suffix == '.yaml'", "suffix == '.jsonc'"))) == 1


def test_numeric_module_constant_overlap_is_excluded_in_siblings() -> None:
    source = "FIRST = 1\nSECOND = 1.0\n" + _siblings("suffix == FIRST", "suffix == SECOND")
    assert _check(source) == []


_QUALIFIED_SIBLINGS = (
    "from provider import ErrorId\n"
    "def classify(error_id):\n"
    "    if error_id == ErrorId.INSUFFICIENT:\n        return insufficient()\n"
    "    if error_id == ErrorId.INVALID_OPTION:\n        return invalid_option()\n"
    "    return rejected()\n"
)


@pytest.mark.parametrize(
    "source",
    [
        _QUALIFIED_SIBLINGS,
        _QUALIFIED_SIBLINGS.replace(
            "    if error_id == ErrorId.INVALID", "    elif error_id == ErrorId.INVALID"
        ).replace("    return rejected()", "    else:\n        return rejected()"),
        _QUALIFIED_SIBLINGS.replace("from provider import ErrorId", "import provider").replace(
            "ErrorId.", "provider.ErrorId."
        ),
        _QUALIFIED_SIBLINGS.replace("from provider import ErrorId", "from provider import ErrorId as Codes").replace(
            "ErrorId.", "Codes."
        ),
        _QUALIFIED_SIBLINGS.replace(
            "from provider import ErrorId",
            "from enum import StrEnum\nclass ErrorId(StrEnum):\n    INSUFFICIENT = 'insufficient'\n    INVALID_OPTION = 'invalid'",
        ),
        _QUALIFIED_SIBLINGS.replace("return insufficient()", "raise Insufficient").replace(
            "return rejected()", "raise Rejected"
        ),
        _QUALIFIED_SIBLINGS.replace("def classify(error_id):", "def classify(error):\n    error_id = error.code"),
        _QUALIFIED_SIBLINGS.replace("def classify", "async def classify"),
        _QUALIFIED_SIBLINGS.replace("    if error_id", "    if (error_id", 1).replace(
            "ErrorId.INSUFFICIENT:", "ErrorId.INSUFFICIENT):"
        ),
    ],
)
def test_terminal_qualified_values_share_one_dispatch_subject(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ439"
    assert "'error_id'" in findings[0].message
    assert fix_source(Path("app/dispatch.py"), source, rule_ids=[PreferMatchValueDispatch.id]) == source


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("ErrorId.INVALID_OPTION", "ErrorId.INSUFFICIENT"),
        ("error_id == ErrorId.INVALID_OPTION", "other == ErrorId.INVALID_OPTION"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id == OtherId.INVALID_OPTION"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id != ErrorId.INVALID_OPTION"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id is ErrorId.INVALID_OPTION"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id == ErrorId.INVALID_OPTION and allowed"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id == ErrorId.INVALID_OPTION()"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id == INVALID_OPTION"),
        ("error_id == ErrorId.INVALID_OPTION", "error_id == 'invalid'"),
        ("return insufficient()", "insufficient()"),
        ("return invalid_option()", "return insufficient()"),
        ("    return rejected()\n", ""),
        ("    if error_id == ErrorId.INVALID_OPTION:", "    checkpoint()\n    if error_id == ErrorId.INVALID_OPTION:"),
        ("error_id ==", "error.code =="),
        ("from provider import ErrorId", "from custom import *"),
        ("from provider import ErrorId", "ErrorId = make_codes()"),
        ("from provider import ErrorId", "from provider import ErrorId\nErrorId = other"),
        ("from provider import ErrorId", "from provider import ErrorId\nErrorId.INSUFFICIENT = replacement"),
        ("def classify(error_id):", "def classify(error_id, ErrorId):"),
        ("from provider import ErrorId", "class ErrorId:\n    INSUFFICIENT = 1\n    INVALID_OPTION = 2"),
    ],
)
def test_qualified_terminal_dispatch_near_misses(old: str, new: str) -> None:
    assert _check(_QUALIFIED_SIBLINGS.replace(old, new)) == []


@pytest.mark.parametrize(("minimum", "expected"), [("3.14", "error"), ("3.10", "error"), ("3.9", None)])
def test_qualified_terminal_dispatch_respects_target_and_blocks(
    tmp_path: Path, minimum: str, expected: str | None
) -> None:
    (tmp_path / "pyproject.toml").write_text(f"[project]\nrequires-python = '>={minimum}'\n")
    path = tmp_path / "dispatch.py"
    path.write_text(_QUALIFIED_SIBLINGS)
    findings = PreferMatchValueDispatch().check(path, _QUALIFIED_SIBLINGS)
    assert [finding.severity.value for finding in findings] == ([expected] if expected else [])


@pytest.mark.parametrize(
    "source",
    [
        _QUALIFIED_SIBLINGS.replace(
            "def classify(error_id):", "def classify(error_id):\n    error_id = normalize(error_id)"
        ),
        _QUALIFIED_SIBLINGS.replace("def classify(error_id):", "def classify():\n    global error_id"),
        _QUALIFIED_SIBLINGS.replace("return insufficient()", "error_id = normalized\n        return insufficient()"),
    ],
)
def test_qualified_dispatch_with_nonlocal_or_rebound_subject_stays_advisory(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.14'\n")
    path = tmp_path / "dispatch.py"
    path.write_text(source)
    findings = PreferMatchValueDispatch().check(path, source)
    assert [finding.severity.value for finding in findings] == ["warning"]


_NO_ELSE = "def apply(fault, report):\n    if fault == 'schema':\n        report.schema = True\n    elif fault == 'missing':\n        report.findings = []\n    elif fault == 'drift':\n        report.level = 'drift'\n"
_ENUM = "from enum import Enum\nclass Level(Enum):\n    ERROR = 1\n    WARNING = 2\n    NOTE = 3\n"


def test_three_arm_ladder_without_else_is_review_only() -> None:
    [finding] = _check(_NO_ELSE)
    assert finding.severity.value == "warning"
    assert "with a fallback" not in finding.message
    helper = "def run():\n    def _apply(fault):\n        if fault == 'a':\n            print(1)\n        elif fault == 'b':\n            print(2)\n        elif fault == 'c':\n            print(3)\n    _apply('a')\n"
    assert len(_check(helper)) == 1
    assert fix_source(Path("app/dispatch.py"), helper, rule_ids=["prefer-match-value-dispatch"]) == helper


@pytest.mark.parametrize(
    "dispatch",
    [
        "def label(level):\n    if level is Level.ERROR:\n        return 'error'\n    elif level is Level.WARNING:\n        return 'warning'\n    else:\n        return 'note'\n",
        "def label(level):\n    if level is Level.ERROR:\n        return 'error'\n    if level is Level.WARNING:\n        return 'warning'\n    return 'note'\n",
    ],
    ids=["ladder", "terminal-siblings"],
)
def test_identity_dispatch_on_proven_enum_members_warns(dispatch: str) -> None:
    [finding] = _check(_ENUM + dispatch)
    assert finding.severity.value == "warning"
    assert "compare with ==" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "def apply(fault):\n    if fault == 'a':\n        go()\n    elif fault == 'b':\n        stop()\n",
        "class Level:\n    ERROR = 1\n    WARNING = 2\ndef label(level):\n    if level is Level.ERROR:\n        return 'e'\n    elif level is Level.WARNING:\n        return 'w'\n    else:\n        return 'n'\n",
        _ENUM.replace("    NOTE = 3\n", "    NOTE = 3\n    def __eq__(self, other):\n        return True\n")
        + "def label(level):\n    if level is Level.ERROR:\n        return 'e'\n    elif level is Level.WARNING:\n        return 'w'\n    else:\n        return 'n'\n",
        "from provider import Level\ndef label(level):\n    if level is Level.ERROR:\n        return 'e'\n    elif level is Level.WARNING:\n        return 'w'\n    else:\n        return 'n'\n",
        _ENUM
        + "def label(level, Level):\n    if level is Level.ERROR:\n        return 'e'\n    elif level is Level.WARNING:\n        return 'w'\n    else:\n        return 'n'\n",
        _ENUM
        + "def label(level, other):\n    if level is Level.ERROR:\n        return 'e'\n    elif other is Level.WARNING:\n        return 'w'\n    else:\n        return 'n'\n",
    ],
    ids=[
        "two-arm-no-else",
        "plain-class-constants",
        "custom-eq-enum",
        "unproven-import",
        "shadowed-enum",
        "two-subjects",
    ],
)
def test_unproven_identity_and_short_ladders_remain(source: str) -> None:
    assert _check(source) == []
