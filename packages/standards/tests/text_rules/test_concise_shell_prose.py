from pathlib import Path

from pydantic import JsonValue, ValidationError
import pytest
from sarj_rule_contracts.examples import verify_examples

from sarj_standards.libs.linting.shell_ast import ShellSyntaxError
from sarj_standards.libs.linting.text_rules.concise_shell_prose import ConciseShellProse
from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


@pytest.fixture(scope="module")
def rule() -> ConciseShellProse:
    return ConciseShellProse()


def test_documented_examples() -> None:
    rule = selected(RuleSelector.parse("text:concise-shell-prose"))
    verify_examples(rule.spec.examples, rule.analyze)


_LONG_HELP = "if [[ ${1:-} == --help ]]; then\ncat <<'DOC'\nUsage: app\nConfigure the account.\nPrepare the workspace.\nRead the runbook.\nDOC\nfi\n"


@pytest.mark.parametrize(
    "source",
    [
        "# One constraint.\n# Another constraint.\n# A third constraint.\nrun\n",
        "# One constraint.\n\n# Another constraint.\n\n# A third constraint.\nrun\n",
        "# " + "word " * 41 + "\nrun\n",
        "run # " + "word " * 41 + "\n",
        "# shellcheck disable=SC1091\n# One explanation.\n# Another explanation.\n# A third explanation.\nrun\n",
        _LONG_HELP,
        _LONG_HELP.replace("--help", "'-h'"),
        _LONG_HELP.replace("--help", "\"--he\"'lp'"),
    ],
)
def test_rejects_long_actual_comments_or_proven_help(source: str, rule: ConciseShellProse) -> None:
    assert len(rule.check(Path("app.sh"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "#!/usr/bin/env bash\n# shellcheck disable=SC1091\n# shfmt -ln=bash\nrun\n",
        "# SPDX-License-Identifier: MIT\n# Copyright 2026 Example\n# Licensed under the MIT license.\nrun\n",
        "printf '%s\\n' '# first' '# second' '# third'\n",
        "cat >settings.ini <<'DOC'\n# First data line\n# Second data line\n# Third data line\n# Fourth data line\nDOC\n",
        "first # first constraint\nsecond # second constraint\nthird # third constraint\n",
        _LONG_HELP.replace("cat <<", "cat >settings.ini <<"),
        _LONG_HELP.replace("== --help", "!= --help"),
        _LONG_HELP.replace("cat <<", "parse_config <<"),
        "cat() { parse_config; }\n" + _LONG_HELP,
        _LONG_HELP.replace("Read the runbook.\n", ""),
    ],
)
def test_preserves_directives_data_short_help_and_unproven_sinks(source: str, rule: ConciseShellProse) -> None:
    assert rule.check(Path("app.sh"), source) == []


def test_malformed_shell_propagates_native_parser_rejection(rule: ConciseShellProse) -> None:
    with pytest.raises(ShellSyntaxError):
        rule.check(Path("app.sh"), "if then\n")


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "# sarj-noqa: SARJ317 -- The external protocol requires these exact lines.\n# First constraint.\n# Second constraint.\n# Third constraint.\nrun\n",
            id="justified-comment-contract",
        ),
        pytest.param(
            _LONG_HELP.replace(
                "cat <<", "# sarj-noqa: SARJ317 -- The external help contract requires this text.\ncat <<"
            ),
            id="preceding-help-contract",
        ),
        pytest.param(
            _LONG_HELP.replace(
                "cat <<'DOC'", "cat <<'DOC' # sarj-noqa: SARJ317 -- Preserve the external help contract."
            ),
            id="inline-help-contract",
        ),
    ],
)
def test_required_long_contracts_need_real_exact_code_justifications(source: str, rule: ConciseShellProse) -> None:
    assert rule.check(Path("app.sh"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_LONG_HELP.replace("cat <<", "# sarj-noqa: SARJ317\ncat <<"), id="missing-justification"),
        pytest.param(
            _LONG_HELP.replace("cat <<", "# sarj-noqa: SARJ300 -- Another rule owns this contract.\ncat <<"),
            id="different-rule",
        ),
        pytest.param(
            _LONG_HELP.replace("Usage: app", "# sarj-noqa: SARJ317 -- This is help data, not a directive."),
            id="heredoc-marker-is-data",
        ),
        pytest.param("printf '%s' '# sarj-noqa: SARJ317 -- Quoted data.'\n" + _LONG_HELP, id="quoted-marker-is-data"),
        pytest.param(
            "# ! First explanation.\n# ! Second explanation.\n# ! Third explanation.\nrun\n", id="fake-shebangs"
        ),
        pytest.param(
            "# Inspect copyright metadata.\n# Keep another setting.\n# Read a third setting.\nrun\n",
            id="copyright-word-is-not-a-notice",
        ),
    ],
)
def test_data_and_fake_directives_do_not_authorize_long_prose(source: str, rule: ConciseShellProse) -> None:
    assert len(rule.check(Path("app.sh"), source)) == 1


def test_help_diagnostic_anchors_the_command_without_changing_help_output(rule: ConciseShellProse) -> None:
    [finding] = rule.check(Path("app.sh"), _LONG_HELP)
    assert finding.line == 2


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param({"Negated": "false"}, id="native-negation-is-boolean"),
        pytest.param(
            {
                "Cmd": {
                    "Type": "TestClause",
                    "X": {
                        "Type": "BinaryTest",
                        "Op": "==",
                        "X": {"Type": "Word", "Parts": [{"Type": "Lit", "Value": 938_271}]},
                        "Y": {},
                    },
                }
            },
            id="native-token-is-text",
        ),
    ],
)
def test_malformed_native_conditions_propagate_validation_without_payloads(
    invalid: dict[str, JsonValue], monkeypatch: pytest.MonkeyPatch, rule: ConciseShellProse
) -> None:
    condition: dict[str, JsonValue] = {
        "Cmd": {"Type": "TestClause", "X": {"Type": "BinaryTest", "Op": "==", "X": {}, "Y": {}}},
        **invalid,
    }
    payload: dict[str, JsonValue] = {"Type": "File", "Stmts": [{"Type": "IfClause", "Cond": [condition]}]}

    def parse(_source: str) -> dict[str, JsonValue]:
        return payload

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Inject malformed native output that real shfmt cannot produce.
        "sarj_standards.libs.linting.text_rules.concise_shell_prose.parse_shell", parse
    )
    with pytest.raises(ValidationError) as error:
        rule.check(Path("app.sh"), "if [[ $1 == --help ]]; then :; fi")
    assert "938271" not in str(error.value)


def test_malformed_native_help_positions_propagate_validation(
    monkeypatch: pytest.MonkeyPatch, rule: ConciseShellProse
) -> None:
    payload: dict[str, JsonValue] = {
        "Type": "File",
        "Stmts": [
            {
                "Type": "IfClause",
                "Cond": [
                    {
                        "Cmd": {
                            "Type": "TestClause",
                            "X": {
                                "Type": "BinaryTest",
                                "Op": "==",
                                "X": {"Type": "Word", "Parts": [{"Type": "Lit", "Value": "--help"}]},
                                "Y": {},
                            },
                        }
                    }
                ],
                "Then": [
                    {
                        "Pos": {"Line": 0, "Col": 1},
                        "Cmd": {"Type": "CallExpr", "Args": []},
                        "Redirs": [{"Op": "<<", "Hdoc": {}}],
                    }
                ],
            }
        ],
    }

    def parse(_source: str) -> dict[str, JsonValue]:
        return payload

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Inject malformed native output that real shfmt cannot produce.
        "sarj_standards.libs.linting.text_rules.concise_shell_prose.parse_shell", parse
    )
    with pytest.raises(ValidationError):
        rule.check(Path("app.sh"), _LONG_HELP)
