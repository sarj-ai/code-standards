from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest
from sarj_python_lint.__main__ import analyze

from sarj_standards import (
    __version__,
    _meta,  # sarj-noqa: SARJ048 — source-tree fallback is under test
)
from sarj_standards._meta import (
    BASEDPYRIGHT_PYTHON315_WATCH,
    BASEDPYRIGHT_STRICT,
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_PYTHON315_WATCH,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
)
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Severity
from sarj_standards.libs.linting.external import parse_basedpyright
from sarj_standards.libs.repository import config_generation


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

_PUBLIC_CONFIGS = (
    RUFF_STRICT,
    RUFF_APPLICATION,
    PYRIGHT_STRICT,
    BASEDPYRIGHT_STRICT,
    ESLINT_STRICT,
    ESLINT_APPLICATION,
    CONFIGS_DIR / "rule-ledger.json",
)
_PRIVATE_TELEMETRY = {
    "anonymized repository label": re.compile(r"\brepo\s+[A-Z]\b"),
    "home-relative path": re.compile(r"(?<!\w)~/"),
    "evaluation corpus provenance": re.compile(r"\bcorpus(?:-wide)?\b", re.IGNORECASE),
    "repository fleet description": re.compile(
        r"\b(?:consumer|first-party|private)\s+repos(?:itories)?\b",
        re.IGNORECASE,
    ),
    "repository measurement": re.compile(
        r"\b\d[\d,]*(?:\.\d+)?%?\s+(?:findings|files|sites|repos(?:itories)?)\b",
        re.IGNORECASE,
    ),
    "operational incident detail": re.compile(
        r"\b(?:prod|production)\s+(?:incident|outage)s?\b",
        re.IGNORECASE,
    ),
    "product or dependency context": re.compile(r"\b(?:arabic|livekit)\b", re.IGNORECASE),
}

#: Expected fallback independent of the module under test.
_SOURCE_TREE_VERSION = "0.0.0.dev0"


def test_version_string() -> None:
    declared = tomllib.loads((_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == declared["project"]["version"]


def test_an_uninstalled_source_tree_reports_a_dev_version() -> None:
    real = importlib.metadata.version

    def _absent(distribution_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(distribution_name)

    importlib.metadata.version = _absent
    try:
        importlib.reload(_meta)
    finally:
        importlib.metadata.version = real
    assert _meta.__version__ == _SOURCE_TREE_VERSION
    importlib.reload(_meta)
    assert _meta.__version__ == __version__


def test_configs_dir_exists() -> None:
    assert CONFIGS_DIR.is_dir(), f"missing: {CONFIGS_DIR}"


@pytest.mark.parametrize(
    "path",
    [
        RUFF_STRICT,
        PYRIGHT_STRICT,
        BASEDPYRIGHT_STRICT,
        ESLINT_STRICT,
        MARKDOWNLINT_STRICT,
        TAPLO_STRICT,
        YAMLLINT_STRICT,
    ],
)
def test_all_blocking_configs_bundled(path: Path) -> None:
    assert path.is_file(), f"missing bundled config: {path}"
    assert path.stat().st_size > 0


@pytest.mark.parametrize(
    "path",
    [RUFF_APPLICATION, ESLINT_APPLICATION, RUFF_PYTHON315_WATCH, BASEDPYRIGHT_PYTHON315_WATCH],
)
def test_application_configs_bundled(path: Path) -> None:
    assert path.is_file(), f"missing bundled application config: {path}"
    assert path.stat().st_size > 0


def test_public_configs_do_not_ship_repository_telemetry() -> None:
    violations: list[str] = []
    for path in _PUBLIC_CONFIGS:
        text = path.read_text(encoding="utf-8")
        for description, pattern in _PRIVATE_TELEMETRY.items():
            if pattern.search(text) is not None:
                violations.append(f"{path.name}: {description}")

    assert violations == []


def test_application_configs_have_no_generation_drift() -> None:
    assert config_generation.sync(check=True)


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION])
def test_ruff_combines_aliased_imports(config: Path) -> None:
    parsed = manifest.as_table(tomllib.loads(config.read_text(encoding="utf-8")))
    if config == RUFF_APPLICATION:
        assert parsed == {"extend": RUFF_STRICT.name}
        parsed = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text(encoding="utf-8")))
    lint = manifest.table_field(parsed, "lint")
    isort = manifest.table_field(lint, "isort")
    assert isort["combine-as-imports"] is True


def test_ruff_accepts_explicit_public_reexports_without_weakening_f401(tmp_path: Path) -> None:
    parsed = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text(encoding="utf-8")))
    lint = manifest.table_field(parsed, "lint")
    ignored = set(manifest.list_field(lint, "ignore"))
    assert "PLC0414" in ignored
    assert {"F401", "I001"}.isdisjoint(ignored)

    source = tmp_path / "exports.py"
    source.write_text(
        "from example import Public as Public\nfrom unused import value\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--config",
            str(RUFF_STRICT),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count('"code": "F401"') == 1
    assert '"code": "PLC0414"' not in result.stdout


def test_legacy_ruff_config_aliases_have_identical_enforcement() -> None:
    assert tomllib.loads(RUFF_APPLICATION.read_text()) == {"extend": RUFF_STRICT.name}
    assert 'export { createConfig, default } from "./eslint.strict.mjs";' in ESLINT_APPLICATION.read_text()


def test_all_managed_configs_enforce_library_catalog() -> None:
    application_ruff = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text()))
    application_lint = manifest.table_field(application_ruff, "lint")
    application_tidy = manifest.table_field(application_lint, "flake8-tidy-imports")
    application_bans = manifest.table_field(application_tidy, "banned-api")
    standard_ruff = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text()))
    standard_lint = manifest.table_field(standard_ruff, "lint")
    standard_tidy = manifest.table_field(standard_lint, "flake8-tidy-imports")
    standard_bans = manifest.table_field(standard_tidy, "banned-api")
    assert "argparse" in application_bans
    assert "pandas" in application_bans
    assert "argparse" in standard_bans
    assert "pandas" in standard_bans

    application_eslint = ESLINT_STRICT.read_text()
    standard_eslint = ESLINT_STRICT.read_text()
    assert '"name": "axios"' in application_eslint
    assert '"name": "lodash"' in application_eslint
    assert 'name: "@clerk/nextjs"' in application_eslint
    assert '"group": ["axios/*"]' in application_eslint
    assert '"@sarj/no-restricted-library-load"' in application_eslint
    assert '"@sarj/prefer-native-random-uuid": "error"' in application_eslint
    assert '"module": "axios"' in application_eslint
    assert '"name": "axios"' in standard_eslint
    assert '"name": "lodash"' in standard_eslint
    assert '"@sarj/no-restricted-library-load"' in standard_eslint


def test_ruff_config_is_valid_toml() -> None:
    text = RUFF_STRICT.read_text()
    data = tomllib.loads(text)  # parses as TOML
    assert "lint" in data
    assert re.search(r'external\s*=\s*\[\s*"SARJ"\s*\]', text)
    assert re.search(r'select\s*=\s*\[\s*"ALL"\s*\]', text)


def test_pyright_allows_directly_awaited_discarded_results() -> None:
    text = PYRIGHT_STRICT.read_text()
    assert '"reportUnusedCallResult": false' in text
    assert '"reportUnusedCoroutine": "error"' in text


def test_requested_ruff_families_remain_globally_enabled() -> None:
    data = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.table_field(manifest.as_table(data), "lint")
    assert manifest.list_field(lint, "select") == ["ALL"]
    assert lint["future-annotations"] is True
    raw_ignored = manifest.list_field(lint, "ignore")
    assert all(isinstance(code, str) for code in raw_ignored)
    ignored = {code for code in raw_ignored if isinstance(code, str)}
    assert not any(
        code.startswith(("ANN", "UP")) or (re.fullmatch(r"F\d+", code) is not None and code != "F822")
        for code in ignored
    )
    assert {"PLC0415", "BLE001"}.isdisjoint(ignored)


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION])
def test_sarj_rule_complements_ruff_dunder_all_validation(config: Path) -> None:
    parsed = manifest.as_table(tomllib.loads(config.read_text(encoding="utf-8")))
    if config == RUFF_APPLICATION:
        assert parsed == {"extend": RUFF_STRICT.name}
        parsed = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text(encoding="utf-8")))
    lint = manifest.table_field(parsed, "lint")
    assert {"F822", "RUF022"}.isdisjoint(manifest.list_field(lint, "ignore"))

    raw_inventory: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
        (CONFIGS_DIR / "rule-inventory.v1.json").read_text(encoding="utf-8"),
    )
    inventory = manifest.as_table(raw_inventory)
    rules = [manifest.as_table(value) for value in manifest.list_field(inventory, "rules")]
    assert any(
        manifest.text_field(rule, "code") == "SARJ438"
        and manifest.text_field(rule, "family") == "python"
        and manifest.text_field(rule, "id") == "no-dunder-all"
        for rule in rules
    )


def test_ruff_rejects_quoted_type_checking_union_annotations(tmp_path: Path) -> None:
    source = tmp_path / "context.py"
    source.write_text(
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from example import BatchId, ScenarioId\n\n\n"
        "class Context:\n"
        '    agent_id: "ScenarioId | None"\n'
        '    batch_id: "BatchId | None" = None\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            "UP037",
            "--config",
            str(RUFF_STRICT),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count('"code": "UP037"') == 2


def test_ruff_requires_match_for_broad_builtin_warning_categories(tmp_path: Path) -> None:
    source = tmp_path / "test_warnings.py"
    source.write_text(
        "import pytest\n\n"
        "class DomainWarning(Warning):\n"
        "    pass\n\n"
        "def emit_warning() -> None:\n"
        "    pass\n\n"
        "def test_broad_warning() -> None:\n"
        "    with pytest.warns(RuntimeWarning):\n"
        "        emit_warning()\n\n"
        "def test_matched_warning() -> None:\n"
        '    with pytest.warns(RuntimeWarning, match="overflow"):\n'
        "        emit_warning()\n\n"
        "def test_specific_warning() -> None:\n"
        "    with pytest.warns(DomainWarning):\n"
        "        emit_warning()\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            "PT030",
            "--config",
            str(RUFF_STRICT),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count('"code": "PT030"') == 1


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION])
def test_s311_is_owned_by_sarj410_in_every_supported_python_test_path(config: Path) -> None:
    data = manifest.as_table(tomllib.loads(config.read_text(encoding="utf-8")))
    if config == RUFF_APPLICATION:
        assert data == {"extend": RUFF_STRICT.name}
        data = manifest.as_table(tomllib.loads(RUFF_STRICT.read_text(encoding="utf-8")))
    lint = manifest.table_field(data, "lint")
    per_file = manifest.table_field(lint, "per-file-ignores")
    patterns = {
        "**/tests/**",
        "**/test/**",
        "**/integration_tests/**",
        "**/test_*.py",
        "**/*_test.py",
        "**/conftest.py",
    }
    assert all("S311" in manifest.list_field(per_file, pattern) for pattern in patterns)
    assert "S311" not in manifest.list_field(lint, "ignore")


def test_random_sampling_has_one_owner_in_tests_and_production(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_sampling.py"
    production_file = tmp_path / "src" / "sampling.py"
    test_file.parent.mkdir()
    production_file.parent.mkdir()
    test_file.write_text(
        "import random\n\n\ndef test_sampling() -> None:\n"
        "    samples = [random.random() for _ in range(10)]\n"
        "    assert len(samples) == 10\n",
        encoding="utf-8",
    )
    production_file.write_text(
        "import random\n\n\ndef sample() -> float:\n    return random.random()\n",
        encoding="utf-8",
    )

    ruff = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            "S311",
            "--config",
            str(RUFF_STRICT),
            str(test_file),
            str(production_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    sarj = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_python_lint",
            "check",
            "--rule",
            "no-repeated-unseeded-stdlib-random-in-test",
            str(test_file),
            str(production_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert ruff.returncode == 1, ruff.stdout + ruff.stderr
    assert ruff.stdout.count('"code": "S311"') == 1
    assert str(production_file) in ruff.stdout
    assert str(test_file) not in ruff.stdout
    assert sarj.returncode == 1, sarj.stdout + sarj.stderr
    assert sarj.stdout.count("SARJ410") == 1
    assert "random.Random(seed)" in sarj.stdout
    assert str(test_file) in sarj.stdout
    assert str(production_file) not in sarj.stdout


def test_ruff_formatter_does_not_rewrite_markdown() -> None:
    data = tomllib.loads(RUFF_STRICT.read_text())
    assert data["format"]["exclude"] == ["*.md"]


def test_pyright_config_is_valid_jsonc() -> None:
    # pyright loads its config as JSONC; a bare-key .toml is silently ignored by
    # `extends`, so the strict pyright config must ship as JSON(C), not TOML.
    raw = PYRIGHT_STRICT.read_text()
    assert isinstance(json.loads(re.sub(r"//.*", "", raw)), dict)  # parses as JSON(C)
    assert re.search(r'"typeCheckingMode"\s*:\s*"strict"', raw)
    assert '"reportExplicitAny"' not in raw
    based = BASEDPYRIGHT_STRICT.read_text()
    assert re.search(r'"reportExplicitAny"\s*:\s*"error"', based)
    assert re.search(r'"enableBasedFeatures"\s*:\s*false', based)
    assert '"allowedUntypedLibraries"' not in based


def test_native_unused_helpers_preserve_test_and_framework_dispatch(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "typeCheckingMode": "basic",
                "reportUnusedFunction": "none",
                "executionEnvironments": [
                    {"root": "tests", "reportUnusedFunction": "warning"},
                    {"root": ".", "reportUnusedFunction": "warning"},
                ],
            }
        )
    )
    source = tests / "test_behavior.py"
    source.write_text(
        "from collections.abc import Callable\n\n"
        "def register(function: Callable[[], int]) -> Callable[[], int]:\n    return function\n\n"
        "def _unused() -> int:\n    return 1\n\n"
        "def _used() -> int:\n    return 2\n\n"
        "@register\ndef _callback() -> int:\n    return 3\n\n"
        "def test_result() -> None:\n    assert _used() == 2\n"
    )
    (tmp_path / "production.py").write_text("def _dispatch() -> int:\n    return 4\n")

    proc = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--outputjson"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    findings = parse_basedpyright(proc.stdout, root=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert {(item.rule_id, item.severity, item.location.path) for item in findings} == {
        ("reportUnusedFunction", Severity.WARNING, "tests/test_behavior.py"),
        ("reportUnusedFunction", Severity.WARNING, "production.py"),
    }
    assert any("_unused" in item.message for item in findings)


def test_native_fixture_audit_tracks_runtime_requests_and_exposes_incomplete_profile_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert importlib.metadata.version("pytest-unused-fixtures") == "0.3.1"
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    (tmp_path / "conftest.py").write_text("import pytest\n@pytest.fixture\ndef root_support():\n    return True\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(
        "import pytest\n"
        "@pytest.fixture\ndef _unrequested_private():\n    return True\n"
        "@pytest.fixture\ndef skipped_support():\n    return True\n"
        "@pytest.fixture(autouse=True)\ndef active_autouse():\n    yield\n"
        "@pytest.fixture\ndef indirect_support(request):\n    return request.param\n"
        "@pytest.fixture\ndef dynamic_support():\n    return 'requested'\n"
        "@pytest.fixture\ndef marked_support():\n    return True\n"
    )
    (tests / "test_behavior.py").write_text(
        "import pytest\n"
        "@pytest.mark.usefixtures('marked_support')\n"
        "@pytest.mark.parametrize('indirect_support', ['value'], indirect=True)\n"
        "def test_runtime_requests(request, indirect_support):\n"
        "    assert indirect_support == 'value'\n"
        "    assert request.getfixturevalue('dynamic_support') == 'requested'\n"
        "@pytest.mark.skip(reason='optional profile unavailable')\n"
        "def test_optional_profile(skipped_support):\n    assert skipped_support\n"
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_unused_fixtures",
            "--unused-fixtures",
            "-v",
            "--unused-fixtures-context",
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    inactive = set(re.findall(r"^(\w+) -- (?:tests/)?conftest\.py:\d+$", proc.stdout, re.MULTILINE))
    assert inactive == {"root_support", "_unrequested_private", "skipped_support"}
    assert "1 passed, 1 skipped" in proc.stdout


@pytest.mark.parametrize("config", [BASEDPYRIGHT_STRICT, BASEDPYRIGHT_PYTHON315_WATCH])
def test_basedpyright_profiles_load_their_complete_inheritance_chain(config: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--project", str(config), str(_meta.__file__)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "could not be read" not in proc.stdout.casefold()
    assert "could not be read" not in proc.stderr.casefold()
    assert "unrecognized setting" not in proc.stdout.casefold()
    assert "unrecognized setting" not in proc.stderr.casefold()


@pytest.mark.parametrize(
    ("source", "expected_rules"),
    [
        pytest.param(
            "from typing import assert_type\n\n"
            "class _Store:\n"
            "    def read(self) -> int:\n"
            "        return 1\n\n"
            "class Service:\n"
            "    def __init__(self, store: _Store) -> None:\n"
            "        self.store = store\n\n"
            "class _StubClient:\n"
            "    def __init__(self) -> None:\n"
            "        self.store = _Store()\n\n"
            "assert_type(Service(_Store()).store, _Store)\n"
            "assert_type(_StubClient().store.read(), int)\n",
            (),
            id="inferred-dependency-and-local-private-helper",
        ),
        pytest.param(
            "class Service:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value = value\n\n"
            "service = Service(1)\n"
            "service.value = 'invalid'\n",
            ("reportAttributeAccessIssue",),
            id="inferred-member-rejects-external-wrong-type",
        ),
        pytest.param(
            "class Service:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value: int = value\n\n"
            "    def update(self) -> None:\n"
            "        self.value = 'invalid'\n",
            ("reportAttributeAccessIssue",),
            id="declared-invariant-rejects-same-class-widening",
        ),
        pytest.param(
            "class Base:\n    value = 1\n\nclass Derived(Base):\n    value = 'invalid'\n",
            ("reportIncompatibleUnannotatedOverride",),
            id="incompatible-inferred-override",
        ),
        pytest.param(
            "class Service:\n"
            "    def __init__(self) -> None:\n"
            "        self.values = []\n\n"
            "def values(service: Service) -> object:\n"
            "    return service.values\n",
            ("reportUnknownMemberType", "reportUnknownVariableType"),
            id="empty-container-still-needs-element-type",
        ),
    ],
)
def test_basedpyright_inference_and_explicit_contracts(
    tmp_path: Path, source: str, expected_rules: tuple[str, ...]
) -> None:
    fixture = tmp_path / "members.py"
    fixture.write_text(source, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--project", str(BASEDPYRIGHT_STRICT), "--outputjson", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload: object = json.loads(proc.stdout)  # pyright: ignore[reportAny] -- analyzer JSON boundary
    diagnostics = manifest.list_field(manifest.as_table(payload), "generalDiagnostics")
    rules = tuple(manifest.text_field(manifest.as_table(item), "rule") for item in diagnostics)
    assert rules == expected_rules, proc.stdout + proc.stderr
    assert proc.returncode == bool(expected_rules), proc.stdout + proc.stderr


def test_python_visibility_contract_is_explicitly_strict() -> None:
    ruff = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.table_field(manifest.as_table(ruff), "lint")
    ignored = set(manifest.list_field(lint, "ignore"))
    assert {
        "SLF001",
        "N801",
        "N802",
        "N803",
        "N804",
        "N805",
        "N806",
        "N807",
        "N811",
        "N812",
        "N813",
        "N814",
        "N815",
        "N816",
        "N817",
        "N818",
        "N999",
        "F401",
    }.isdisjoint(ignored)
    assert "PLC2701" in ignored

    upstream = PYRIGHT_STRICT.read_text()
    for setting in ("reportPrivateUsage", "reportPrivateImportUsage", "reportUnsupportedDunderAll"):
        assert re.search(rf'"{setting}"\s*:\s*"error"', upstream)
    assert '"reportPrivateLocalImportUsage"' not in upstream
    assert re.search(r'"reportPrivateLocalImportUsage"\s*:\s*"error"', BASEDPYRIGHT_STRICT.read_text())


def test_eslint_config_is_esm() -> None:
    text = ESLINT_STRICT.read_text()
    assert "export default" in text


def test_yamllint_accepts_github_actions_on_key() -> None:
    text = YAMLLINT_STRICT.read_text()
    assert "check-keys: false" in text


def test_taplo_excludes_generated_strict_configs() -> None:
    data = tomllib.loads(TAPLO_STRICT.read_text())
    assert data["exclude"] == ["**/.ruff-strict.toml", "**/.taplo.toml"]


def test_consistent_type_assertions_options_are_schema_compatible() -> None:
    text = ESLINT_STRICT.read_text()
    match = re.search(
        r'"@typescript-eslint/consistent-type-assertions"\s*:\s*\[\s*"error"\s*,\s*\{(?P<options>[^}]*)\}',
        text,
    )
    assert match is not None
    options = match.group("options")
    if 'assertionStyle: "never"' in options:
        assert "objectLiteralTypeAssertions" not in options


def test_eslint_config_avoids_eslint_10_only_unicorn_rules() -> None:
    text = ESLINT_STRICT.read_text()
    assert "prohibitLocalVariables" not in text
    assert '"unicorn/no-array-for-each"' not in text
    assert '"unicorn/no-for-each"' not in text
    assert "CallExpression[callee.property.name='forEach']" in text


def test_prefer_nullish_coalescing_ignores_primitives() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/prefer-nullish-coalescing"\s*:\s*\[\s*"error"\s*,\s*\{[^}]*ignorePrimitives\s*:\s*\{',
        text,
    )


def test_naming_convention_allows_framework_names() -> None:
    text = ESLINT_STRICT.read_text()
    assert re.search(
        r'"@typescript-eslint/naming-convention".+?format:\s*\["camelCase"\].+?filter:\s*\{\s*regex:\s*"\^\(UNSAFE_\|__\)"',
        text,
        re.DOTALL,
    )


def test_eslint_config_does_not_assume_react_compiler() -> None:
    text = ESLINT_STRICT.read_text()
    assert "CallExpression[callee.name='useMemo']" not in text
    assert "CallExpression[callee.name='useCallback']" not in text


def test_cli_list(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "show", "configs"],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    assert "ruff" in proc.stdout
    assert "pyright" in proc.stdout
    assert "eslint" in proc.stdout
    assert "markdownlint" in proc.stdout
    assert "taplo" in proc.stdout
    assert "yamllint" in proc.stdout


def test_cli_path_ruff() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "show", "config", "ruff"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == str(RUFF_STRICT)


def test_cli_unknown_subcommand_exits_nonzero(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "bogus"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode != 0


def test_ruff_ignores_sections_forbidden_by_typed_docstring_policy() -> None:
    parsed: object = tomllib.loads(RUFF_STRICT.read_text())
    lint = manifest.as_table(manifest.as_table(parsed).get("lint"))
    ignored = manifest.list_field(lint, "ignore")

    assert {"DOC201", "DOC402"} <= {item for item in ignored if isinstance(item, str)}


def test_eslint_module_sort_does_not_conflict_with_imports_first() -> None:
    config = ESLINT_STRICT.read_text()

    assert '"perfectionist/sort-modules": "off"' in config
    assert '"perfectionist/sort-objects": "off"' in config


def test_eslint_async_and_void_rules_have_single_authorities() -> None:
    config = ESLINT_STRICT.read_text()

    assert '"@typescript-eslint/promise-function-async": "off"' in config
    assert '"@typescript-eslint/no-inferrable-types": "off"' in config
    assert "{ ignoreArrowShorthand: true }" in config
    assert '"unicorn/no-thenable": "off"' in config
    assert '"unicorn/no-useless-undefined": "off"' in config
    assert '"unicorn/no-useless-switch-case": "off"' in config
    assert '"react/forbid-component-props": "off"' in config
    assert '"react/forbid-dom-props": "off"' in config


@pytest.mark.parametrize("config", [RUFF_STRICT, RUFF_APPLICATION])
@pytest.mark.parametrize(
    ("filename", "source", "custom_count", "native_count"),
    [
        pytest.param(
            "app/models.py",
            'from collections import namedtuple\nRow = namedtuple("Row", ["id", "name"])\n',
            1,
            0,
            id="static-direct-positive",
        ),
        pytest.param(
            "app/models.py",
            'from collections import namedtuple as nt\nRow = nt("Row", ["id", "name"])\n',
            1,
            0,
            id="static-import-alias-positive",
        ),
        pytest.param(
            "app/models.py",
            'from collections import namedtuple\ndef record_from_schema(fields):\n    return namedtuple("Row", fields)\n',
            0,
            0,
            id="dynamic-field-schema-valid",
        ),
        pytest.param(
            "app/models.py",
            'from collections import namedtuple\nRow = namedtuple("Row", ["1st", "class"], rename=True)\n',
            0,
            0,
            id="renamed-external-field-valid",
        ),
        pytest.param(
            "app/models.py",
            'import collections\nclass Row(collections.namedtuple("Row", ["id", "name"])):\n    id: int\n    name: str\n',
            0,
            0,
            id="fully-annotated-subclass-valid",
        ),
        pytest.param(
            "tests/test_namedtuple.py",
            'from collections import namedtuple\nRow = namedtuple("Row", ["id", "name"])\ndef test_record():\n    assert Row(1, "Ada")._fields == ("id", "name")\n',
            0,
            0,
            id="namedtuple-subject-test-valid",
        ),
        pytest.param(
            "app/models.py",
            'import collections\nimport sys\nif sys.version_info < (3, 11):\n    Row = collections.namedtuple("Row", ["id", "name"])\n',
            0,
            0,
            id="compatibility-branch-valid",
        ),
        pytest.param(
            "app/models.py",
            'import collections\ndef record(collections):\n    Row = collections.namedtuple("Row", ["id", "name"])\n    return Row\n',
            0,
            0,
            id="unrelated-parameter-shadow-valid",
        ),
        pytest.param(
            "app/models.pyi",
            'from collections import namedtuple\nRow = namedtuple("Row", ["id", "name"])\n',
            0,
            1,
            id="native-stub-owner",
        ),
        pytest.param(
            "app/models.pyi",
            "from typing import NamedTuple\nclass Row(NamedTuple):\n    id: int\n    name: str\n",
            0,
            0,
            id="typed-stub-valid",
        ),
        pytest.param(
            "app/models.py",
            "from collections import namedtuple\nRow = namedtuple(\n",
            0,
            0,
            id="malformed-abstain",
        ),
    ],
)
def test_namedtuple_policy_has_one_owner_per_source_type(
    tmp_path: Path, *, config: Path, filename: str, source: str, custom_count: int, native_count: int
) -> None:
    fixture = tmp_path / filename
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(source, encoding="utf-8")
    assert len(analyze(["prefer-struct-over-namedtuple"], [fixture])) == custom_count
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "json",
            "--config",
            str(config),
            str(fixture),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    payload: object = json.loads(result.stdout)  # pyright: ignore[reportAny] -- native JSON boundary
    findings = [manifest.as_table(item) for item in manifest.list_field({"findings": payload}, "findings")]
    assert sum(finding.get("code") == "PYI024" for finding in findings) == native_count
