from pathlib import Path
import textwrap

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


def test_flags_returned_and_assigned_none_conditional_expressions() -> None:
    diagnostics = _check(
        """
        def frames(self, key):
            pcm = self._pcm.get(key)
            return self._frames(pcm) if pcm is not None else None

        def label(user):
            name: str = "anonymous" if user.profile is None else user.profile.name
            return name

        def size(cache, key):
            total = 0 if (entry := cache.get(key)) is None else entry.size
            return total
        """
    )

    assert [(diagnostic.line, diagnostic.severity) for diagnostic in diagnostics] == [
        (4, Severity.WARNING),
        (7, Severity.WARNING),
        (11, Severity.WARNING),
    ]
    assert all(diagnostic.code == "SARJ589" for diagnostic in diagnostics)
    assert "`match pcm:`" in diagnostics[0].message
    assert "`match user.profile:`" in diagnostics[1].message
    assert "`match entry := cache.get(key):`" in diagnostics[2].message


def test_skips_default_value_idioms_and_inline_positions() -> None:
    assert (
        _lines(
            """
            def connect(timeout=None, retries=None, items=()):
                timeout = timeout if timeout is not None else 30
                fallback = 30 if retries is None else retries
                bound = entry if (entry := lookup()) is not None else default()
                client = open_client(retries=retries if retries is not None else 3)
                values = [item.value if item is not None else 0 for item in items]
                pick = lambda item: item.value if item is not None else 0
                pair = (timeout if timeout is None else 1, 2)
                text = f"{retries if retries is not None else 'none'}"
                both = timeout is None and retries is None
                return client, values, pick, pair, text, both, fallback, bound

            def defaults(value=None if FLAG is None else 1):
                yield value if value is not None else 0
            """
        )
        == []
    )


def test_skips_non_none_and_unsupported_conditional_subjects() -> None:
    assert (
        _lines(
            """
            def other(items, key, flag):
                first = items[0].name if items[0] is not None else None
                called = load().name if load() is not None else None
                equal = flag.name if flag == None else None
                truthy = flag.name if flag else None
                return first, called, equal, truthy
            """
        )
        == []
    )


def test_flags_walrus_split_and_plain_none_guards_followed_by_use() -> None:
    diagnostics = _check(
        """
        def walrus(cache, key):
            if (entry := cache.get(key)) is None:
                return None
            return entry.value

        def split(session):
            models = session.userdata.model_config
            if models is None:
                raise LookupError("models")
            return models.tts

        def parameter(index):
            if index is None:
                return None
            return index + 1

        def loop(items):
            for item in items:
                if (value := item.get()) is None:
                    continue
                consume(value)
        """
    )

    assert [diagnostic.line for diagnostic in diagnostics] == [3, 9, 14, 20]
    assert "`match entry := cache.get(key):`" in diagnostics[0].message
    assert "`match models := session.userdata.model_config:`" in diagnostics[1].message
    assert "`match index:`" in diagnostics[2].message
    assert "`match value := item.get():`" in diagnostics[3].message


def test_skips_guards_without_later_use_or_outside_the_guard_shape() -> None:
    assert (
        _lines(
            """
            def unused(cache, key):
                if (entry := cache.get(key)) is None:
                    return None
                return key

            def rebound(value):
                if value is None:
                    return None
                value = 3
                return value

            def non_terminal(value):
                if value is None:
                    value = default()
                return value

            def with_else(value):
                if value is None:
                    return None
                else:
                    log()
                return value

            def compound(value, other):
                if value is None or other is None:
                    return None
                if not value:
                    return None
                if value == None:
                    return None
                if value is not None:
                    return value
                return value

            def attribute(self):
                if self.value is None:
                    return None
                return self.value
            """
        )
        == []
    )


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
    assert "`match entry := await store.get(key):`" in owned.message


def test_flags_awaited_walrus_guard() -> None:
    assert _lines(
        """
            async def load(store, key):
                if (entry := await store.get(key)) is None:
                    return
                consume(entry)
            """
    ) == [3]


def test_isinstance_conditionals_are_left_to_sarj080() -> None:
    assert (
        _lines(
            """
            def settings(value):
                return value if isinstance(value, str) else None
            """
        )
        == []
    )


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
            if value is None:  # sarj-noqa: SARJ589 -- keep the guard before the expensive branch
                return None
            return value.name
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
