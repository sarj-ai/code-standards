from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sarj_iac_lint._hcl import Block, ParsedDocument, document_result, tokens
from sarj_iac_lint.rules.no_terraform_guard_blocks import owned_guards


if TYPE_CHECKING:
    from collections.abc import Mapping


type _GuardShape = tuple[str, tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...], tuple[_GuardShape, ...]]


@dataclass(frozen=True, slots=True)
class GuardContract:
    path: str
    owner: tuple[str, ...]
    kind: str
    shape: str


@dataclass(frozen=True, slots=True)
class GuardContracts:
    root: Path
    entries: frozenset[GuardContract]

    def accepts(self, path: Path, owner: Block, guard: Block) -> bool:
        relative = path.resolve().relative_to(self.root.resolve()).as_posix()
        return _contract(relative, owner, guard) in self.entries


def relative_tf_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or path.as_posix() != value or path.suffix != ".tf":
        message = "guard contract paths must be exact repository-relative .tf paths"
        raise ValueError(message)
    if any(part in {".", ".."} for part in path.parts) or any(char in value for char in ("\\", "\x00", ":")):
        message = "guard contract paths cannot contain traversal or special separators"
        raise ValueError(message)
    return value


def contracts_for_source(path: str, source: str) -> tuple[GuardContract, ...]:
    relative_tf_path(path)
    _complete_structure(path=path, source=source)
    parsed = document_result(source)
    if not isinstance(parsed, ParsedDocument):
        message = f"cannot contract malformed HCL: {path}"
        raise TypeError(message)
    owners = [(owner.type, *owner.labels) for owner in parsed.root.blocks if tuple(owned_guards(owner))]
    if len(set(owners)) != len(owners):
        message = f"ambiguous duplicate owner: {path}"
        raise ValueError(message)
    result = tuple(_contract(path, owner, guard) for owner in parsed.root.blocks for guard in owned_guards(owner))
    if len(set(result)) != len(result):
        message = f"duplicate guard contract: {path}"
        raise ValueError(message)
    return result


def verify_sources(entries: frozenset[GuardContract], sources: Mapping[str, str]) -> None:
    expected_paths = {entry.path for entry in entries}
    if set(sources) != expected_paths:
        message = "missing or unowned guard contract source"
        raise ValueError(message)
    actual = frozenset(entry for path, source in sources.items() for entry in contracts_for_source(path, source))
    if actual != entries:
        message = "missing, new, changed or stale Terraform guard contract"
        raise ValueError(message)


def _contract(path: str, owner: Block, guard: Block) -> GuardContract:
    return GuardContract(
        path,
        (owner.type, *owner.labels),
        guard.type,
        json.dumps(_shape(guard), separators=(",", ":"), ensure_ascii=True),
    )


def _shape(block: Block) -> _GuardShape:
    names = [attribute.name for attribute in block.attributes]
    if len(set(names)) != len(names):
        message = "duplicate attributes cannot establish a guard contract"
        raise ValueError(message)
    if block.type in {"validation", "precondition", "postcondition", "assert"} and (
        set(names) != {"condition", "error_message"} or block.blocks
    ):
        message = "guard must own exactly condition and error_message"
        raise ValueError(message)
    # Native tokens preserve strings, heredocs, operators, identifiers and order.
    # Only insignificant whitespace/comments between tokens are normalized.
    attributes = tuple(sorted((attribute.name, tokens(attribute.value)) for attribute in block.attributes))
    if any(not value for _, value in attributes):
        message = "empty guard expression"
        raise ValueError(message)
    return block.type, block.labels, attributes, tuple(_shape(child) for child in block.blocks)


def _complete_structure(*, path: str, source: str) -> None:
    closers: list[str] = []
    for token in tokens(source):
        if token in {"{", "[", "("}:
            closers.append({"{": "}", "[": "]", "(": ")"}[token])
        elif token in {"}", "]", ")"} and (not closers or closers.pop() != token):
            message = f"malformed HCL structure: {path}"
            raise ValueError(message)
    if closers:
        message = f"incomplete HCL structure: {path}"
        raise ValueError(message)
