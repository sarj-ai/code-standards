from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_iac_lint.declaration_fixes import observes_source
from sarj_iac_lint.rules.no_restated_comment import has_generated_header
from sarj_iac_lint.terraform import comment_texts, terraform_blocks

from .devops_tools import checked_tool
from .external import run_process_input


if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path


def format_sources(root: Path, sources: Mapping[Path, str], *, selected: Collection[Path]) -> dict[Path, str]:
    targets = tuple(sorted(path for path in selected if path.suffix == ".tf"))
    if not targets:
        return {}
    parsed = {path: terraform_blocks(path, source) for path, source in sources.items()}
    observed = {
        directory: observes_source({path: blocks for path, blocks in parsed.items() if path.parent == directory})
        for directory in {path.parent for path in targets}
    }
    tool = checked_tool("terraform", root=root)
    executable = str(tool.executable) if tool.executable is not None else tool.name
    changes: dict[Path, str] = {}
    for path in targets:
        source = sources[path]
        formatted = _format_one(root, path, source, executable)
        if formatted == source:
            continue
        if has_generated_header(source):
            message = f"Review the generator for generated Terraform source {path}; no files changed"
            raise ValueError(message)
        if observed[path.parent]:
            message = (
                f"Terraform formatting requires review of source-reading functions in {path.parent}; no files changed"
            )
            raise ValueError(message)
        changes[path] = formatted
    return changes


def _format_one(root: Path, path: Path, source: str, executable: str) -> str:
    output = run_process_input((executable, "fmt", "-"), cwd=root, source=source)
    if output.returncode:
        message = f"Terraform formatting failed for {path}: {output.stderr.strip()}"
        raise ValueError(message)
    formatted = output.stdout
    if _comments(source) != _comments(formatted):
        message = f"Terraform fmt would change nonempty comments in {path}; preserve legal notices and functional directives through a reviewed edit"
        raise ValueError(message)
    terraform_blocks(path, formatted)
    return formatted


def _comments(source: str) -> tuple[str, ...]:
    retained: list[str] = []
    for comment in comment_texts(source):
        body = comment[2:-2] if comment.startswith("/*") else comment[2:] if comment.startswith("//") else comment[1:]
        if body.strip():
            retained.append("\n".join(line.strip() for line in comment.splitlines()))
    return tuple(retained)
