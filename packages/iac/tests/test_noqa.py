from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.__main__ import analyze, main
from sarj_iac_lint._hcl import suppression_comment_lines
from sarj_iac_lint.rule_base import ExampleOutcome, is_suppressed
from sarj_iac_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


def test_bare_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_BARE)])
    assert rc == 0
    assert not capsys.readouterr().out


def test_coded_noqa_suppresses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_CODE)])
    assert rc == 0
    assert not capsys.readouterr().out


def test_wrong_code_does_not_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_NOQA_WRONG)])
    assert rc == 1
    assert "SARJ201" in capsys.readouterr().out


def test_absent_noqa_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["check", "--rule", "require-deletion-protection", _write(tmp_path, _SQL_PLAIN)])
    assert rc == 1
    assert "SARJ201" in capsys.readouterr().out


def _write(tmp_path: Path, content: str) -> str:
    f = tmp_path / "main.tf"
    f.write_text(content, encoding="utf-8")
    return str(f)


_SQL_PLAIN = """
resource "aws_db_instance" "main" {
  engine = "postgres"
}
"""

_SQL_NOQA_BARE = """
resource "aws_db_instance" "main" {  # sarj-noqa
  engine = "postgres"
}
"""

_SQL_NOQA_CODE = """
resource "aws_db_instance" "main" {  # sarj-noqa: SARJ201 — ephemeral
  engine = "postgres"
}
"""

_SQL_NOQA_WRONG = """
resource "aws_db_instance" "main" {  # sarj-noqa: SARJ999
  engine = "postgres"
}
"""


_LEXICAL_NOQA_CASES = (
    (
        "quoted-documentation",
        'resource "google_service_account_key" "main" { keepers = { documentation = "# sarj-noqa: SARJ211" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "escaped-quote",
        'resource "google_service_account_key" "main" { keepers = { documentation = "documentation \\" # sarj-noqa: SARJ211" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "interpolation-nested-quote",
        'resource "google_service_account_key" "main" { keepers = { documentation = "${upper("# sarj-noqa: SARJ211")}" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "interpolation-object",
        'resource "google_service_account_key" "main" { keepers = { documentation = "${lookup({reason = "# sarj-noqa: SARJ211"}, "reason")}" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "escaped-interpolation",
        'resource "google_service_account_key" "main" { keepers = { documentation = "$${# sarj-noqa: SARJ211}" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "escaped-directive",
        'resource "google_service_account_key" "main" { keepers = { documentation = "%%{# sarj-noqa: SARJ211}" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "unicode-documentation",
        'resource "google_service_account_key" "main" { keepers = { documentation = "文档 # sarj-noqa: SARJ211" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "ordinary-key",
        'resource "google_service_account_key" "main" { service_account_id = "app" }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "reasoned-line-comment",
        'resource "google_service_account_key" "main" { # sarj-noqa: SARJ211 — legacy migration expires Friday\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "bare-line-comment",
        'resource "google_service_account_key" "main" { # sarj-noqa — migration tracked externally\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "case-and-comma",
        'resource "google_service_account_key" "main" { # SaRj-NoQa: sarj201, sarj211 — legacy migration\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "wrong-code",
        'resource "google_service_account_key" "main" { # sarj-noqa: SARJ201 — isolated deletion policy\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "block-comment",
        'resource "google_service_account_key" "main" { /* # sarj-noqa: SARJ211 — legacy migration */\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "quoted-block-reason",
        'resource "google_service_account_key" "main" { /* "# sarj-noqa: SARJ211" legacy migration */\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "slash-comment-marker",
        'resource "google_service_account_key" "main" { // # sarj-noqa: SARJ211 — legacy migration\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "slash-directive-existing-contract",
        'resource "google_service_account_key" "main" { // sarj-noqa: SARJ211 — legacy migration\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "different-line-comment",
        '# sarj-noqa: SARJ211 — previous line only\nresource "google_service_account_key" "main" { service_account_id = "app" }\n',
        2,
        "SARJ211",
        False,
    ),
    (
        "crlf-line-comment",
        'resource "google_service_account_key" "main" { # sarj-noqa: SARJ211 — migration\r\n service_account_id = "app"\r\n}\r\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "data-then-real-comment",
        'resource "google_service_account_key" "main" { keepers = { documentation = "# sarj-noqa: SARJ999" } } # sarj-noqa: SARJ211 — migration\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "first-real-directive-retained",
        'resource "google_service_account_key" "main" { /* # sarj-noqa: SARJ999 */ # sarj-noqa: SARJ211 — migration\n service_account_id = "app"\n}\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "hash-in-quoted-block-delimiters",
        'locals { documentation = "/* # sarj-noqa: SARJ211 */" }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "hash-in-template-block-delimiters",
        'locals { documentation = "${upper("/* # sarj-noqa: SARJ211 */")}" }\n',
        1,
        "SARJ211",
        False,
    ),
    ("heredoc-body", "locals {\n documentation = <<EOF\n# sarj-noqa: SARJ211\nEOF\n}\n", 3, "SARJ211", False),
    (
        "indented-heredoc-body",
        "locals {\n documentation = <<-EOF\n  # sarj-noqa: SARJ211\n  EOF\n}\n",
        3,
        "SARJ211",
        False,
    ),
    (
        "heredoc-interpolation-body",
        'locals {\n documentation = <<EOF\n${upper("# sarj-noqa: SARJ211")}\nEOF\n}\n',
        3,
        "SARJ211",
        False,
    ),
    (
        "heredoc-then-comment",
        "locals {\n documentation = <<EOF\n# sarj-noqa: SARJ211\nEOF\n} # sarj-noqa: SARJ211 — migration\n",
        5,
        "SARJ211",
        True,
    ),
    (
        "malformed-heredoc-opener-comment",
        "locals {\n documentation = <<EOF # sarj-noqa: SARJ211 — migration\nordinary documentation\nEOF\n}\n",
        2,
        "SARJ211",
        True,
    ),
    (
        "multiline-block-comment",
        '/* documentation\n# sarj-noqa: SARJ211 — migration\n*/\nresource "google_service_account_key" "main" { service_account_id = "app" }\n',
        2,
        "SARJ211",
        True,
    ),
    (
        "multiple-block-comments",
        '/* # sarj-noqa: SARJ211 */ locals { value = "# sarj-noqa: SARJ999" } /* second reason */\n',
        1,
        "SARJ211",
        True,
    ),
    ("comment-quote-is-data", '# rationale " # sarj-noqa: SARJ211 — migration\n', 1, "SARJ211", True),
    (
        "comment-heredoc-spelling",
        '# rationale <<EOF\nresource "google_service_account_key" "main" { service_account_id = "app" }\n# sarj-noqa: SARJ211 — migration\n',
        3,
        "SARJ211",
        True,
    ),
    ("unterminated-quoted-marker", 'locals { value = "# sarj-noqa: SARJ211\n', 1, "SARJ211", False),
    ("unterminated-interpolation", 'locals { value = "${upper("# sarj-noqa: SARJ211")\n', 1, "SARJ211", False),
    ("unterminated-heredoc", "locals {\nvalue = <<EOF\n# sarj-noqa: SARJ211\n", 3, "SARJ211", False),
    ("unterminated-block-comment", "locals { /* # sarj-noqa: SARJ211\n", 1, "SARJ211", True),
    (
        "nested-template-real-comment",
        'locals { value = "${jsonencode({reason = "data"})}" } # sarj-noqa: SARJ211 — migration\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "nested-template-source-data",
        'locals { value = "${jsonencode({reason = "# sarj-noqa: SARJ211"})}" }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "nested-template-source-data-and-real-comment",
        'locals { value = "${jsonencode({reason = "# sarj-noqa: SARJ999"})}" } # sarj-noqa: SARJ211 — migration\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "block-comment-quote-before-data",
        'resource "google_service_account_key" "main" { /* reason " */ keepers = { reason = "# sarj-noqa: SARJ211" } }\n',
        1,
        "SARJ211",
        False,
    ),
    (
        "template-real-comment",
        'locals { value = "${upper("data")}" } # sarj-noqa: SARJ211 — migration\n',
        1,
        "SARJ211",
        True,
    ),
    (
        "real-comment-with-block-spelling",
        "# reason /* historical text # sarj-noqa: SARJ211 — migration\n",
        1,
        "SARJ211",
        True,
    ),
)


@pytest.mark.parametrize(
    ("name", "source", "line", "code", "expected"),
    _LEXICAL_NOQA_CASES,
    ids=tuple(case[0] for case in _LEXICAL_NOQA_CASES),
)
@pytest.mark.parametrize("crlf", [False, True])
def test_noqa_uses_shared_comment_provenance(
    name: str, source: str, line: int, code: str, *, expected: bool, crlf: bool
) -> None:

    source = source.replace("\n", "\r\n") if crlf else source
    assert is_suppressed(source.splitlines(), line, code) is expected, name


_EMITTING_NOQA_IDS = frozenset(
    {
        "block-comment",
        "block-comment-quote-before-data",
        "quoted-documentation",
        "different-line-comment",
        "escaped-interpolation",
        "interpolation-nested-quote",
        "quoted-block-reason",
        "ordinary-key",
        "data-then-real-comment",
        "reasoned-line-comment",
        "unicode-documentation",
        "slash-comment-marker",
        "interpolation-object",
        "escaped-directive",
        "first-real-directive-retained",
        "bare-line-comment",
        "slash-directive-existing-contract",
        "case-and-comma",
        "crlf-line-comment",
        "escaped-quote",
        "wrong-code",
    }
)


@pytest.mark.parametrize(
    ("name", "source", "line", "code", "expected"),
    tuple(case for case in _LEXICAL_NOQA_CASES if case[0] in _EMITTING_NOQA_IDS),
    ids=tuple(case[0] for case in _LEXICAL_NOQA_CASES if case[0] in _EMITTING_NOQA_IDS),
)
@pytest.mark.parametrize("crlf", [False, True])
def test_shared_provenance_filters_actual_findings(
    name: str, source: str, line: int, code: str, tmp_path: Path, *, expected: bool, crlf: bool
) -> None:
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    findings = analyze(["no-managed-service-account-key"], [path])
    expected_count = 0 if expected else 1
    assert len(findings) == expected_count, name
    assert all(item.line == line and item.code == code for item in findings)
    assert findings == analyze(["no-managed-service-account-key"], [path])


_NOQA_DIRECTIVE_CASES = (
    ("bare", "# sarj-noqa", True),
    ("reasoned", "# sarj-noqa: SARJ211 — migration", True),
    ("ascii-reason", "# sarj-noqa: SARJ211 -- migration", True),
    ("endash-reason", "# sarj-noqa: SARJ211 – migration", True),
    ("case-list", "# SARJ-NOQA: sarj999, sarj211 — migration", True),
    ("duplicate-code", "# sarj-noqa: SARJ211,SARJ211 — migration", True),
    ("wrong-code", "# sarj-noqa: SARJ999 — migration", False),
    ("near-number", "# sarj-noqa: SARJ2110 — migration", False),
    ("empty-colon", "# sarj-noqa:", False),
    ("empty-colon-reason", "# sarj-noqa: — migration", False),
    ("marker-alias", "# sarj-noqa-extra", False),
    ("marker-underscore", "# sarj-noqa_extra", False),
    ("unicode-marker", "# sarj-noqaé", False),
    ("double-comma", "# sarj-noqa: SARJ211,,SARJ212", False),
    ("leading-comma", "# sarj-noqa: ,SARJ211", False),
    ("trailing-comma", "# sarj-noqa: SARJ211,", False),
    ("hyphen-code", "# sarj-noqa: SARJ211-extra", False),
    ("unicode-code", "# sarj-noqa: SARJ211é", False),
    ("split-code", "# sarj-noqa: SARJ 211", False),
    ("missing-comma", "# sarj-noqa: SARJ211 SARJ212", False),
    ("colon-code", "# sarj-noqa: SARJ211:extra", False),
    ("invalid-code-start", "# sarj-noqa: 211,SARJ211", False),
    ("first-marker", "# sarj-noqa: SARJ999 — wrong # sarj-noqa: SARJ211", False),
)


@pytest.mark.parametrize(
    ("name", "marker", "expected"), _NOQA_DIRECTIVE_CASES, ids=tuple(case[0] for case in _NOQA_DIRECTIVE_CASES)
)
@pytest.mark.parametrize("crlf", [False, True])
def test_noqa_requires_complete_directive_codes(
    name: str, marker: str, tmp_path: Path, *, expected: bool, crlf: bool
) -> None:
    source = f'resource "google_service_account_key" "main" {{}} {marker}\n'
    source = source.replace("\n", "\r\n") if crlf else source
    assert is_suppressed(source.splitlines(), 1, "SARJ211") is expected, name
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    findings = analyze(["no-managed-service-account-key"], [path])
    assert len(findings) == (0 if expected else 1), name
    assert findings == analyze(["no-managed-service-account-key"], [path])


@pytest.mark.parametrize("rule_id", tuple(REGISTRY))
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("crlf", [False, True])
def test_reasoned_noqa_preserves_registered_rule_selection(
    rule_id: str, tmp_path: Path, *, selected: bool, crlf: bool
) -> None:
    rule = REGISTRY[rule_id]
    spec = rule.native_spec()
    assert spec is not None
    example = next(
        item
        for item in spec.examples
        if item.outcome == ExampleOutcome.MATCH and not str(item.focus_path).endswith(".json")
    )
    paths: list[Path] = []
    for item in example.files:
        path = tmp_path / str(item.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
        paths.append(path)
    focus = tmp_path / str(example.focus_path)
    original = analyze([rule_id], paths)
    assert any(item.path == focus for item in original)
    code = rule.code if selected else "SARJ999"
    revised = (
        "\n".join(
            f"{line} # sarj-noqa: {code} — migration" if line.strip() else line
            for line in focus.read_text(encoding="utf-8").splitlines()
        )
        + "\n"
    )
    revised = revised.replace("\n", "\r\n") if crlf else revised
    focus.write_bytes(revised.encode())
    findings = analyze([rule_id], paths)
    expected_count = 0 if selected else sum(item.path == focus for item in original)
    assert sum(item.path == focus for item in findings) == expected_count
    assert findings == analyze([rule_id], paths)


def test_shared_comment_projection_is_reused_for_diagnostics() -> None:
    source = "\n".join(
        f'resource "google_service_account_key" "item_{i}" {{}} # sarj-noqa: SARJ211 — migration' for i in range(50)
    )
    comments = suppression_comment_lines(source)
    before = suppression_comment_lines.cache_info()
    lines = source.splitlines()
    assert all(is_suppressed(lines, line, "SARJ211", comments=comments) for line in range(1, 51))
    assert suppression_comment_lines.cache_info() == before
    assert suppression_comment_lines(source) is comments


def test_noqa_does_not_freeze_the_registered_code_catalog() -> None:
    source = "# sarj-noqa: FutureRule_42 — migration"
    assert is_suppressed([source], 1, "FutureRule_42")
    assert not is_suppressed([source], 1, "FutureRule_420")


@pytest.mark.parametrize(
    ("marker", "expected_codes"),
    [
        ("# ordinary comment", frozenset({"SARJ201", "SARJ211", "SARJ212"})),
        ("# sarj-noqa: SARJ211 — migration", frozenset({"SARJ201", "SARJ212"})),
        ("# sarj-noqa: SARJ211,SARJ212 — migration", frozenset({"SARJ201"})),
        ("# sarj-noqa: SARJ2110 — migration", frozenset({"SARJ201", "SARJ211", "SARJ212"})),
        ("# sarj-noqa: SARJ211,,SARJ212 — migration", frozenset({"SARJ201", "SARJ211", "SARJ212"})),
        ("# sarj-noqa", frozenset[str]()),
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_noqa_selects_codes_with_all_registered_rules(
    marker: str, expected_codes: frozenset[str], tmp_path: Path, *, crlf: bool
) -> None:
    source = 'resource "google_service_account_key" "main" {}\nresource "google_project_iam_member" "editor" { role = "roles/editor" }\nresource "google_sql_database" "app" {}\n'
    revised = "\n".join(f"{line} {marker}" for line in source.splitlines()) + "\n"
    revised = revised.replace("\n", "\r\n") if crlf else revised
    path = tmp_path / "main.tf"
    path.write_bytes(revised.encode())
    findings = analyze(list(REGISTRY), [path])
    assert {item.code for item in findings} == expected_codes
    assert len(findings) == len(expected_codes)
    assert findings == analyze(list(REGISTRY), [path])


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (" - external contract", 0),
        (" -\texternal contract", 0),
        (" -external contract", 0),
        ("\t- external contract", 0),
        ("\t-- external contract", 0),
        ("-extra", 1),
        ("- external contract", 1),
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_native_comment_reason_requires_separated_single_dash(
    suffix: str, expected: int, tmp_path: Path, *, crlf: bool
) -> None:
    source = (
        f'resource "google_service_account_key" "main" {{ # sarj-noqa: SARJ211{suffix}\n'
        ' service_account_id = "app"\n}\n'
    )
    source = source.replace("\n", "\r\n") if crlf else source
    path = tmp_path / "main.tf"
    path.write_bytes(source.encode())
    findings = analyze(["no-managed-service-account-key"], [path])
    assert len(findings) == expected
    assert findings == analyze(["no-managed-service-account-key"], [path])
