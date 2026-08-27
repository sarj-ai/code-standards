from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import RuleExample, Severity
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import PreferWalrusAwaitedNoneGuard


def _check(source: str):
    return PreferWalrusAwaitedNoneGuard().check(Path("service.py"), textwrap.dedent(source))


def _example_id(example: RuleExample) -> str:
    return example.example_id


@pytest.mark.parametrize(
    "example",
    PreferWalrusAwaitedNoneGuard.public_examples(),
    ids=_example_id,
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferWalrusAwaitedNoneGuard().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_compact_awaited_none_guard() -> None:
    diagnostics = _check(
        """
        async def load(store, call_id):
            call_detail = await store.get_detail(call_id)
            if call_detail is None:
                return
            consume(call_detail)
        """
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ432"
    assert diagnostics[0].severity is Severity.WARNING
    assert "if (call_detail := await store.get_detail(call_id)) is None:" in diagnostics[0].message


@pytest.mark.parametrize(
    "source",
    [
        "async def f(store):\n    value = await store.get()\n    if value is not None:\n        use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        raise LookupError\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        log()\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    else:\n        use(value)\n",
        "async def f(store):\n    value = await store.get()  # preserve lookup boundary\n    if value is None:\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    # absence is expected\n    if value is None:\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n\n    if value is None:\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:  # pragma: no cover\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    value = fallback\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n",
        "async def f(store):\n    value = await store.get(\n        'a very long value'\n    )\n    if value is None:\n        return\n    use(value)\n",
        "def f(store):\n    value = store.get()\n    if value is None:\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if (\n        value is None  # keep guard rationale\n    ):\n        return\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    def value(): ...\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    import module as value\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    from module import thing as value\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    class value: ...\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    async def value(): ...\n    use(value)\n",
        "async def f(store):\n    value = await store.get()\n    if value is None:\n        return\n    try:\n        run()\n    except Error as value:\n        use(value)\n",
        "async def f(store, item):\n    value = await store.get()\n    if value is None:\n        return\n    match item:\n        case {'value': value}:\n            use(value)\n",
    ],
)
def test_preserves_broader_or_comment_bearing_patterns(source: str) -> None:
    assert _check(source) == []


def test_skips_a_combined_condition_over_120_columns() -> None:
    assert (
        _check(
            """
            async def load(store):
                value = await store.get_detail_with_a_deliberately_long_method_name("a deliberately long identifier that pushes the condition over the policy limit")
                if value is None:
                    return
                consume(value)
            """
        )
        == []
    )


@pytest.mark.parametrize(("length", "expected"), [(120, 1), (121, 0)])
def test_applies_the_combined_line_limit_exactly(length: int, expected: int) -> None:
    prefix = '    if (value := await store.get("'
    suffix = '")) is None:'
    argument = "x" * (length - len(prefix) - len(suffix))
    source = (
        "async def load(store):\n"
        f'    value = await store.get("{argument}")\n'
        "    if value is None:\n"
        "        return\n"
        "    consume(value)\n"
    )

    assert len(_check(source)) == expected


def test_expands_tabs_when_applying_the_line_limit() -> None:
    prefix = '        if (value := await store.get("'
    suffix = '")) is None:'
    argument = "x" * (120 - len(prefix) - len(suffix))
    source = (
        "async def load(store):\n"
        f'\tvalue = await store.get("{argument}")\n'
        "\tif value is None:\n"
        "\t\treturn\n"
        "\tconsume(value)\n"
    )

    diagnostics = PreferWalrusAwaitedNoneGuard().check(Path("service.py"), source)
    assert len(diagnostics) == 1


def test_hash_inside_string_is_not_a_comment() -> None:
    assert (
        len(
            _check(
                """
            async def load(store):
                value = await store.get("#fragment")
                if value is None:
                    return
                consume(value)
            """
            )
        )
        == 1
    )


def test_honors_suppression_on_assignment() -> None:
    assert (
        _check(
            """
            async def load(store):
                value = await store.get()  # sarj-noqa: SARJ432 -- two-step trace boundary
                if value is None:
                    return
                consume(value)
            """
        )
        == []
    )
