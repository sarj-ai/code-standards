from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sarj_standards.cli.main import build_parser


class _CorpusArgs(argparse.Namespace):
    roots: list[Path]
    github_org: str | None
    limit: int
    changes: frozenset[str]
    cache_dir: Path | None
    include_text: Path | None
    manifest: Path | None

    def __init__(self) -> None:
        super().__init__()
        self.roots = []
        self.github_org = None
        self.limit = 5000
        self.changes = frozenset({"added", "deleted"})
        self.cache_dir = None
        self.include_text = None
        self.manifest = None


def _parse(*argv: str) -> _CorpusArgs:
    return build_parser().parse_args(["maintain", "comment-corpus", *argv], namespace=_CorpusArgs())


def test_comment_corpus_preserves_local_root_mode() -> None:
    parsed = _parse("repository-a", "repository-b", "--include-text", "private.jsonl")

    assert parsed.roots == [Path("repository-a"), Path("repository-b")]
    assert parsed.github_org is None
    assert parsed.include_text == Path("private.jsonl")


def test_comment_corpus_parses_private_organization_mode() -> None:
    parsed = _parse(
        "--github-org",
        "example-org",
        "--limit",
        "5000",
        "--changes",
        "added,deleted",
        "--cache-dir",
        "private-cache",
        "--include-text",
        "private.jsonl",
        "--manifest",
        "private-manifest.json",
    )

    assert parsed.roots == []
    assert parsed.github_org == "example-org"
    assert parsed.limit == 5000
    assert parsed.changes == frozenset({"added", "deleted"})
    assert parsed.cache_dir == Path("private-cache")
    assert parsed.include_text == Path("private.jsonl")
    assert parsed.manifest == Path("private-manifest.json")


@pytest.mark.parametrize("value", ["", "context", "added,context"])
def test_comment_corpus_rejects_unknown_diff_sides(value: str) -> None:
    with pytest.raises(SystemExit):
        _parse("--github-org", "example-org", "--changes", value)


def test_comment_corpus_requires_one_source() -> None:
    with pytest.raises(SystemExit):
        _parse()
