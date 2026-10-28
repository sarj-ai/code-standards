from __future__ import annotations

from pathlib import Path
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
