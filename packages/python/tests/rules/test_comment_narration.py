import ast
from pathlib import Path

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.excessive_commentary import ExcessiveCommentary


_PATH = Path("app/service.py")
_COMMENTS = "# Load current account profile activation settings\n# Build current account profile activation response\n"
_CALLS = "load_current_account_profile_activation_settings()\nbuild_current_account_profile_activation_response()\n"
_FLAT = "def activate():\n" + "".join("    " + line for line in (_COMMENTS + _CALLS).splitlines(keepends=True))


@pytest.mark.parametrize(
    "source",
    [
        _COMMENTS + _CALLS,
        _FLAT,
        _FLAT.replace("def activate():", "async def activate():"),
        _FLAT.replace("def activate():", "def test_activate():"),
        _FLAT.replace("    load_current", "    settings = load_current").replace(
            "    build_current", "    return build_current"
        ),
        "class Service:\n" + "".join("    " + line for line in _FLAT.splitlines(keepends=True)),
        "def outer():\n" + "".join("    " + line for line in _FLAT.splitlines(keepends=True)),
    ],
    ids=("module", "function", "async", "test", "assignment-and-return", "method", "nested-function"),
)
def test_exact_ordered_action_names_are_errors_with_a_line_preserving_fix(source: str) -> None:
    findings = ExcessiveCommentary().check(_PATH, source)
    assert [finding.severity for finding in findings] == [Severity.ERROR]
    fixed = fix_source(_PATH, source, rule_ids=["excessive-commentary"])
    comment_rows = frozenset(_COMMENTS.splitlines())
    expected = "".join("\n" if line.strip() in comment_rows else line for line in source.splitlines(keepends=True))
    assert fixed == expected
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert compile(fixed, str(_PATH), "exec", dont_inherit=True) == compile(
        source, str(_PATH), "exec", dont_inherit=True
    )
    assert ExcessiveCommentary().check(_PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=["excessive-commentary"]) == fixed


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("# Load current", "# Read current"),
        ("# Load current", "# Load fresh current"),
        ("# Load current", "# Load `current`"),
        ("# Load current", "# Load current RFC 9110"),
        ("# Build current", "# Then build current"),
        ("# Build current", "# Build current after closing the stream"),
        (
            "load_current_account_profile_activation_settings()",
            "load_current_account_profile_activation_settings(token)",
        ),
        (
            "load_current_account_profile_activation_settings()",
            "client.load_current_account_profile_activation_settings()",
        ),
        (
            "load_current_account_profile_activation_settings()",
            "load_current_account_profile_activation_settings(factory())",
        ),
        ("    load_current", "    await load_current"),
        ("    load_current", "    return load_current"),
        ("    load_current", "    left = right = load_current"),
        ("    load_current", "    settings: factory() = load_current"),
        ("    load_current", "    if ready: load_current"),
        ("    load_current", "    for item in items: load_current"),
        ("    load_current", "    audit()\n    load_current"),
        ("    load_current", "    # Preserve an independent protocol fact.\n    load_current"),
        ("settings()\n", "settings()  # remote state is changed here\n"),
        ("def activate():\n", "def activate():\n    already_started = True\n"),
        ("def activate():\n", 'def activate():\n    """Published command documentation."""\n'),
        ("    # Build", "\n    # Build"),
    ],
    ids=(
        "different-action",
        "novel-word",
        "quote",
        "reference",
        "ordering-qualifier",
        "novel-order-fact",
        "argument",
        "qualified-call",
        "nested-side-effect",
        "await",
        "unreachable-action",
        "multiple-targets",
        "annotation-effect",
        "guard",
        "loop",
        "additional-action",
        "intervening-comment",
        "trailing-fact",
        "prior-statement",
        "prior-docstring",
        "separated-paragraph",
    ),
)
def test_exact_action_narration_abstains_on_meaning_or_unowned_behavior(old: str, new: str) -> None:
    source = _FLAT.replace(old, new)
    ast.parse(source)
    assert ExcessiveCommentary().check(_PATH, source) == []
    assert fix_source(_PATH, source, rule_ids=["excessive-commentary"]) == source


def test_reordered_actions_do_not_match_the_original_paragraph() -> None:
    source = _COMMENTS + "".join(reversed(_CALLS.splitlines(keepends=True)))
    assert ExcessiveCommentary().check(_PATH, source) == []


@pytest.mark.parametrize(
    "wrapper",
    ["if ready:\n", "for item in items:\n", "while ready:\n", "with resource():\n", "class Setup:\n"],
    ids=("guard", "loop", "while", "context-manager", "class-namespace"),
)
def test_structured_suite_owners_are_not_flat_action_owners(wrapper: str) -> None:
    source = wrapper + "".join("    " + line for line in (_COMMENTS + _CALLS).splitlines(keepends=True))
    assert ExcessiveCommentary().check(_PATH, source) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Must keep current account profile activation settings",
        "Load current account profile activation settings only",
        "Load current account profile activation settings without retries",
        "Then load current account profile activation settings",
        "Load every current account profile activation setting",
    ],
)
def test_existing_restatement_qualifiers_veto_even_exact_identifier_words(sentence: str) -> None:
    source = (
        f"# {sentence}\n# Build current account profile activation response\n"
        f"{'_'.join(sentence.casefold().split())}()\n"
        "build_current_account_profile_activation_response()\n"
    )
    assert ExcessiveCommentary().check(_PATH, source) == []


@pytest.mark.parametrize("count", [2, 3, 4])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_exact_accumulation_narration_has_a_line_preserving_fix(count: int, newline: str) -> None:
    subjects = ("account", "endpoint", "profile", "action")[:count]
    comments = "".join(f"    # Collect current {subject} profile activation reasons\n" for subject in subjects)
    calls = "".join(
        f"    values.extend(collect_current_{subject}_profile_activation_reasons())\n" for subject in subjects
    )
    source = f"def reasons():\n{comments}    values = []\n{calls}    return values\n".replace("\n", newline)
    findings = ExcessiveCommentary().check(_PATH, source)
    assert [finding.severity for finding in findings] == [Severity.ERROR]
    fixed = fix_source(_PATH, source, rule_ids=["excessive-commentary"])
    assert fixed == source.replace(comments.replace("\n", newline), newline * count)
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert compile(fixed, str(_PATH), "exec", dont_inherit=True) == compile(
        source, str(_PATH), "exec", dont_inherit=True
    )
    assert ExcessiveCommentary().check(_PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=["excessive-commentary"]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "# Load account settings\n# Build account response\nload_account_settings()\nbuild_account_response()\n",
        "# Load current account profile activation settings\nload_current_account_profile_activation_settings()\n",
        "# Generated by protoc. Do not edit.\n" + _COMMENTS + _CALLS,
        _FLAT.replace("# Load current", "# sarj-noqa: SARJ434 -- generated adapter narration; load current"),
        "def incomplete(:\n" + _COMMENTS,
    ],
    ids=("under-word-floor", "one-line", "generated", "directive", "malformed"),
)
def test_candidate_floor_and_owned_exclusions(source: str) -> None:
    assert ExcessiveCommentary().check(_PATH, source) == []
