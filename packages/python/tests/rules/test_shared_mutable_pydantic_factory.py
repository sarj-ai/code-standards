from pathlib import Path
from textwrap import dedent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.shared_mutable_pydantic_factory import SharedMutablePydanticFactory


def _source(binding: str, factory: str = "lambda: SHARED") -> str:
    return (
        "from pydantic import BaseModel, Field\n"
        f"{binding}\n"
        "class Parent(BaseModel):\n"
        f"    values: object = Field(default_factory={factory})\n"
    )


CASES = (
    EvaluationCase("shared-list", Language.PYTHON, _source("SHARED = []"), ExpectedOutcome.MATCH),
    EvaluationCase("shared-dict", Language.PYTHON, _source("SHARED = {}"), ExpectedOutcome.MATCH),
    EvaluationCase("shared-set", Language.PYTHON, _source("SHARED = {1}"), ExpectedOutcome.MATCH),
    EvaluationCase("constructor", Language.PYTHON, _source("SHARED = list()"), ExpectedOutcome.MATCH),
    EvaluationCase("annotated-binding", Language.PYTHON, _source("SHARED: list[int] = []"), ExpectedOutcome.MATCH),
    EvaluationCase("alias", Language.PYTHON, _source("ORIGINAL = []\nSHARED = ORIGINAL"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "mutable-model",
        Language.PYTHON,
        _source("class Child(BaseModel):\n    count: int = 0\nSHARED = Child()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "factory-function",
        Language.PYTHON,
        _source("SHARED = []\ndef factory():\n    return SHARED", "factory"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "factory-function-alias",
        Language.PYTHON,
        _source("SHARED = []\ndef factory():\n    return SHARED\nmake = factory", "make"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("fresh-literal", Language.PYTHON, _source("SHARED = []", "lambda: []")),
    EvaluationCase("fresh-constructor", Language.PYTHON, _source("SHARED = []", "list")),
    EvaluationCase(
        "validated-default",
        Language.PYTHON,
        _source("SHARED = []").replace("lambda: SHARED)", "lambda: SHARED, validate_default=True)"),
    ),
    EvaluationCase(
        "unknown-default-validation",
        Language.PYTHON,
        _source("SHARED = []").replace("lambda: SHARED)", "lambda: SHARED, **options)"),
    ),
    EvaluationCase(
        "configured-owner",
        Language.PYTHON,
        _source("SHARED = []").replace(
            "class Parent(BaseModel):", "class Parent(BaseModel):\n    model_config = {'validate_default': True}"
        ),
    ),
    EvaluationCase(
        "transforming-owner",
        Language.PYTHON,
        _source("SHARED = []") + "    def model_post_init(self, context):\n        self.values = self.values.copy()\n",
    ),
    EvaluationCase("explicit-copy", Language.PYTHON, _source("SHARED = []", "lambda: SHARED.copy()")),
    EvaluationCase("immutable", Language.PYTHON, _source("SHARED = (1, 2)")),
    EvaluationCase("unknown-service", Language.PYTHON, _source("SHARED = Service()")),
    EvaluationCase("rebound-before", Language.PYTHON, _source("SHARED = []\nSHARED = ()")),
    EvaluationCase("rebound-after", Language.PYTHON, _source("SHARED = []") + "SHARED = ()\n"),
    EvaluationCase("conditional-rebind", Language.PYTHON, _source("SHARED = []\nif flag:\n    SHARED = ()")),
    EvaluationCase("deleted-binding", Language.PYTHON, _source("SHARED = []") + "del SHARED\n"),
    EvaluationCase(
        "exception-rebind",
        Language.PYTHON,
        _source("SHARED = []") + "try:\n    operation()\nexcept Exception as SHARED:\n    pass\n",
    ),
    EvaluationCase(
        "pattern-rebind",
        Language.PYTHON,
        _source("SHARED = []") + "match value:\n    case {'value': SHARED}:\n        pass\n",
    ),
    EvaluationCase(
        "global-rebind", Language.PYTHON, _source("SHARED = []") + "def reset():\n    global SHARED\n    SHARED = ()\n"
    ),
    EvaluationCase("alias-cycle", Language.PYTHON, _source("SHARED = OTHER\nOTHER = SHARED")),
    EvaluationCase("lambda-argument", Language.PYTHON, _source("SHARED = []", "lambda SHARED: SHARED")),
    EvaluationCase("lambda-default", Language.PYTHON, _source("SHARED = []", "lambda SHARED=None: SHARED")),
    EvaluationCase("unknown-function", Language.PYTHON, _source("SHARED = []", "make")),
    EvaluationCase(
        "function-parameter", Language.PYTHON, _source("def factory(SHARED):\n    return SHARED", "factory")
    ),
    EvaluationCase(
        "rebound-factory",
        Language.PYTHON,
        _source("SHARED=[]\ndef factory():\n    return SHARED\nfactory=other", "factory"),
    ),
    EvaluationCase("shadowed-constructor", Language.PYTHON, _source("list = other\nSHARED = list()")),
    EvaluationCase("shadowed-field", Language.PYTHON, _source("Field = other\nSHARED = []")),
    EvaluationCase(
        "classvar",
        Language.PYTHON,
        _source("from typing import ClassVar\nSHARED=[]").replace("values: object", "values: ClassVar[object]"),
    ),
    EvaluationCase("private-field", Language.PYTHON, _source("SHARED=[]").replace("values:", "_values:")),
    EvaluationCase(
        "frozen-model",
        Language.PYTHON,
        _source("class Child(BaseModel, frozen=True):\n    count: int = 0\nSHARED = Child()"),
    ),
    EvaluationCase(
        "config-model",
        Language.PYTHON,
        _source("class Child(BaseModel):\n    model_config = {'frozen': True}\nSHARED = Child()"),
    ),
    EvaluationCase(
        "inherited-model", Language.PYTHON, _source("class Child(Other):\n    count: int = 0\nSHARED = Child()")
    ),
    EvaluationCase("malformed", Language.PYTHON, "class Parent(:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = SharedMutablePydanticFactory().check(Path("models.py"), case.source)
    assert len(diagnostics) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_documented_examples() -> None:
    verify_native_rule(SharedMutablePydanticFactory, analyze)


def test_import_aliases() -> None:
    source = (
        _source("SHARED=[]")
        .replace("from pydantic import BaseModel, Field", "import pydantic as p")
        .replace("(BaseModel)", "(p.BaseModel)")
        .replace("Field(", "p.Field(")
    )
    assert len(SharedMutablePydanticFactory().check(Path("models.py"), source)) == 1


def test_exact_suppression() -> None:
    source = _source("SHARED=[]").rstrip() + "  # sarj-noqa: SARJ459 -- intentionally shared\n"
    assert not SharedMutablePydanticFactory().check(Path("models.py"), source)


def test_generated_file() -> None:
    assert not SharedMutablePydanticFactory().check(Path("generated/models.py"), _source("SHARED=[]"))


def test_nested_scope_is_not_inferred() -> None:
    source = dedent("""
        from pydantic import BaseModel, Field
        SHARED = []
        def build():
            SHARED = ()
            class Parent(BaseModel):
                values: object = Field(default_factory=lambda: SHARED)
    """)
    assert not SharedMutablePydanticFactory().check(Path("models.py"), source)
