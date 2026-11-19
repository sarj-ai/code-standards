from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_pydantic_field_bounds import PreferPydanticFieldBounds


CASES = (
    (
        "simple-lower",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "simple-strict",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count <= 0:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "simple-upper",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count > 10:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "simple-upper-strict",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count >= 10:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "reversed-operands",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if 1 > self.count:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "negative-bound",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < -1:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "field-default",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int = 1\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "aliased-model",
        'from pydantic import BaseModel as Base, model_validator as check\nclass Model(Base):\n    count: int\n    @check(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "quoted-int",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: "int"\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        1,
    ),
    (
        "cross-field",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    other: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < self.other:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "float-nan",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: float\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "custom-exception",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise DomainError("out of range")\n        return self\n',
        0,
    ),
    (
        "computed-message",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError(message())\n        return self\n',
        0,
    ),
    (
        "transform",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        self.count += 1\n        return self\n',
        0,
    ),
    (
        "unrelated-work",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        log()\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "context",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self, info):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "before-mode",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="before")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "wrap-mode",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="wrap")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "custom-base",
        'from custom import BaseModel\nfrom pydantic import model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "mixed-base",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel, Other):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "class-decorator",
        'from pydantic import BaseModel, model_validator\n@decorate\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "shadowed-int",
        'from pydantic import BaseModel, model_validator\nint = str\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "other-decorator",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @other\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "equality",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count == 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    (
        "else-path",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):\n        if self.count < 1:\n            raise ValueError("out of range")\n        else:\n            normalize()\n        return self\n',
        0,
    ),
    (
        "suppressed",
        'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    count: int\n    @model_validator(mode="after")\n    def bounded(self):  # sarj-noqa: SARJ582 -- transport error contract\n        if self.count < 1:\n            raise ValueError("out of range")\n        return self\n',
        0,
    ),
    ("malformed", "class Model(:", 0),
)


@pytest.mark.parametrize(("case_id", "source", "count"), CASES, ids=[row[0] for row in CASES])
def test_pure_integer_bounds(case_id: str, source: str, count: int) -> None:
    findings = PreferPydanticFieldBounds().check(Path("app/model.py"), source)
    assert len(findings) == count, case_id
    assert all(finding.severity is Severity.WARNING for finding in findings)
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)


def test_documented_examples() -> None:
    verify_native_rule(PreferPydanticFieldBounds, analyze)


def test_pydantic_class_bound_receiver_is_not_an_instance_guard() -> None:
    source = CASES[0][1].replace("self", "cls")
    assert PreferPydanticFieldBounds().check(Path("app/model.py"), source) == []


def test_overwritten_validator_is_not_a_unique_model_member() -> None:
    source = CASES[0][1] + "    bounded = 1\n"
    assert PreferPydanticFieldBounds().check(Path("app/model.py"), source) == []


@pytest.mark.parametrize("path", ["tests/test_model.py", "tests/fakes/model.py", "vendor/model.py"])
def test_nonproduction_and_generated_boundaries(path: str) -> None:
    assert PreferPydanticFieldBounds().check(Path(path), CASES[0][1]) == []


def test_selected_rule_suppression() -> None:
    assert (
        check_source(
            [PreferPydanticFieldBounds()],
            Path("app/model.py"),
            {case_id: source for case_id, source, _ in CASES}["suppressed"],
        )
        == []
    )
