from pathlib import Path
import textwrap

from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._autofix import fix_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import PreferWalrusAwaitedNoneGuard
from sarj_python_lint.rules.prefer_walrus_none_guard import PreferWalrusNoneGuard


def _check(source: str):
    return PreferWalrusNoneGuard().check(Path("service.py"), textwrap.dedent(source))


def test_documented_examples() -> None:
    verify_native_rule(PreferWalrusNoneGuard, analyze)


def test_flags_sync_lookup_split_from_none_guard() -> None:
    diagnostics = _check(
        """
        def load(cache, key):
            entry = cache.get(key)
            if entry is None:
                return
            consume(entry)
        """
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ589"
    assert diagnostics[0].severity is Severity.WARNING
    assert diagnostics[0].line == 3
    assert "if (entry := cache.get(key)) is None:" in diagnostics[0].message


def test_flags_raising_guard_and_plain_function_call() -> None:
    diagnostics = _check(
        """
        def load(key):
            entry = find_entry(key)
            if entry is None:
                raise LookupError(key)
            return entry.value
        """
    )

    assert [diagnostic.line for diagnostic in diagnostics] == [3]


def test_flags_is_not_none_guard_that_consumes_binding() -> None:
    diagnostics = _check(
        """
        def load(cache, key):
            entry = cache.get(key)
            if entry is not None:
                return entry.value
            return fallback()
        """
    )

    assert len(diagnostics) == 1
    assert "is not None:" in diagnostics[0].message


def test_flags_guard_with_message_assignment_before_raise() -> None:
    diagnostics = _check(
        """
        def load(cache, key):
            entry = cache.get(key)
            if entry is None:
                message = f"missing {key}"
                raise LookupError(message)
            return entry
        """
    )

    assert len(diagnostics) == 1


def test_skips_awaited_lookup_owned_by_sarj432() -> None:
    source = """
    async def load(store, key):
        entry = await store.get(key)
        if entry is None:
            return
        consume(entry)
    """

    assert _check(source) == []
    assert len(PreferWalrusAwaitedNoneGuard().check(Path("service.py"), textwrap.dedent(source))) == 1


def test_skips_regex_lookup_owned_by_sarj081() -> None:
    assert (
        _check(
            """
            import re

            def parse(text):
                found = re.search("x", text)
                if found is None:
                    return None
                return found.group(0)
            """
        )
        == []
    )


def test_skips_non_call_values_and_truthiness_guards() -> None:
    assert (
        _check(
            """
            def load(cache, key):
                entry = cache[key]
                if entry is None:
                    return
                consume(entry)

            def other(cache, key):
                entry = cache.get(key)
                if not entry:
                    return
                consume(entry)
            """
        )
        == []
    )


def test_skips_is_none_guard_without_later_use() -> None:
    assert (
        _check(
            """
            def load(cache, key):
                entry = cache.get(key)
                if entry is None:
                    return
                consume(key)
            """
        )
        == []
    )


def test_skips_is_not_none_guard_with_later_use() -> None:
    assert (
        _check(
            """
            def load(cache, key):
                entry = cache.get(key)
                if entry is not None:
                    return entry.value
                record(entry)
            """
        )
        == []
    )


def test_skips_non_terminal_guards_else_and_comments() -> None:
    assert (
        _check(
            """
            def no_terminal(cache, key):
                entry = cache.get(key)
                if entry is None:
                    entry = default()
                consume(entry)

            def with_else(cache, key):
                entry = cache.get(key)
                if entry is None:
                    return
                else:
                    pass
                consume(entry)

            def with_comment(cache, key):
                entry = cache.get(key)
                # a deliberate tracing boundary
                if entry is None:
                    return
                consume(entry)
            """
        )
        == []
    )


def test_skips_multiline_lookup_and_overlong_condition() -> None:
    long_argument = "x" * 100
    assert (
        _check(
            f"""
            def multiline(cache, key):
                entry = cache.get(
                    key,
                )
                if entry is None:
                    return
                consume(entry)

            def overlong(cache):
                entry = cache.get("{long_argument}")
                if entry is None:
                    return
                consume(entry)
            """
        )
        == []
    )


def test_respects_suppression_and_stub_files() -> None:
    source = textwrap.dedent(
        """
        def load(cache, key):
            entry = cache.get(key)  # sarj-noqa: SARJ589 -- keep the tracing boundary
            if entry is None:
                return
            consume(entry)
        """
    )

    assert PreferWalrusNoneGuard().check(Path("service.py"), source) == []
    assert PreferWalrusNoneGuard().check(Path("service.pyi"), source.replace("  # sarj-noqa", "  # x")) == []


def test_safe_autofix_moves_lookup_into_guard() -> None:
    source = (
        "def load(cache, key):\n    entry = cache.get(key)\n    if entry is None:\n        return\n    consume(entry)\n"
    )

    assert fix_source(Path("app/service.py"), source, rule_ids=["prefer-walrus-none-guard"]) == (
        "def load(cache, key):\n    if (entry := cache.get(key)) is None:\n        return\n    consume(entry)\n"
    )
