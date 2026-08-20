from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from . import manifest, transaction


if TYPE_CHECKING:
    from pathlib import Path


ExclusionKind = Literal["path", "rule"]


@dataclass(frozen=True)
class Change:
    kind: ExclusionKind
    value: str
    added: bool
    changed: bool


def read(root: Path) -> manifest.Manifest:
    adopted = manifest.load(root.resolve())
    if adopted is None:
        msg = "repository is not adopted; run `code-standards setup` first"
        raise ValueError(msg)
    return adopted


def add(root: Path, kind: ExclusionKind, value: str) -> Change:
    return _change(root, kind, value, add_value=True)


def remove(root: Path, kind: ExclusionKind, value: str) -> Change:
    return _change(root, kind, value, add_value=False)


def _change(root: Path, kind: ExclusionKind, value: str, *, add_value: bool) -> Change:
    resolved = root.resolve()
    target = manifest.manifest_path(resolved)
    transaction.validate_targets(resolved, (target,))
    expected = target.read_bytes() if target.is_file() else None
    adopted = read(resolved)
    normalized = (
        manifest.validate_excluded_path(resolved, value) if kind == "path" else manifest.validate_excluded_rule(value)
    )
    values = adopted.excluded_paths if kind == "path" else adopted.excluded_rules
    present = normalized in values
    changed = (add_value and not present) or (not add_value and present)
    if not changed:
        return Change(kind, normalized, add_value, changed=False)

    updated_values = (*values, normalized) if add_value else tuple(item for item in values if item != normalized)
    updated = (
        replace(adopted, excluded_paths=updated_values)
        if kind == "path"
        else replace(adopted, excluded_rules=updated_values)
    )
    transaction.assert_expected(resolved, target, expected)
    transaction.atomic_write_text(resolved, target, updated.render())
    # Treat serialization as a trust boundary too: a successful mutation must
    # always leave a schema-valid manifest behind.
    _ = read(resolved)
    return Change(kind, normalized, add_value, changed=True)
