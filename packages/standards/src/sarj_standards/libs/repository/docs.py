"""Generate small documentation sections from repository source of truth."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- validates fixed local CLI examples.
import sys
import tomllib
from typing import TYPE_CHECKING, Final, TypeGuard


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


_START: Final = "<!-- generated:{name}:start -->"
_END: Final = "<!-- generated:{name}:end -->"
_LOCAL_LINK: Final = re.compile(r"\[[^]]+\]\((?!https?://|mailto:)([^)#]*)(?:#([^)]+))?\)")
_HEADING: Final = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_STANDARDS_COMMAND: Final = re.compile(r"^\s*(sarj-standards(?:\s+.+)?)\s*$", re.MULTILINE)
_ESSENTIAL_DOCUMENTS: Final = (
    Path("README.md"),
    Path("CLAUDE.md"),
    Path(".github/SECURITY.md"),
    Path("packages/standards/README.md"),
    Path("packages/python/README.md"),
    Path("packages/sql/README.md"),
    Path("packages/iac/README.md"),
    Path("packages/typescript/README.md"),
    Path("packages/tsconfig/README.md"),
    Path("plugins/sarj-audit/README.md"),
)


@dataclass(frozen=True, slots=True)
class DocumentationResult:
    """Outcome of a deterministic documentation check or synchronization."""

    changed: tuple[Path, ...]
    checked: tuple[Path, ...]

    @property
    def status(self) -> int:
        """Return a process-compatible status: one means generated drift."""
        return int(bool(self.changed))


def check(root: Path) -> DocumentationResult:
    """Report generated documentation sections that differ from source."""
    return _update(root.resolve(), write=False)


def sync(root: Path) -> DocumentationResult:
    """Synchronize every generated documentation section with source."""
    return _update(root.resolve(), write=True)


def _update(root: Path, *, write: bool) -> DocumentationResult:
    readme = root / "README.md"
    source = readme.read_text(encoding="utf-8")
    rendered = _render_document(
        source,
        {
            "packages": lambda: _packages(root),
            "rules": lambda: _rules(root),
        },
        path=readme,
    )
    changed = () if rendered == source else (readme,)
    if changed and write:
        readme.write_text(rendered, encoding="utf-8")
    checked = _documentation_paths(root)
    _validate_documents(checked)
    return DocumentationResult(changed=changed, checked=checked)


def _validate_documents(paths: tuple[Path, ...]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        msg = f"required documentation is missing: {', '.join(str(path) for path in missing)}"
        raise ValueError(msg)
    for path in paths:
        source = path.read_text(encoding="utf-8")
        _validate_local_links(path, source)
        _validate_cli_examples(path, source)


def _documentation_paths(root: Path) -> tuple[Path, ...]:
    essential = {root / relative for relative in _ESSENTIAL_DOCUMENTS}
    maintained = {
        *root.glob("plugins/*/commands/*.md"),
        *root.glob("plugins/*/skills/*/SKILL.md"),
        *root.glob("plugins/*/skills/*/references/*.md"),
    }
    return tuple(sorted(essential | maintained))


def _validate_local_links(path: Path, source: str) -> None:
    for match in _LOCAL_LINK.finditer(source):
        relative, anchor = match.groups()
        target = (path.parent / relative).resolve() if relative else path
        if not target.exists():
            msg = f"{path} links to missing local target {relative!r}"
            raise ValueError(msg)
        if anchor and target.suffix.lower() == ".md":
            headings = {
                _heading_slug(heading.group(1)) for heading in _HEADING.finditer(target.read_text(encoding="utf-8"))
            }
            if anchor not in headings:
                msg = f"{path} links to missing Markdown heading {anchor!r} in {relative or path.name!r}"
                raise ValueError(msg)


def _heading_slug(heading: str) -> str:
    normalized = re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
    return re.sub(r"-+", "-", normalized)


def _validate_cli_examples(path: Path, source: str) -> None:
    for match in _STANDARDS_COMMAND.finditer(source):
        command = shlex.split(match.group(1))
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed interpreter and argv.
            [sys.executable, "-m", "sarj_standards", *command[1:], "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            msg = f"{path} contains an invalid command example: {match.group(1)!r}"
            raise ValueError(msg)


def _render_document(
    source: str,
    sections: Mapping[str, Callable[[], str]],
    *,
    path: Path,
) -> str:
    rendered = source
    for name, build in sections.items():
        start = _START.format(name=name)
        end = _END.format(name=name)
        if rendered.count(start) != 1 or rendered.count(end) != 1:
            msg = f"{path} must contain exactly one {start!r} and {end!r} marker"
            raise ValueError(msg)
        before, remainder = rendered.split(start, 1)
        _old, after = remainder.split(end, 1)
        body = build().strip()
        rendered = f"{before}{start}\n{body}\n{end}{after}"
    return rendered


def _packages(root: Path) -> str:
    definitions = (
        ("packages/standards/pyproject.toml", "PyPI", "Python orchestration and shared configuration"),
        ("packages/python/pyproject.toml", "PyPI", "Python AST rules"),
        ("packages/sql/pyproject.toml", "PyPI", "PostgreSQL migration rules"),
        ("packages/iac/pyproject.toml", "PyPI", "Terraform and IaC rules"),
        ("packages/typescript/package.json", "npm", "ESLint rules and presets"),
        ("packages/tsconfig/package.json", "npm", "Strict TypeScript configurations"),
    )
    rows = ["| Package | Registry | Purpose |", "| --- | --- | --- |"]
    for relative, registry, purpose in definitions:
        path = root / relative
        metadata = _manifest(path)
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            msg = f"{path} does not declare a package name"
            raise ValueError(msg)
        rows.append(f"| [`{name}`]({path.parent.relative_to(root).as_posix()}/) | {registry} | {purpose} |")
    return "\n".join(rows)


def _rules(root: Path) -> str:
    ledger_path = root / "packages/standards/src/sarj_standards/configs/rule-ledger.json"
    raw_ledger: object = json.loads(ledger_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    if not _is_object_table(raw_ledger):
        msg = f"{ledger_path} is not an object"
        raise TypeError(msg)
    ledger = raw_ledger
    rules = ledger.get("rules")
    if not _is_object_table(rules):
        msg = f"{ledger_path} has no rules object"
        raise TypeError(msg)
    rule_groups = rules
    rows = ["| Family | Active rules |", "| --- | ---: |"]
    for key, label in (
        ("eslint", "TypeScript"),
        ("python", "Python"),
        ("sql", "SQL"),
        ("iac", "IaC"),
        ("text", "Text"),
    ):
        entries = rule_groups.get(key)
        if not _is_object_list(entries):
            msg = f"{ledger_path} has an invalid {key!r} rule list"
            raise ValueError(msg)
        rows.append(f"| {label} | {len(entries)} |")
    rows.append("\nRule identifiers and lifecycle data are available through `sarj-standards show rules`.")
    return "\n".join(rows)


def _manifest(path: Path) -> dict[str, object]:
    if path.suffix == ".toml":
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        project: object = document.get("project")
        if not _is_object_table(project):
            msg = f"{path} has no project table"
            raise ValueError(msg)
        return project
    document: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    if not _is_object_table(document):
        msg = f"{path} is not an object"
        raise TypeError(msg)
    return document


def _is_object_table(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
