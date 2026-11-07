from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest

from sarj_standards.libs.adoption.configs import OXLINT_SUPPRESSIONS
from sarj_standards.libs.diagnostics import Completion, ToolReport
from sarj_standards.libs.linting import oxlint
from tests.oxlint_project import analyze, project


if TYPE_CHECKING:
    from pathlib import Path


# A consumer config that turns the whole floor off.
_OPT_OUT: Final = """
import { createConfig } from "./oxlint.strict.ts";
export default {
  extends: [createConfig()],
  rules: {
    "@sarj/no-vague-suppression-description": "off",
    "@sarj/directive-require-description": "off",
    "typescript/ban-ts-comment": "off",
  },
};
"""


def _floor(report: ToolReport) -> list[tuple[str | None, int | None]]:
    return sorted(
        (item.rule_id, None if item.location.region is None else item.location.region.start.line + 1)
        for item in report.diagnostics
        if item.tags == oxlint.REQUIRED_TAGS
    )


@pytest.mark.parametrize("selected", [None, frozenset({"no-debugger"})], ids=["full", "selected"])
def test_consumer_config_cannot_turn_the_floor_off(tmp_path: Path, selected: frozenset[str] | None) -> None:
    source = (
        "export const a = 1;\n"
        "// eslint-disable-next-line no-debugger -- needed\n"
        "debugger;\n"
        "// @ts-ignore\n"
        "export const b: number = a;\n"
        "// eslint-disable-next-line no-debugger\n"
        "debugger;\n"
    )
    root = project(tmp_path / "repo", {"src/a.ts": source}, config=_OPT_OUT)

    report = analyze(root, oxlint.OxlintRequest(rules=selected), "src")

    assert report.completion is Completion.COMPLETE
    assert _floor(report) == [
        ("@sarj/directive-require-description", 6),
        ("@sarj/no-vague-suppression-description", 2),
        ("typescript/ban-ts-comment", 4),
    ]


@pytest.mark.parametrize(
    ("directive", "expected"),
    [
        ("// oxlint-disable-next-line no-debugger", "@sarj/no-oxlint-directive"),
        ("/* oxlint-disable no-debugger */", "@sarj/no-oxlint-directive"),
        ("debugger; // oxlint-disable-line no-debugger", "@sarj/no-oxlint-directive"),
        # The guard's own report is suppressible, so the directive rules,
        # which read both prefixes, protect it.
        (
            "/* oxlint-disable @sarj/no-oxlint-directive, no-debugger */",
            "@sarj/directive-no-restricted-disable",
        ),
        (
            "debugger; // oxlint-disable-line @sarj/no-oxlint-directive, no-debugger",
            "@sarj/directive-no-restricted-disable",
        ),
        ("// oxlint-disable-next-line no-debugger", "@sarj/directive-require-description"),
    ],
)
def test_oxlint_directives_cannot_hide_from_the_comment_floor(tmp_path: Path, directive: str, expected: str) -> None:
    source = f"{directive}\n" if directive.startswith("debugger") else f"{directive}\ndebugger;\n"
    root = project(tmp_path / "repo", {"src/a.ts": f"export {{}};\n{source}"})

    report = analyze(root, oxlint.OxlintRequest(), "src")

    assert report.issues == ()
    assert expected in {rule for rule, _line in _floor(report)}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            (
                "export {};\n// eslint-disable-next-line @sarj/no-vague-suppression-description, no-debugger -- needed\n"
                "debugger;\n"
            ),
            "@sarj/directive-no-restricted-disable",
        ),
        ("export {};\n/* eslint-disable */\ndebugger;\n", "unicorn/no-abusive-eslint-disable"),
        ("export {};\n/* oxlint-disable */\ndebugger;\n", "unicorn/no-abusive-eslint-disable"),
        (
            "export {};\n/* eslint-disable no-debugger -- block */\ndebugger;\n",
            "@sarj/directive-no-use",
        ),
        (
            "export {};\n/* oxlint-disable no-debugger -- block */\ndebugger;\n/* oxlint-enable no-debugger -- block */\n",
            "@sarj/directive-no-use",
        ),
        ("export {};\n/* eslint-disable no-debugger -- block */\ndebugger;\n", "@sarj/directive-disable-enable-pair"),
    ],
)
def test_directives_cannot_disable_the_floor_or_everything(tmp_path: Path, source: str, expected: str) -> None:
    root = project(tmp_path / "repo", {"src/a.ts": source})

    report = analyze(root, oxlint.OxlintRequest(), "src")

    assert report.issues == ()
    assert expected in {rule for rule, _line in _floor(report)}


def test_floor_findings_cannot_be_bulk_suppressed(tmp_path: Path) -> None:
    root = project(tmp_path / "repo", {"src/a.ts": "// eslint-disable-next-line no-debugger -- needed\ndebugger;\n"})
    (root / OXLINT_SUPPRESSIONS).write_text(
        json.dumps({"src/a.ts": {"@sarj/no-vague-suppression-description": {"count": 1}}}), encoding="utf-8"
    )

    report = analyze(root, oxlint.OxlintRequest(), "src")

    (finding,) = (item for item in report.diagnostics if item.tags == oxlint.REQUIRED_TAGS)
    assert finding.rule_id == "@sarj/no-vague-suppression-description"
    assert finding.location.path == OXLINT_SUPPRESSIONS
    assert "cannot be bulk-suppressed" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "/* eslint-disable */\ndeclare const value: number;\n",
        "/* oxlint-disable */\ndeclare const value: number;\n",
        "// eslint-disable-next-line no-debugger\ndebugger;\n",
        "// oxlint-disable-next-line no-debugger\ndebugger;\n",
    ],
)
def test_line_one_directives_are_reported_without_a_crash(tmp_path: Path, source: str) -> None:
    # The JS eslint-comments plugin reported column -1 of the directive's line,
    # which Oxlint 1.91 rejects on line 1, aborting every JS rule for the file.
    # A report inside the directive also escapes the area that directive disables.
    root = project(tmp_path / "repo", {"src/a.ts": source})

    report = analyze(root, oxlint.OxlintRequest(), "src")

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert ("@sarj/directive-require-description", 1) in _floor(report)
