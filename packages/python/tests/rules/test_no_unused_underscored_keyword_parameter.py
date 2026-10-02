from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_unused_underscored_keyword_parameter import NoUnusedUnderscoredKeywordParameter
from sarj_python_lint.rules.no_unused_value_marker import NoUnusedValueMarker


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


PROBLEM = RuleProblem(
    key="unused-underscored-keyword-parameter",
    summary="An unused keyword-only input is hidden from unused-argument lint by an underscore prefix.",
    harm="Callers must supply an ignore-marked keyword whose value the implementation never reads.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=("def emit(*, _email=None):\n    return 'ready'\n",),
    good_examples=("def emit():\n    return 'ready'\n", "def callback(_event):\n    return 'ready'\n"),
    exclusions=("Positional callback slots, decorated contracts, inherited methods, stubs, and generated source.",),
)


def _case_id(case: EvaluationCase) -> str:
    return case.case_id


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase(
            "optional-keyword",
            Language.PYTHON,
            "def emit(*, _email=None):\n    return 'ready'\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "required-keyword",
            Language.PYTHON,
            "def emit(*, _email: str):\n    return 'ready'\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "async-keyword",
            Language.PYTHON,
            "async def emit(*, _email=None):\n    await send()\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "private-helper", Language.PYTHON, "def _emit(*, _email=None):\n    return 'ready'\n", ExpectedOutcome.MATCH
        ),
        EvaluationCase(
            "method",
            Language.PYTHON,
            "class Sink:\n    def emit(self, *, _email=None):\n        self.sent = True\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "static-method",
            Language.PYTHON,
            "class Sink:\n    @staticmethod\n    def emit(*, _email=None):\n        return 'ready'\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "class-method",
            Language.PYTHON,
            "class Sink:\n    @classmethod\n    def emit(cls, *, _email=None):\n        return cls()\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "nested-function",
            Language.PYTHON,
            "def outer():\n    def emit(*, _email=None):\n        return 'ready'\n    return emit\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "same-spelling-elsewhere",
            Language.PYTHON,
            "def emit(*, _email=None):\n    return 'ready'\ndef other(_email):\n    return _email\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "literal-only", Language.PYTHON, "def emit(*, _email=None):\n    return '_email'\n", ExpectedOutcome.MATCH
        ),
        EvaluationCase(
            "annotation-only",
            Language.PYTHON,
            "def emit(*, _email: str=None):\n    return 'ready'\n",
            ExpectedOutcome.MATCH,
        ),
        EvaluationCase(
            "fixture-path",
            Language.PYTHON,
            "def emit(*, _email=None):\n    return 'ready'\n",
            ExpectedOutcome.MATCH,
            PurePosixPath("tests/test_sink.py"),
        ),
        EvaluationCase("used-keyword", Language.PYTHON, "def emit(*, _email=None):\n    return _email\n"),
        EvaluationCase("removed-keyword", Language.PYTHON, "def emit():\n    return 'ready'\n"),
        EvaluationCase("ordinary-unused", Language.PYTHON, "def emit(*, email=None):\n    return 'ready'\n"),
        EvaluationCase("positional-callback", Language.PYTHON, "def callback(_event):\n    return 'ready'\n"),
        EvaluationCase("positional-only-callback", Language.PYTHON, "def callback(_event, /):\n    return 'ready'\n"),
        EvaluationCase(
            "variadic-callback", Language.PYTHON, "def callback(*_events, **_options):\n    return 'ready'\n"
        ),
        EvaluationCase(
            "closure-read",
            Language.PYTHON,
            "def emit(*, _email=None):\n    def read():\n        return _email\n    return read\n",
        ),
        EvaluationCase("lambda-read", Language.PYTHON, "def emit(*, _email=None):\n    return lambda: _email\n"),
        EvaluationCase(
            "augmentation-read", Language.PYTHON, "def emit(*, _email=0):\n    _email += 1\n    return 'ready'\n"
        ),
        EvaluationCase(
            "rebound-read-conservative",
            Language.PYTHON,
            "def emit(*, _email=None):\n    _email = 'ready'\n    return _email\n",
        ),
        EvaluationCase(
            "nested-shadow-conservative",
            Language.PYTHON,
            "def emit(*, _email=None):\n    def read(_email):\n        return _email\n    return read\n",
        ),
        EvaluationCase(
            "decorated-callback", Language.PYTHON, "@handler\ndef emit(*, _email=None):\n    return 'ready'\n"
        ),
        EvaluationCase(
            "override-alias",
            Language.PYTHON,
            "from typing import override as overrides\nclass Sink(Base):\n    @overrides\n    def emit(self, *, _email=None):\n        self.sent = True\n",
        ),
        EvaluationCase(
            "inherited-contract",
            Language.PYTHON,
            "class Sink(Base):\n    def emit(self, *, _email=None):\n        self.sent = True\n",
        ),
        EvaluationCase("abstract-stub", Language.PYTHON, "def emit(*, _email=None):\n    raise NotImplementedError\n"),
        EvaluationCase("ellipsis-stub", Language.PYTHON, "def emit(*, _email=None):\n    ...\n"),
        EvaluationCase("pass-stub", Language.PYTHON, "def emit(*, _email=None):\n    pass\n"),
        EvaluationCase("return-stub", Language.PYTHON, "def emit(*, _email=None):\n    return None\n"),
        EvaluationCase(
            "docstring-stub", Language.PYTHON, "def emit(*, _email=None):\n    'Required callback.'\n    pass\n"
        ),
        EvaluationCase("dynamic-locals", Language.PYTHON, "def emit(*, _email=None):\n    return locals()\n"),
        EvaluationCase(
            "dynamic-local-alias",
            Language.PYTHON,
            "def emit(*, _email=None):\n    arguments = locals\n    return arguments()\n",
        ),
        EvaluationCase(
            "conditional-inherited-method",
            Language.PYTHON,
            "class Sink(Base):\n    if enabled:\n        def emit(self, *, _email=None):\n            self.sent = True\n",
        ),
        EvaluationCase(
            "shadowed-staticmethod",
            Language.PYTHON,
            "class Sink:\n    staticmethod = handler\n    @staticmethod\n    def emit(*, _email=None):\n        return 'ready'\n",
        ),
        EvaluationCase(
            "dynamic-locals-alias",
            Language.PYTHON,
            "from builtins import locals as arguments\ndef emit(*, _email=None):\n    return arguments()\n",
        ),
        EvaluationCase("dynamic-eval", Language.PYTHON, "def emit(*, _email=None):\n    return eval('_email')\n"),
        EvaluationCase("sdk-keyword-call", Language.PYTHON, "Settings(_env_file='config.env')\n"),
        EvaluationCase(
            "generated-path",
            Language.PYTHON,
            "def emit(*, _email=None):\n    return 'ready'\n",
            path=PurePosixPath("generated/client.py"),
        ),
        EvaluationCase(
            "vendor-path",
            Language.PYTHON,
            "def emit(*, _email=None):\n    return 'ready'\n",
            path=PurePosixPath("vendor/client.py"),
        ),
        EvaluationCase(
            "generated-header",
            Language.PYTHON,
            "# This file is generated; do not edit.\ndef emit(*, _email=None):\n    return 'ready'\n",
        ),
        EvaluationCase("malformed", Language.PYTHON, "def emit(*, _email=):\n"),
        EvaluationCase(
            "exact-suppression",
            Language.PYTHON,
            "def emit(*, _email=None):  # sarj-noqa: SARJ475 — external keyword callback contract\n    return 'ready'\n",
        ),
        EvaluationCase(
            "unrelated-suppression",
            Language.PYTHON,
            "def emit(*, _email=None):  # sarj-noqa: SARJ452 — unrelated rule fixture\n    return 'ready'\n",
            ExpectedOutcome.MATCH,
        ),
    ],
    ids=_case_id,
)
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = NoUnusedUnderscoredKeywordParameter().check(Path(case.path), case.source)

    assert bool(diagnostics) is (case.expected is ExpectedOutcome.MATCH)
    assert len(diagnostics) <= 1
    assert all(item.code == "SARJ475" and item.severity is Severity.WARNING for item in diagnostics)


@pytest.mark.parametrize(
    "example",
    NoUnusedUnderscoredKeywordParameter.public_examples(),
    ids=[example.example_id for example in NoUnusedUnderscoredKeywordParameter.public_examples()],
)
def test_documentation_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoUnusedUnderscoredKeywordParameter().check(Path(focus.path), focus.source)) == example.expected_count


def test_reports_each_parameter_once_in_declaration_order() -> None:
    source = "def emit(\n    *,\n    _email=None,\n    _phone=None,\n):\n    return 'ready'\n"
    rule = NoUnusedUnderscoredKeywordParameter()

    assert [(item.line, item.col) for item in rule.check(Path("app.py"), source)] == [(3, 5), (4, 5)]
    assert rule.check(Path("app.py"), source) == rule.check(Path("app.py"), source)


def test_discard_binding_is_owned_by_existing_marker_rule() -> None:
    source = "def emit(*, _email=None):\n    _ = _email\n    return 'ready'\n"

    assert NoUnusedUnderscoredKeywordParameter().check(Path("app.py"), source) == []
    assert len(NoUnusedValueMarker().check(Path("app.py"), source)) == 1
