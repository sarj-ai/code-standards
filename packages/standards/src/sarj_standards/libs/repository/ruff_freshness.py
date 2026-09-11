from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed gh argv maintains one durable CI issue.
import tomllib
from typing import TYPE_CHECKING, Annotated, Final, Protocol

from packaging.version import InvalidVersion, Version
from pydantic import TypeAdapter
import typer

from sarj_standards.libs.adoption.manifest import as_table, list_field, table_field, text_field


if TYPE_CHECKING:
    from collections.abc import Sequence


_ISSUE_TITLE: Final = "[Ruff freshness] Standards is behind PyPI"
_MANIFESTS: Final = (
    ("packages/standards/pyproject.toml", "=="),
    ("packages/bootstrap/pyproject.toml", ">="),
    ("packages/python/pyproject.toml", ">="),
    ("packages/sql/pyproject.toml", ">="),
    ("packages/iac/pyproject.toml", ">="),
)
_RUFF_REQUIREMENT = re.compile(r"^ruff(?P<operator>==|>=)(?P<version>[^;\s]+)")
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])
_JSON_LIST_ADAPTER = TypeAdapter(list[object])
_ISSUE_LIST_ADAPTER = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True, slots=True)
class Freshness:
    latest: str
    stale: tuple[str, ...]

    @property
    def current(self) -> bool:
        return not self.stale


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    state: str


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


def _run_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed gh executable; argv is never interpreted by a shell.
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def evaluate(root: Path, metadata: object) -> Freshness:
    latest = _latest_stable(metadata)
    stale: list[str] = []
    for relative, expected_operator in _MANIFESTS:
        path = root / relative
        requirements = _ruff_requirements(path)
        expected = f"ruff{expected_operator}{latest}"
        if expected not in requirements:
            rendered = ", ".join(requirements) if requirements else "missing"
            stale.append(f"{relative}: expected {expected}, found {rendered}")
    return Freshness(latest, tuple(stale))


def _latest_stable(metadata: object) -> str:
    document = as_table(metadata)
    if not document:
        msg = "PyPI metadata must be an object"
        raise TypeError(msg)
    raw = text_field(table_field(document, "info"), "version")
    if raw is None:
        msg = "PyPI metadata has no info.version"
        raise TypeError(msg)
    try:
        version = Version(raw)
    except InvalidVersion as exc:
        msg = f"PyPI returned invalid Ruff version {raw!r}"
        raise ValueError(msg) from exc
    if version.is_prerelease or version.is_devrelease:
        msg = f"PyPI latest Ruff version is not stable: {raw}"
        raise ValueError(msg)
    return str(version)


def _ruff_requirements(path: Path) -> tuple[str, ...]:
    document = _JSON_OBJECT_ADAPTER.validate_python(tomllib.loads(path.read_text(encoding="utf-8")))
    values: list[str] = []
    dependencies = list_field(table_field(document, "project"), "dependencies")
    values.extend(value for value in dependencies if isinstance(value, str) and value.startswith("ruff"))
    for group in table_field(document, "dependency-groups").values():
        if isinstance(group, list):
            group_values = _JSON_LIST_ADAPTER.validate_python(group)
            values.extend(value for value in group_values if isinstance(value, str) and value.startswith("ruff"))
    normalized: list[str] = []
    for value in values:
        match = _RUFF_REQUIREMENT.match(value)
        normalized.append(value if match is None else f"ruff{match.group('operator')}{match.group('version')}")
    return tuple(sorted(set(normalized)))


def synchronize_issue(
    result: Freshness,
    *,
    repository: str,
    run_url: str,
    runner: CommandRunner = _run_command,
) -> None:
    listed = runner(
        (
            "gh",
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "all",
            "--limit",
            "100",
            "--json",
            "number,title,state",
        )
    )
    if listed.returncode != 0:
        raise OSError(listed.stderr.strip() or "gh issue list failed")
    issues = _ISSUE_LIST_ADAPTER.validate_json(listed.stdout)
    existing = _matching_issue(issues)
    if result.current:
        if existing is not None and existing.state == "OPEN":
            _run_gh(runner, "issue", "close", str(existing.number), "--repo", repository, "--reason", "completed")
        return
    body = "\n".join(
        (
            f"Latest stable Ruff: `{result.latest}`.",
            "",
            "Unsynchronized manifests:",
            *(f"- {line}" for line in result.stale),
            "",
            f"Freshness run: {run_url}",
        )
    )
    if existing is None:
        _run_gh(runner, "issue", "create", "--repo", repository, "--title", _ISSUE_TITLE, "--body", body)
    else:
        _run_gh(runner, "issue", "edit", str(existing.number), "--repo", repository, "--body", body)
        if existing.state == "CLOSED":
            _run_gh(runner, "issue", "reopen", str(existing.number), "--repo", repository)


def _matching_issue(issues: Sequence[dict[str, object]]) -> Issue | None:
    for item in issues:
        number = item.get("number")
        if item.get("title") == _ISSUE_TITLE and type(number) is int:
            return Issue(number, text_field(item, "state") or "")
    return None


def _run_gh(runner: CommandRunner, *arguments: str) -> None:
    completed = runner(("gh", *arguments))
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or f"gh {' '.join(arguments[:2])} failed")


def main(
    metadata_path: Annotated[Path, typer.Option("--metadata-path", exists=True, dir_okay=False)],
    root: Annotated[Path | None, typer.Option("--root", file_okay=False)] = None,
    repository: Annotated[str | None, typer.Option("--repository")] = None,
    run_url: Annotated[str, typer.Option("--run-url")] = "",
) -> None:
    metadata = _JSON_OBJECT_ADAPTER.validate_json(metadata_path.read_text(encoding="utf-8"))
    result = evaluate((Path.cwd() if root is None else root).resolve(), metadata)
    if repository:
        synchronize_issue(result, repository=repository, run_url=run_url)
    if result.current:
        typer.echo(f"Ruff {result.latest} is synchronized across all managed manifests.")
        return
    for item in result.stale:
        typer.echo(f"error: {item}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    typer.run(main)
