from pathlib import Path
import textwrap

from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_next_over_search_loop import PreferNextOverSearchLoop


def _check(source: str):
    return PreferNextOverSearchLoop().check(Path("service.py"), textwrap.dedent(source))


def _suggestions(source: str) -> list[str]:
    return [diagnostic.message.split("`")[1] for diagnostic in _check(source)]


def test_documented_examples() -> None:
    verify_native_rule(PreferNextOverSearchLoop, analyze)


def test_flags_first_match_loop_with_none_fallback() -> None:
    diagnostics = _check(
        """
        def find(users, name):
            for user in users:
                if user.name == name:
                    return user
            return None
        """
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ590"
    assert diagnostics[0].severity is Severity.WARNING
    assert diagnostics[0].line == 3
    assert "return next((user for user in users if user.name == name), None)" in diagnostics[0].message


def test_flags_bare_return_projection_and_name_default() -> None:
    assert _suggestions(
        """
        def bare(users):
            for user in users:
                if user.active:
                    return user.id
            return

        def named(users, fallback):
            for user in users:
                if user.active:
                    return user.id
            return fallback
        """
    ) == [
        "return next((user.id for user in users if user.active), None)",
        "return next((user.id for user in users if user.active), fallback)",
    ]


def test_parenthesizes_tuple_target_tuple_result_and_conditional_iterable() -> None:
    assert _suggestions(
        """
        def pair(items, wanted):
            for key, value in items:
                if key == wanted:
                    return key, value
            return None

        def choose(primary, secondary, use_primary):
            for item in primary if use_primary else secondary:
                if item.ok:
                    return item
            return None
        """
    ) == [
        "return next(((key, value) for (key, value) in items if key == wanted), None)",
        "return next((item for item in (primary if use_primary else secondary) if item.ok), None)",
    ]


def test_allows_awaited_iterable_and_nested_tuple_targets() -> None:
    assert _suggestions(
        """
        async def account(client, name):
            for subscriber in await client.list():
                if subscriber.name == name:
                    return subscriber.account
            return None

        def secret_for(items, provider):
            for (stored, _), secret in items:
                if stored == provider:
                    return secret
            return None
        """
    ) == [
        "return next((subscriber.account for subscriber in await client.list() if subscriber.name == name), None)",
        "return next((secret for ((stored, _), secret) in items if stored == provider), None)",
    ]


def test_flags_loops_in_nested_blocks() -> None:
    assert (
        len(
            _check(
                """
                def find(groups, enabled):
                    if enabled:
                        for group in groups:
                            if group.default:
                                return group
                        return None
                    return None
                """
            )
        )
        == 1
    )


def test_skips_constant_match_results_that_are_membership_tests() -> None:
    assert (
        _check(
            """
            def has_admin(users):
                for user in users:
                    if user.is_admin:
                        return True
                return False

            def drop_noise(event, texts):
                for text in texts:
                    if "noise" in text:
                        return None
                return event
            """
        )
        == []
    )


def test_skips_default_bound_by_loop_target_and_computed_default() -> None:
    assert (
        _check(
            """
            def last(users):
                for user in users:
                    if user.active:
                        return user
                return user

            def computed(users):
                for user in users:
                    if user.active:
                        return user
                return build_default()
            """
        )
        == []
    )


def test_skips_loops_with_extra_statements_else_or_effects() -> None:
    assert (
        _check(
            """
            def logged(users):
                for user in users:
                    log(user)
                    if user.active:
                        return user
                return None

            def with_else(users):
                for user in users:
                    if user.active:
                        return user
                else:
                    pass
                return None

            def with_if_else(users):
                for user in users:
                    if user.active:
                        return user
                    else:
                        continue
                return None

            async def awaited(users):
                for user in users:
                    if await user.active():
                        return user
                return None

            def walrus(users):
                for user in users:
                    if (role := user.role) is not None:
                        return role
                return None

            def no_fallback(users):
                for user in users:
                    if user.active:
                        return user
                raise LookupError
            """
        )
        == []
    )


def test_skips_async_for_and_complex_targets() -> None:
    assert (
        _check(
            """
            async def first(stream):
                async for item in stream:
                    if item.ok:
                        return item
                return None

            def attr_target(holder, items):
                for holder.item in items:
                    if holder.item.ok:
                        return holder.item
                return None
            """
        )
        == []
    )


def test_skips_comments_multiline_pieces_and_overlong_suggestions() -> None:
    long_name = "x" * 90
    assert (
        _check(
            f"""
            def commented(users):
                for user in users:
                    # first active user wins
                    if user.active:
                        return user
                return None

            def multiline(users):
                for user in users:
                    if (
                        user.active
                    ):
                        return user
                return None

            def overlong(users):
                for user in users:
                    if user.{long_name}:
                        return user
                return None
            """
        )
        == []
    )


def test_respects_suppression_generated_and_stub_files() -> None:
    source = textwrap.dedent(
        """
        def find(users):
            for user in users:  # sarj-noqa: SARJ590 -- loop body will grow logging
                if user.active:
                    return user
            return None
        """
    )

    assert PreferNextOverSearchLoop().check(Path("service.py"), source) == []
    assert PreferNextOverSearchLoop().check(Path("service.pyi"), source.replace("  # sarj-noqa", "  # x")) == []
