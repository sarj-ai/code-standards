from __future__ import annotations

import json
from typing import TYPE_CHECKING, NamedTuple, TypeGuard

import pytest

from sarj_standards import __version__
import sarj_standards.api as standards_api
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.linting import policy as lint_policy
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from pathlib import Path


_SELECTOR = "python:no-string-concat-in-loop"


class _EvaluationResult(NamedTuple):
    status: int
    payload: dict[str, object]


def _source(root: Path) -> Path:
    path = root / "app" / "render.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        'def render(items):\n    result = ""\n    for item in items:\n        result += f"{item}\\n"\n    return result\n',
        encoding="utf-8",
    )
    return path


def _manifest(*, excluded: bool = False, baseline: str | None = None) -> Manifest:
    return Manifest(
        version=__version__,
        configs=("ruff", "pyright"),
        python_dest=".",
        typescript_dest=".",
        excluded_rules=(_SELECTOR,) if excluded else (),
        diagnostic_baseline=baseline,
    )


def _evaluate(root: Path, scope: str, capsys: pytest.CaptureFixture[str]) -> _EvaluationResult:
    status = main(
        [
            "--root",
            str(root),
            "maintain",
            "rules",
            "evaluate",
            "--rule",
            _SELECTOR,
            "--scope",
            scope,
            "--format",
            "json",
            "app/render.py",
        ]
    )
    payload: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    return _EvaluationResult(status, payload)


def _diagnostic(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def test_corpus_evaluation_runs_only_the_selected_rule(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _source(tmp_path)

    status, payload = _evaluate(tmp_path, "corpus", capsys)

    assert status == 1
    raw_diagnostics = payload["diagnostics"]
    assert isinstance(raw_diagnostics, list)
    diagnostics: list[dict[str, object]] = raw_diagnostics  # pyright: ignore[reportUnknownVariableType]
    assert len(diagnostics) == 1
    assert diagnostics[0]["ruleId"] == "no-string-concat-in-loop"


def test_text_evaluation_summarizes_per_rule_findings_and_next_step(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _source(tmp_path)

    status = main(
        [
            "--root",
            str(tmp_path),
            "maintain",
            "rules",
            "evaluate",
            "--rule",
            _SELECTOR,
            "--format",
            "text",
            "app/render.py",
        ]
    )
    output = capsys.readouterr().out

    assert status == 1
    assert f"  {_SELECTOR}: 1 finding" in output
    assert "next: review these findings for false positives" in output
    assert f"code-standards maintain rules stage-warning {_SELECTOR}" in output


def test_observe_rejects_a_rule_that_is_not_warning_stage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _source(tmp_path)
    (tmp_path / MANIFEST_NAME).write_text(_manifest().render(), encoding="utf-8")

    status = main(
        [
            "--root",
            str(tmp_path),
            "observe",
            "--rule",
            _SELECTOR,
            "--format",
            "json",
            "app/render.py",
        ]
    )
    captured = capsys.readouterr()

    assert status == 2
    assert "warning-stage rules only" in captured.err
    assert f"next: code-standards maintain rules stage-warning {_SELECTOR}" in captured.err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("observe", "--help"), "findings with exit 0"),
        (("maintain", "rules", "evaluate", "--help"), "findings exit 1"),
    ],
)
def test_selected_rule_help_explains_exit_semantics(
    argv: tuple[str, ...],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="0"):
        _ = main(list(argv))

    assert expected in capsys.readouterr().out


def test_warning_lifecycle_is_nonblocking_but_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _source(tmp_path)
    (tmp_path / MANIFEST_NAME).write_text(_manifest().render(), encoding="utf-8")
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "rule-warning-levels.v1.json").write_text(
        json.dumps({"schemaVersion": 1, "rules": [_SELECTOR]}),
        encoding="utf-8",
    )
    lint_policy.warning_selectors.cache_clear()
    monkeypatch.setattr(lint_policy, "CONFIGS_DIR", configs)
    warning_selector = RuleSelector.parse(_SELECTOR)
    assert lint_policy.warning_selectors() == frozenset({warning_selector})
    monkeypatch.setattr(standards_api, "_warning_rule_keys", lambda: frozenset({warning_selector}))

    corpus_status, corpus = _evaluate(tmp_path, "corpus", capsys)
    effective_status, effective = _evaluate(tmp_path, "effective", capsys)
    observe_status = main(
        ["--root", str(tmp_path), "observe", "--rule", _SELECTOR, "--format", "json", "app/render.py"]
    )
    observed: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]

    effective_diagnostics = effective["diagnostics"]
    corpus_diagnostics = corpus["diagnostics"]
    assert isinstance(effective_diagnostics, list)
    assert isinstance(corpus_diagnostics, list)
    corpus_items: list[object] = corpus_diagnostics  # pyright: ignore[reportUnknownVariableType]
    effective_items: list[object] = effective_diagnostics  # pyright: ignore[reportUnknownVariableType]
    corpus_diagnostic = corpus_items[0]
    effective_diagnostic = effective_items[0]
    assert _diagnostic(corpus_diagnostic)
    assert _diagnostic(effective_diagnostic)
    assert corpus_diagnostic["severity"] == "error"
    assert corpus_status == 1
    assert effective_diagnostic["severity"] == "warning"
    assert effective_status == 0
    assert observe_status == 0
    assert isinstance(observed["diagnostics"], list)
    diagnostics: list[object] = observed["diagnostics"]  # pyright: ignore[reportUnknownVariableType]
    assert len(diagnostics) == 1
    lint_policy.warning_selectors.cache_clear()


def test_corpus_ignores_rule_exclusion_while_policy_honors_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _source(tmp_path)
    (tmp_path / MANIFEST_NAME).write_text(_manifest(excluded=True).render(), encoding="utf-8")

    corpus_status, corpus = _evaluate(tmp_path, "corpus", capsys)
    policy_status, policy = _evaluate(tmp_path, "effective", capsys)

    assert corpus_status == 1
    assert corpus["diagnostics"]
    assert policy_status == 0
    assert policy["diagnostics"] == []


def test_corpus_ignores_diagnostic_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _source(tmp_path)
    baseline = tmp_path / "diagnostic-baseline.json"
    baseline.write_text('{"schemaVersion":1,"diagnostics":[]}\n', encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(_manifest(baseline=baseline.name).render(), encoding="utf-8")

    status, payload = _evaluate(tmp_path, "corpus", capsys)

    assert status == 1
    assert payload["diagnostics"]


def test_evaluate_rejects_unknown_selector(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _source(tmp_path)

    status = main(
        [
            "--root",
            str(tmp_path),
            "maintain",
            "rules",
            "evaluate",
            "--rule",
            "python:not-real",
            "app/render.py",
        ]
    )

    assert status == 2
    payload: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    assert payload["completion"] == "failed"
