from __future__ import annotations  # ruff: ignore[implicit-namespace-package] -- standalone release bootstrap metadata entrypoint.

from pathlib import Path
import sys
import tomllib
from typing import TypeGuard


_RUNTIME_PREFIXES = ("pydantic==", "typer==", "packaging==")


def main() -> None:
    project: object = tomllib.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["project"]  # pyright: ignore[reportAny] -- TOML input is narrowed immediately at the standalone bootstrap boundary.
    if not _table(project):
        message = "invalid release package metadata"
        raise ValueError(message)
    match sys.argv[1]:
        case "standards-tag":
            version = project["version"]
            if not isinstance(version, str) or not version or any(character.isspace() for character in version):
                message = "invalid Standards package version"
                raise ValueError(message)
            sys.stdout.write(f"standards-v{version}\n")
        case "runtime-requirements":
            dependencies = project["dependencies"]
            if not _list(dependencies) or not all(isinstance(spec, str) for spec in dependencies):
                message = "invalid release package dependencies"
                raise ValueError(message)
            selected = [spec for spec in dependencies if isinstance(spec, str) and spec.startswith(_RUNTIME_PREFIXES)]
            if len(selected) != len(_RUNTIME_PREFIXES):
                message = "release analysis requires exact Pydantic, Typer and Packaging pins"
                raise SystemExit(message)
            sys.stdout.write("\n".join(selected) + "\n")
        case _:
            message = "unsupported release metadata operation"
            raise SystemExit(message)


def _table(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


if __name__ == "__main__":
    main()
