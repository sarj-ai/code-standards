from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.interpreter_argv import ProgramKind, classify_interpreter
from sarj_python_lint.rules.no_interpreter_source_arguments import NoInterpreterSourceArguments


_CASES: tuple[tuple[str, tuple[str, ...], ProgramKind], ...] = (
    ("ruby-source", ("ruby", "-e", "puts 1"), "inline"),
    ("ruby-attached-source", ("ruby", "-eputs 1"), "inline"),
    ("ruby-require-separated", ("ruby", "-r", "json", "-e", "puts 1"), "inline"),
    ("ruby-require-attached", ("ruby", "-rjson", "-e", "puts 1"), "inline"),
    ("ruby-include-separated", ("ruby", "-I", ".", "-e", "puts 1"), "inline"),
    ("ruby-include-attached", ("ruby", "-I.", "-e", "puts 1"), "inline"),
    ("ruby-directory-separated", ("ruby", "-C", ".", "-e", "puts 1"), "inline"),
    ("ruby-directory-attached", ("ruby", "-C.", "-e", "puts 1"), "inline"),
    ("ruby-encoding-separated", ("ruby", "-E", "utf-8", "-e", "puts 1"), "inline"),
    ("ruby-encoding-attached", ("ruby", "-Eutf-8", "-e", "puts 1"), "inline"),
    ("ruby-long-encoding-separated", ("ruby", "--encoding", "utf-8", "-e", "puts 1"), "inline"),
    ("ruby-long-encoding-attached", ("ruby", "--encoding=utf-8", "-e", "puts 1"), "inline"),
    ("ruby-cluster-before-operand", ("ruby", "-wr", "json", "-e", "puts 1"), "inline"),
    ("ruby-source-in-cluster", ("ruby", "-we", "puts 1"), "inline"),
    ("ruby-empty-source", ("ruby", "-e", ""), "inline"),
    ("ruby-field-attached", ("ruby", "-Fe", "program.rb"), "external"),
    ("ruby-field-separated-file", ("ruby", "-F", "e", "-e", "puts 1"), "external"),
    ("ruby-field-separated-source", ("ruby", "-F", "-e", "puts 1"), "inline"),
    ("ruby-extension-attached", ("ruby", "-ie", "program.rb"), "external"),
    ("ruby-extension-without-operand", ("ruby", "-i", "-e", "puts 1"), "inline"),
    ("ruby-directory-attached-source-text", ("ruby", "-xe", "program.rb"), "external"),
    ("ruby-require-operand-source-text", ("ruby", "-r", "-e", "program.rb"), "external"),
    ("ruby-file-boundary", ("ruby", "-r", "json", "program.rb", "-e", "puts 1"), "external"),
    ("ruby-option-boundary", ("ruby", "-r", "json", "--", "-e", "puts 1"), "external"),
    ("ruby-plus-file-boundary", ("ruby", "+e", "puts 1"), "external"),
    ("ruby-missing-source", ("ruby", "-e"), "unknown"),
    ("ruby-missing-encoding", ("ruby", "-E"), "unknown"),
    ("ruby-missing-require", ("ruby", "-r"), "unknown"),
    ("ruby-missing-long-operand", ("ruby", "--encoding"), "unknown"),
    ("ruby-unknown-short", ("ruby", "-z", "-e", "puts 1"), "unknown"),
    ("ruby-unknown-cluster", ("ruby", "-ze", "puts 1"), "unknown"),
    ("ruby-unknown-long", ("ruby", "--unknown", "-e", "puts 1"), "unknown"),
    ("ruby-help", ("ruby", "--help", "-e", "puts 1"), "external"),
    ("ruby-short-help", ("ruby", "-he", "puts 1"), "external"),
    ("ruby-version", ("ruby", "--version", "-e", "puts 1"), "external"),
    ("ruby-version-verbose", ("ruby", "-v", "-e", "puts 1"), "inline"),
    ("ruby-warnings-operand", ("ruby", "-W2", "-e", "puts 1"), "inline"),
    ("ruby-record-separator", ("ruby", "-0777", "-e", "puts 1"), "inline"),
    ("ruby-wrapper", ("env", "MODE=test", "ruby", "-r", "json", "-e", "puts 1"), "inline"),
    ("ruby-query-wrapper", ("command", "-v", "ruby", "-e", "puts 1"), "other"),
    ("ruby-unproven-wrapper", ("env", "-S", "ruby -e 'puts 1'"), "unknown"),
    ("python-options", ("python3", "-W", "once", "-Xdev", "-c", "print(1)"), "inline"),
    ("python-operand-source-text", ("python3", "-W", "-c", "program.py"), "external"),
    ("python-module", ("python3", "-m", "tools.check", "-c", "1"), "external"),
    ("python-missing-source", ("python3", "-c"), "unknown"),
    ("node-preloader", ("node", "--require", "preload.js", "-e", "1"), "inline"),
    ("node-attached-preloader", ("node", "-rpreload.js", "program.js", "-e", "1"), "external"),
    ("jq-arguments", ("jq", "--arg", "mode", "strict", ".items"), "inline"),
    ("jq-file", ("jq", "--arg", "mode", "strict", "-f", "filter.jq"), "external"),
    ("awk-arguments", ("awk", "-v", "mode=strict", "{print 1}"), "inline"),
    ("awk-file", ("awk", "-v", "mode=strict", "-f", "filter.awk"), "external"),
    ("shell-cluster", ("bash", "-ceu", "make check"), "shell"),
    ("perl-include", ("perl", "-I", ".", "-e", "print 1"), "inline"),
    ("php-source", ("php", "-r", "echo 1;"), "inline"),
)


@pytest.mark.parametrize(("case_id", "argv", "kind"), _CASES, ids=[case[0] for case in _CASES])
def test_interpreter_option_operands(case_id: str, argv: tuple[str, ...], kind: ProgramKind) -> None:
    assert classify_interpreter(argv).kind == kind, case_id
    source = f"import subprocess\nsubprocess.run({argv!r})\n"
    case = EvaluationCase(
        case_id, Language.PYTHON, source, ExpectedOutcome.MATCH if kind == "inline" else ExpectedOutcome.NO_MATCH
    )
    findings = NoInterpreterSourceArguments().check(Path("tools/check.py"), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH), case_id


@pytest.mark.parametrize("source", ["puts 1", "", "--help"])
def test_ruby_source_payload_is_preserved(source: str) -> None:
    result = classify_interpreter(("ruby", "-r", "json", "-e", source))
    assert (result.kind, result.payload) == ("inline", source)
