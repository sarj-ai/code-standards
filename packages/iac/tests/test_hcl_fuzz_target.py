from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint._hcl import Attribute, Block


CORPUS = Path(__file__).resolve().parents[1] / "fuzz/corpus/hcl_document"
sys.path.insert(0, str(CORPUS.parents[1]))

import hcl_document_target as target  # ruff: ignore[module-import-not-at-top-of-file]


if TYPE_CHECKING:
    from collections.abc import Iterator


class _DocumentSequence:
    def __init__(self, *values: Block) -> None:
        self.values: Iterator[Block] = iter(values)
        self.calls: int = 0
        self.clears: int = 0

    def __call__(self, _source: str) -> Block:
        self.calls += 1
        return next(self.values)

    def cache_clear(self) -> None:
        self.clears += 1


def _block(
    *,
    depth: int = 0,
    line: int = 1,
    end_line: int = 1,
    attributes: tuple[Attribute, ...] = (),
    children: tuple[Block, ...] = (),
) -> Block:
    return Block("resource", (), depth, line, 1, end_line, attributes, children)


def test_fuzz_target_replays_every_seed() -> None:
    seeds = sorted(CORPUS.iterdir())

    assert len(seeds) == 6
    for seed in seeds:
        target.test_one_input(seed.read_bytes())


def test_constructive_oracle_rejects_an_empty_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = Block("", (), 0, 1, 1, 1, (), ())
    sequence = _DocumentSequence(empty)
    monkeypatch.setattr(target, "document", sequence)

    with pytest.raises(target.FuzzInvariantError, match="lost its top-level block"):
        target.verify_constructive_model(b"arbitrary */ transform\n${}")


def test_fuzz_target_executes_both_parser_oracles(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = _block()
    sequence = _DocumentSequence(parsed, parsed)
    block_calls = 0
    constructive_calls: list[bytes] = []

    def fake_blocks(_source: str) -> tuple[Block, ...]:
        nonlocal block_calls
        block_calls += 1
        return parsed.blocks

    monkeypatch.setattr(target, "document", sequence)
    monkeypatch.setattr(target, "blocks", fake_blocks)
    monkeypatch.setattr(target, "verify_constructive_model", constructive_calls.append)

    source = b'resource "a" {}'
    target.test_one_input(source)

    assert constructive_calls == [source]
    assert sequence.calls == 2
    assert sequence.clears == 2
    assert block_calls == 1


def test_fuzz_target_rejects_nondeterministic_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = _DocumentSequence(_block(), _block(end_line=2))

    def ignore_constructive_model(_data: bytes) -> None:
        pass

    monkeypatch.setattr(target, "document", sequence)
    monkeypatch.setattr(target, "verify_constructive_model", ignore_constructive_model)

    with pytest.raises(target.FuzzInvariantError, match="not deterministic"):
        target.test_one_input(b'resource "a" {}')


def test_fuzz_target_rejects_wrapper_disagreement(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = _block()
    sequence = _DocumentSequence(parsed, parsed)

    def disagreeing_blocks(_source: str) -> tuple[Block, ...]:
        return (_block(),)

    def ignore_constructive_model(_data: bytes) -> None:
        pass

    monkeypatch.setattr(target, "document", sequence)
    monkeypatch.setattr(target, "blocks", disagreeing_blocks)
    monkeypatch.setattr(target, "verify_constructive_model", ignore_constructive_model)

    with pytest.raises(target.FuzzInvariantError, match=r"blocks\(\) disagrees"):
        target.test_one_input(b'resource "a" {}')


@pytest.mark.parametrize(
    ("block", "expected_depth", "line_count", "message"),
    [
        (_block(depth=1), 0, 1, "child depth"),
        (_block(line=2), 0, 1, "source span"),
        (_block(depth=129), 129, 1, "depth limit"),
        (_block(attributes=(Attribute("value", "true", 0, 1),)), 0, 1, "attribute source position"),
    ],
    ids=["child-depth", "source-span", "depth-limit", "attribute-position"],
)
def test_walk_blocks_rejects_invalid_trees(
    block: Block,
    expected_depth: int,
    line_count: int,
    message: str,
) -> None:
    with pytest.raises(target.FuzzInvariantError, match=message):
        tuple(target.walk_blocks((block,), expected_depth=expected_depth, line_count=line_count))


def test_walk_blocks_checks_nested_nodes() -> None:
    tree = _block(children=(_block(depth=1, line=2, end_line=2),))

    with pytest.raises(target.FuzzInvariantError, match="source span"):
        tuple(target.walk_blocks((tree,), expected_depth=0, line_count=1))
