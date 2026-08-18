from __future__ import annotations

from datetime import timedelta
import json
from typing import TYPE_CHECKING, Self

import pytest

from sarj_standards.libs.release import registry as registry_module
from sarj_standards.libs.release.registry import (
    RegistryRequirement,
    lint_config_requirements,
    require_lint_config_dependencies,
    target_requirement,
    wait_for_lint_config_dependencies,
)


if TYPE_CHECKING:
    from pathlib import Path
    from urllib.request import Request


def _bundle(root: Path, *, python_pin: str = "sarj-python-lint==1.2.3") -> None:
    manifest = root / "packages/standards/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f'[project]\nname = "sarj-standards"\nversion = "4.0.0"\ndependencies = ["{python_pin}", "ruff==1.0.0"]\n',
        encoding="utf-8",
    )
    peers = root / "packages/standards/src/sarj_standards/configs/eslint.peers.json"
    peers.parent.mkdir(parents=True)
    peers.write_text(json.dumps({"peers": {"@sarj/eslint-plugin": "9.8.7"}}), encoding="utf-8")


def test_lint_config_requirements_read_exact_pypi_and_npm_pins(tmp_path: Path) -> None:
    _bundle(tmp_path)

    assert lint_config_requirements(tmp_path) == (
        RegistryRequirement("npm", "@sarj/eslint-plugin", "9.8.7"),
        RegistryRequirement("pypi", "sarj-python-lint", "1.2.3"),
    )


def test_lint_config_requirements_reject_nonexact_sibling_pin(tmp_path: Path) -> None:
    _bundle(tmp_path, python_pin="sarj-python-lint>=1.2.3")

    with pytest.raises(ValueError, match="must use an exact pin"):
        lint_config_requirements(tmp_path)


def test_lint_config_preflight_reports_the_first_missing_publication(tmp_path: Path) -> None:
    _bundle(tmp_path)

    with pytest.raises(ValueError, match=r"npm publication is unavailable: @sarj/eslint-plugin@9\.8\.7"):
        require_lint_config_dependencies(tmp_path, checker=lambda requirement: requirement.registry == "pypi")


def test_target_requirement_uses_authoritative_manifest_version(tmp_path: Path) -> None:
    manifest = tmp_path / "packages/python/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[project]\nname = "sarj-python-lint"\nversion = "2.3.4"\n', encoding="utf-8")

    assert target_requirement(tmp_path, "python") == RegistryRequirement("pypi", "sarj-python-lint", "2.3.4")


def test_bootstrap_requirement_uses_its_authoritative_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "packages/bootstrap/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[project]\nname = "sarj-standards-bootstrap"\nversion = "1.0.0"\n', encoding="utf-8")

    assert target_requirement(tmp_path, "bootstrap") == RegistryRequirement("pypi", "sarj-standards-bootstrap", "1.0.0")


def test_lint_config_preflight_waits_for_registry_propagation(tmp_path: Path) -> None:
    _bundle(tmp_path)
    python_attempts = iter((False, False, True))
    delays: list[float] = []

    def checker(requirement: RegistryRequirement) -> bool:
        return True if requirement.registry == "npm" else next(python_attempts)

    requirements = wait_for_lint_config_dependencies(
        tmp_path,
        attempts=3,
        delay=timedelta(milliseconds=250),
        checker=checker,
        sleeper=delays.append,
    )

    assert requirements == lint_config_requirements(tmp_path)
    assert delays == [0.25, 0.25]


def test_lint_config_preflight_fails_after_its_bounded_attempts(tmp_path: Path) -> None:
    _bundle(tmp_path)
    delays: list[float] = []

    with pytest.raises(ValueError, match=r"after 2 attempt\(s\).*sarj-python-lint@1\.2\.3"):
        _ = wait_for_lint_config_dependencies(
            tmp_path,
            attempts=2,
            delay=timedelta(milliseconds=500),
            checker=lambda requirement: requirement.registry == "npm",
            sleeper=delays.append,
        )

    assert delays == [0.5]


def test_lint_config_preflight_retries_transient_errors_and_keeps_successes(tmp_path: Path) -> None:
    _bundle(tmp_path)
    calls: dict[str, int] = {}

    def checker(requirement: RegistryRequirement) -> bool:
        calls[requirement.name] = calls.get(requirement.name, 0) + 1
        if requirement.registry == "npm":
            return True
        if calls[requirement.name] == 1:
            message = "temporary registry outage"
            raise OSError(message)
        return True

    requirements = wait_for_lint_config_dependencies(
        tmp_path,
        attempts=2,
        delay=timedelta(),
        checker=checker,
        sleeper=lambda _seconds: None,
    )

    assert requirements == lint_config_requirements(tmp_path)
    assert calls["@sarj/eslint-plugin"] == 1
    assert calls["sarj-python-lint"] == 2


def test_lint_config_preflight_rejects_negative_retry_delay(tmp_path: Path) -> None:
    _bundle(tmp_path)

    with pytest.raises(ValueError, match="finite and non-negative"):
        wait_for_lint_config_dependencies(
            tmp_path,
            delay=timedelta(seconds=-1),
            checker=lambda _requirement: True,
        )


def test_pypi_publication_requires_exact_version_in_simple_api(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "files": [
                {"filename": "sarj_python_lint-1.2.30-py3-none-any.whl"},
                {"filename": "sarj_python_lint-1.2.3-py3-none-any.whl"},
            ]
        }
    ).encode()

    class Response:
        status: int = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return payload

    seen: list[Request] = []

    def open_url(request: Request, *, timeout: int) -> Response:
        _ = timeout
        seen.append(request)
        return Response()

    monkeypatch.setattr(registry_module, "urlopen", open_url)

    assert registry_module.publication_exists(RegistryRequirement("pypi", "sarj-python-lint", "1.2.3"))
    assert seen
    request = seen[0]
    assert request.full_url == "https://pypi.org/simple/sarj-python-lint/"
    assert "application/vnd.pypi.simple.v1+json" in request.headers["Accept"]


def test_pypi_simple_metadata_without_exact_version_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"files": [{"filename": "sarj_python_lint-1.2.30-py3-none-any.whl"}]}).encode()

    class Response:
        status: int = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return payload

    def open_url(_request: object, *, timeout: int) -> Response:
        _ = timeout
        return Response()

    monkeypatch.setattr(registry_module, "urlopen", open_url)

    assert not registry_module.publication_exists(RegistryRequirement("pypi", "sarj-python-lint", "1.2.3"))
