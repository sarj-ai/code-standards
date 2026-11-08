from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import result_cache
from sarj_standards.libs.linting.analysis import analyze


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.diagnostics import ToolReport


_WORKFLOW = (
    "name: Notify\non: pull_request\njobs:\n  notify:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - id: build\n        env:\n          TITLE: ${{ github.event.pull_request.title }}\n"
    "        run: bash scripts/payload.sh\n"
    "      - uses: slackapi/slack-github-action@v4\n        with:\n"
    "          webhook-type: incoming-webhook\n"
    "          payload: ${{ steps.build.outputs.payload }}\n"
)
_UNSAFE_BUILDER = (
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    'payload=$(jq -nc --arg title "${TITLE:?}" '
    '\'{blocks: [{type: "section", text: {type: "mrkdwn", text: "PR: \\($title)"}}]}\')\n'
    'printf \'payload=%s\\n\' "$payload" >>"${GITHUB_OUTPUT:?}"\n'
)
_SAFE_BUILDER = _UNSAFE_BUILDER.replace('type: "mrkdwn"', 'type: "plain_text"')
_SLACK_RULE = "slack-event-text-in-mrkdwn"


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE_WRITE", "1")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- editable test installs have no immutable engine record.
        result_cache, "_engine_identity", lambda: "engine"
    )
    root = tmp_path / "repository"
    _write(root, ".github/workflows/notify.yml", _WORKFLOW)
    _write(root, "scripts/payload.sh", _SAFE_BUILDER)
    _write(root, "docs/guide.md", "# Guide\n\n<!-- hidden note -->\n")
    return root


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _text_report(root: Path) -> ToolReport:
    paths = [str(path) for path in sorted(root.rglob("*")) if path.is_file()]
    [report] = [tool for tool in analyze(paths, root=root).tools if tool.name == "sarj-text-lint"]
    return report


def _slack_findings(report: ToolReport) -> int:
    return sum(item.rule_id == _SLACK_RULE for item in report.diagnostics)


def test_cached_text_lint_matches_the_uncached_report(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repository, "scripts/payload.sh", _UNSAFE_BUILDER)
    cold = _text_report(repository)
    warm = _text_report(repository)
    monkeypatch.delenv("SARJ_STANDARDS_RESULT_CACHE")
    uncached = _text_report(repository)

    assert cold == warm == uncached
    assert _slack_findings(cold) == 1
    err = capsys.readouterr().err
    assert "text-lint reused 0 of 3 units" in err
    assert "text-lint reused 3 of 3 units" in err


def test_editing_only_the_referenced_builder_reruns_the_workflow(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _slack_findings(_text_report(repository)) == 0
    _write(repository, "scripts/payload.sh", _UNSAFE_BUILDER)

    report = _text_report(repository)

    assert _slack_findings(report) == 1
    assert "text-lint reused 1 of 3 units" in capsys.readouterr().err.splitlines()[-1]


def test_deleting_the_referenced_builder_reruns_the_workflow(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repository, "scripts/payload.sh", _UNSAFE_BUILDER)
    assert _slack_findings(_text_report(repository)) == 1
    (repository / "scripts/payload.sh").unlink()

    assert _slack_findings(_text_report(repository)) == 0
    assert "text-lint reused 1 of 2 units" in capsys.readouterr().err.splitlines()[-1]


def test_read_only_runs_store_nothing(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SARJ_STANDARDS_RESULT_CACHE_WRITE")

    _text_report(repository)
    _text_report(repository)

    assert capsys.readouterr().err.count("text-lint reused 0 of 3 units") == 2
