from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
from textwrap import indent
import tokenize
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sarj_python_lint._analysis_session import AnalysisSession


_PATH = Path("app/service.py")
_RULE = "no-unused-value-marker"


def test_fixes_share_analysis_only_within_the_same_source_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "def empty():\n    _ = 1\n"
    expected = "def empty():\n    pass\n"
    contexts: list[PythonFileContext] = []
    original_init = PythonFileContext.__init__

    def initialize(context: PythonFileContext, path: Path, text: str, session: AnalysisSession | None = None) -> None:
        original_init(context, path, text, session)
        contexts.append(context)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe actual constructor sharing; injection bypasses the measured lookup.
        PythonFileContext, "__init__", initialize
    )
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == expected
    assert [context.source for context in contexts] == [source, expected]
    assert contexts[0].tree is not contexts[1].tree
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed
    assert len(contexts) == 3
    assert contexts[2].source == expected
    assert contexts[2] is not contexts[1]


@pytest.mark.parametrize("source", [pytest.param("", id="empty"), pytest.param("def empty():\n    pass\n", id="clean")])
def test_no_findings_do_not_tokenize_a_candidate_view(source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    tokenized: list[bool] = []
    original_tokens = tokenize.generate_tokens

    def generate_tokens(readline: Callable[[], str]) -> Iterator[tokenize.TokenInfo]:
        tokenized.append(True)
        yield from original_tokens(readline)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the real tokenizer lookup on the clean path; injection bypasses it.
        tokenize, "generate_tokens", generate_tokens
    )
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    assert tokenized == []


@pytest.mark.parametrize("ending", [pytest.param("\n", id="LF"), pytest.param("\r\n", id="CRLF")])
@pytest.mark.parametrize(
    ("body", "calls", "case_count", "expected"),
    [
        pytest.param(
            "if isinstance(value, str):\n    return 'text'\n"
            "if isinstance(value, bytes):\n    return 'bytes'\nreturn 'other'\n",
            "_label('x'), _label(b'x'), _label(None)",
            2,
            "('text', 'bytes', 'other')\n",
            id="whole-two-branch-sequence-and-fallback",
        ),
        pytest.param(
            "if isinstance(value, int):\n    return 'integer'\n"
            "if isinstance(value, bool):\n    return 'boolean'\n"
            "if isinstance(value, str):\n    return 'text'\nreturn 'other'\n",
            "_label(True), _label(1), _label('x'), _label(None)",
            3,
            "('integer', 'integer', 'text', 'other')\n",
            id="whole-three-branch-int-before-bool",
        ),
        pytest.param(
            "if isinstance(value, bool):\n    return 'boolean'\n"
            "if isinstance(value, int):\n    return 'integer'\n"
            "if isinstance(value, str):\n    return 'text'\nreturn 'other'\n",
            "_label(True), _label(1), _label('x'), _label(None)",
            3,
            "('boolean', 'integer', 'text', 'other')\n",
            id="whole-three-branch-bool-before-int",
        ),
        pytest.param(
            "if isinstance(value, str):\n    if value == 'x':\n        return 'found'\n"
            "    else:\n        return 'text'\n"
            "if isinstance(value, bytes):\n    return 'bytes'\nreturn 'other'\n",
            "_label('x'), _label('y'), _label(b'x'), _label(None)",
            2,
            "('found', 'text', 'bytes', 'other')\n",
            id="authoritative-nested-termination",
        ),
    ],
)
def test_adjacent_type_dispatch_fixes_the_entire_closed_sequence(
    tmp_path: Path, *, body: str, calls: str, case_count: int, expected: str, ending: str
) -> None:
    source = _closed_dispatch(body, calls).replace("\n", ending)

    fixed = fix_source(_PATH, source, rule_ids=["prefer-match-type-dispatch"])

    assert fixed != source
    helper = next(
        node for node in ast.walk(ast.parse(fixed)) if isinstance(node, ast.FunctionDef) and node.name == "_label"
    )
    assert isinstance(helper.body[0], ast.Match)
    assert len(helper.body[0].cases) == case_count
    assert not any(isinstance(node, ast.If) for node in helper.body)
    assert fix_source(_PATH, fixed, rule_ids=["prefer-match-type-dispatch"]) == fixed
    script = tmp_path / "closed_dispatch.py"
    for candidate in (source, fixed):
        script.write_text(candidate + "\nprint(label())\n", encoding="utf-8", newline="")
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout == expected


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "if isinstance(value, str):\n    return 'text'\n# keep this explanation\n"
            "if isinstance(value, bytes):\n    return 'bytes'\nreturn 'other'\n",
            id="comment-between-branches",
        ),
        pytest.param(
            "if isinstance(value, str):\n    return 'text'\n"
            "if isinstance(value, bytes):\n    return 'bytes'  # keep this explanation\nreturn 'other'\n",
            id="comment-in-last-branch",
        ),
        pytest.param(
            "if isinstance(value, str) or isinstance(value, bytes):\n    return 'text'\n"
            "if isinstance(value, int):\n    return 'integer'\nreturn 'other'\n",
            id="OR-stays-manual",
        ),
        pytest.param(
            "if isinstance(value, str):\n    return 'text'\nmarker = 0\n"
            "if isinstance(value, bytes):\n    return 'bytes'\nreturn marker\n",
            id="intervening-statement",
        ),
        pytest.param(
            "if isinstance(value, str):\n    return 'text'\n"
            "if isinstance(value, bytes):\n    return 'bytes'\n"
            "if isinstance(value, int):\n    return 'integer'\nelif isinstance(value, float):\n    return 'float'\n",
            id="mixed-tail-stays-whole-and-manual",
        ),
        pytest.param(
            "if isinstance(value, str):\n    yield value\n    return\nif isinstance(value, bytes):\n    return\n",
            id="generator-custody-unchanged",
        ),
    ],
)
def test_adjacent_dispatch_preserves_manual_boundaries(body: str) -> None:
    source = _closed_dispatch(body, "_label('x')")

    assert fix_source(_PATH, source, rule_ids=["prefer-match-type-dispatch"]) == source


@pytest.mark.parametrize("kind", ["unknown", "escaped", "module", "shadowed", "namespace-mutated", "evaluated-subject"])
def test_adjacent_dispatch_retains_existing_subject_and_caller_guards(kind: str) -> None:
    body = (
        "if isinstance(value, str):\n    return 'text'\n"
        "if isinstance(value, bytes):\n    return 'bytes'\nreturn 'other'\n"
    )
    source = _closed_dispatch(body, "_label('x')")
    match kind:
        case "unknown":
            source = source.replace("def label():", "def label(value):").replace("_label('x')", "_label(value)")
        case "escaped":
            source = source.replace("return _label('x')", "return _label")
        case "module":
            source = "def _label(value):\n" + indent(body, "    ")
        case "shadowed":
            source = "isinstance = callable\n" + source
        case "namespace-mutated":
            source = "import builtins\nbuiltins.str = bytes\n" + source
        case "evaluated-subject":
            source = source.replace("isinstance(value,", "isinstance(value.strip(),")
        case _:
            pytest.fail(f"unknown dispatch boundary: {kind}")

    assert fix_source(_PATH, source, rule_ids=["prefer-match-type-dispatch"]) == source


@pytest.mark.parametrize("control", ["break", "continue"])
def test_adjacent_dispatch_does_not_widen_effectful_loop_custody(tmp_path: Path, control: str) -> None:
    body = (
        "for marker in (0, 1):\n"
        f"    if isinstance(value, str):\n        {control}\n"
        "    if isinstance(value, bytes):\n        return 'bytes'\n"
        "return 'other'\n"
    )
    source = _closed_dispatch(body, "_label('x'), _label(b'x'), _label(None)")

    fixed = fix_source(_PATH, source, rule_ids=["prefer-match-type-dispatch"])

    assert fixed == source
    script = tmp_path / "loop_dispatch.py"
    script.write_text(fixed + "\nprint(label())\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "('other', 'bytes', 'other')\n"


def _closed_dispatch(body: str, calls: str) -> str:
    return "def label():\n    def _label(value):\n" + indent(body, "        ") + f"    return {calls}\n"
