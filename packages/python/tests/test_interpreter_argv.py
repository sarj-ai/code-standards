from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.interpreter_argv import ProgramKind, classify_interpreter, unwrap_command
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
    ("dumb-init-bare-child", ("dumb-init", "python3", "-c", "1"), "inline"),
    ("dumb-init-child-boundary", ("/usr/bin/dumb-init", "--", "python3", "-c", "1"), "inline"),
    ("dumb-init-native-script", ("dumb-init", "python3", "scripts/check.py", "-c", "1"), "external"),
    ("dumb-init-single-child", ("dumb-init", "--single-child", "python3", "-c", "1"), "inline"),
    ("dumb-init-short-single-child", ("dumb-init", "-c", "python3", "-c", "1"), "inline"),
    ("dumb-init-verbose", ("dumb-init", "--verbose", "python3", "-c", "1"), "inline"),
    ("dumb-init-short-verbose", ("dumb-init", "-v", "python3", "-c", "1"), "inline"),
    ("dumb-init-help", ("dumb-init", "--help", "python3", "-c", "1"), "other"),
    ("dumb-init-short-help", ("dumb-init", "-h", "python3", "-c", "1"), "other"),
    ("dumb-init-version", ("dumb-init", "--version", "python3", "-c", "1"), "other"),
    ("dumb-init-short-version", ("dumb-init", "-V", "python3", "-c", "1"), "other"),
    ("dumb-init-help-after-boundary", ("dumb-init", "--", "--help", "python3", "-c", "1"), "other"),
    ("dumb-init-source-option-data", ("dumb-init", "--", "python3", "-c", "--help"), "inline"),
    ("dumb-init-no-child", ("dumb-init",), "other"),
    ("dumb-init-no-child-after-boundary", ("dumb-init", "--"), "other"),
    ("dumb-init-unproven-rewrite", ("dumb-init", "--rewrite", "15:3", "python3", "-c", "1"), "unknown"),
    ("dumb-init-unproven-attached-rewrite", ("dumb-init", "--rewrite=15:3", "python3", "-c", "1"), "unknown"),
    ("dumb-init-unproven-cluster", ("dumb-init", "-cv", "python3", "-c", "1"), "unknown"),
    ("dumb-init-unknown-option", ("dumb-init", "--unknown", "python3", "-c", "1"), "unknown"),
    ("dumb-init-shell-builtin-is-external", ("dumb-init", "command", "python3", "-c", "1"), "other"),
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


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("env", "-Spython3", "-c", "print(1)"), "unknown"),
        (("env", "--split-string=python3", "-c", "print(1)"), "unknown"),
        (("env", "-iSpython3", "-c", "print(1)"), "unknown"),
        (("env", "-S", "python3 -c print(1)"), "unknown"),
        (("env", "--help", "python3", "-c", "print(1)"), "other"),
        (("env", "--version", "python3", "-c", "print(1)"), "other"),
        (("env", "--unknown", "python3", "-c", "print(1)"), "unknown"),
        (("env", "-u"), "unknown"),
        (("env", "-uMODE", "python3", "-c", "print(1)"), "inline"),
        (("env", "-i", "MODE=fixture", "python3", "-c", "print(1)"), "inline"),
        (("env", "--", "python3", "-c", "print(1)"), "inline"),
        (("env", "--", "MODE=fixture", "python3", "-c", "print(1)"), "inline"),
        (("env", "MODE=fixture", "-uMODE", "python3", "-c", "print(1)"), "other"),
        (("env", "MODE=fixture", "--help", "python3", "-c", "print(1)"), "other"),
        (("env", "-u", "", "python3", "-c", "print(1)"), "unknown"),
        (("env", "-uBAD=VALUE", "python3", "-c", "print(1)"), "unknown"),
        (("env", "-C", "", "python3", "-c", "print(1)"), "unknown"),
        (("env", "BAD-NAME=fixture", "python3", "-c", "print(1)"), "inline"),
        (("env", "1NAME=fixture", "python3", "-c", "print(1)"), "inline"),
        (("env", "SPACE NAME=fixture", "python3", "-c", "print(1)"), "inline"),
        (("env", "=fixture", "python3", "-c", "print(1)"), "unknown"),
    ],
)
def test_env_execution_boundaries(argv: tuple[str, ...], expected: ProgramKind) -> None:
    assert classify_interpreter(argv).kind == expected


def test_executable_env_does_not_promote_shell_builtins() -> None:
    assert unwrap_command(("env", "command", "bash", "-c", "printf fixture"), allow_shell_builtins=False) == (
        "command",
        "bash",
        "-c",
        "printf fixture",
    )
    assert unwrap_command(("command", "bash", "-c", "printf fixture")) == ("bash", "-c", "printf fixture")


def test_env_only_wrapper_policy_preserves_other_executable_operands() -> None:
    assert unwrap_command(
        ("env", "sudo", "bash", "-c", "printf fixture"),
        allow_shell_builtins=False,
        allowed_wrappers=frozenset({"env"}),
    ) == ("sudo", "bash", "-c", "printf fixture")
    assert unwrap_command(("env", "sudo", "bash", "-c", "printf fixture")) == ("bash", "-c", "printf fixture")


def test_dumb_init_preserves_child_operands_and_wrapper_policy() -> None:
    child = ("python3", "scripts/check.py", "--help", "--rewrite", "15:3", "-c", "1")
    assert unwrap_command(("dumb-init", "--single-child", "--verbose", "--", *child)) == child
    assert unwrap_command(("dumb-init", *child), allowed_wrappers=frozenset({"env"})) == ("dumb-init", *child)
    assert unwrap_command(("dumb-init", "--", "exec", *child)) == ("exec", *child)
    assert classify_interpreter(("dumb-init", "env", "MODE=test", "python3", "-c", "1")).kind == "inline"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(("bash", "-s", "external.sh"), "stdin", id="stdin-data"),
        pytest.param(("bash", "-s", "--", "-c", "data"), "stdin", id="stdin-boundary"),
        pytest.param(("bash", "-s"), "stdin", id="stdin-only"),
        pytest.param(("bash", "-s", "+s", "data"), "stdin", id="stdin-plus-s"),
        pytest.param(("bash", "+s", "data"), "stdin", id="plus-s"),
        pytest.param(("bash", "-su", "data"), "stdin", id="stdin-cluster"),
        pytest.param(("bash", "-o", "posix", "-s", "data"), "stdin", id="option-before-s"),
        pytest.param(("bash", "-s", "-o", "posix", "data"), "stdin", id="option-after-s"),
        pytest.param(("bash", "-os", "posix", "data"), "stdin", id="value-s-cluster"),
        pytest.param(("bash", "-c", "printf NATIVE_COMMAND"), "shell", id="source-c"),
        pytest.param(("bash", "-sc", "printf NATIVE_COMMAND"), "shell", id="source-sc"),
        pytest.param(("bash", "+c", "printf NATIVE_COMMAND"), "shell", id="source-plus-c"),
        pytest.param(("bash", "-oc", "posix", "printf NATIVE_COMMAND"), "shell", id="source-oc"),
        pytest.param(("bash", "-co", "posix", "printf NATIVE_COMMAND"), "shell", id="source-co"),
        pytest.param(("bash", "scripts/external.sh"), "external", id="external-script"),
        pytest.param(("bash", "-s", "-Z", "data"), "unknown", id="unknown-short"),
        pytest.param(("bash", "-s", "--unknown", "data"), "unknown", id="unknown-long"),
        pytest.param(("bash", "-s", "-o", "s", "data"), "unknown", id="invalid-value"),
        pytest.param(("bash", "--help", "-s", "data"), "other", id="help"),
        pytest.param(("bash", "--version", "-s", "data"), "other", id="version"),
        pytest.param(("bash", "--noprofile", "-s", "data"), "stdin", id="long-before-short"),
        pytest.param(("bash", "-s", "--noprofile", "data"), "unknown", id="long-after-short"),
    ],
)
def test_shell_stdin_source_arguments(argv: tuple[str, ...], expected: ProgramKind) -> None:
    assert classify_interpreter(argv).kind == expected
    assert classify_interpreter(argv) == classify_interpreter(argv)


@pytest.mark.parametrize("option", ["-oc", "-co"])
def test_shell_cluster_values_preserve_source_and_forwarded_args(option: str) -> None:
    invocation = classify_interpreter(("bash", option, "posix", "python3 -c 1", "name", "scripts/data.py"))
    assert invocation.payload == "python3 -c 1"
    assert invocation.forwarded == ("scripts/data.py",)


@pytest.mark.parametrize("shell", ["bash", "sh", "dash"])
@pytest.mark.parametrize(
    ("arguments", "kind", "payload", "forwarded"),
    [
        pytest.param(("-c", "-e", "python3 -c 1", "name", "data"), "shell", "python3 -c 1", ("data",), id="after-c"),
        pytest.param(("-ec", "python3 -c 1"), "shell", "python3 -c 1", (), id="cluster-ec"),
        pytest.param(("-ce", "-u", "python3 -c 1"), "shell", "python3 -c 1", (), id="cluster-ce-later-u"),
        pytest.param(("-c", "-o", "errexit", "python3 -c 1"), "shell", "python3 -c 1", (), id="named-after-c"),
        pytest.param(("-co", "errexit", "-e", "python3 -c 1"), "shell", "python3 -c 1", (), id="cluster-co"),
        pytest.param(("-oc", "errexit", "python3 -c 1"), "shell", "python3 -c 1", (), id="cluster-oc"),
        pytest.param(("-c", "--", "python3 -c 1"), "shell", "python3 -c 1", (), id="boundary-after-c"),
        pytest.param(("-c", "-", "python3 -c 1"), "shell", "python3 -c 1", (), id="single-dash-after-c"),
        pytest.param(("-c", "--", "-e"), "shell", "-e", (), id="option-looking-source-after-boundary"),
        pytest.param(("-c", "-e", ""), "shell", "", (), id="empty-source"),
        pytest.param(
            ("-c", "printf fixture", "name", "-e"), "shell", "printf fixture", ("-e",), id="source-freezes-options"
        ),
        pytest.param(
            ("-c", "-e", "python3 scripts/check.py"), "shell", "python3 scripts/check.py", (), id="native-call-source"
        ),
        pytest.param(("scripts/check.sh", "-c", "python3 -c 1"), "external", None, (), id="script-freezes-options"),
        pytest.param(("--", "-c", "python3 -c 1"), "external", None, (), id="boundary-before-c"),
        pytest.param(("-c", "-e"), "unknown", None, (), id="missing-source"),
        pytest.param(("-c", "--"), "unknown", None, (), id="missing-source-after-boundary"),
        pytest.param(("-c", "-Z", "python3 -c 1"), "unknown", None, (), id="unknown-option-after-c"),
        pytest.param(("-c", "-o", "invalid-option", "python3 -c 1"), "unknown", None, (), id="invalid-named-option"),
        pytest.param(("-c", "-o"), "unknown", None, (), id="missing-named-operand"),
        pytest.param(("-c", "-O", "extglob", "python3 -c 1"), "unknown", None, (), id="unproven-shopt-after-c"),
        pytest.param(("-cO", "extglob", "python3 -c 1"), "unknown", None, (), id="unproven-clustered-shopt"),
    ],
)
def test_shell_command_string_after_options(
    shell: str, arguments: tuple[str, ...], kind: ProgramKind, payload: str | None, forwarded: tuple[str, ...]
) -> None:
    invocation = classify_interpreter((shell, *arguments))
    assert (invocation.kind, invocation.payload, invocation.forwarded) == (kind, payload, forwarded)


@pytest.mark.parametrize("shell", ["zsh", "ksh"])
@pytest.mark.parametrize("option", ["-co", "-oc"])
def test_unproven_dialect_cluster_operands(shell: str, option: str) -> None:
    assert classify_interpreter((shell, option, "errexit", "python3 -c 1")).kind == "unknown"


@pytest.mark.parametrize(
    "options",
    [("-y",), ("-o", "shwordsplit"), ("-oshwordsplit",), ("-onoclobber",)],
    ids=["short-y", "named-option", "attached-named-option", "operand-contains-c"],
)
def test_zsh_external_option_namespace_is_preserved(options: tuple[str, ...]) -> None:
    assert classify_interpreter(("zsh", *options, "scripts/check.sh")).kind == "external"


@pytest.mark.parametrize("shell", ["zsh", "ksh"])
@pytest.mark.parametrize(
    "options",
    [("-c", "-e"), ("-ec",), ("-ce", "-u"), ("-c", "-o", "noclobber"), ("-c", "--")],
    ids=["after-c", "cluster-ec", "cluster-ce-later-u", "named-operand", "option-boundary"],
)
def test_other_shell_command_string_after_options(shell: str, options: tuple[str, ...]) -> None:
    invocation = classify_interpreter((shell, *options, "python3 -c 1", "name", "data"))
    assert (invocation.kind, invocation.payload, invocation.forwarded) == ("shell", "python3 -c 1", ("data",))


def test_zsh_command_option_namespace_is_preserved() -> None:
    assert classify_interpreter(("zsh", "-c", "-o", "shwordsplit", "python3 -c 1")).payload == "python3 -c 1"


@pytest.mark.parametrize("shell", ["zsh", "ksh"])
def test_other_shell_uppercase_option_is_unproven(shell: str) -> None:
    assert classify_interpreter((shell, "-c", "-O", "python3 -c 1", "name", "data")).kind == "unknown"
