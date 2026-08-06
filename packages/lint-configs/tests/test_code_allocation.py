"""`SARJ###` is one namespace across three packages, and only this package can see it."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final, Protocol, TypeIs

from pre_commit.clientlib import (
    load_manifest as load_precommit_manifest,  # pyright: ignore[reportUnknownVariableType] -- pre-commit is untyped
)
import pytest
from sarj_iac_lint.rules import REGISTRY as IAC_REGISTRY
from sarj_python_lint.rules import REGISTRY as PYTHON_REGISTRY
from sarj_sql_lint.rules import REGISTRY as SQL_REGISTRY
import yaml

from sarj_lint_configs import manifest
from sarj_lint_configs.textlint import REGISTRY as TEXT_REGISTRY


if TYPE_CHECKING:
    from collections.abc import Mapping


class _Coded(Protocol):
    """The one thing the three packages' unrelated `Rule` base classes share."""

    @property
    def code(self) -> str: ...


_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_PATH = _REPO_ROOT / ".pre-commit-hooks.yaml"

#: Distribution name to (registry, the hundreds digit its codes must use).
_BANDS: Final[Mapping[str, tuple[Mapping[str, _Coded | type[_Coded]], int]]] = {
    "sarj-python-lint": (PYTHON_REGISTRY, 0),
    "sarj-sql-lint": (SQL_REGISTRY, 1),
    "sarj-iac-lint": (IAC_REGISTRY, 2),
    "sarj-lint-configs:text": (TEXT_REGISTRY, 3),
}

_CODE_RE = re.compile(r"^SARJ(\d)(\d{2})$")

#: Sarj distributions must never carry a second version authority in the hook
#: manifest; the consumer's repository revision selects the complete tree.
_VERSIONED_SARJ_RE = re.compile(r"^sarj-[a-z-]+\s*(?:==|>=|~=|<=|>|<)")


@pytest.mark.parametrize("distribution", sorted(_BANDS))
def test_every_code_sits_in_its_packages_band(distribution: str) -> None:
    registry, band = _BANDS[distribution]
    wrong = sorted(
        f"{rule_id} = {cls.code}"
        for rule_id, cls in registry.items()
        if (match := _CODE_RE.match(cls.code)) is None or int(match.group(1)) != band
    )
    assert not wrong, (
        f"{distribution} codes must be SARJ{band}xx, but these are not: {wrong}. "
        "The bands are what keep a bare `# sarj-noqa: SARJ###` unambiguous across linters."
    )


def test_no_two_packages_allocate_the_same_code() -> None:
    owners: dict[str, list[str]] = {}
    for distribution, (registry, _band) in sorted(_BANDS.items()):
        for rule_id, cls in sorted(registry.items()):
            owners.setdefault(cls.code, []).append(f"{distribution}:{rule_id}")
    collisions = sorted(f"{code} -> {names}" for code, names in owners.items() if len(names) > 1)
    assert not collisions, (
        f"one SARJ code allocated by two packages: {collisions}. A consumer's "
        "`# sarj-noqa: <code>` cannot say which linter it meant, so it silences both."
    )


def _published_hooks() -> list[Mapping[str, object]]:
    parsed: object = yaml.safe_load(_HOOKS_PATH.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    assert _is_object_list(parsed)
    return [manifest.as_table(item) for item in parsed]


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _published_hook() -> Mapping[str, object]:
    hooks = _published_hooks()
    assert hooks
    return hooks[0]


def test_pre_commit_hooks_use_revision_local_dependencies_without_version_literals() -> None:
    """The consumer's `rev` is the only version authority for repository hooks."""
    invalid: list[str] = []
    for hook in _published_hooks():
        hook_id = hook.get("id")
        dependencies = hook.get("additional_dependencies", [])
        assert isinstance(hook_id, str)
        assert _is_object_list(dependencies)
        for raw_dependency in dependencies:
            assert isinstance(raw_dependency, str)
            if _VERSIONED_SARJ_RE.match(raw_dependency):
                invalid.append(f"{hook_id}: {raw_dependency}")
                continue
            dependency = (_REPO_ROOT / raw_dependency).resolve()
            assert dependency.is_relative_to(_REPO_ROOT)
            assert (dependency / "pyproject.toml").is_file(), f"{hook_id}: {raw_dependency}"
    assert not invalid, f"versioned Sarj hook dependencies duplicate the consumer rev: {invalid}"


def test_umbrella_hook_installs_the_complete_revision_local_bundle() -> None:
    hook = _published_hook()

    assert hook.get("id") == "sarj-standards"
    assert hook.get("additional_dependencies") == [
        "./packages/lint-configs",
        "./packages/sql",
        "./packages/iac",
    ]


def test_pre_commit_accepts_the_published_manifest_schema() -> None:
    loaded: object = load_precommit_manifest(str(_HOOKS_PATH))  # pyright: ignore[reportUnknownVariableType] -- narrowed below
    assert _is_object_list(loaded)  # pyright: ignore[reportUnknownArgumentType] -- untyped pre-commit boundary
    hooks = [manifest.as_table(item) for item in loaded]

    assert len(hooks) == len(_published_hooks())
    assert hooks[0]["id"] == "sarj-standards"


def test_remote_python_hooks_provision_the_required_interpreter() -> None:
    python_hooks = [hook for hook in _published_hooks() if hook.get("language") == "python"]

    assert python_hooks
    assert {hook.get("language_version") for hook in python_hooks} == {"python3.14"}


def test_every_published_hook_has_one_verifiable_revision_authority() -> None:
    hooks = _published_hooks()
    unknown = [hook_id for hook in hooks if manifest.expected_precommit_rev(((hook_id := str(hook["id"])),)) is None]

    assert not unknown
    assert manifest.expected_precommit_rev(("sarj-no-sequential-await", "sarj-prefer-jsonb")) == (
        f"lint-configs-v{manifest.adopted_version()}"
    )


def test_repository_root_deliberately_supplies_python_hooks() -> None:
    root_manifest = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest.as_table(root_manifest.get("project"))

    assert project.get("name") == "sarj-python-lint"
    assert project.get("version") == version("sarj-python-lint")


def test_ci_representatives_cover_every_hook_environment_recipe() -> None:
    hooks = {str(hook["id"]): hook for hook in _published_hooks()}
    representatives = {
        "sarj-standards",
        "sarj-no-sequential-await",
        "sarj-enforce-timestamptz",
        "sarj-require-deletion-protection",
    }
    covered = {_hook_dependencies(hooks[hook_id]) for hook_id in representatives}
    actual = {_hook_dependencies(hook) for hook in hooks.values()}

    assert covered == actual


def _hook_dependencies(hook: Mapping[str, object]) -> tuple[str, ...]:
    dependencies = hook.get("additional_dependencies", [])
    assert _is_object_list(dependencies)
    assert all(isinstance(item, str) for item in dependencies)
    return tuple(item for item in dependencies if isinstance(item, str))


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "docs/design.md",
        "infra/main.tf",
        ".env.test",
        "docker/Dockerfile.dev",
        "requirements-dev.in",
        "requirements/prod.txt",
    ],
)
def test_published_hook_regex_matches_real_repository_paths(path: str) -> None:
    """YAML single quotes preserve backslashes, so double escaping breaks extensions."""
    hook = _published_hook()
    files = hook.get("files")
    assert isinstance(files, str)
    pattern = re.compile(files)

    assert pattern.search(path), path


@pytest.mark.parametrize("path", ["src/app.ts", "assets/logo.png", "notes/README.txt"])
def test_published_hook_regex_ignores_unrelated_paths(path: str) -> None:
    hook = _published_hook()
    files = hook.get("files")
    assert isinstance(files, str)

    assert re.compile(files).search(path) is None, path


def test_warning_first_rules_are_visible_from_the_published_hook() -> None:
    hook = _published_hook()

    assert hook.get("verbose") is True
