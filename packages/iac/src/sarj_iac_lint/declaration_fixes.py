from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits

from sarj_iac_lint._hcl import (
    ParsedDocument,
    analysis_session,
    comment_locations,
    document_result,
    physical_lines,
    template_expressions,
    tokens,
)
from sarj_iac_lint.rules.canonical_terraform_declarations import CanonicalTerraformDeclarations
from sarj_iac_lint.terraform import is_terraform_override, terraform_blocks


if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

    from sarj_iac_lint._hcl import Block


type _Shape = tuple[str, tuple[str, ...], tuple[tuple[str, str], ...], tuple[_Shape, ...]]
_SOURCE_READS = frozenset(
    {
        "file",
        "filebase64",
        "filemd5",
        "filesha256",
        "filesha512",
        "filebase64sha256",
        "filebase64sha512",
        "templatefile",
    }
)


def consolidate_declarations(sources: Mapping[Path, str], *, selected: Collection[Path]) -> dict[Path, str]:
    modules: dict[Path, dict[Path, str]] = defaultdict(dict)
    for path, source in sources.items():
        modules[path.parent][path] = source
    changed: dict[Path, str] = {}
    with analysis_session(sources.values()):
        for module in modules.values():
            changed.update(_module_changes(module, frozenset(selected)))
    return changed


def _module_changes(sources: Mapping[Path, str], selected: frozenset[Path]) -> dict[Path, str]:
    if any(is_terraform_override(path) for path in sources):
        return {}
    parsed = {path: terraform_blocks(path, source) for path, source in sources.items()}
    if not _unique_interfaces(parsed) or observes_source(parsed):
        return {}
    moves = {path: _source_moves(path, sources, selected, parsed[path]) for path in sorted(selected & sources.keys())}
    updated = _apply_moves(sources, moves)
    before = Counter(_shape(block) for blocks in parsed.values() for block in blocks)
    after = Counter(
        _shape(block) for path, source in sources.items() for block in terraform_blocks(path, updated.get(path, source))
    )
    if before != after:
        message = "Terraform declaration movement changed the module's semantic structure"
        raise ValueError(message)
    return {path: source for path, source in updated.items() if source != sources[path]}


def _unique_interfaces(parsed: Mapping[Path, tuple[Block, ...]]) -> bool:
    declarations = Counter(
        (block.type, block.labels)
        for blocks in parsed.values()
        for block in blocks
        if block.type in {"variable", "output"}
    )
    return all(count == 1 for count in declarations.values())


def _source_moves(
    path: Path, sources: Mapping[Path, str], selected: frozenset[Path], blocks: tuple[Block, ...]
) -> list[tuple[Path, TextEdit]]:
    source = sources[path]
    if path.suffix != ".tf" or comment_locations(source):
        return []
    allowed = {finding.line for finding in CanonicalTerraformDeclarations().check(path, source)}
    result: list[tuple[Path, TextEdit]] = []
    for block in blocks:
        if block.type not in {"variable", "output"} or block.line not in allowed or block.blocks:
            continue
        target = path.with_name("variables.tf" if block.type == "variable" else "outputs.tf")
        if target not in selected or target not in sources or comment_locations(sources[target]):
            continue
        if not _compatible_lines(source=source, target=sources[target]):
            continue
        edit = _block_edit(source, block, blocks)
        if edit is not None:
            result.append((target, edit))
    return result


def _apply_moves(sources: Mapping[Path, str], moves: Mapping[Path, list[tuple[Path, TextEdit]]]) -> dict[Path, str]:
    updated = {
        path: apply_edits(sources[path], (edit for _, edit in changes)) for path, changes in moves.items() if changes
    }
    fragments: dict[Path, list[str]] = defaultdict(list)
    for path, changes in moves.items():
        for target, edit in changes:
            fragments[target].append(sources[path][edit.start : edit.end])
    for target, bodies in fragments.items():
        updated[target] = _append_blocks(updated.get(target, sources[target]), bodies)
    return updated


def _append_blocks(content: str, bodies: list[str]) -> str:
    newline = "\r\n" if "\r\n" in content or ("\n" not in content and any("\r\n" in body for body in bodies)) else "\n"
    for body in bodies:
        if content and not content.endswith(newline * 2):
            content += newline if content.endswith(newline) else newline * 2
        content += body + ("" if body.endswith(newline) else newline)
    return content


def observes_source(parsed: Mapping[Path, tuple[Block, ...]]) -> bool:
    pending = [block for blocks in parsed.values() for block in blocks]
    while pending:
        block = pending.pop()
        pending.extend(block.blocks)
        for attribute in block.attributes:
            for expression in (attribute.value, *template_expressions(attribute.value)):
                parts = tokens(expression)
                if any(
                    part in _SOURCE_READS and parts[index + 1 : index + 2] == ("(",) for index, part in enumerate(parts)
                ):
                    return True
    return False


def _compatible_lines(*, source: str, target: str) -> bool:
    endings = {"crlf" if "\r\n" in value else "lf" for value in (source, target) if "\n" in value}
    return len(endings) <= 1 and all(
        "\r" not in value.replace("\r\n", "") and "\n" not in value.replace("\r\n", "")
        for value in (source, target)
        if "\r" in value
    )


def _block_edit(source: str, block: Block, siblings: tuple[Block, ...]) -> TextEdit | None:
    lines = physical_lines(source, keepends=True)
    if block.col != 1 or not 1 <= block.line <= block.end_line <= len(lines):
        return None
    if any(
        other is not block and not (other.end_line < block.line or other.line > block.end_line) for other in siblings
    ):
        return None
    if not lines[block.end_line - 1].rstrip().endswith("}"):
        return None
    start = sum(map(len, lines[: block.line - 1]))
    end = sum(map(len, lines[: block.end_line]))
    parsed = document_result(source[start:end])
    if not isinstance(parsed, ParsedDocument) or parsed.root.attributes or len(parsed.root.blocks) != 1:
        return None
    if _shape(parsed.root.blocks[0]) != _shape(block):
        return None
    return TextEdit(start, end, "")


def _shape(block: Block) -> _Shape:
    return (
        block.type,
        block.labels,
        tuple((attribute.name, attribute.value) for attribute in block.attributes),
        tuple(_shape(child) for child in block.blocks),
    )
