from pathlib import Path
import textwrap

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint._autofix import fix_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_match_none_check import PreferMatchNoneCheck
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import PreferWalrusAwaitedNoneGuard


def _check(source: str):
    return PreferMatchNoneCheck().check(Path("service.py"), textwrap.dedent(source))


def _lines(source: str) -> list[int]:
    return [diagnostic.line for diagnostic in _check(source)]


def test_documented_examples() -> None:
    verify_native_rule(PreferMatchNoneCheck, analyze)


@pytest.mark.parametrize(
    "present",
    [
        "str()",
        "False",
        "0",
        "-2",
        "1+3j",
        "''",
        "[first, *rest]",
        "{'key': name}",
        "(str() | False) as result",
        "int() if allow()",
        "value if value is not None",
        "_ if value is not None",
        "First()",
        "Second(field=value)",
        "tree.Name(id=name)",
        "Node()",
        "Text()",
    ],
)
def test_rejects_absence_before_provably_disjoint_values(present: str) -> None:
    source = (
        "import ast as tree\nfrom ast import Constant as Node\nfrom builtins import str as Text\n"
        "class First: pass\nclass Second(First): pass\n"
        "def decide(value):\n    match value:\n"
        "        case None: return 'missing'\n"
        f"        case {present}: return 'present'\n"
        "        case _: return 'unknown'\n"
    )
    [finding] = _check(source)
    assert (finding.line, finding.code, finding.severity) == (8, "SARJ589", Severity.ERROR)
    assert "Keep their relative order" in finding.message
    assert fix_source(Path("app/service.py"), source, rule_ids=["prefer-match-none-check"]) == source


@pytest.mark.parametrize(
    ("fallback", "captured"), [("_", False), ("selected", True), ("selected if selected is not None", True)]
)
def test_binary_match_prefers_an_identity_check(fallback: str, captured: bool) -> None:
    source = (
        "def render():\n    match read_once():\n"
        "        case None: return 'missing'\n"
        f"        case {fallback}: return 'present'\n"
    )
    [finding] = _check(source)
    assert finding.severity is Severity.ERROR
    assert "if value is not None" in finding.message
    assert ("binding of `selected` on the present path" in finding.message) is captured
    assert fix_source(Path("app/service.py"), source, rule_ids=["prefer-match-none-check"]) == source


@pytest.mark.parametrize(
    "arms",
    [
        ["case str(): pass", "case None: pass", "case _: pass"],
        ["case str(): pass", "case None: pass", "case other: pass"],
        ["case None if enabled(): pass", "case str(): pass", "case _: pass"],
        ["case None as absent: pass", "case str(): pass"],
        ["case None: pass", "case str() | None: pass"],
        ["case None: pass", "case object(): pass", "case _: pass"],
        ["case None: pass", "case Foreign(): pass"],
        ["case None: pass", "case Markers.EMPTY: pass", "case str(): pass"],
        ["case None: pass", "case candidate if ready(candidate): pass", "case str(): pass"],
        ["case None: pass", "case candidate if unrelated is not None: pass"],
        ["case None: pass", "case _ if other is not None: pass"],
        ["case None: pass", "case _ if value.lookup is not None: pass"],
        ["case None: pass", "case candidate if ready() and candidate is not None: pass"],
        ["case None: pass"],
    ],
    ids=(
        "present-first",
        "final-capture",
        "guarded-absence",
        "bound-absence",
        "overlapping-alternative",
        "object-overlaps-none",
        "unresolved-class",
        "unresolved-value",
        "observable-capture-guard",
        "unrelated-capture-guard",
        "unrelated-wildcard-guard",
        "observed-attribute",
        "compound-guard",
        "absence-only",
    ),
)
def test_preserves_present_first_guards_and_uncertain_matches(arms: list[str]) -> None:
    assert _check("def decide(value):\n    match value:\n" + "".join(f"        {arm}\n" for arm in arms)) == []


def test_guarded_wildcard_can_check_the_existing_plain_subject() -> None:
    source = (
        "def decide(value):\n    match value:\n        case None: pass\n        case _ if value is not None: pass\n"
    )
    [finding] = _check(source)
    assert finding.severity is Severity.ERROR
    assert "if value is not None" in finding.message
    assert _check(source.replace("match value:", "match value.property:")) == []


def test_reordering_preserves_captures_and_prior_changes_to_the_matched_name() -> None:
    source = """
        def keep_existing(value):
            keep = 7
            match value:
                case None: return keep
                case str(): return 2
                case keep if keep is not None: return 3

        def subject_rebound(value):
            match value:
                case _ if (value := 1) == 2: return 0
                case None: return 7
                case _ if value is not None: return 3
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    ("declarations", "pattern"),
    [
        ("class Meta(type): pass\nclass Thing(metaclass=Meta): pass", "Thing()"),
        ("class Meta(type): pass\nclass Parent(metaclass=Meta): pass\nclass Child(Parent): pass", "Child()"),
        ("@decorate\nclass Thing: pass", "Thing()"),
        ("from typing import Protocol\nclass Reader(Protocol): pass", "Reader()"),
        ("class Thing: pass\nThing = factory()", "Thing()"),
        ("def other(int): pass", "int()"),
        ("import ast\nast.Name = factory()", "ast.Name()"),
        ("from external import *", "list()"),
        ("from external import Thing", "Thing()"),
    ],
)
def test_unresolved_and_observable_class_patterns_keep_their_order(declarations: str, pattern: str) -> None:
    source = (
        f"{declarations}\ndef decide(value):\n    match value:\n        case None: pass\n        case {pattern}: pass\n"
    )
    assert _check(source) == []


def test_match_does_not_assume_future_class_or_import_bindings() -> None:
    assert (
        _check(
            "match None:\n    case None: pass\n    case Later(): pass\nclass Later: pass\n"
            "match None:\n    case None: pass\n    case node.Name(): pass\nimport ast as node\n"
        )
        == []
    )


def test_keeps_explicit_none_checks_and_early_exits() -> None:
    source = """
        async def load(store, supplied):
            if supplied is None:
                return None
            if (value := await store.get()) is None:
                return None
            if isinstance(value, str) and (setting := supplied.optional) is not None:
                use(setting)
            return value.name if value is not None else supplied.name
    """
    assert _check(source) == []
    assert PreferWalrusAwaitedNoneGuard().check(Path("service.py"), textwrap.dedent(source)) == []


def test_awaited_split_guard_is_left_to_sarj432() -> None:
    source = """
        async def load(store, key):
            entry = await store.get(key)
            if entry is None:
                return
            consume(entry)
    """
    assert _check(source) == []
    [owned] = PreferWalrusAwaitedNoneGuard().check(Path("service.py"), textwrap.dedent(source))
    assert "`if (entry := await store.get(key)) is None:`" in owned.message


def test_flags_split_lookup_consumed_under_is_not_none() -> None:
    diagnostics = _check(
        """
        def load(cache, key):
            entry = cache.get(key)
            if entry is not None:
                return entry.value
            return fallback()
        """
    )

    assert [diagnostic.line for diagnostic in diagnostics] == [3]
    assert "if (entry := cache.get(key)) is not None:" in diagnostics[0].message


def test_skips_is_not_none_lookup_with_later_use_and_regex_lookups() -> None:
    assert (
        _lines(
            """
            import re

            def load(cache, key):
                entry = cache.get(key)
                if entry is not None:
                    return entry.value
                record(entry)

            def parse(text):
                found = re.search("x", text)
                if found is not None:
                    return found.group(0)
                return None
            """
        )
        == []
    )


def test_respects_suppression_legacy_targets_and_stub_files(tmp_path: Path) -> None:
    source = textwrap.dedent(
        """
        def load(value):
            match value:
                case None:  # sarj-noqa: SARJ589 -- preserve the audited branch ordering
                    return None
                case str():
                    return value
        """
    )
    unsuppressed = source.replace("  # sarj-noqa", "  # x")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'legacy'\nversion = '1.0.0'\nrequires-python = '>=3.9'\n"
    )

    assert check_source([PreferMatchNoneCheck()], Path("service.py"), source) == []
    assert PreferMatchNoneCheck().check(Path("service.pyi"), unsuppressed) == []
    assert PreferMatchNoneCheck().check(tmp_path / "service.py", unsuppressed) == []


def test_safe_autofix_binds_only_the_is_not_none_lookup() -> None:
    consumed = (
        "def load(cache, key):\n"
        "    entry = cache.get(key)\n"
        "    if entry is not None:\n"
        "        return entry.value\n"
        "    return None\n"
    )
    guarded = (
        "def load(cache, key):\n    entry = cache.get(key)\n    if entry is None:\n        return\n    consume(entry)\n"
    )

    assert fix_source(Path("app/service.py"), consumed, rule_ids=["prefer-match-none-check"]) == (
        "def load(cache, key):\n"
        "    if (entry := cache.get(key)) is not None:\n"
        "        return entry.value\n"
        "    return None\n"
    )
    assert fix_source(Path("app/service.py"), guarded, rule_ids=["prefer-match-none-check"]) == guarded
