from pathlib import Path
from textwrap import dedent

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_python_lint.rules.no_long_comment import NoLongComment
from sarj_python_lint.rules.no_restated_comment import NoRestatedComment
from sarj_python_lint.rules.prefer_self_documenting_constant import (
    PreferSelfDocumentingConstant,
)
from sarj_python_lint.rules.trailing_value_narration import TrailingValueNarration


def _check(source: str, path: str = "service.py"):
    return PreferSelfDocumentingConstant().check(Path(path), dedent(source))


@pytest.mark.parametrize(
    ("comment", "value", "unit"),
    [
        ("# Request deadline in seconds.", "10", "seconds"),
        ("# Pause 250ms between calls.", "250", "milliseconds"),
        ("# Keep the buffer below 8 MiB.", "8", "mebibytes"),
        ("# Reserve 25.0 percent of workers.", "25.0", "percent"),
        ("# 3 attempts are enough.", "3", "attempts"),
        ("# Fetch 100 rows at a time.", "100", "rows"),
        ("# Render at 640 pixels.", "640", "pixels"),
    ],
)
def test_warns_when_comment_is_the_only_source_of_a_scalar_unit(comment: str, value: str, unit: str) -> None:
    findings = _check(f"{comment}\nREQUEST_LIMIT = {value}\n")

    assert len(findings) == 1
    assert findings[0].code == "SARJ097"
    assert findings[0].severity is Severity.WARNING
    assert unit in findings[0].message
    assert "preserving non-obvious rationale" in findings[0].message


@pytest.mark.parametrize(
    ("comment_number", "value"),
    [("five", "5"), ("twenty-five", "25"), ("one hundred", "100"), ("1_000", "1000")],
)
def test_binds_digit_and_word_numbers_to_the_assigned_value(comment_number: str, value: str) -> None:
    findings = _check(f"# Wait {comment_number} seconds.\nTIMEOUT = {value}\n")

    assert len(findings) == 1
    assert "seconds" in findings[0].message


@pytest.mark.parametrize("comment_number", ["six", "twenty-six", "101", "1_001"])
def test_does_not_borrow_a_mismatched_digit_or_word_number(comment_number: str) -> None:
    assert _check(f"# Wait {comment_number} seconds.\nTIMEOUT = 5\n") == []


def test_warns_for_private_annotated_and_class_constants() -> None:
    findings = _check(
        """
        # Provider timeout in seconds.
        _PROVIDER_TIMEOUT: float = 5.0

        class Limits:
            # Maximum response size in bytes.
            RESPONSE_SIZE: int = 4096
        """
    )

    assert [finding.line for finding in findings] == [3, 7]
    assert "`_PROVIDER_TIMEOUT`" in findings[0].message
    assert "`RESPONSE_SIZE`" in findings[1].message


@pytest.mark.parametrize(
    "source",
    [
        "# Request deadline in seconds.\nREQUEST_DEADLINE_SECONDS = 10",
        "# Request deadline in seconds.\nREQUEST_DEADLINE: Seconds = 10",
        '# Request deadline in seconds.\nREQUEST_DEADLINE: Annotated[int, "seconds"] = 10',
        "# Retry attempts.\nMAX_RETRIES = 3",
        "# Page rows.\nMAX_RECORDS = 100",
        "# Request deadline.\nREQUEST_DEADLINE = 10",
        "# Require a second entry point.\nMIN_ENTRY_POINTS = 2",
        "# assertEqual(first, second) has two operands.\nEQUALITY_ARITY = 2",
        "# Request deadline in seconds.\nrequest_deadline = 10",
        "# Request deadline in seconds.\n__REQUEST_DEADLINE = 10",
        "# Request deadline in seconds.\nA = B = 10",
        "# Request deadline in seconds.\nobj.REQUEST_DEADLINE = 10",
        "# Request deadline in seconds.\nREQUEST_DEADLINE = True",
        "# Request deadline in seconds.\nREQUEST_DEADLINE = settings.timeout",
        "# Request deadline in seconds.\nREQUEST_DEADLINE = 5 * 60",
        "# Gemini requires at least ten seconds.\nREQUEST_DEADLINE = timedelta(seconds=10)",
        "# Gemini requires at least ten seconds.\nREQUEST_DEADLINE = datetime.timedelta(seconds=10)",
        "def configure():\n    # Request deadline in seconds.\n    REQUEST_DEADLINE = 10",
        "# Request deadline in seconds.\n\nREQUEST_DEADLINE = 10",
        "class Limits:\n        # Request deadline in seconds.\n    REQUEST_DEADLINE = 10",
        "REQUEST_DEADLINE = 10  # seconds",
    ],
)
def test_ignores_values_outside_the_proven_scalar_scope(source: str) -> None:
    assert _check(source) == []


def test_consecutive_same_indent_comments_form_one_attached_block() -> None:
    findings = _check(
        """
        # This stays aligned with the provider contract.
        # The value is measured in seconds.
        REQUEST_DEADLINE = 10
        """
    )

    assert len(findings) == 1
    assert "seconds" in findings[0].message


@pytest.mark.parametrize(
    "directive",
    [
        "noqa: E501",
        "sarj-noqa: SARJ097",
        "type: ignore[assignment]",
        "ruff: noqa",
        "fmt: off",
        "pragma: no cover",
        "nosec",
    ],
)
def test_directive_anywhere_in_the_attached_run_exempts_the_constant(directive: str) -> None:
    source = f"# Timeout in seconds.\n# {directive}\nTIMEOUT = 5\n"

    assert _check(source) == []


def test_does_not_guess_when_rationale_mentions_multiple_units() -> None:
    source = "# Three retry attempts keep the total below 15 seconds.\nMAX_RETRIES = 3\n"

    assert _check(source) == []


def test_does_not_borrow_a_different_number_or_ordinal_from_the_rationale() -> None:
    source = "# The second implementation takes 3-55 ms.\nMIN_ENTRY_POINTS = 2\n"

    assert _check(source) == []


def test_reports_module_and_class_constants_in_source_order() -> None:
    findings = _check(
        """
        class Limits:
            # Timeout in seconds.
            TIMEOUT = 5

        # Buffer size in bytes.
        BUFFER_SIZE = 1024
        """
    )

    assert [finding.line for finding in findings] == [4, 7]


def test_only_direct_module_and_direct_class_bodies_are_considered() -> None:
    source = """
    # Timeout in seconds.
    MODULE_TIMEOUT = 5

    class Outer:
        # Timeout in seconds.
        CLASS_TIMEOUT = 5

        class Nested:
            # Timeout in seconds.
            NESTED_CLASS_TIMEOUT = 5

        if enabled:
            # Timeout in seconds.
            CONDITIONAL_CLASS_TIMEOUT = 5

    if enabled:
        # Timeout in seconds.
        CONDITIONAL_MODULE_TIMEOUT = 5

    def configure():
        # Timeout in seconds.
        LOCAL_TIMEOUT = 5

        class LocalClass:
            # Timeout in seconds.
            LOCAL_CLASS_TIMEOUT = 5
    """

    assert [finding.line for finding in _check(source)] == [3, 7, 11]


@pytest.mark.parametrize(
    "base",
    ["Enum", "enum.IntEnum", "StrEnum", "Flag", "enum.IntFlag", "ProjectIntEnum", "FeatureFlag"],
)
def test_enum_members_are_not_constant_candidates(base: str) -> None:
    source = f"""
    class Status({base}):
        # Timeout in seconds.
        TIMEOUT = 5
    """

    assert _check(source) == []


@pytest.mark.parametrize("value", ["0", "-1"])
@pytest.mark.parametrize("policy", ["disabled", "unlimited", "unknown", "inherit", "unset", "sentinel"])
def test_policy_sentinels_are_not_misread_as_duration_values(value: str, policy: str) -> None:
    source = f"# Measured in seconds; {value} means {policy}.\nTIMEOUT = {value}\n"

    assert _check(source) == []


def test_a_conflicting_existing_unit_does_not_suggest_a_second_suffix() -> None:
    source = "# Fetch 100 rows.\nROW_LIMIT_SECONDS = 100\n"

    assert _check(source) == []


def test_public_constant_message_warns_about_compatibility() -> None:
    findings = _check("# Five seconds.\nTIMEOUT = 5\n")

    assert len(findings) == 1
    assert "preserving public compatibility" in findings[0].message


def test_private_constant_message_stays_direct() -> None:
    findings = _check("# Five seconds.\n_TIMEOUT = 5\n")

    assert len(findings) == 1
    assert "public compatibility" not in findings[0].message


@pytest.mark.parametrize(
    "value",
    [
        "{401, 402, 403, 408, 429}",
        "[401, 403]",
        "(401, 403)",
        "frozenset({401, 403})",
        "builtins.frozenset((401, 403))",
    ],
)
def test_warns_for_bare_integers_in_status_code_collections(value: str) -> None:
    findings = _check(f"# Provider-unavailable responses include 401 and 403.\n_UNAVAILABLE_STATUS_CODES = {value}\n")

    assert len(findings) == 1
    assert "http.HTTPStatus" in findings[0].message
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        "# Provider unavailable.\nSTATUS_CODES = {401}",
        "# Provider unavailable.\nSTATUS_CODES = {99, 600}",
        "# Provider unavailable.\nSTATUS_CODES = {True, False}",
        "# Provider unavailable.\nSTATUS_CODES = range(400, 500)",
        "# Provider unavailable.\nSTATUS_CODES = frozenset(values)",
        "# Provider unavailable.\nSTATUS_CODES = custom_set({401, 403})",
        "# Provider unavailable.\nSTATUS_CODES = {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}",
        "# Codes 401 and 429 are unavailable.\nSTATUS_CODES = {401, HTTPStatus.FORBIDDEN, 429}",
        "# Codes 401 and 403 are unavailable.\nSTATUS_CODES = {401, '403'}",
        "# Codes 401 and 403 are unavailable.\nSTATUS_CODES = {401, *extra, 403}",
        "# Code 401 is unavailable.\nSTATUS_CODES = {401, 403}",
        "# Codes 401 and 404 are unavailable.\nSTATUS_CODES = {401, 403}",
        "# Codes 401 and 403 are unavailable.\nSTATUS_CODES = [401, 401]",
        "# Codes 401 and 403 are unavailable.\nSTATUS_CODEC = {401, 403}",
        "# Provider unavailable.\nCLIENT_ERRORS = {401, 403}",
        "# Provider unavailable.\nstatus_codes = {401, 403}",
        "# Provider unavailable.\n\nSTATUS_CODES = {401, 403}",
        "def configure():\n    # Provider unavailable.\n    STATUS_CODES = {401, 403}",
    ],
)
def test_ignores_status_collections_outside_the_proven_scope(source: str) -> None:
    assert _check(source) == []


def test_reports_one_diagnostic_per_constant() -> None:
    findings = _check(
        """
        # Provider-unavailable codes include 401 and 403 responses.
        UNAVAILABLE_STATUS_CODES = {401, 403}
        """
    )

    assert len(findings) == 1


def test_status_name_may_carry_additional_tokens() -> None:
    findings = _check(
        "# Authentication failures 401 and 403 are unavailable.\nHTTP_STATUS_CODE_ALLOWLIST = [401, 403]\n"
    )

    assert len(findings) == 1


def test_ignores_generated_and_malformed_source() -> None:
    generated = "# Generated by schema compiler. Do not edit.\n# Timeout in seconds.\nTIMEOUT = 5\n"

    assert _check(generated, "generated.py") == []
    assert _check("# Timeout in seconds.\nTIMEOUT = (") == []


def test_applies_to_test_constants_because_the_signal_is_not_runtime_specific() -> None:
    findings = _check("# Retry after five seconds.\nRETRY_DELAY = 5\n", "tests/test_retry.py")

    assert len(findings) == 1


def test_adjacent_comment_rules_do_not_duplicate_the_leading_unit_finding() -> None:
    source = "# Timeout in seconds.\nTIMEOUT = 5\n"
    path = Path("service.py")
    rules = [
        PreferSelfDocumentingConstant(),
        NoCommentCruft(),
        NoRestatedComment(),
        TrailingValueNarration(),
        NoLongComment(),
    ]

    findings = [finding for rule in rules for finding in rule.check(path, source)]

    assert [finding.code for finding in findings] == ["SARJ097"]


def test_inline_unit_narration_remains_owned_by_sarj051() -> None:
    source = "TIMEOUT = 5  # 5 seconds\n"
    path = Path("service.py")

    findings = [
        finding
        for rule in (PreferSelfDocumentingConstant(), TrailingValueNarration())
        for finding in rule.check(path, source)
    ]

    assert [finding.code for finding in findings] == ["SARJ051"]


def test_cli_reports_the_new_rule_as_a_non_blocking_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "limits.py"
    target.write_text("# Timeout in seconds.\nTIMEOUT = 5\n", encoding="utf-8")

    assert main(["check", "--rule", "prefer-self-documenting-constant", str(target)]) == 0
    assert "SARJ097 warning:" in capsys.readouterr().out


def test_exact_code_suppression_is_honored_on_the_constant_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "limits.py"
    target.write_text(
        "# Timeout in seconds.\nTIMEOUT = 5  # sarj-noqa: SARJ097 — external contract\n",
        encoding="utf-8",
    )

    assert main(["check", "--rule", "prefer-self-documenting-constant", str(target)]) == 0
    assert not capsys.readouterr().out
