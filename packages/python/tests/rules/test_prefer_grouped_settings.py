from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.prefer_grouped_settings import PreferGroupedSettings


_FLAT = (
    "from pydantic_settings import BaseSettings\n"
    "class Settings(BaseSettings):\n"
    "    embedder_url: str\n"
    "    embedder_token: str\n"
)
_CASES = (
    EvaluationCase("flat-component", Language.PYTHON, _FLAT, ExpectedOutcome.MATCH),
    EvaluationCase(
        "three-fields-one-group", Language.PYTHON, _FLAT + "    embedder_timeout: float\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "aliased-base",
        Language.PYTHON,
        _FLAT.replace("import BaseSettings", "import BaseSettings as Configuration").replace(
            "Settings(BaseSettings)", "Settings(Configuration)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified-base",
        Language.PYTHON,
        _FLAT.replace("from pydantic_settings import BaseSettings", "import pydantic_settings as config").replace(
            "Settings(BaseSettings)", "Settings(config.BaseSettings)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "local-inherited-settings",
        Language.PYTHON,
        _FLAT.replace(
            "class Settings(BaseSettings):", "class Common(BaseSettings):\n    enabled: bool\nclass Settings(Common):"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-env-alias-only",
        Language.PYTHON,
        "from pydantic import Field\nfrom pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    url: str = Field(alias='EMBEDDER_URL')\n    token: str = Field(alias='EMBEDDER_TOKEN')\n",
    ),
    EvaluationCase(
        "unrelated-model",
        Language.PYTHON,
        _FLAT.replace("pydantic_settings import BaseSettings", "pydantic import BaseModel as BaseSettings"),
    ),
    EvaluationCase("ordinary-class", Language.PYTHON, _FLAT.replace("class Settings(BaseSettings)", "class Settings")),
    EvaluationCase("unknown-base", Language.PYTHON, _FLAT.replace("pydantic_settings", "custom_settings")),
    EvaluationCase("single-prefixed-field", Language.PYTHON, _FLAT.replace("    embedder_token: str\n", "")),
    EvaluationCase(
        "character-prefix-is-not-namespace", Language.PYTHON, _FLAT.replace("embedder_url", "embedding_url")
    ),
    EvaluationCase("private-field", Language.PYTHON, _FLAT.replace("embedder_token", "_embedder_token")),
    EvaluationCase(
        "classvar-field",
        Language.PYTHON,
        "from typing import ClassVar\n" + _FLAT.replace("embedder_token: str", "embedder_token: ClassVar[str]"),
    ),
    EvaluationCase(
        "final-field",
        Language.PYTHON,
        "from typing import Final\n" + _FLAT.replace("embedder_token: str", "embedder_token: Final[str]"),
    ),
    EvaluationCase("existing-prefix-field", Language.PYTHON, _FLAT + "    embedder: str\n"),
    EvaluationCase(
        "generic-bound-modifiers",
        Language.PYTHON,
        _FLAT.replace("embedder_url", "max_calls").replace("embedder_token", "max_retries"),
    ),
    EvaluationCase(
        "generic-boolean-modifiers",
        Language.PYTHON,
        _FLAT.replace("embedder_url", "is_ready").replace("embedder_token", "is_enabled"),
    ),
    EvaluationCase("equivalent-redeclaration", Language.PYTHON, _FLAT.replace("embedder_token", "embedder_url")),
    EvaluationCase(
        "class-suppression",
        Language.PYTHON,
        _FLAT.replace(
            "class Settings(BaseSettings):",
            "class Settings(BaseSettings):  # sarj-noqa: SARJ532 -- fixed public configuration API",
        ),
    ),
    EvaluationCase(
        "first-field-suppression",
        Language.PYTHON,
        _FLAT.replace("embedder_url: str", "embedder_url: str  # sarj-noqa: SARJ532 -- fixed public configuration API"),
    ),
    EvaluationCase(
        "unknown-decorator", Language.PYTHON, _FLAT.replace("class Settings", "@rewrites_fields\nclass Settings")
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _FLAT),
    EvaluationCase("malformed", Language.PYTHON, "class Settings(:"),
)


def test_documented_examples() -> None:
    verify_native_rule(PreferGroupedSettings, analyze)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_settings_namespace_cases(case: EvaluationCase) -> None:
    findings = PreferGroupedSettings().check(Path("app/settings.py"), case.source)
    expected = ["SARJ532"] if case.expected == ExpectedOutcome.MATCH else []
    assert [finding.code for finding in findings] == expected
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_each_component_has_one_stable_diagnostic() -> None:
    source = _FLAT + "    database_host: str\n    database_port: int\n"
    findings = PreferGroupedSettings().check(Path("app/config.py"), source)
    assert [(finding.line, finding.col) for finding in findings] == [(3, 5), (5, 5)]
    assert len({(finding.line, finding.col) for finding in findings}) == 2


def test_test_settings_fixtures_are_excluded() -> None:
    assert PreferGroupedSettings().check(Path("tests/test_settings.py"), _FLAT) == []


def test_only_owned_fields_form_a_new_group() -> None:
    source = _FLAT.replace(
        "class Settings(BaseSettings):\n    embedder_url: str\n",
        "class Common(BaseSettings):\n    embedder_url: str\nclass Settings(Common):\n",
    )
    assert PreferGroupedSettings().check(Path("app/settings.py"), source) == []


def test_imported_settings_base_is_resolved_in_the_project(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    init = package / "__init__.py"
    init.write_text("")
    base = package / "base.py"
    base.write_text("from pydantic_settings import BaseSettings\nclass Common(BaseSettings):\n    enabled: bool\n")
    settings = package / "settings.py"
    settings.write_text(
        _FLAT.replace("from pydantic_settings import BaseSettings", "from app.base import Common as BaseSettings")
    )
    sources = {path: path.read_text() for path in (init, base, settings)}
    rule = PreferGroupedSettings()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(settings, sources[settings])] == ["SARJ532"]
