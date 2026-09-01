from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("generated/client.py", "\n".join(f"# Narrative implementation sentence number {i}." for i in range(8))),
        ("app.py", "# noqa: explanation one two three four five six seven eight\nvalue = 1\n"),
        ("app.py", "# First constraint.\n# - one mode\n# - another mode\n# - fallback mode\nvalue = 1\n"),
        (
            "app.py",
            (
                "# Keep `traceparent` because RFC-812 requires propagation.\n"
                "# The timeout is 10 ms.\n"
                "# The client reads wire_value.\n"
                "# Remove this with API-901.\nvalue = 1\n"
            ),
        ),
        (
            "app.py",
            (
                "# Keep this ordering because cleanup can outlive the command.\n"
                "# Otherwise a background task can retain the temporary directory.\n"
                "# The cleanup must never mask the command outcome.\n"
                "# This invariant also prevents a retry race.\nvalue = 1\n"
            ),
        ),
    ],
)
def test_owned_exclusions_do_not_report(path: str, source: str) -> None:
    assert ExcessiveCommentary().check(Path(path), source) == []


def test_three_extends_are_not_a_comment_or_comprehension_violation() -> None:
    source = """reasons = []
reasons.extend(integration_reasons())
reasons.extend(endpoint_reasons())
reasons.extend(action_reasons())
"""
    assert ExcessiveCommentary().check(Path("activation.py"), source) == []
