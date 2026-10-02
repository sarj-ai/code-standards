from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.__main__ import check_source
from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "python/app/parser.py") -> list[Diagnostic]:
    return PreferMatchTypeDispatch().check(Path(path), source)


_MIXED_PROBLEM = RuleProblem(
    key="mixed-type-dispatch",
    summary="A terminating type-check prefix and a two-arm if/elif tail repeat the same dispatch subject.",
    harm="The structural alternatives are split between two adjacent dispatch idioms, making the branch order harder to read.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(
        "if isinstance(value, str): return 'text'\nif isinstance(value, int): return 'number'\nelif isinstance(value, list): return 'list'\n",
    ),
    good_examples=(
        "match value:\n    case str(): return 'text'\n    case int(): return 'number'\n    case list(): return 'list'\n",
    ),
    exclusions=(
        "Non-terminating prefixes, unknown or repeated types, guarded type tests, and nonadjacent statements.",
    ),
)


_MIXED_CASES = (
    EvaluationCase(
        "continue-prefix",
        Language.PYTHON,
        "def check(values):\n    for value in values:\n        if isinstance(value, str):\n            continue\n        if isinstance(value, int):\n            consume(value)\n        elif isinstance(value, list):\n            consume(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "break-prefix",
        Language.PYTHON,
        "def check(values):\n    for value in values:\n        if isinstance(value, str):\n            break\n        if isinstance(value, int):\n            consume(value)\n        elif isinstance(value, list):\n            consume(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "exact-shape",
        Language.PYTHON,
        "import ast\ndef check(parent, root):\n    if isinstance(parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):\n        return True\n    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):\n        if root in bindings(parent):\n            return True\n    elif isinstance(parent, ast.ClassDef):\n        visit(parent)\n        if root in names(parent):\n            return True\n    return False\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-tail-fallthrough",
        Language.PYTHON,
        "def check(value, enabled):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, bool):\n        if enabled:\n            return 'bool'\n    elif isinstance(value, int):\n        return 'int'\n    return 'fallback'\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "multiple-terminal-prefixes",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, bytes):\n        return 'bytes'\n    if isinstance(value, list):\n        consume(value)\n    elif isinstance(value, int):\n        consume(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "tail-else",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, list):\n        consume(value)\n    elif isinstance(value, int):\n        consume(value)\n    else:\n        reject(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        "import ast as syntax\ndef check(value):\n    if isinstance(value, syntax.Name):\n        return True\n    if isinstance(value, syntax.FunctionDef):\n        visit(value)\n    elif isinstance(value, syntax.ClassDef):\n        visit(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        "from ast import Name as N, FunctionDef as F, ClassDef as C\ndef check(value):\n    if isinstance(value, N):\n        return True\n    if isinstance(value, F):\n        visit(value)\n    elif isinstance(value, C):\n        visit(value)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "non-terminating-prefix",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        consume(value)\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "conditionally-terminating-prefix",
        Language.PYTHON,
        "def check(value, enabled):\n    if isinstance(value, str):\n        if enabled:\n            return 'text'\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "suppressing-context-manager",
        Language.PYTHON,
        "from contextlib import suppress\ndef check(value):\n    if isinstance(value, str):\n        with suppress(ValueError):\n            raise ValueError\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "prefix-else",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        return 'text'\n    else:\n        log(value)\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "different-subject",
        Language.PYTHON,
        "def check(first, second):\n    if isinstance(first, str):\n        return 'text'\n    if isinstance(second, int):\n        consume(second)\n    elif isinstance(second, list):\n        consume(second)\n",
    ),
    EvaluationCase(
        "intervening-effect",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        return 'text'\n    log(value)\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "repeated-type",
        Language.PYTHON,
        "def check(value):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, str):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "unknown-import",
        Language.PYTHON,
        "from vendor import First, Second, Third\ndef check(value):\n    if isinstance(value, First):\n        return 'first'\n    if isinstance(value, Second):\n        consume(value)\n    elif isinstance(value, Third):\n        consume(value)\n",
    ),
    EvaluationCase(
        "guarded-tail",
        Language.PYTHON,
        "def check(value, ready):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, int) and ready:\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "runtime-type-group",
        Language.PYTHON,
        "def check(value, types):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, types):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase(
        "shadowed-isinstance",
        Language.PYTHON,
        "def check(value, isinstance):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, int):\n        consume(value)\n    elif isinstance(value, list):\n        consume(value)\n",
    ),
    EvaluationCase("malformed", Language.PYTHON, "if isinstance(value, str):\nif\n"),
)


@pytest.mark.parametrize("case", _MIXED_CASES, ids=tuple(case.case_id for case in _MIXED_CASES))
def test_mixed_dispatch_cases(case: EvaluationCase) -> None:
    diagnostics = _check(case.source)

    assert bool(diagnostics) is (case.expected is ExpectedOutcome.MATCH)
    assert len(diagnostics) <= 1


@pytest.mark.parametrize(
    "value", ["text", True, False, 1, [], None], ids=("text", "true", "false", "int", "list", "none")
)
@pytest.mark.parametrize("enabled", [False, True])
def test_match_preserves_nested_guard_fallthrough(value: object, enabled: bool) -> None:
    original = next(case.source for case in _MIXED_CASES if case.case_id == "builtin-tail-fallthrough")
    replacement = "def check(value, enabled):\n    match value:\n        case str():\n            return 'text'\n        case bool():\n            if enabled:\n                return 'bool'\n        case int():\n            return 'int'\n    return 'fallback'\n"
    source = (
        original
        + replacement.replace("def check(", "def replacement(")
        + (
            "assert check(value, enabled) == replacement(value, enabled)\n"
            "if isinstance(value, bool) and not enabled:\n"
            "    assert check(value, enabled) == 'fallback'\n"
        )
    )
    exec(compile(source, "<reviewed-example>", "exec"), {"value": value, "enabled": enabled})  # ruff: ignore[exec-builtin] -- execute reviewed equivalence fixtures without external inputs.


def test_invalid_tail_preserves_existing_prefix_diagnostic() -> None:
    source = "from vendor import First, Second\ndef check(value):\n    if isinstance(value, str):\n        return 'text'\n    if isinstance(value, bytes):\n        return 'bytes'\n    if isinstance(value, int):\n        return 'int'\n    if isinstance(value, First):\n        consume(value)\n    elif isinstance(value, Second):\n        consume(value)\n"

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 3
    assert "3-branch terminating isinstance sequence" in diagnostics[0].message


def test_mixed_dispatch_respects_exact_suppression() -> None:
    source = next(case.source for case in _MIXED_CASES if case.case_id == "builtin-tail-fallthrough").replace(
        "if isinstance(value, str):",
        "if isinstance(value, str):  # sarj-noqa: SARJ080 — legacy visitor signature fixture",
    )

    assert check_source([PreferMatchTypeDispatch()], Path("app/parser.py"), source) == []


def test_mixed_dispatch_excludes_generated_source() -> None:
    assert _check(_MIXED_CASES[1].source, "generated/parser.py") == []


def test_ordinary_two_arm_tail_remains_allowed() -> None:
    source = "def check(value):\n    if isinstance(value, str):\n        consume(value)\n    elif isinstance(value, int):\n        consume(value)\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "with suppress(ValueError):\n    raise ValueError",
        "with suppress(ValueError):\n    return parse_value()",
        "with suppress(ValueError):\n    with managed():\n        return 1",
        "if ready:\n    with suppress(ValueError):\n        raise ValueError\nelse:\n    return 1",
    ],
)
def test_context_manager_branch_can_fall_through(body: str) -> None:
    branch = "\n".join(f"        {line}" for line in body.splitlines())
    source = (
        "from contextlib import suppress\n"
        "def classify(value):\n    if isinstance(value, bool):\n"
        f"{branch}\n"
        "    if isinstance(value, int):\n        return 'int'\n"
        "    if isinstance(value, str):\n        return 'str'\n"
        "    return 'fallback'\n"
    )
    assert PreferMatchTypeDispatch().check(Path("app/classify.py"), source) == []


@pytest.mark.parametrize("terminal", ["raise ValueError", "return await parse_value()"])
def test_async_context_manager_branch_can_fall_through(terminal: str) -> None:
    source = (
        "async def classify(value):\n    if isinstance(value, bool):\n"
        f"        async with managed():\n            {terminal}\n"
        "    if isinstance(value, int):\n        return 'int'\n"
        "    if isinstance(value, str):\n        return 'str'\n"
        "    return 'fallback'\n"
    )
    assert PreferMatchTypeDispatch().check(Path("app/classify.py"), source) == []


@pytest.mark.parametrize("with_statement", ["with managed():", "async with managed():"])
def test_outer_return_after_context_manager_still_terminates(with_statement: str) -> None:
    source = (
        "async def classify(value):\n    if isinstance(value, bool):\n"
        f"        {with_statement}\n            process(value)\n        return 'bool'\n"
        "    if isinstance(value, int):\n        return 'int'\n"
        "    if isinstance(value, str):\n        return 'str'\n"
    )
    findings = PreferMatchTypeDispatch().check(Path("app/classify.py"), source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ080"


_PUBLIC_EXAMPLES = PreferMatchTypeDispatch.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_three_branch_isinstance_ladder_as_error() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ080"
    assert diagnostics[0].severity.value == "error"
    assert "3-branch isinstance ladder" in diagnostics[0].message


def test_allows_two_branch_ladder() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    ("first_type", "first_field", "second_type", "second_field"),
    [
        ("Name", "id", "Attribute", "attr"),
        ("Attribute", "attr", "Name", "id"),
    ],
)
def test_flags_two_arm_ast_name_or_attribute_projection(
    first_type: str,
    first_field: str,
    second_type: str,
    second_field: str,
) -> None:
    source = f"""
import ast

def dotted_tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.{first_type}):
        return node.{first_field}
    if isinstance(node, ast.{second_type}):
        return node.{second_field}
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity.value == "error"
    assert "two-arm ast.Name/ast.Attribute projection" in diagnostics[0].message


def test_flags_two_arm_ast_projection_with_direct_imports() -> None:
    source = """
from ast import Attribute, Name, expr

def dotted_tail(node: expr) -> str | None:
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        return node.attr
    return None
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("imports", "name_type", "attribute_type"),
    [
        ("import ast as syntax", "syntax.Name", "syntax.Attribute"),
        (
            "from ast import Attribute as AstAttribute, Name as AstName",
            "AstName",
            "AstAttribute",
        ),
    ],
    ids=("module-alias", "symbol-aliases"),
)
def test_flags_two_arm_ast_projection_with_import_aliases(
    imports: str,
    name_type: str,
    attribute_type: str,
) -> None:
    source = f"""
{imports}

def dotted_tail(node) -> str | None:
    if isinstance(node, {name_type}):
        return node.id
    if isinstance(node, {attribute_type}):
        return node.attr
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "two-arm ast.Name/ast.Attribute projection" in diagnostics[0].message


def test_flags_two_arm_ast_projection_with_bare_return_fallback() -> None:
    source = """
import ast

def dotted_tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return
"""

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "if ready:\n        if isinstance(node, ast.Name):\n            return node.id\n        if isinstance(node, ast.Attribute):\n            return node.attr\n        return None",
        "try:\n        parse(node)\n    except ValueError:\n        if isinstance(node, ast.Name):\n            return node.id\n        if isinstance(node, ast.Attribute):\n            return node.attr\n        return None",
        "match ready:\n        case True:\n            if isinstance(node, ast.Name):\n                return node.id\n            if isinstance(node, ast.Attribute):\n                return node.attr\n            return None",
    ],
    ids=("if-body", "except-handler", "match-case"),
)
def test_flags_two_arm_ast_projection_in_nested_statement_blocks(body: str) -> None:
    source = f"import ast\n\ndef dotted_tail(node, ready):\n    {body}\n"

    assert len(_check(source)) == 1


def test_reports_general_dispatch_in_except_handler_once() -> None:
    source = """
def parse(value):
    try:
        load(value)
    except ValueError:
        if isinstance(value, str):
            return text(value)
        if isinstance(value, bytes):
            return binary(value)
        if isinstance(value, dict):
            return mapping(value)
        return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "3-branch terminating isinstance sequence" in diagnostics[0].message


@pytest.mark.parametrize(
    ("source", "path"),
    [
        (
            """# Generated by a parser generator. Do not edit.
import ast

def dotted_tail(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
""",
            "python/app/generated_parser.py",
        ),
        (
            """import ast as syntax

def dotted_tail(syntax, node):
    if isinstance(node, syntax.Name):
        return node.id
    if isinstance(node, syntax.Attribute):
        return node.attr
    return None
""",
            "python/app/parser.py",
        ),
        (
            """from ast import Attribute as AstAttribute, Name as AstName
AstName = custom_name_type

def dotted_tail(node):
    if isinstance(node, AstName):
        return node.id
    if isinstance(node, AstAttribute):
        return node.attr
    return None
""",
            "python/app/parser.py",
        ),
    ],
    ids=("generated", "shadowed-module-alias", "rebound-symbol-alias"),
)
def test_allows_unproven_two_arm_ast_alias_projections(source: str, path: str) -> None:
    assert _check(source, path) == []


def test_reports_only_general_finding_for_longer_sequence_ending_in_ast_projection() -> None:
    source = """
import ast

def dotted_tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "3-branch terminating isinstance sequence" in diagnostics[0].message


@pytest.mark.parametrize(
    "body",
    [
        "if isinstance(node, ast.Name):\n        return node.attr\n    if isinstance(node, ast.Attribute):\n        return node.id\n    return None",
        "if isinstance(node, ast.Name):\n        observe(node)\n        return node.id\n    if isinstance(node, ast.Attribute):\n        return node.attr\n    return None",
        "if isinstance(node, ast.Name):\n        return node.id\n    if isinstance(other, ast.Attribute):\n        return other.attr\n    return None",
        "if isinstance(node, ast.Name):\n        return node.id\n    if isinstance(node, ast.Attribute):\n        return node.attr\n    return 'unknown'",
        "if isinstance(node, ast.Name):\n        return node.id\n    elif isinstance(node, ast.Attribute):\n        return node.attr\n    return None",
        "if isinstance(node, ast.Name) and ready:\n        return node.id\n    if isinstance(node, ast.Attribute):\n        return node.attr\n    return None",
    ],
)
def test_allows_near_miss_two_arm_ast_projections(body: str) -> None:
    source = f"import ast\n\ndef dotted_tail(node, other, ready):\n    {body}\n"
    assert _check(source) == []


def test_allows_nested_imported_class_guard() -> None:
    source = """
from app.models import ActiveBatchSettings, CustomScenario

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario):
        raise TypeError("custom scenario required")
    return settings.scenario.id
"""

    assert _check(source) == []


def test_allows_nested_guard_that_returns() -> None:
    source = """
class CustomScenario: ...
class ActiveBatchSettings: ...

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario):
        return None
    return settings.scenario.id
"""
    assert _check(source) == []


def test_allows_nested_module_local_class_guard_that_raises_type_error() -> None:
    source = """
class CustomScenario: ...
class ActiveBatchSettings: ...

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario):
        message = "custom scenario required"
        raise TypeError(message)
    return settings.scenario.id
"""
    assert _check(source) == []


def test_allows_nested_guard_with_imported_runtime_type_group() -> None:
    source = """
from app.models import ActiveBatchSettings, ScenarioKinds

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, ScenarioKinds):
        raise TypeError("custom scenario required")
    return settings.scenario.id
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "condition",
    [
        "not isinstance(settings, ActiveBatchSettings)",
        "not isinstance(settings, ActiveBatchSettings) or not isinstance(scenario, CustomScenario)",
        "not isinstance(settings, dict) or not isinstance(settings['scenario'], dict)",
        "not isinstance(settings, ActiveBatchSettings) and not isinstance(settings.scenario, CustomScenario)",
        "not isinstance(settings.scenario, CustomScenario) or not isinstance(settings, ActiveBatchSettings)",
        "not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario) or not ready",
    ],
)
def test_allows_non_structural_or_unsafe_nested_guards(condition: str) -> None:
    source = f"""
from app.models import ActiveBatchSettings, CustomScenario

def retry(settings, scenario, ready):
    if {condition}:
        raise TypeError
    return settings
"""
    assert _check(source) == []


def test_allows_nested_guard_that_does_not_terminate() -> None:
    source = """
from app.models import ActiveBatchSettings, CustomScenario

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario):
        log.warning("custom scenario required")
    return settings
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "preamble",
    [
        "TypeError = RuntimeError",
        "isinstance = custom_isinstance",
    ],
)
def test_allows_nested_guard_when_required_builtin_is_shadowed(preamble: str) -> None:
    source = f"""
from app.models import ActiveBatchSettings, CustomScenario
{preamble}

def retry(settings):
    if not isinstance(settings, ActiveBatchSettings) or not isinstance(settings.scenario, CustomScenario):
        raise TypeError("custom scenario required")
    return settings.scenario.id
"""
    assert _check(source) == []


def test_flags_three_terminating_sibling_checks() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, bytes):
        return binary(value)
    if isinstance(value, dict):
        return mapping(value)
    raise TypeError(type(value))
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "terminating isinstance sequence" in diagnostics[0].message


@pytest.mark.parametrize("unrelated_position", ["before", "after"])
def test_finds_sibling_dispatch_next_to_unrelated_terminating_if(unrelated_position: str) -> None:
    unrelated = "    if ready:\n        return cached()\n"
    dispatch = """    if isinstance(value, str):
        return text(value)
    if isinstance(value, bytes):
        return binary(value)
    if isinstance(value, dict):
        return mapping(value)
"""
    body = unrelated + dispatch if unrelated_position == "before" else dispatch + unrelated
    source = f"def parse(value: object):\n{body}    return None\n"

    assert len(_check(source)) == 1


def test_allows_nonterminating_sibling_checks() -> None:
    source = """
def observe(value: object) -> None:
    if isinstance(value, str):
        strings.add(value)
    if isinstance(value, bytes):
        binaries.add(value)
    if isinstance(value, dict):
        mappings.add(value)
"""

    assert _check(source) == []


def test_allows_mixed_subjects() -> None:
    source = """
def parse(first: object, second: object):
    if isinstance(first, str):
        return text(first)
    elif isinstance(second, bytes):
        return binary(second)
    elif isinstance(first, dict):
        return mapping(first)
    return None
"""

    assert _check(source) == []


def test_allows_guarded_branches() -> None:
    source = """
def parse(value: object):
    if isinstance(value, str) and value:
        return text(value)
    elif isinstance(value, bytes) and value:
        return binary(value)
    elif isinstance(value, dict) and value:
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_repeated_or_overlapping_types() -> None:
    source = """
def parse(value: object):
    if isinstance(value, (str, bytes)):
        return scalar(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_flags_disjoint_tuple_and_union_type_arms() -> None:
    source = """
def parse(value: object):
    if isinstance(value, (str, bytes)):
        return scalar(value)
    elif isinstance(value, dict | list):
        return collection(value)
    elif isinstance(value, int):
        return number(value)
    return None
"""

    assert len(_check(source)) == 1


def test_flags_unshadowed_module_local_classes() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert len(_check(source)) == 1


def test_allows_imported_class_like_runtime_bindings() -> None:
    source = """
from contracts import Text, Binary, Mapping

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_function_shadow_of_module_class() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...

def parse(value: object, Text):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_import_rebinding_of_module_classes() -> None:
    source = """
class Text: ...
class Binary: ...
class Mapping: ...
from groups import Text, Binary, Mapping

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "shadow",
    [
        "def Text(): ...",
        "def outer():\n    class Text: ...",
    ],
)
def test_allows_declaration_rebinding_of_module_class(shadow: str) -> None:
    source = f"""
class Text: ...
class Binary: ...
class Mapping: ...
{shadow}

def parse(value: object):
    if isinstance(value, Text):
        return text(value)
    elif isinstance(value, Binary):
        return binary(value)
    elif isinstance(value, Mapping):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "Supported = (str, bytes)",
        "Supported = str | bytes",
        "Supported = load_types()",
    ],
)
def test_allows_runtime_type_group_bindings(declaration: str) -> None:
    source = f"""
{declaration}

def parse(value: object):
    if isinstance(value, Supported):
        return scalar(value)
    elif isinstance(value, dict):
        return mapping(value)
    elif isinstance(value, list):
        return sequence(value)
    return None
"""

    assert _check(source) == []


def test_flags_proven_stdlib_ast_classes() -> None:
    source = """
import ast

def name(node: ast.AST):
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None
"""

    assert len(_check(source)) == 1


def test_flags_directly_imported_stdlib_ast_classes() -> None:
    source = """
from ast import Name, expr, operator

def name(node):
    if isinstance(node, Name):
        return node.id
    elif isinstance(node, expr):
        return "expression"
    elif isinstance(node, operator):
        return "operator"
    return None
"""

    assert len(_check(source)) == 1


def test_allows_shadowed_ast_module() -> None:
    source = """
import ast

def name(ast, node):
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return None
"""

    assert _check(source) == []


def test_allows_non_type_stdlib_ast_attributes() -> None:
    source = """
import ast

def name(node):
    if isinstance(node, ast.walk):
        return "walk"
    elif isinstance(node, ast.dump):
        return "dump"
    elif isinstance(node, ast.parse):
        return "parse"
    return None
"""

    assert _check(source) == []


def test_allows_shadowed_isinstance() -> None:
    source = """
def parse(value: object, isinstance):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "nested_import",
    [
        "from fake import check as isinstance",
        "from fake import Text as str",
        "import fake as ast",
    ],
)
def test_allows_function_local_import_shadow(nested_import: str) -> None:
    source = f"""
import ast

def parse(value: object):
    {nested_import}
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, ast.Name):
        return name(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_allows_wildcard_import_with_unproven_bindings() -> None:
    source = """
from fake import *

def parse(value):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        """
def parse(value):
    try:
        load()
    except Exception as isinstance:
        if isinstance(value, str):
            return text(value)
        elif isinstance(value, bytes):
            return binary(value)
        elif isinstance(value, dict):
            return mapping(value)
""",
        """
def parse(value):
    try:
        load()
    except Exception as str:
        if isinstance(value, str):
            return text(value)
        elif isinstance(value, bytes):
            return binary(value)
        elif isinstance(value, dict):
            return mapping(value)
""",
        """
def parse(payload, value):
    match payload:
        case {"fn": isinstance}:
            if isinstance(value, str):
                return text(value)
            elif isinstance(value, bytes):
                return binary(value)
            elif isinstance(value, dict):
                return mapping(value)
""",
        """
def parse(payload, value):
    match payload:
        case {"type": str}:
            if isinstance(value, str):
                return text(value)
            elif isinstance(value, bytes):
                return binary(value)
            elif isinstance(value, dict):
                return mapping(value)
""",
    ],
)
def test_allows_exception_and_pattern_shadow_bindings(source: str) -> None:
    assert _check(source) == []


def test_allows_issubclass_dispatch() -> None:
    source = """
def classify(cls: type):
    if issubclass(cls, Text):
        return "text"
    elif issubclass(cls, Binary):
        return "binary"
    elif issubclass(cls, Mapping):
        return "mapping"
    return None
"""

    assert _check(source) == []


def test_allows_locally_caught_validation_raise() -> None:
    source = """
def parse(value: object):
    try:
        if value is None:
            raise ValueError("required")
        return value
    except ValueError:
        return None
"""

    assert _check(source) == []


def test_allows_sequential_passthrough_guards() -> None:
    source = """
def parse(value: object):
    if value is None:
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value
    return coerce(value)
"""

    assert _check(source) == []


def test_allows_repeated_captures_in_existing_match() -> None:
    source = """
def body(node):
    match node:
        case Function(body=body) | Class(body=body):
            mutate(node)
            return body
    return []
"""

    assert _check(source) == []


def test_allows_generated_source() -> None:
    source = """# Generated by OpenAPI generator. Do not edit.
def parse(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    assert _check(source) == []


def test_reports_multiple_dispatches_in_source_order() -> None:
    source = """
def first(value: object):
    if isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)

def second(value: object):
    if isinstance(value, int):
        return integer(value)
    elif isinstance(value, float):
        return floating(value)
    elif isinstance(value, complex):
        return number(value)
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 2
    assert [(item.line, item.col) for item in diagnostics] == sorted((item.line, item.col) for item in diagnostics)


def test_finds_valid_child_ladder_under_unrelated_outer_if() -> None:
    source = """
def parse(value: object):
    if ready:
        return cached()
    elif isinstance(value, str):
        return text(value)
    elif isinstance(value, bytes):
        return binary(value)
    elif isinstance(value, dict):
        return mapping(value)
    return None
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5


@pytest.mark.parametrize("source", ["", "# comment\n", "def f(:\n    pass"])
def test_trivial_or_invalid_source_is_ignored(source: str) -> None:
    assert _check(source) == []
