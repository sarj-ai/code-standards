from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from sarj_standards.libs.linting import oxlint, oxlint_directives
from sarj_standards.libs.linting.oxlint_directives import UnusedDirective
from tests.oxlint_project import analyze, project, run_native


if TYPE_CHECKING:
    from pathlib import Path


_WHOLE: Final = "Unused eslint-disable directive (no problems were reported)."


def _span(source: str, text: str, message: str) -> UnusedDirective:
    encoded, needle = source.encode("utf-8"), text.encode("utf-8")
    # An enable report names the rule in the closing comment, the last match.
    start = encoded.rindex(needle) if "-enable directive" in message else encoded.index(needle)
    return UnusedDirective(message, start, start + len(needle))


@pytest.mark.parametrize(
    ("source", "span", "message", "expected"),
    [
        (
            "const a = 1;\n  // eslint-disable-next-line no-debugger -- café is fine\nexport { a };\n",
            "// eslint-disable-next-line no-debugger -- café is fine",
            _WHOLE,
            "const a = 1;\nexport { a };\n",
        ),
        (
            "export const a = 1; // oxlint-disable-line no-debugger\nexport const b = 2;\n",
            "// oxlint-disable-line no-debugger",
            "Unused oxlint-disable directive (no problems were reported).",
            "export const a = 1;\nexport const b = 2;\n",
        ),
        (
            "// eslint-disable-next-line no-console, no-debugger -- logging is the point\nconsole.info(1);\n",
            "no-debugger",
            "Unused eslint-disable directive (no problems were reported from no-debugger).",
            "// eslint-disable-next-line no-console -- logging is the point\nconsole.info(1);\n",
        ),
        (
            "/* eslint-disable no-console, no-debugger -- pair */\nconsole.info(1);\n/* eslint-enable no-console, no-debugger */\n",
            "no-debugger",
            "Unused eslint-enable directive (no matching eslint-disable directives were found for no-debugger).",
            "/* eslint-disable no-console, no-debugger -- pair */\nconsole.info(1);\n/* eslint-enable no-console */\n",
        ),
        (
            "export {};\n/* eslint-enable no-debugger */\n",
            "no-debugger",
            "Unused eslint-enable directive (no matching eslint-disable directives were found for no-debugger).",
            "export {};\n",
        ),
        (
            "export {};\n/* eslint-enable */\n",
            " eslint-enable ",
            "Unused eslint-enable directive (no matching eslint-disable directives were found).",
            "export {};\n",
        ),
        (
            # Oxlint reports an unused block pair at its enable comment.
            (
                "export const a = 1;\n/* eslint-disable no-console -- pair */\nexport const b = 2;\n"
                "/* eslint-enable no-console */\nconsole.info(a, b);\n"
            ),
            "/* eslint-enable no-console */",
            _WHOLE,
            "export const a = 1;\nexport const b = 2;\nconsole.info(a, b);\n",
        ),
    ],
)
def test_unused_directive_edits_keep_the_surrounding_source(
    source: str, span: str, message: str, expected: str
) -> None:
    unused = _span(source, span, message)

    assert oxlint_directives.remove_unused_directives(source.encode("utf-8"), [unused]).decode("utf-8") == expected


@pytest.mark.parametrize("tool", ["eslint", "oxlint"])
def test_a_rule_unused_in_a_block_pair_is_removed_from_both_comments(tool: str) -> None:
    # Oxlint reports the unused rule of a block disable inside its enable comment.
    source = f"/* {tool}-disable no-console, no-debugger -- pair */\nconsole.info(1);\n/* {tool}-enable no-console, no-debugger */\n"
    start = source.encode("utf-8").rindex(b"no-debugger")
    message = f"Unused {tool}-disable directive (no problems were reported from no-debugger)."

    after = oxlint_directives.remove_unused_directives(
        source.encode("utf-8"), [UnusedDirective(message, start, start + len("no-debugger"))]
    )

    assert after.decode("utf-8") == (
        f"/* {tool}-disable no-console -- pair */\nconsole.info(1);\n/* {tool}-enable no-console */\n"
    )


@pytest.mark.parametrize(
    ("source", "span", "message", "error"),
    [
        ("export const a = 1;\n", "a = 1", _WHOLE, "not inside a comment"),
        ("// a note about eslint\n", "a note", _WHOLE, "not an eslint/oxlint directive"),
        ("export {};\n/* eslint-enable no-console */\n", "/* eslint-enable no-console */", _WHOLE, "no eslint-disable"),
        ("// eslint-disable-next-line no-console\n", "no-console", "unrelated", "not an Oxlint unused-directive"),
    ],
)
def test_unexpected_reports_raise_instead_of_guessing(source: str, span: str, message: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        oxlint_directives.remove_unused_directives(source.encode("utf-8"), [_span(source, span, message)])


def test_plan_removes_every_unused_directive_oxlint_reports(tmp_path: Path) -> None:
    source = (
        "export const a = 1;\n"
        "// eslint-disable-next-line no-debugger -- the next line has no debugger\n"
        "export const b = 2;\n"
        "// eslint-disable-next-line typescript/no-explicit-any, no-debugger -- the SDK payload is untyped\n"
        "export const e: any = a;\n"
        "export const c = 3; // eslint-disable-line no-debugger -- inline note\n"
        "/* eslint-disable no-console -- block */\n"
        "export const d = 4;\n"
        "/* eslint-enable no-console */\n"
        "// eslint-disable-next-line no-debugger -- used\n"
        "debugger;\n"
    )
    root = project(tmp_path / "repo", {"src/a.ts": source, "src/clean.ts": "export {};\n"}, git=True)

    expected = oxlint_directives.plan(root, ("src/a.ts", "src/clean.ts"), run=run_native)

    assert set(expected) == {"src/a.ts"}
    after = expected["src/a.ts"].after.decode("utf-8")
    assert after == (
        "export const a = 1;\n"
        "export const b = 2;\n"
        "// eslint-disable-next-line typescript/no-explicit-any -- the SDK payload is untyped\n"
        "export const e: any = a;\n"
        "export const c = 3;\n"
        "export const d = 4;\n"
        "// eslint-disable-next-line no-debugger -- used\n"
        "debugger;\n"
    )
    assert (root / "src/a.ts").read_text(encoding="utf-8") == source
    assert not list(root.rglob(".sarj-oxlint-*"))

    oxlint_directives.apply(root, expected)

    assert oxlint_directives.validate(root, expected) == frozenset({"src/a.ts"})
    report = analyze(root, oxlint.OxlintRequest(), "src")
    assert report.issues == ()
    assert {item.rule_id for item in report.diagnostics} == set()


def test_plan_keeps_a_partly_unused_block_pair_closed(tmp_path: Path) -> None:
    source = (
        "/* eslint-disable no-console, no-debugger -- pair */\n"
        "console.info(1);\n"
        "/* eslint-enable no-console, no-debugger -- pair */\n"
        "debugger;\n"
    )
    root = project(tmp_path / "repo", {"src/a.ts": source}, git=True)

    expected = oxlint_directives.plan(root, ("src/a.ts",), run=run_native)
    oxlint_directives.apply(root, expected)

    assert (root / "src/a.ts").read_text(encoding="utf-8") == (
        "/* eslint-disable no-console -- pair */\nconsole.info(1);\n/* eslint-enable no-console -- pair */\ndebugger;\n"
    )
    rules = {item.rule_id for item in analyze(root, oxlint.OxlintRequest(), "src").diagnostics}
    # The debugger after the pair is reported again, so no disable is left open.
    assert "no-debugger" in rules
    assert "@sarj/directive-disable-enable-pair" not in rules


def test_plan_refuses_sources_oxlint_cannot_finish(tmp_path: Path) -> None:
    # A parse error leaves the file unlinted; no plan is safe.
    root = project(
        tmp_path / "repo", {"src/a.ts": "// eslint-disable-next-line no-debugger\nexport const = ;\n"}, git=True
    )

    with pytest.raises(ValueError, match="Oxlint failed before producing a directive-only plan"):
        oxlint_directives.plan(root, ("src/a.ts",), run=run_native)


def test_plan_lets_the_formatter_read_untracked_inputs_the_caller_owns(tmp_path: Path) -> None:
    # A migrating update seeds the oxfmt config before the rollout commits it.
    source = "// eslint-disable-next-line no-debugger -- unused\nexport const a = 1;\n"
    root = project(tmp_path / "repo", {"src/a.ts": source, "package.json": '{"private":true}\n'}, git=True)
    (root / ".oxfmtrc.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be tracked repository inputs"):
        oxlint_directives.plan(root, ("src/a.ts",), run=run_native)
    # Owned, the config passes; the fixture then stops at the missing oxfmt pin.
    with pytest.raises(ValueError, match="one unambiguous declared dependency"):
        oxlint_directives.plan(root, ("src/a.ts",), run=run_native, owned=(".oxfmtrc.json",))


@pytest.mark.parametrize("severity", ["off", "warn", "error"])
def test_plan_preserves_the_configured_unused_directive_policy(tmp_path: Path, severity: str) -> None:
    source = (
        "// eslint-disable-next-line no-debugger -- retained by consumer policy\n"
        "export const value = 1;\n"
        "// eslint-disable-next-line no-debugger -- actually used\n"
        "debugger;\n"
    )
    outside = "// eslint-disable-next-line no-debugger -- outside selection\nexport const other = 2;\n"
    config = (
        'import { createConfig } from "./oxlint.strict.ts";\n'
        f'export default {{ extends: [createConfig()], options: {{ reportUnusedDisableDirectives: "{severity}" }} }};\n'
    )
    root = project(tmp_path / "repo", {"src/a.ts": source, "src/other.ts": outside}, config=config, git=True)
    expected = oxlint_directives.plan(root, ("src/a.ts",), run=run_native)

    if severity == "off":
        assert expected == {}
    else:
        assert set(expected) == {"src/a.ts"}
        assert expected["src/a.ts"].after.decode("utf-8") == (
            "export const value = 1;\n// eslint-disable-next-line no-debugger -- actually used\ndebugger;\n"
        )
    assert (root / "src/a.ts").read_text(encoding="utf-8") == source
    assert (root / "src/other.ts").read_text(encoding="utf-8") == outside
