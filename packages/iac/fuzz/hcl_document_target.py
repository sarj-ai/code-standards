# ruff: file-ignore[implicit-namespace-package]

from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import NoReturn


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from sarj_iac_lint._hcl import Block, blocks, document  # ruff: ignore[module-import-not-at-top-of-file]


MAX_INPUT_BYTES = 500_000
MAX_BLOCK_DEPTH = 128
DEPTH_ERROR = f"HCL nesting exceeds the supported depth of {MAX_BLOCK_DEPTH}"


class FuzzInvariantError(AssertionError):
    """Raised when a parser invariant fails under fuzzing."""


def _fail(message: str) -> NoReturn:
    raise FuzzInvariantError(message)


def walk_blocks(nodes: tuple[Block, ...], *, expected_depth: int, line_count: int) -> Iterator[Block]:
    for node in nodes:
        if node.depth != expected_depth:
            _fail("child depth is inconsistent with its parent")
        if not 1 <= node.line <= node.end_line <= line_count:
            _fail("block source span is invalid")
        if node.depth > MAX_BLOCK_DEPTH:
            _fail("accepted block exceeds the parser depth limit")
        for attribute in node.attributes:
            if attribute.line < 1 or attribute.col < 1:
                _fail("attribute source position is invalid")
        yield node
        yield from walk_blocks(node.blocks, expected_depth=expected_depth + 1, line_count=line_count)


def verify_constructive_model(data: bytes) -> None:
    padding = " " * (1 + (data[0] % 8 if data else 0))
    comment = data[:256].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ").replace("*/", "* /")
    marker = data[:256].hex()
    source = (
        f"/* {comment} */\n"
        f'resource{padding}"fixed"{padding}"target" {{\n'
        f"  deletion_protection{padding}={padding}true\n"
        f'  marker{padding}={padding}"{marker}"\n'
        f"  nested {{\n    enabled{padding}={padding}true\n  }}\n"
        "}\n"
    )
    document.cache_clear()
    parsed = document(source)
    if len(parsed.blocks) != 1:
        _fail("constructive model lost its top-level block")
    resource = parsed.blocks[0]
    if resource.type != "resource" or resource.labels != ("fixed", "target"):
        _fail("constructive model changed resource identity")
    deletion_protection = resource.attribute("deletion_protection")
    if deletion_protection is None or deletion_protection.value != "true":
        _fail("constructive model lost its protected attribute")
    nested = resource.child("nested")
    if nested is None:
        _fail("constructive model lost its nested block")
    enabled = nested.attribute("enabled")
    if enabled is None or enabled.value != "true":
        _fail("constructive model lost its nested attribute")


def test_one_input(data: bytes) -> None:
    if len(data) > MAX_INPUT_BYTES:
        return
    verify_constructive_model(data)
    source = data.decode("utf-8", errors="replace")
    document.cache_clear()
    try:
        first = document(source)
    except ValueError as exc:
        if str(exc) != DEPTH_ERROR:
            raise
        return

    document.cache_clear()
    second = document(source)
    if first != second:
        _fail("uncached parsing is not deterministic")
    if blocks(source) != first.blocks:
        _fail("blocks() disagrees with document().blocks")

    line_count = max(len(source.splitlines()), 1)
    tuple(walk_blocks(first.blocks, expected_depth=0, line_count=line_count))
