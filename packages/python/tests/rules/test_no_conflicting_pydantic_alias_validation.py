from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_conflicting_pydantic_alias_validation import NoConflictingPydanticAliasValidation


if TYPE_CHECKING:
    from pathlib import Path


_PREFIX = "from pydantic import BaseModel, ConfigDict\n"


@pytest.mark.parametrize(
    ("config", "count"),
    [
        pytest.param("ConfigDict(validate_by_alias=False, validate_by_name=False)", 1, id="disabled"),
        pytest.param("{'validate_by_alias': False, 'validate_by_name': False}", 1, id="dict"),
        pytest.param("ConfigDict(validate_by_name=False, validate_by_alias=False)", 1, id="order"),
        pytest.param("ConfigDict(validate_by_alias=True, validate_by_name=False)", 0, id="alias-enabled"),
        pytest.param("ConfigDict(validate_by_alias=False, validate_by_name=True)", 0, id="name-enabled"),
        pytest.param("ConfigDict(validate_by_alias=False)", 0, id="implicit-fallback"),
        pytest.param("ConfigDict(validate_by_name=False)", 0, id="default-alias"),
        pytest.param("ConfigDict(validate_by_alias=flag, validate_by_name=False)", 0, id="dynamic"),
        pytest.param("ConfigDict(validate_by_alias=False, validate_by_name=False, **options)", 0, id="unpack"),
        pytest.param("{'validate_by_alias': False, 'validate_by_name': False, **options}", 0, id="dict-unpack"),
        pytest.param(
            "{'validate_by_alias': False, 'validate_by_name': False, 'validate_by_name': True}", 0, id="duplicate"
        ),
        pytest.param("settings", 0, id="opaque"),
    ],
)
def test_validation_paths(tmp_path: Path, config: str, count: int) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="example"\nversion="0.1"\ndependencies=["pydantic>=2.11"]\n'
    )
    source = _PREFIX + f"class Model(BaseModel):\n    model_config = {config}\n    value: int\n"
    assert len(NoConflictingPydanticAliasValidation().check(tmp_path / "models.py", source)) == count


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "class Model(Parent):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)",
            id="unknown-parent",
        ),
        pytest.param(
            "@adapt\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)",
            id="class-wrapper",
        ),
        pytest.param(
            "class Model(BaseModel, validate_by_name=True):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)",
            id="keyword-override",
        ),
        pytest.param(
            "class Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n    model_config = ConfigDict(validate_by_name=True)",
            id="overwritten-config",
        ),
        pytest.param(
            "class Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)  # sarj-noqa: SARJ493 -- invalid schema fixture",
            id="suppression",
        ),
        pytest.param(
            "class Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n    model_config['validate_by_name'] = True",
            id="mutation",
        ),
        pytest.param(
            "# @generated\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)",
            id="generated",
        ),
        pytest.param(
            "from typing import ClassVar\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n    _change: ClassVar[None] = model_config.update(validate_by_name=True)",
            id="indirect-config-mutation",
        ),
    ],
)
def test_uncertain_configurations(tmp_path: Path, body: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="example"\nversion="0.1"\ndependencies=["pydantic==2.14.0"]\n'
    )
    assert not NoConflictingPydanticAliasValidation().check(
        tmp_path / "models.py",
        ("# @generated\n" + _PREFIX + body.removeprefix("# @generated\n"))
        if body.startswith("# @generated")
        else _PREFIX + body,
    )


@pytest.mark.parametrize("dependency", ["pydantic<2.11", "pydantic>=2", "pydantic"], ids=["old", "broad", "unbounded"])
def test_version_boundary(tmp_path: Path, dependency: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname="example"\nversion="0.1"\ndependencies=["{dependency}"]\n'
    )
    source = (
        _PREFIX
        + "class Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n"
    )
    assert not NoConflictingPydanticAliasValidation().check(tmp_path / "models.py", source)


def test_documented_examples() -> None:
    verify_native_rule(NoConflictingPydanticAliasValidation, analyze)
