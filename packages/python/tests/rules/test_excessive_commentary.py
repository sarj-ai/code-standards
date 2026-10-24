from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.excessive_commentary import ExcessiveCommentary


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_PUBLIC_EXAMPLES = ExcessiveCommentary.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(ExcessiveCommentary().check(Path(focus.path), focus.source)) == example.expected_count


def test_cited_activation_comment_is_reported_once() -> None:
    source = """def reasons_not_to_activate():
    # Everything standing between this integration and being usable.
    # Returns all the reasons rather than the first failure.
    # Someone activating a half-built integration wants the complete list.
    # That avoids discovering one problem per round trip.
    reasons = []
    reasons.extend(integration_reasons())
    reasons.extend(endpoint_reasons())
    reasons.extend(action_reasons())
    return reasons
"""
    findings = ExcessiveCommentary().check(Path("activation.py"), source)
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("generated/client.py", "\n".join(f"# Narrative implementation sentence number {i}." for i in range(8))),
        ("app.py", "# noqa: explanation one two three four five six seven eight\nvalue = 1\n"),
        ("app.py", "# First constraint.\n# - one mode\n# - another mode\n# - fallback mode\nvalue = 1\n"),
    ],
)
def test_owned_exclusions_do_not_report(path: str, source: str) -> None:
    assert ExcessiveCommentary().check(Path(path), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            (
                "# Keep `traceparent` because RFC-812 requires propagation.\n"
                "# The timeout is 10 ms.\n"
                "# The client reads wire_value.\n"
                "# Remove this with API-901.\nvalue = 1\n"
            ),
            [],
        ),
        (
            (
                "# Keep this ordering because cleanup can outlive the command.\n"
                "# Otherwise a background task can retain the temporary directory.\n"
                "# The cleanup must never mask the command outcome.\n"
                "# This invariant also prevents a retry race.\nvalue = 1\n"
            ),
            [Severity.WARNING],
        ),
    ],
)
def test_constraints_and_references_obey_review_budget(source: str, expected: list[Severity]) -> None:
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("app.py"), source)] == expected


def test_three_extends_are_not_a_comment_or_comprehension_violation() -> None:
    source = """reasons = []
reasons.extend(integration_reasons())
reasons.extend(endpoint_reasons())
reasons.extend(action_reasons())
"""
    assert ExcessiveCommentary().check(Path("activation.py"), source) == []


def test_long_comment_without_manual_accumulation_receives_review_advisory() -> None:
    source = """def render_response():
    # This paragraph describes several nearby implementation choices in detail.
    # It has enough words and lines to exceed the general prose budget used here.
    # Mature projects sometimes retain such context while a subsystem is evolving.
    # A deterministic style rule must not classify every such paragraph as harmful.
    response = build_response()
    return response
"""
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("response.py"), source)] == [
        Severity.WARNING
    ]


def test_long_comment_before_unused_empty_collection_receives_review_advisory() -> None:
    source = """def collect_items():
    # This paragraph describes several nearby implementation choices in detail.
    # It has enough words and lines to exceed the general prose budget used here.
    # An empty collection alone does not prove that the prose narrates accumulation.
    # Require repeated adjacent mutation calls to keep the warning high confidence.
    items = []
    return load_items(items)
"""
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("items.py"), source)] == [Severity.WARNING]


def test_protocol_citation_does_not_exempt_shape_narration() -> None:
    source = """def authentication_methods(payload):
    # Inspect this field only when the selected identity provider uses it.
    # Its value contains the RFC 8176 method names as a list of strings.
    # Another shape indicates an invalid provider response and causes rejection.
    # The validator rejects malformed data instead of interpreting it as absent.
    methods = payload.get("methods")
    return methods
"""
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("app.py"), source)] == [Severity.WARNING]


def test_concise_protocol_constraint_remains_allowed() -> None:
    source = '# RFC 8176 defines these method identifiers.\n# Keep unknown identifiers opaque at this boundary.\nmethods = payload["methods"]\n'
    assert ExcessiveCommentary().check(Path("app.py"), source) == []


def test_constraint_before_accumulation_stays_warning_level() -> None:
    source = """def reasons():
    # Collect every failure because the caller presents the complete set.
    # Otherwise a retry reveals only the next missing prerequisite each time.
    # The operator needs every failed prerequisite from the same observed state.
    # Keep the returned order stable while the caller repairs those prerequisites.
    failures = []
    failures.extend(connection_failures())
    failures.extend(configuration_failures())
    return failures
"""
    assert [finding.severity for finding in ExcessiveCommentary().check(Path("app.py"), source)] == [Severity.WARNING]


_COMMENT_BLOCKS = (
    (
        "narration",
        "Build the complete response from the supplied input values.\nThen collect the selected fields and prepare the response values.\nFinally return the completed response to the original caller.",
        1,
    ),
    (
        "walkthrough",
        "Start by collecting the available values for this operation.\nNext convert the selected values into the expected response shape.\nThe following expression then returns those values to its caller.",
        1,
    ),
    (
        "reason",
        "Keep this copy because the downstream client retains its input.\nThe caller can modify its original values after this operation.\nA shared reference would then alter the pending response contents.",
        1,
    ),
    (
        "reference",
        "The upstream wire contract is defined by RFC-8176.\nThe registered vocabulary distinguishes a verified factor from a password.\nChanging this decision requires coordinating the issuer and its consumers.",
        1,
    ),
    (
        "directive",
        "pragma: no cover\nThis branch represents an integration failure during application startup.\nThe integration harness owns this externally triggered recovery path.",
        0,
    ),
)
_COMMENT_CONTEXTS = (
    ("module", "{block}value = build_response()\n", ""),
    ("function", "def render():\n{block}    value = build_response()\n", "    "),
    ("async", "async def render():\n{block}    value = build_response()\n", "    "),
    ("test", "def test_render():\n{block}    value = build_response()\n", "    "),
    ("method", "class Renderer:\n    def render(self):\n{block}        value = build_response()\n", "        "),
    ("loop", "for item in items:\n{block}    value = build_response()\n", "    "),
    ("branch", "if ready:\n{block}    value = build_response()\n", "    "),
    ("context", "with resource():\n{block}    value = build_response()\n", "    "),
    ("nested", "def outer():\n    def render():\n{block}        value = build_response()\n", "        "),
    ("generated", "# Generated by protoc. Do not edit.\n{block}value = build_response()\n", ""),
)


@pytest.fixture
def commentary_rule() -> ExcessiveCommentary:
    return ExcessiveCommentary()


@pytest.mark.parametrize(("kind", "text", "expected"), _COMMENT_BLOCKS, ids=[case[0] for case in _COMMENT_BLOCKS])
@pytest.mark.parametrize(
    ("context", "template", "indent"), _COMMENT_CONTEXTS, ids=[case[0] for case in _COMMENT_CONTEXTS]
)
def test_fifty_comment_contexts(
    *,
    commentary_rule: ExcessiveCommentary,
    kind: str,
    text: str,
    expected: int,
    context: str,
    template: str,
    indent: str,
) -> None:
    block = "".join(indent + "# " + line + "\n" for line in text.splitlines())
    findings = commentary_rule.check(Path("app/response.py"), template.format(block=block))
    assert len(findings) == (0 if context == "generated" else expected), kind
