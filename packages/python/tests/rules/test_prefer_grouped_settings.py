import ast
import cProfile
from pathlib import Path
import subprocess
import sys

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit
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
    assert all(finding.severity is Severity.ERROR for finding in findings)


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


_ADDITIONAL_CASES = (
    EvaluationCase(
        "dedicated-provider-is-already-nested",
        Language.PYTHON,
        "from pydantic_settings import BaseSettings\n"
        "class ZohoSettings(BaseSettings):\n"
        "    zoho_client_id: str\n"
        "    zoho_client_secret: str\n"
        "class Settings(BaseSettings):\n"
        "    zoho: ZohoSettings\n",
    ),
    EvaluationCase(
        "already-focused-settings-wrapper",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class ComponentSettings")
        + "class Parent(BaseSettings):\n    embedder_settings: ComponentSettings\n",
    ),
    EvaluationCase(
        "already-focused-config-wrapper",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class ComponentSettings")
        + "class Parent(BaseSettings):\n    embedder_config: ComponentSettings\n",
    ),
    EvaluationCase(
        "already-focused-provider-wrapper",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class ComponentSettings")
        + "class Parent(BaseSettings):\n    provider: ComponentSettings\n",
    ),
    EvaluationCase(
        "matching-parent-already-groups-a-mixed-child",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class KnowledgeBaseSettings")
        + "    whole_kb_max_tokens: int\n"
        + "class Parent(BaseSettings):\n    embedder: KnowledgeBaseSettings\n",
    ),
    EvaluationCase(
        "matching-parent-already-groups-a-provider-with-an-enabled-flag",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class BackendSettings")
        + "    enabled: bool\n"
        + "class Parent(BaseSettings):\n    embedder: BackendSettings\n",
    ),
    EvaluationCase(
        "provider-wrapper-keeps-a-bare-scalar-enabled-flag",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class BackendSettings")
        + "    enabled: bool\n"
        + "class Parent(BaseSettings):\n    provider: BackendSettings\n",
    ),
    EvaluationCase(
        "provider-wrapper-retains-a-bare-nested-competing-component",
        Language.PYTHON,
        _FLAT.replace(
            "class Settings(BaseSettings):",
            "class DatabaseSettings(BaseSettings):\n    host: str\nclass BackendSettings(BaseSettings):",
        )
        + "    database: DatabaseSettings\n"
        + "class Parent(BaseSettings):\n    provider: BackendSettings\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dedicated-owner-is-not-inferred-from-class-name",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class EmbedderSettings"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "generic-expectation-modifier",
        Language.PYTHON,
        _FLAT.replace("embedder_url", "expected_issuer").replace("embedder_token", "expected_audience"),
    ),
    EvaluationCase(
        "generic-use-modifier",
        Language.PYTHON,
        _FLAT.replace("embedder_url: str", "use_cache: bool").replace("embedder_token: str", "use_tls: bool"),
    ),
    EvaluationCase(
        "different-cloud-components-are-already-nested",
        Language.PYTHON,
        "from pydantic_settings import BaseSettings\n"
        "class CloudTasksSettings(BaseSettings):\n"
        "    queue: str\n"
        "class Settings(BaseSettings):\n"
        "    cloud_run_revision: str\n"
        "    cloud_tasks: CloudTasksSettings\n",
    ),
    EvaluationCase(
        "nested-provider-siblings-are-not-flat",
        Language.PYTHON,
        "from pydantic_settings import BaseSettings\n"
        "class PollySettings(BaseSettings):\n"
        "    region: str\n"
        "class TranscribeSettings(BaseSettings):\n"
        "    region: str\n"
        "class Settings(BaseSettings):\n"
        "    aws_polly: PollySettings\n"
        "    aws_transcribe: TranscribeSettings\n",
    ),
    EvaluationCase(
        "nested-field-does-not-erase-two-flat-fields",
        Language.PYTHON,
        "from pydantic_settings import BaseSettings\n"
        "class TasksSettings(BaseSettings):\n"
        "    queue: str\n"
        "class Settings(BaseSettings):\n"
        "    cloud_tasks: TasksSettings\n"
        "    cloud_project: str\n"
        "    cloud_region: str\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "multiword-python-namespace",
        Language.PYTHON,
        _FLAT.replace("embedder_", "vector_database_"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "environment-aliases-do-not-erase-python-namespace",
        Language.PYTHON,
        "from pydantic import Field\n"
        + _FLAT.replace("embedder_url: str", "embedder_url: str = Field(alias='FIRST_URL')").replace(
            "embedder_token: str", "embedder_token: str = Field(alias='SECOND_TOKEN')"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "homogeneous-child-is-focused-independent-of-parent-field-name",
        Language.PYTHON,
        _FLAT + "class Parent(BaseSettings):\n    other: Settings\n",
    ),
    EvaluationCase(
        "ordinary-parent-does-not-prove-settings-ownership",
        Language.PYTHON,
        _FLAT + "class Parent:\n    embedder: Settings\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unknown-parent-does-not-prove-settings-ownership",
        Language.PYTHON,
        _FLAT + "class Parent(UnknownSettings):\n    embedder: Settings\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "decorated-parent-does-not-prove-settings-ownership",
        Language.PYTHON,
        _FLAT + "@rewrites_fields\nclass Parent(BaseSettings):\n    embedder: Settings\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "different-subcomponent-still-needs-grouping",
        Language.PYTHON,
        _FLAT.replace("class Settings", "class KnowledgeBaseSettings")
        + "    whole_kb_max_tokens: int\n"
        + "class Parent(BaseSettings):\n    knowledge_base: KnowledgeBaseSettings\n",
        ExpectedOutcome.MATCH,
    ),
)


@pytest.mark.parametrize("case", _ADDITIONAL_CASES, ids=tuple(case.case_id for case in _ADDITIONAL_CASES))
def test_grouping_precision_and_error_cases(case: EvaluationCase) -> None:
    findings = PreferGroupedSettings().check(Path("app/settings.py"), case.source)
    expected = ["SARJ532"] if case.expected == ExpectedOutcome.MATCH else []
    assert [finding.code for finding in findings] == expected
    assert all(finding.severity is Severity.ERROR for finding in findings)


def test_imported_component_is_already_owned_by_its_matching_parent_field(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    init = package / "__init__.py"
    init.write_text("")
    component = package / "component.py"
    component.write_text(_FLAT.replace("class Settings", "class EmbedderSettings"))
    parent = package / "settings.py"
    parent.write_text(
        "from pydantic_settings import BaseSettings\n"
        "from app.component import EmbedderSettings as Provider\n"
        "class Settings(BaseSettings):\n"
        "    embedder: Provider | None = None\n"
    )
    sources = {path: path.read_text() for path in (init, component, parent)}
    rule = PreferGroupedSettings()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert rule.check(component, sources[component]) == []
    assert rule.check(parent, sources[parent]) == []


@pytest.mark.parametrize(
    ("parent_source", "parent_filename"),
    [
        (
            "class OtherSettings(BaseSettings):\n    url: str\nclass Parent(BaseSettings):\n    embedder: OtherSettings\n",
            "parent.py",
        ),
        ("class Parent(UnknownSettings):\n    embedder: Provider\n", "parent.py"),
        ("@rewrites_fields\nclass Parent(BaseSettings):\n    embedder: Provider\n", "parent.py"),
        ("class Parent(BaseSettings):\n    embedder: Provider\n", "test_parent.py"),
        ("# @generated\nclass Parent(BaseSettings):\n    embedder: Provider\n", "parent.py"),
        (
            ("class Parent(BaseSettings):\n    Provider: ClassVar[type[str]] = str\n    embedder: Provider\n"),
            "parent.py",
        ),
    ],
    ids=("different-child", "unknown-base", "decorator", "test-source", "generated-source", "shadowed-annotation"),
)
def test_unproven_cross_file_parent_does_not_erase_flat_group(
    tmp_path: Path, parent_source: str, parent_filename: str
) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    init = package / "__init__.py"
    init.write_text("")
    component = package / "component.py"
    component.write_text(_FLAT.replace("class Settings", "class EmbedderSettings"))
    parent = package / parent_filename
    header = "# @generated\n" if parent_source.startswith("# @generated\n") else ""
    parent.write_text(
        header + "from typing import ClassVar\n"
        "from pydantic_settings import BaseSettings\n"
        "from app.component import EmbedderSettings as Provider\n" + parent_source.removeprefix(header)
    )
    sources = {path: path.read_text() for path in (init, component, parent)}
    rule = PreferGroupedSettings()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert [finding.code for finding in rule.check(component, sources[component])] == ["SARJ532"]


def test_nested_ownership_scan_is_shared_across_files_and_invalidates_with_source(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    sources = {
        package / "__init__.py": "",
        package / "first.py": _FLAT.replace("class Settings", "class FirstSettings").replace("embedder_", "first_"),
        package / "second.py": _FLAT.replace("class Settings", "class SecondSettings").replace("embedder_", "second_"),
        package / "orphan.py": _FLAT.replace("class Settings", "class OrphanSettings"),
        package / "parent.py": (
            "from pydantic_settings import BaseSettings\n"
            "from app.first import FirstSettings\n"
            "from app.second import SecondSettings\n"
            "class Parent(BaseSettings):\n"
            "    first: FirstSettings\n"
            "    second: SecondSettings\n"
        ),
    }
    for path, source in sources.items():
        path.write_text(source)
    indexes = ProjectIndexSet.build(list(sources), sources)
    profile = cProfile.Profile()

    def snapshot_calls() -> int:
        return sum(
            entry.callcount for entry in profile.getstats() if entry.code is ProjectIndexSet.source_snapshot.__code__
        )

    rule = PreferGroupedSettings()
    rule.prepare(indexes)
    with profile:
        for _ in range(2):
            assert rule.check(package / "first.py", sources[package / "first.py"]) == []
            assert rule.check(package / "second.py", sources[package / "second.py"]) == []
            assert [finding.code for finding in rule.check(package / "orphan.py", sources[package / "orphan.py"])] == [
                "SARJ532"
            ]
    assert snapshot_calls() == 1

    parent = indexes.unit(package / "parent.py")
    assert parent is not None
    changed_source = parent.source.replace("    first: FirstSettings", "    first: str")
    changed = indexes.with_unit(
        SourceUnit(parent.path, parent.module, changed_source, ast.parse(changed_source), parent.imports)
    )
    changed_context = PythonFileContext(package / "first.py", sources[package / "first.py"])
    changed_context.session.project = changed
    with profile:
        assert [finding.code for finding in rule.check_context(changed_context)] == ["SARJ532"]
    assert snapshot_calls() == 2

    rule.prepare(indexes)
    with profile:
        assert rule.check(package / "first.py", sources[package / "first.py"]) == []
    assert snapshot_calls() == 3
    rule.prepare(changed)
    with profile:
        assert [finding.code for finding in rule.check(package / "first.py", sources[package / "first.py"])] == [
            "SARJ532"
        ]
    assert snapshot_calls() == 4


def _metamorphic_cases() -> tuple[tuple[Path, EvaluationCase], ...]:
    cases: list[tuple[Path, EvaluationCase]] = []
    for prefix in (
        "embedder",
        "vector",
        "database",
        "search",
        "billing",
        "cache",
        "telemetry",
        "storage",
        "webhook",
        "speech",
    ):
        flat = _FLAT.replace("embedder_", f"{prefix}_")
        scenarios = (
            ("flat", Path("app/settings.py"), flat, ExpectedOutcome.MATCH),
            (
                "import-alias",
                Path("app/settings.py"),
                flat.replace("import BaseSettings", "import BaseSettings as Configuration").replace(
                    "Settings(BaseSettings)", "Settings(Configuration)"
                ),
                ExpectedOutcome.MATCH,
            ),
            (
                "focused-owner",
                Path("app/settings.py"),
                flat.replace("class Settings", "class ComponentSettings")
                + f"class Parent(BaseSettings):\n    {prefix}: ComponentSettings\n",
                ExpectedOutcome.NO_MATCH,
            ),
            (
                "nested-fields",
                Path("app/settings.py"),
                (
                    "from pydantic_settings import BaseSettings\n"
                    "class FirstSettings(BaseSettings):\n    url: str\n"
                    "class SecondSettings(BaseSettings):\n    token: str\n"
                    "class Settings(BaseSettings):\n"
                    f"    {prefix}_first: FirstSettings\n    {prefix}_second: SecondSettings\n"
                ),
                ExpectedOutcome.NO_MATCH,
            ),
            (
                "unknown-base",
                Path("app/settings.py"),
                flat.replace("pydantic_settings", "custom_settings"),
                ExpectedOutcome.NO_MATCH,
            ),
            ("test-source", Path("tests/test_settings.py"), flat, ExpectedOutcome.NO_MATCH),
            ("generated", Path("app/settings.py"), "# @generated\n" + flat, ExpectedOutcome.NO_MATCH),
            (
                "field-suppression",
                Path("app/settings.py"),
                flat.replace(
                    f"{prefix}_url: str",
                    f"{prefix}_url: str  # sarj-noqa: SARJ532 -- fixed public configuration API",
                ),
                ExpectedOutcome.NO_MATCH,
            ),
            (
                "env-alias-only",
                Path("app/settings.py"),
                (
                    "from pydantic import Field\nfrom pydantic_settings import BaseSettings\n"
                    "class Settings(BaseSettings):\n"
                    f"    url: str = Field(alias='{prefix.upper()}_URL')\n"
                    f"    token: str = Field(alias='{prefix.upper()}_TOKEN')\n"
                ),
                ExpectedOutcome.NO_MATCH,
            ),
            (
                "expectation-modifier",
                Path("app/settings.py"),
                flat.replace(f"{prefix}_url", f"expected_{prefix}").replace(f"{prefix}_token", "expected_audience"),
                ExpectedOutcome.NO_MATCH,
            ),
        )
        cases.extend(
            (path, EvaluationCase(f"{prefix}-{name}", Language.PYTHON, source, expected))
            for name, path, source, expected in scenarios
        )
    return tuple(cases)


_METAMORPHIC_CASES = _metamorphic_cases()


@pytest.mark.parametrize(
    ("path", "case"), _METAMORPHIC_CASES, ids=tuple(case.case_id for _, case in _METAMORPHIC_CASES)
)
def test_distinct_settings_metamorphic_cases(path: Path, case: EvaluationCase) -> None:
    findings = PreferGroupedSettings().check(path, case.source)
    expected = ["SARJ532"] if case.expected == ExpectedOutcome.MATCH else []
    assert [finding.code for finding in findings] == expected
    assert all(finding.severity is Severity.ERROR for finding in findings)


def test_rule_registry_starts_from_a_cold_native_python_process(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_python_lint", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("sarj-python-lint ")
