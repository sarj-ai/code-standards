"""Synthetic coverage for merged-PR comment corpus collection."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import stat

import pytest

from sarj_standards.libs.repository import pr_comment_corpus


_BASE = "a" * 40
_HEAD = "b" * 40
_MERGE = "c" * 40


@dataclass(frozen=True)
class _PullRequestFixture:
    repository: str
    clone_url: str
    number: int
    merged_at: str
    base: str = _BASE
    head: str = _HEAD
    merge: str | None = None
    path: str = "src/example.py"
    before: str = "value = 1\n"
    after: str = "# added explanation\nvalue = 1\n"
    diff: str = "@@ -0,0 +1 @@\n+# added explanation\n"


class _Runner:
    def __init__(self, pull_requests: tuple[_PullRequestFixture, ...]) -> None:
        self.pull_requests: tuple[_PullRequestFixture, ...] = pull_requests
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
        self.calls.append((argv, cwd))
        if argv[:4] == ("gh", "api", "--paginate", "--slurp"):
            route = argv[4]
            if route.startswith("orgs/"):
                repositories = {request.repository: request.clone_url for request in self.pull_requests}
                return json.dumps(
                    [[{"full_name": name, "clone_url": clone_url} for name, clone_url in repositories.items()]]
                )
            repository = route.removeprefix("repos/").split("/pulls?", maxsplit=1)[0]
            values = [
                {
                    "number": request.number,
                    "merged_at": request.merged_at,
                    "base": {"sha": request.base},
                    "head": {"sha": request.head},
                    "merge_commit_sha": request.merge,
                }
                for request in self.pull_requests
                if request.repository == repository
            ]
            return json.dumps([values])
        if argv[:3] == ("git", "init", "--bare"):
            Path(argv[3]).mkdir(parents=True)
            return ""
        if argv[:2] == ("git", "fetch"):
            return ""
        request = self._request(argv)
        if argv[:3] == ("git", "diff", "--name-status"):
            return f"M\0{request.path}\0"
        if argv[:3] == ("git", "diff", "--unified=0"):
            return request.diff
        if argv[:2] == ("git", "show"):
            revision, _, _path = argv[2].partition(":")
            return request.before if revision == request.base else request.after
        message = f"unexpected command: {argv!r}"
        raise AssertionError(message)

    def _request(self, argv: tuple[str, ...]) -> _PullRequestFixture:
        joined = " ".join(argv)
        for request in self.pull_requests:
            effective_head = request.merge or request.head
            if request.base in joined and effective_head in joined:
                return request
            if argv[:2] == ("git", "show") and argv[2].split(":", maxsplit=1)[0] in {
                request.base,
                request.head,
                effective_head,
            }:
                return request
        message = f"no request fixture for: {argv!r}"
        raise AssertionError(message)


def _config(tmp_path: Path, *, limit: int, changes: frozenset[str] | None = None) -> pr_comment_corpus.CollectionConfig:
    return pr_comment_corpus.CollectionConfig(
        organization="example-private-org",
        limit=limit,
        changes=changes or frozenset({"added", "deleted"}),
        cache_dir=tmp_path / "cache",
        output=tmp_path / "records.jsonl",
        manifest=tmp_path / "manifest.json",
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_pull_requests_are_processed_in_stable_global_newest_first_order(tmp_path: Path) -> None:
    runner = _Runner(
        (
            _PullRequestFixture("org/alpha", "https://example.test/alpha.git", 4, "2026-01-02T00:00:00Z"),
            _PullRequestFixture("org/beta", "https://example.test/beta.git", 9, "2026-02-01T00:00:00Z"),
        )
    )

    summary = pr_comment_corpus.collect(_config(tmp_path, limit=2, changes=frozenset({"added"})), runner=runner)
    records = _jsonl(tmp_path / "records.jsonl")

    assert summary.collected == 2
    assert [(record["repository"], record["pull_request"]) for record in records] == [
        ("org/beta", 9),
        ("org/alpha", 4),
    ]


def test_limit_is_exact_across_deleted_and_added_groups_for_a_modification(tmp_path: Path) -> None:
    request = _PullRequestFixture(
        "org/repo",
        "https://example.test/repo.git",
        7,
        "2026-02-01T00:00:00Z",
        before="# deleted one\n\n# deleted two\n",
        after="# added one\n\n# added two\n",
        diff="@@ -1,3 +1,3 @@\n-# deleted one\n+# added one\n \n-# deleted two\n+# added two\n",
    )

    summary = pr_comment_corpus.collect(_config(tmp_path, limit=3), runner=_Runner((request,)))
    records = _jsonl(tmp_path / "records.jsonl")

    assert summary.collected == 3
    assert len(records) == 3
    assert {record["side"] for record in records} == {"added", "deleted"}


def test_modified_comment_is_counted_once_on_each_selected_side(tmp_path: Path) -> None:
    request = _PullRequestFixture(
        "org/repo",
        "https://example.test/repo.git",
        7,
        "2026-02-01T00:00:00Z",
        before="# before\n",
        after="# after\n",
        diff="@@ -1 +1 @@\n-# before\n+# after\n",
    )

    summary = pr_comment_corpus.collect(_config(tmp_path, limit=2), runner=_Runner((request,)))

    assert summary.collected == 2
    assert [record["side"] for record in _jsonl(tmp_path / "records.jsonl")] == ["deleted", "added"]


def test_merged_result_is_preferred_over_an_ephemeral_pull_request_head(tmp_path: Path) -> None:
    request = _PullRequestFixture(
        "org/repo",
        "https://example.test/repo.git",
        7,
        "2026-02-01T00:00:00Z",
        merge=_MERGE,
    )
    runner = _Runner((request,))

    pr_comment_corpus.collect(_config(tmp_path, limit=1, changes=frozenset({"added"})), runner=runner)

    fetches = [argv for argv, _cwd in runner.calls if argv[:2] == ("git", "fetch")]
    assert any(_MERGE in argv and _HEAD not in argv for argv in fetches)


def test_python_extraction_groups_adjacent_comments_and_finds_real_docstrings() -> None:
    source = '''#!/usr/bin/env python3
# coding: utf-8
"""Module documentation.

Still the same group.
"""
VALUE = "not a docstring"
# first line
# second line

def function() -> None:
    """Function documentation."""
    text = "# not a comment"
'''

    groups = pr_comment_corpus.extract_comment_groups("sample.py", source=source)

    assert [(group.kind, group.start_line, group.end_line) for group in groups] == [
        ("comment", 1, 2),
        ("docstring", 3, 6),
        ("comment", 8, 9),
        ("docstring", 12, 12),
    ]
    assert all("not a comment" not in group.text for group in groups)


def test_javascript_extraction_ignores_markers_in_strings_and_templates() -> None:
    source = """const stringValue = "// not a comment";
const templateValue = `/* not a comment */`;
/** API documentation. */
const value = 1; // trailing explanation
const view = <div>{/* JSX explanation. */}</div>;
/* ordinary block. */
"""

    groups = pr_comment_corpus.extract_comment_groups("sample.tsx", source=source)

    assert [(group.kind, group.start_line) for group in groups] == [
        ("jsdoc", 3),
        ("comment", 4),
        ("jsx_comment", 5),
        ("block_comment", 6),
    ]
    assert all("not a comment" not in group.text for group in groups)


@pytest.mark.parametrize(
    ("path", "source", "language"),
    [
        ("sample.py", "# note\n", "python"),
        ("sample.pyi", "# note\n", "python"),
        ("sample.js", "// note\n", "typescript"),
        ("sample.jsx", "// note\n", "typescript"),
        ("sample.mjs", "// note\n", "typescript"),
        ("sample.cjs", "// note\n", "typescript"),
        ("sample.ts", "// note\n", "typescript"),
        ("sample.tsx", "// note\n", "typescript"),
        ("sample.mts", "// note\n", "typescript"),
        ("sample.cts", "// note\n", "typescript"),
    ],
)
def test_supported_extensions(path: str, source: str, language: str) -> None:
    groups = pr_comment_corpus.extract_comment_groups(path, source=source)

    assert len(groups) == 1
    assert groups[0].language == language


def test_unsupported_extensions_do_not_produce_groups() -> None:
    assert pr_comment_corpus.extract_comment_groups("sample.md", source="<!-- note -->\n") == ()


def test_generated_and_directive_comments_are_retained_and_tagged() -> None:
    groups = pr_comment_corpus.extract_comment_groups(
        "generated.ts",
        source="// Generated file; do not edit.\n\n// eslint-disable-next-line no-console\nconsole.log('x');\n",
    )

    assert len(groups) == 2
    assert {tag for group in groups for tag in group.tags} == {"directive", "generated"}


def test_changed_ranges_account_for_multiple_hunks_and_both_sides() -> None:
    ranges = pr_comment_corpus.parse_changed_ranges(
        "@@ -2,2 +2 @@\n-old\n-old two\n+new\n@@ -10 +9,2 @@\n-old three\n+new two\n+new three\n"
    )

    assert ranges.old == ((2, 3), (10, 10))
    assert ranges.new == ((2, 2), (9, 10))


def test_private_outputs_are_owner_only_and_create_new(tmp_path: Path) -> None:
    request = _PullRequestFixture("secret/repo", "https://example.test/repo.git", 1, "2026-01-01T00:00:00Z")
    config = _config(tmp_path, limit=1, changes=frozenset({"added"}))

    pr_comment_corpus.collect(config, runner=_Runner((request,)))

    assert stat.S_IMODE(config.output.stat().st_mode) == 0o600
    assert config.manifest is not None
    assert stat.S_IMODE(config.manifest.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        pr_comment_corpus.collect(config, runner=_Runner((request,)))


@pytest.mark.parametrize(("failure", "skip"), [("blob", "blob_unavailable"), ("parse", "pull_request_error")])
def test_fetch_and_parse_failures_are_accounted_in_private_manifest(tmp_path: Path, failure: str, skip: str) -> None:
    request = _PullRequestFixture("secret/repo", "https://example.test/repo.git", 1, "2026-01-01T00:00:00Z")

    class FailingRunner(_Runner):
        def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
            if failure == "blob" and argv[:2] == ("git", "show"):
                message = "synthetic unavailable blob"
                raise OSError(message)
            if failure == "parse" and argv[:3] == ("git", "diff", "--name-status"):
                return "M\0"
            return super().run(argv, cwd=cwd)

    config = _config(tmp_path, limit=1, changes=frozenset({"added"}))

    with pytest.raises(RuntimeError, match="corpus incomplete"):
        pr_comment_corpus.collect(config, runner=FailingRunner((request,)))

    assert config.manifest is not None
    manifest = config.manifest.read_text(encoding="utf-8")
    assert '"collected": 0' in manifest
    assert '"complete": false' in manifest
    assert f'"{skip}": 1' in manifest


def test_aggregate_summary_does_not_expose_repository_or_comment_identity(tmp_path: Path) -> None:
    request = _PullRequestFixture(
        "secret/customer-repository",
        "https://example.test/customer.git",
        321,
        "2026-01-01T00:00:00Z",
        after="# uniquely sensitive explanation\nvalue = 1\n",
        diff="@@ -0,0 +1 @@\n+# uniquely sensitive explanation\n",
    )

    summary = pr_comment_corpus.collect(
        _config(tmp_path, limit=1, changes=frozenset({"added"})), runner=_Runner((request,))
    ).render()

    assert "secret/customer-repository" not in summary
    assert "customer.git" not in summary
    assert "321" not in summary
    assert "uniquely sensitive explanation" not in summary
    assert "collected" in summary.lower()
