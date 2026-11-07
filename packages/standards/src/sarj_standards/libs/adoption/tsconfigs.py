from __future__ import annotations

import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from pydantic import JsonValue


# The repository's tsconfig graph as tsrs sees it: Oxlint type-checks tsconfig.json projects and the
# projects their `references` reach.

TSCONFIG_JSON: Final = "tsconfig.json"
#: What `can_reference` checks, for the fix of a reference `update` could not add.
REFERENCE_RULE: Final = (
    "unless that tsconfig.json is solution-style, with `files: []` and no `include`, the referenced project "
    "needs `composite: true` and must emit"
)
_TSCONFIG_NAME: Final = re.compile(r"tsconfig(?:\.[\w.-]+)?\.json")
_STRING_OR_COMMENT: Final = re.compile(r'(?P<string>"(?:\\[\s\S]|[^"\\\n])*")|//[^\n]*|/\*[\s\S]*?\*/')
_TRAILING_COMMA: Final = re.compile(r",(\s*[}\]])")


def read(paths: Iterable[Path]) -> dict[Path, dict[str, JsonValue]]:
    # The tsconfig files among `paths` that parse as JSONC objects; tsrs reports the rest itself.
    return {
        path: document
        for path in paths
        if _TSCONFIG_NAME.fullmatch(path.name) and isinstance(document := _jsonc(path), dict)
    }


def parents(path: Path, document: Mapping[str, JsonValue]) -> Iterator[Path]:
    # Package specifiers resolve from node_modules and never name a repository tsconfig.
    value = document.get("extends")
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, str) and item.startswith("."):
            target = normalized(path.parent / item)
            yield target if target.suffix == ".json" else target.with_name(target.name + ".json")


def is_project(document: Mapping[str, JsonValue]) -> bool:
    return not {"include", "files"}.isdisjoint(document.keys())


def unreferenced_projects(documents: Mapping[Path, Mapping[str, JsonValue]]) -> Iterator[Path]:
    # The projects `update` would add to a tsconfig.json's `references`: tsrs skips them today.
    extended = {target for path, document in documents.items() for target in parents(path, document)}
    reached = _referenced(documents)
    return (
        path
        for path, document in documents.items()
        if path not in extended and path not in reached and _is_separate_project(path, document)
    )


def can_reference(owner: Mapping[str, JsonValue], project: Mapping[str, JsonValue]) -> bool:
    # A solution-style tsconfig (`files: []`, no `include`) may reference any project; one that compiles
    # files of its own may only reference a composite project that emits (TS6306, TS6310).
    if owner.get("files") == [] and "include" not in owner:
        return True
    options = project.get("compilerOptions")
    return isinstance(options, dict) and options.get("composite") is True and options.get("noEmit") is not True


def normalized(path: Path) -> Path:
    # Lexical, like the paths callers plan mutations with; resolving would leave a symlinked root.
    return Path(os.path.normpath(path))


def _referenced(documents: Mapping[Path, Mapping[str, JsonValue]]) -> frozenset[Path]:
    # Every project the tsconfig.json files reach through `references`, which is what tsrs type-checks.
    pending = [path for path in documents if path.name == TSCONFIG_JSON]
    reached: set[Path] = set()
    while pending:
        owner = pending.pop()
        references = documents.get(owner, {}).get("references")
        for reference in references if isinstance(references, list) else []:
            target = reference.get("path") if isinstance(reference, dict) else None
            if not isinstance(target, str):
                continue
            resolved = normalized(owner.parent / target)
            resolved = resolved if resolved.suffix == ".json" else resolved / TSCONFIG_JSON
            if resolved not in reached:
                reached.add(resolved)
                pending.append(resolved)
    return frozenset(reached)


def _is_separate_project(path: Path, document: Mapping[str, JsonValue]) -> bool:
    # A variant of a tsconfig.json project (tsconfig.build.json) covers files that project already has.
    return (
        path.name != TSCONFIG_JSON
        and is_project(document)
        and not any(target.name == TSCONFIG_JSON for target in parents(path, document))
    )


def _jsonc(path: Path) -> JsonValue | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None
    stripped = _STRING_OR_COMMENT.sub(lambda match: match.group("string") or "", text)
    try:
        return parse_json(_TRAILING_COMMA.sub(r"\1", stripped))
    except ValueError:
        return None
