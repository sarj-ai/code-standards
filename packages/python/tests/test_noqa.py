from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Diagnostic, is_suppressed
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._suppression_comments import comment_lines


def test_sarj_noqa_suppresses_diag():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa: SARJ021 — grandfathered 2026-05-20\n"
    assert is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_bare_sarj_noqa_also_suppresses():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa\n"
    assert is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_sarj_noqa_with_different_code_does_not_suppress():
    src = "query = 'SELECT * FROM calls'  # sarj-noqa: SARJ999\n"
    assert not is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def test_ruff_noqa_does_not_suppress_sarj():
    src = "query = 'SELECT * FROM calls'  # noqa: SARJ021 — old syntax\n"
    assert not is_suppressed(src.splitlines(), _diagnostic().line, "SARJ021")


def _diagnostic() -> Diagnostic:
    return Diagnostic(path=Path("<t>.py"), line=1, col=1, code="SARJ021", message="test")


_CASES = (
    ("single-quoted-data", "query = '# sarj-noqa: SARJ021'\n", 1, False),
    ("double-quoted-data", 'query = "# sarj-noqa: SARJ021"\n', 1, False),
    ("template-string-data", "query = t'# sarj-noqa: SARJ021'\n", 1, False),
    ("bytes-data", "query = b'# sarj-noqa: SARJ021'\n", 1, False),
    ("raw-data", "query = r'# sarj-noqa: SARJ021'\n", 1, False),
    ("unicode-data", "query = u'# sarj-noqa: SARJ021'\n", 1, False),
    ("formatted-string-data", "query = f'# sarj-noqa: SARJ021 {name}'\n", 1, False),
    ("triple-quoted-single-data", "query = '''# sarj-noqa: SARJ021'''\n", 1, False),
    ("triple-quoted-multiline-data", 'query = """data\n# sarj-noqa: SARJ021\n"""\n', 2, False),
    ("module-docstring-data", '"""# sarj-noqa: SARJ021"""\n', 1, False),
    ("bare-string-marker", "query = '# sarj-noqa'\n", 1, False),
    ("escaped-quote-data", "query = '\\'# sarj-noqa: SARJ021' \n", 1, False),
    (
        "different-real-comment-after-data",
        "query = '# sarj-noqa: SARJ021' # sarj-noqa: SARJ999 -- external contract\n",
        1,
        False,
    ),
    ("reasoned-exact-comment", "query = 'value' # sarj-noqa: SARJ021 -- external protocol contract\n", 1, True),
    (
        "reasoned-comment-after-unrelated-data",
        "query = '# sarj-noqa: SARJ999' # sarj-noqa: SARJ021 -- external protocol contract\n",
        1,
        True,
    ),
    (
        "reasoned-comment-on-closing-string",
        "query = '''data\n# sarj-noqa: SARJ999\n''' # sarj-noqa: SARJ021 -- external protocol contract\n",
        3,
        True,
    ),
    ("bare-comment-preserved", "query = 'value' # sarj-noqa\n", 1, True),
    ("different-code-comment", "query = 'value' # sarj-noqa: SARJ999 -- external protocol contract\n", 1, False),
    ("comma-list-comment", "query = 'value' # sarj-noqa: SARJ999, SARJ021 -- external protocol contract\n", 1, True),
    ("lowercase-code-comment", "query = 'value' # SARJ-NOQA: sarj021 -- external protocol contract\n", 1, True),
    (
        "duplicate-code-comment",
        "query = 'value' # sarj-noqa: SARJ021, SARJ021 -- external protocol contract\n",
        1,
        True,
    ),
    ("different-line-comment", "# sarj-noqa: SARJ021 -- external protocol contract\nquery = 'value'\n", 2, False),
    ("ordinary-ruff-comment", "query = 'value' # noqa: SARJ021 -- external protocol contract\n", 1, False),
    ("crlf-comment", "query = 'value' # sarj-noqa: SARJ021 -- external protocol contract\r\n", 1, True),
    ("bom-comment", "\ufeffquery = 'value' # sarj-noqa: SARJ021 -- external protocol contract\n", 1, True),
    ("unterminated-multiline", "query = '''# sarj-noqa: SARJ021\n", 1, False),
    ("malformed-indentation", "if True:\n  query = 1 # sarj-noqa: SARJ021\n query = 2\n", 2, False),
    ("incomplete-expression", "query = ( # sarj-noqa: SARJ021\n", 1, False),
)


@pytest.mark.parametrize(("case_id", "source", "line", "suppressed"), _CASES, ids=[case[0] for case in _CASES])
def test_suppression_requires_real_comment(case_id: str, source: str, line: int, *, suppressed: bool) -> None:
    assert is_suppressed(source.splitlines(), line, "SARJ021") is suppressed, case_id


@pytest.mark.parametrize("line", [0, -1, 2])
def test_suppression_invalid_line_is_not_a_waiver(line: int) -> None:
    assert not is_suppressed(["query = 1 # sarj-noqa: SARJ021"], line, "SARJ021")


def test_comment_cache_is_bounded_and_reuses_exact_source() -> None:
    comment_lines.cache_clear()
    lines = ("query = 1 # sarj-noqa: SARJ021 -- external contract",)
    first = comment_lines(lines)
    assert comment_lines(lines) is first
    assert comment_lines.cache_info().misses == 1
    assert comment_lines.cache_info().hits == 1
    comment_lines(("query = 2 # sarj-noqa: SARJ999 -- independent contract",))
    assert comment_lines.cache_info().currsize == 1
    assert comment_lines(lines) == first
    expected_misses = 3
    assert comment_lines.cache_info().misses == expected_misses


def test_mutating_a_standalone_callers_lines_invalidates_comment_provenance() -> None:
    lines = ["query = 1 # sarj-noqa: SARJ021 -- external contract"]
    assert is_suppressed(lines, 1, "SARJ021")
    lines[0] = "query = '# sarj-noqa: SARJ021'"
    assert not is_suppressed(lines, 1, "SARJ021")
    lines[0] = "query = 1 # sarj-noqa: SARJ021 -- external contract"
    assert is_suppressed(lines, 1, "SARJ021")


def test_cached_comment_mapping_cannot_be_mutated() -> None:
    comments = comment_lines(("query = 1 # sarj-noqa: SARJ021 -- external contract",))
    with pytest.raises(TypeError):
        comments[1] = "# sarj-noqa: SARJ999"  # type: ignore[index] -- runtime immutable mapping contract.


_PROCESS_CASES = (
    ("inline-string-marker", "import subprocess\nsubprocess.run(['python3', '-c', '# sarj-noqa: SARJ484'])\n", 1),
    ("inline-bare-string-marker", "import subprocess\nsubprocess.run(['python3', '-c', '# sarj-noqa'])\n", 1),
    (
        "reasoned-real-comment",
        "import subprocess\nsubprocess.run(['python3', '-c', 'pass']) # sarj-noqa: SARJ484 -- fixture exercises argv analysis\n",
        0,
    ),
    (
        "different-comment-after-string",
        "import subprocess\nsubprocess.run(['python3', '-c', '# sarj-noqa: SARJ484']) # sarj-noqa: SARJ999 -- independent fixture\n",
        1,
    ),
    (
        "real-comment-after-different-string",
        "import subprocess\nsubprocess.run(['python3', '-c', '# sarj-noqa: SARJ999']) # sarj-noqa: SARJ484 -- fixture exercises argv analysis\n",
        0,
    ),
    (
        "module-argument-is-data",
        "import subprocess\nsubprocess.run(['python3', '-m', 'tools.check', '# sarj-noqa: SARJ484'])\n",
        0,
    ),
    (
        "shadowed-process-module",
        "import subprocess\ndef check(subprocess):\n    subprocess.run(['python3', '-c', '# sarj-noqa: SARJ484'])\n",
        0,
    ),
    (
        "source-only-repeated-analysis",
        "import subprocess\nsubprocess.run(['python3', '-c', '# sarj-noqa: SARJ484'])\nsubprocess.run(['python3', '-c', '# sarj-noqa: SARJ484'])\n",
        2,
    ),
)


@pytest.mark.parametrize(("case_id", "source", "count"), _PROCESS_CASES, ids=[case[0] for case in _PROCESS_CASES])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_comment_provenance_reaches_rules_and_file_runner(
    tmp_path: Path, case_id: str, source: str, count: int, encoding: str
) -> None:
    path = tmp_path / "check.py"
    path.write_text(source, encoding=encoding)
    selected = ["no-interpreter-source-arguments"]
    findings = analyze(selected, [path])
    assert len(findings) == count, case_id
    assert len({(finding.line, finding.col, finding.code) for finding in findings}) == count
    assert analyze(selected, [path]) == findings


def test_shared_suppression_distinguishes_independent_rule_codes() -> None:
    path = Path("check.py")
    rules = [REGISTRY["no-dunder-all"](), REGISTRY["no-delete-statement"]()]
    source = '__all__ = ["record"]; del record # sarj-noqa: SARJ438 -- public compatibility contract\n'
    findings = check_source(rules, path, source)
    assert [finding.code for finding in findings] == ["SARJ442"]
    data = '__all__ = ["# sarj-noqa: SARJ438"]; del record\n'
    findings = check_source(rules, path, data)
    assert {finding.code for finding in findings} == {"SARJ438", "SARJ442"}


def test_invalid_suppression_policy_diagnostic_remains_unsuppressable() -> None:
    path = Path("check.py")
    source = "value = 1 # sarj-noqa: SARJ419 -- needed\n"
    findings = check_source([REGISTRY["no-vague-suppression-description"]()], path, source)
    assert any(finding.code == "SARJ419" for finding in findings)


def test_nonmarker_query_does_not_scan_or_build_a_cache_entry() -> None:
    comment_lines.cache_clear()
    lines = ["value = 1"] * 100
    assert not is_suppressed(lines, 1, "SARJ021")
    assert comment_lines.cache_info().misses == 0


_GRAMMAR_CASES = (
    ("invalid-marker-prefix", "value = 1 # sarj-noqax", False),
    ("invalid-empty-selector", "value = 1 # sarj-noqa:", False),
    ("invalid-selector-suffix", "value = 1 # sarj-noqa: SARJ484-extra", False),
    ("invalid-empty-list-item", "value = 1 # sarj-noqa: SARJ484,,SARJ021", False),
    ("invalid-unicode-selector-suffix", "value = 1 # sarj-noqa: SARJ484é", False),
    ("bare-compatible", "value = 1 # sarj-noqa", True),
    ("reasoned-exact", "value = 1 # sarj-noqa: SARJ484 -- public contract", True),
    ("single-dash-reason", "value = 1 # sarj-noqa: SARJ484 - public contract", True),
    ("single-dash-reason-without-following-space", "value = 1 # sarj-noqa: SARJ484 -public contract", True),
    ("single-dash-reason-with-following-tab", "value = 1 # sarj-noqa: SARJ484 -\tpublic contract", True),
    ("tab-separated-single-dash-reason", "value = 1 # sarj-noqa: SARJ484\t- public contract", True),
    ("attached-single-dash", "value = 1 # sarj-noqa: SARJ484- public contract", False),
    ("attached-single-dash-selector", "value = 1 # sarj-noqa: SARJ484-public contract", False),
    ("comma-list", "value = 1 # sarj-noqa: SARJ021, SARJ484 -- public contract", True),
)


@pytest.mark.parametrize(("case_id", "source", "suppressed"), _GRAMMAR_CASES, ids=[case[0] for case in _GRAMMAR_CASES])
def test_suppression_requires_a_complete_marker_and_code_list(case_id: str, source: str, *, suppressed: bool) -> None:
    assert is_suppressed(source.splitlines(), 1, "SARJ484") is suppressed, case_id
