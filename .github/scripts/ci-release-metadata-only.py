from __future__ import annotations  # ruff: ignore[implicit-namespace-package] -- standalone CI entry point.

import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- bounded Git reads on the trusted routing runner.
import sys
import tomllib
from typing import TypeGuard


def release_metadata_only(base: str, head: str, path: str) -> bool:
    return _normalized_document(base, path) == _normalized_document(head, path)


def _normalized_document(revision: str, path: str) -> dict[str, object]:
    source = subprocess.check_output(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git command; no shell interprets revision or path.
        ["git", "show", f"{revision}:{path}"],  # ruff: ignore[start-process-with-partial-path] -- routing runner owns Git on PATH.
        text=True,
        timeout=30,
    )
    document: dict[str, object] = tomllib.loads(source)
    if path.endswith("pyproject.toml"):
        project = _mapping(document["project"])
        project = _without_version(project)
        dependencies: list[str] = []
        for dependency in _sequence(project.get("dependencies", [])):
            if not isinstance(dependency, str):
                msg = "expected dependency string"
                raise TypeError(msg)
            dependencies.append(
                re.sub(r"^(sarj-(?:python|sql|iac)-lint|sarj-rule-contracts)==[0-9]+(?:\.[0-9]+)*$", r"\1", dependency)
            )
        return {**document, "project": {**project, "dependencies": dependencies}}
    local_sources = {
        "code-standards": ".",
        "sarj-python-lint": "../python",
        "sarj-sql-lint": "../sql",
        "sarj-iac-lint": "../iac",
        "sarj-rule-contracts": "../contracts",
    }
    packages: list[dict[str, object]] = []
    for package_value in _sequence(document["package"]):
        package = _mapping(package_value)
        name = package["name"]
        if (
            isinstance(name, str)
            and name in local_sources
            and package.get("source") == {"editable": local_sources[name]}
        ):
            package = _without_version(package)
        packages.append(package)
    return {**document, "package": packages}


def _without_version(document: dict[str, object]) -> dict[str, object]:
    if "version" not in document:
        key = "version"
        raise KeyError(key)
    return {key: value for key, value in document.items() if key != "version"}


def _mapping(value: object) -> dict[str, object]:
    if not _is_table(value):
        msg = "expected TOML table"
        raise TypeError(msg)
    return value


def _is_table(value: object) -> TypeGuard[dict[str, object]]:
    return _is_mapping(value) and all(isinstance(key, str) for key in value)


def _is_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _sequence(value: object) -> list[object]:
    if not _is_sequence(value):
        msg = "expected TOML array"
        raise TypeError(msg)
    return value


def _is_sequence(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


if __name__ == "__main__":
    sys.exit(0 if release_metadata_only(*sys.argv[1:]) else 1)
