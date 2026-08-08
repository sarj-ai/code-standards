from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_frozen_after_validator_field_write import NoFrozenAfterValidatorFieldWrite


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "models.py"):
    return NoFrozenAfterValidatorFieldWrite().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = NoFrozenAfterValidatorFieldWrite.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoFrozenAfterValidatorFieldWrite().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    ("source", "field", "count"),
    [
        pytest.param(
            """
            from pydantic import BaseModel, ConfigDict, model_validator
            class Model(BaseModel):
                model_config = ConfigDict(frozen=True)
                value: int
                @model_validator(mode="after")
                def normalize(self):
                    self.value = abs(self.value)
                    return self
            """,
            "value",
            1,
            id="direct-assignment",
        ),
        pytest.param(
            """
            import pydantic as pd
            class Model(pd.BaseModel):
                model_config = pd.ConfigDict(extra="forbid", frozen=True)
                count: int
                @pd.model_validator(mode="after")
                def increment(model):
                    model.count += 1
                    return model
            """,
            "count",
            1,
            id="module-alias-augassign-custom-receiver",
        ),
        pytest.param(
            """
            from pydantic import BaseModel as PydanticModel
            from pydantic.config import ConfigDict as ModelConfig
            from pydantic import model_validator as validate_model
            class Model(PydanticModel):
                model_config = ModelConfig(frozen=True)
                first: int
                second: int
                @validate_model(mode="after")
                def normalize(self):
                    self.first, self.second = self.second, self.first
                    return self
            """,
            "first",
            2,
            id="aliased-imports-destructuring",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, ConfigDict, model_validator
            class Model(BaseModel):
                model_config = ConfigDict(frozen=True)
                value: int
                @model_validator(mode="after")
                async def normalize(self):
                    if self.value < 0:
                        self.value = 0
                    return self
            """,
            "value",
            1,
            id="nested-control-flow-async-validator",
        ),
    ],
)
def test_reports_declared_field_writes_in_frozen_after_validators(source: str, field: str, count: int) -> None:
    findings = _check(source)

    assert len(findings) == count
    assert all(finding.code == "SARJ401" for finding in findings)
    assert any(f"`{field}`" in finding.message for finding in findings)


@pytest.mark.parametrize(
    "source",
    [
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=False)
            value: int
            @model_validator(mode="after")
            def normalize(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        FROZEN = True
        class Model(BaseModel):
            model_config = ConfigDict(frozen=FROZEN)
            value: int
            @model_validator(mode="after")
            def normalize(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="before")
            @classmethod
            def normalize(cls, values):
                values["value"] = 1
                return values
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode=validation_mode)
            def normalize(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            @classmethod
            def normalize(cls, value):
                cls.value = 1
                return value
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                local = self.value
                self._cache = local
                self.other = local
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        from typing import ClassVar, Final
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            version: ClassVar[int] = 1
            label: Final[str] = "model"
            @model_validator(mode="after")
            def validate(self):
                self.version = 2
                self.label = "next"
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            items: list[int]
            @model_validator(mode="after")
            def validate(self):
                self.items.append(1)
                object.__setattr__(self, "items", [])
                setattr(self, "items", [])
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                def deferred():
                    self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Parent(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
        class Child(Parent):
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Mixin: pass
        class Model(Mixin, BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, model_validator
        class Model(BaseModel):
            model_config = {"frozen": True}
            value: int
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
        """,
        """
        from not_pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
        """,
        """
        from pydantic import BaseModel, ConfigDict, model_validator
        def model_validator(*args, **kwargs): return lambda value: value
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
        """,
    ],
)
def test_ignores_writes_that_are_not_proven_frozen_field_mutations(source: str) -> None:
    assert _check(source) == []


def test_skips_tests_generated_files_and_malformed_source() -> None:
    source = """
        from pydantic import BaseModel, ConfigDict, model_validator
        class Model(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: int
            @model_validator(mode="after")
            def validate(self):
                self.value = 1
                return self
    """
    assert _check(source, "tests/test_models.py") == []
    assert _check("# generated by schema compiler\n" + dedent(source)) == []
    assert _check("class Broken(") == []
