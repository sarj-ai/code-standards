from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring


PROBLEM = RuleProblem(
    key="shared-runtime-docstring-consumption",
    summary="Class and function docstring rules must preserve every recognized runtime reader.",
    harm="Diverging analysis can recommend removing docstrings that affect runtime output.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=('class RetryPolicy:\n    """Retry policy."""\n    attempts = 3\n',),
    good_examples=('class RetryPolicy:\n    """Retry policy."""\n    attempts = 3\nhelp(RetryPolicy)\n',),
)

_DECLARATIONS = (
    'class RetryPolicy:\n    """Retry policy."""\n    attempts = 3\n'
    'def get_task(task_id: str):\n    """Get a task."""\n    return None\n'
)


@pytest.mark.parametrize(
    "reader",
    [
        pytest.param("print({owner}.__doc__)", id="attribute"),
        pytest.param("help({owner})", id="help"),
        pytest.param("inspect.getdoc({owner})", id="getdoc"),
        pytest.param("pydoc.render_doc({owner})", id="render-doc"),
        pytest.param('getattr({owner}, "__doc__")', id="getattr"),
        pytest.param('print({owner}.__dict__["__doc__"])', id="dict"),
        pytest.param('print(vars({owner})["__doc__"])', id="vars"),
        pytest.param("alias = {owner}\nhelp(alias)", id="alias"),
        pytest.param("alias: object = {owner}\nhelp(alias)", id="annotated-alias"),
        pytest.param("second = first\nfirst = {owner}\nhelp(second)", id="reverse-ordered-alias-chain"),
        pytest.param("first = second\nsecond = first\nsecond = {owner}\nhelp(first)", id="alias-cycle"),
        pytest.param("alias = module.{owner}\nhelp(alias)", id="qualified-alias"),
    ],
)
def test_labeled_runtime_readers_preserve_both_docstring_kinds(reader: str) -> None:
    uses = "\n".join(reader.format(owner=owner) for owner in ("RetryPolicy", "get_task"))
    case = EvaluationCase("runtime-reader", Language.PYTHON, _DECLARATIONS + uses + "\n")
    assert case.language in PROBLEM.languages
    context = PythonFileContext(Path("app.py"), case.source)
    for rule in (RedundantClassDocstring(), RedundantDocstring()):
        assert rule.check_context(context) == []


@pytest.mark.parametrize(
    "use",
    [
        pytest.param("", id="unconsumed"),
        pytest.param("print(RetryPolicy.attempts)", id="other-attribute"),
        pytest.param('getattr(RetryPolicy, "attempts")', id="other-getattr"),
        pytest.param('print(vars(RetryPolicy)["attempts"])', id="other-dict-key"),
        pytest.param("alias = RetryPolicy\nprint(alias)", id="unread-alias"),
    ],
)
def test_labeled_non_readers_keep_both_existing_diagnostics(use: str) -> None:
    case = EvaluationCase("unconsumed-docstrings", Language.PYTHON, _DECLARATIONS + use + "\n", ExpectedOutcome.MATCH)
    context = PythonFileContext(Path("app.py"), case.source)
    forward = [
        finding for rule in (RedundantClassDocstring(), RedundantDocstring()) for finding in rule.check_context(context)
    ]
    assert [(finding.code, finding.line, finding.col) for finding in forward] == [("SARJ085", 2, 5), ("SARJ050", 5, 5)]
    reverse = [
        finding for rule in (RedundantDocstring(), RedundantClassDocstring()) for finding in rule.check_context(context)
    ]
    assert sorted(finding.format() for finding in forward) == sorted(finding.format() for finding in reverse)


def test_shared_docstring_fact_is_immutable_lazy_and_local_to_one_source() -> None:
    path = Path("app.py")
    consumed = PythonFileContext(path, _DECLARATIONS + "alias = RetryPolicy\nhelp(alias)\n")
    untouched = PythonFileContext(path, _DECLARATIONS)
    assert "consumed_docstring_names" not in vars(consumed)
    assert consumed.consumed_docstring_names == frozenset({"RetryPolicy", "alias"})
    assert isinstance(consumed.consumed_docstring_names, frozenset)
    assert consumed.consumed_docstring_names is consumed.consumed_docstring_names
    assert untouched.consumed_docstring_names == frozenset()
    assert len(RedundantClassDocstring().check_context(untouched)) == 1
    assert RedundantClassDocstring().check_context(consumed) == []


def test_alias_reassignments_conservatively_preserve_all_observed_docstrings() -> None:
    context = PythonFileContext(Path("app.py"), _DECLARATIONS + "alias = RetryPolicy\nalias = get_task\nhelp(alias)\n")
    assert RedundantClassDocstring().check_context(context) == []
    assert RedundantDocstring().check_context(context) == []
