from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_redundant_local_alias import NoRedundantLocalAlias


def test_documented_examples() -> None:
    verify_native_rule(NoRedundantLocalAlias, analyze)


@pytest.mark.parametrize(
    ("source", "expected", "fixes"),
    [
        pytest.param(
            'def render(item):\n    payload = item\n    return t"{dict(payload=payload)}"\n',
            0,
            0,
            id="template-expression-text",
        ),
        pytest.param(
            'async def render(item):\n    payload = item\n    return t"{dict(payload=payload)}"\n',
            0,
            0,
            id="async-template-expression-text",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    return f"{dict(payload=payload)}"\n',
            1,
            0,
            id="ordinary-formatted-value",
        ),
        pytest.param(
            'def render(item):\n    label = t"{dict(payload=item)}"\n    payload = item\n    return dict(payload=payload), label\n',
            1,
            0,
            id="unrelated-template-keyword",
        ),
        pytest.param(
            'def label(item):\n    return t"{dict(payload=item)}"\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n',
            1,
            1,
            id="sibling-safe-fix",
        ),
        pytest.param(
            'def render(item, other):\n    payload = item\n    return t"{other:{dict(payload=payload)}}"\n',
            0,
            0,
            id="conservative-template-format-spec",
        ),
    ],
)
def test_template_expression_boundaries(source: str, expected: int, fixes: int) -> None:
    diagnostics = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert len(diagnostics) == expected
    assert sum(len(diagnostic.fixes) for diagnostic in diagnostics) == fixes


@pytest.mark.parametrize(
    ("source", "expected", "filename"),
    [
        pytest.param(
            "def render():\n    item = make_item()\n    payload = item\n    consume(payload=payload)\n    retain(item)\n",
            1,
            "case.py",
            id="local-call",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=payload)\n", 1, "case.py", id="parameter"
        ),
        pytest.param(
            "class Renderer:\n    def render(self, item):\n        payload = item\n        consume(payload=payload)\n",
            1,
            "case.py",
            id="method",
        ),
        pytest.param(
            "from contextlib import asynccontextmanager\n\n@asynccontextmanager\nasync def resources():\n    item = make_item()\n    payload = item\n    manager: Manager = make_manager()\n    async with manager:\n        result = build(payload=payload, manager=manager)\n        yield (result, item)\n",
            1,
            "case.py",
            id="async-manager",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item.append(1)\n    consume(payload=payload)\n",
            1,
            "case.py",
            id="object-mutation",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item = replacement()\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="source-rebound",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    payload = replacement()\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="alias-rebound",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    del item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="source-deleted",
        ),
        pytest.param(
            "def render(item):\n    payload: Payload = item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="alias-typed",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    retain(payload)\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="alias-two-reads",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(data=payload)\n", 0, "case.py", id="keyword-mismatch"
        ),
        pytest.param("def render(item):\n    payload = item\n    consume(payload)\n", 0, "case.py", id="positional"),
        pytest.param("item = make_item()\npayload = item\nconsume(payload=payload)\n", 0, "case.py", id="module"),
        pytest.param(
            "class Renderer:\n    item = make_item()\n    payload = item\n    result = consume(payload=payload)\n",
            0,
            "case.py",
            id="class",
        ),
        pytest.param(
            "item = make_item()\ndef render():\n    payload = item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="global-source",
        ),
        pytest.param(
            "def render():\n    global item\n    payload = item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="global-declaration",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    def nested():\n        return payload\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="closure",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    def change():\n        nonlocal item\n        item = replacement()\n    change()\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="nested-source-write",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    callback = lambda: payload\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="lambda-capture",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=[payload for _ in range(2)])\n",
            0,
            "case.py",
            id="comprehension",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume((item := replacement()), payload=payload)\n",
            0,
            "case.py",
            id="walrus-earlier-argument",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    for item in items:\n        consume(payload=payload)\n",
            0,
            "case.py",
            id="loop-target",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        item = make_item()\n    payload = item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="branch-binding",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    inspect(locals())\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="reflection",
        ),
        pytest.param(
            "def render(item):\n    payload = cast(Payload, item)\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="cast",
        ),
        pytest.param(
            "def render(item):\n    payload = item.value\n    consume(payload=payload)\n", 0, "case.py", id="attribute"
        ),
        pytest.param(
            "def render(item):\n    payload, = item\n    consume(payload=payload)\n", 0, "case.py", id="destructure"
        ),
        pytest.param(
            "def render(item):\n    payload = other = item\n    consume(payload=payload)\n", 0, "case.py", id="chained"
        ),
        pytest.param(
            "# @generated\ndef render(item):\n    payload = item\n    consume(payload=payload)\n",
            0,
            "case.py",
            id="generated",
        ),
        pytest.param("def render(item):\n    payload = item\n    consume(payload=payload)\n", 0, "case.pyi", id="stub"),
        pytest.param("def render(:\n    payload = item\n", 0, "case.py", id="malformed"),
    ],
)
def test_contract(source: str, expected: int, filename: str) -> None:
    diagnostics = NoRedundantLocalAlias().check(Path(filename), source)
    assert len(diagnostics) == expected
    assert all(diagnostic.code == "SARJ531" and diagnostic.severity is Severity.WARNING for diagnostic in diagnostics)


def test_exact_suppression() -> None:
    source = "def render(item):\n    payload = item  # sarj-noqa: SARJ531 -- Keep the reviewed local contract.\n    consume(payload=payload)\n"
    assert check_source([NoRedundantLocalAlias()], Path("case.py"), source) == []
    wrong_code = source.replace("SARJ531", "SARJ440")
    assert len(check_source([NoRedundantLocalAlias()], Path("case.py"), wrong_code)) == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "def render(item):\n    payload = item\n    with manager:\n        consume(payload=payload)\n",
            1,
            id="outer-to-inner",
        ),
        pytest.param(
            "def render(item):\n    with manager:\n        payload = item\n        consume(payload=payload)\n",
            1,
            id="same-inner-suite",
        ),
        pytest.param(
            "def render(item):\n    with manager:\n        fail()\n        payload = item\n    consume(payload=payload)\n",
            0,
            id="exit-skips-alias",
        ),
        pytest.param(
            "def render():\n    with manager:\n        fail()\n        item = make_item()\n    payload = item\n    consume(effect(), payload=payload)\n",
            0,
            id="exit-skips-source",
        ),
        pytest.param(
            "def render(item):\n    with first:\n        payload = item\n    with second:\n        consume(payload=payload)\n",
            0,
            id="sibling-with",
        ),
        pytest.param(
            "def render(item):\n    with first:\n        with second:\n            payload = item\n        consume(payload=payload)\n",
            0,
            id="nested-exit",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=payload)\n    del payload\n",
            0,
            id="alias-deleted",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item += other\n    consume(payload=payload)\n",
            0,
            id="source-augassign",
        ),
        pytest.param(
            "def render(item, payload):\n    payload = item\n    consume(payload=payload)\n", 0, id="alias-parameter"
        ),
        pytest.param(
            "def render():\n    import module as item\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="source-import",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    import module as payload\n    consume(payload=payload)\n",
            0,
            id="alias-import",
        ),
        pytest.param(
            "def render():\n    with factory() as item:\n        payload = item\n        consume(payload=payload)\n",
            0,
            id="source-with-target",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    with factory() as payload:\n        consume(payload=payload)\n",
            0,
            id="alias-with-target",
        ),
        pytest.param(
            "def render():\n    def item():\n        pass\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="source-function-target",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    try:\n        fail()\n    except Error as item:\n        consume(payload=payload)\n",
            0,
            id="except-target",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    match value:\n        case {"item": item}:\n            consume(payload=payload)\n',
            0,
            id="pattern-target",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    callback = lambda value=payload: value\n    consume(payload=payload)\n",
            0,
            id="lambda-default-capture",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    callback = lambda value: value\n    consume(payload=payload)\n",
            0,
            id="unrelated-lambda",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    values = [payload for payload in other]\n    consume(payload=payload)\n",
            0,
            id="shadowed-comprehension",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    values = (payload for _ in other)\n    consume(payload=payload)\n",
            0,
            id="generator-capture",
        ),
        pytest.param(
            "def outer():\n    def inner(item):\n        payload = item\n        consume(payload=payload)\n    return inner\n",
            1,
            id="inner-independent-local",
        ),
        pytest.param(
            "def outer(item):\n    def inner():\n        payload = item\n        consume(payload=payload)\n    return inner\n",
            0,
            id="free-source",
        ),
        pytest.param(
            "def first(item):\n    payload = item\n    consume(payload=payload)\ndef second(payload):\n    return payload\n",
            1,
            id="separate-shadowed-functions",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(other=(item := replacement()), payload=payload)\n",
            0,
            id="earlier-keyword-walrus",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=payload, *((item := replacement()),))\n",
            0,
            id="later-positional-walrus",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    (item := make_callable())(payload=payload)\n",
            0,
            id="callee-walrus",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=payload, other=(item := replacement()))\n",
            0,
            id="later-keyword-rebind",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(*item, payload=payload)\n", 1, id="star-mutation"
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(item.value, payload=payload)\n",
            1,
            id="attribute-before-keyword",
        ),
        pytest.param(
            "def render(item):\n    consume(payload=payload)\n    payload = item\n",
            0,
            id="alias-read-before-assignment",
        ),
        pytest.param(
            "def render(item):\n    payload = item  # type: Payload\n    consume(payload=payload)\n",
            0,
            id="assignment-type-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = (\n        item\n    )  # type: Payload\n    consume(payload=payload)\n",
            0,
            id="multiline-type-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    payload: Payload\n    consume(payload=payload)\n",
            0,
            id="standalone-annotation",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    other: "payload"\n    consume(payload=payload)\n',
            0,
            id="quoted-annotation",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    other = cast("payload", value)\n    consume(payload=payload)\n',
            0,
            id="quoted-cast",
        ),
        pytest.param(
            "def render():\n    item = list[int]\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="implicit-type-alias",
        ),
        pytest.param(
            "def render():\n    type item = list[int]\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="pep695-type-alias",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=payload) if isinstance(item, str) else None\n",
            0,
            id="conditional-narrowing",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    is_text(item) and consume(payload=payload)\n",
            0,
            id="boolean-narrowing",
        ),
        pytest.param(
            "def render():\n    item: Item = make_item()\n    payload = item\n    consume(payload=payload)\n",
            1,
            id="typed-source",
        ),
        pytest.param(
            "def outer(item):\n    def inner():\n        nonlocal item\n        payload = item\n        consume(payload=payload)\n    return inner\n",
            0,
            id="nonlocal-source",
        ),
        pytest.param(
            "def render(item):\n    global payload\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="global-alias",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    inspect(vars())\n    consume(payload=payload)\n",
            0,
            id="vars-observer",
        ),
        pytest.param(
            "from builtins import locals as inspect_scope\ndef render(item):\n    payload = item\n    inspect_scope()\n    consume(payload=payload)\n",
            0,
            id="aliased-locals",
        ),
        pytest.param(
            "import inspect\ndef render(item):\n    payload = item\n    inspect.currentframe()\n    consume(payload=payload)\n",
            0,
            id="frame-observer",
        ),
        pytest.param(
            "import sys\ndef render(item):\n    payload = item\n    count = sys.getrefcount(item)\n    consume(payload=payload)\n    return count\n",
            0,
            id="refcount-observer",
        ),
        pytest.param(
            "from sys import getrefcount as count_refs\ndef render(item):\n    payload = item\n    count_refs(item)\n    consume(payload=payload)\n",
            0,
            id="aliased-refcount",
        ),
        pytest.param(
            "import gc\ndef render(item):\n    payload = item\n    gc.get_referrers(item)\n    consume(payload=payload)\n",
            0,
            id="referrers-observer",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    if flag:\n        consume(payload=payload)\n",
            0,
            id="conditional-use",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    while ready:\n        consume(payload=payload)\n",
            0,
            id="while-use",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    try:\n        consume(payload=payload)\n    finally:\n        close()\n",
            0,
            id="try-finally",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    try:\n        fail()\n    except Error:\n        consume(payload=payload)\n",
            0,
            id="try-handler",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    assert isinstance(item, str)\n    consume(payload=payload)\n",
            0,
            id="assert-narrowing",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return consume(payload=payload)\n", 1, id="return-use"
        ),
        pytest.param("def render(item):\n    payload = item\n    raise Error(payload=payload)\n", 1, id="raise-use"),
        pytest.param(
            "async def render(item):\n    payload = item\n    await pause()\n    await consume(payload=payload)\n",
            1,
            id="await-between",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    yield item\n    consume(payload=payload)\n",
            1,
            id="yield-between",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    yield item\n    item = replacement()\n    consume(payload=payload)\n",
            0,
            id="source-after-yield",
        ),
        pytest.param(
            "class Renderer:\n    async def render(self, item):\n        payload = item\n        async with manager:\n            await consume(payload=payload)\n",
            1,
            id="async-method",
        ),
        pytest.param(
            "async def render(item):\n    payload = item\n    async with manager(payload=payload):\n        await finish(item)\n",
            1,
            id="async-context-expression",
        ),
        pytest.param(
            "async def render():\n    item = await make_item()\n    payload = item\n    await consume(payload=payload)\n",
            1,
            id="awaited-source",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item.value = replacement()\n    consume(payload=payload)\n",
            1,
            id="attribute-mutation",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item[0] = replacement()\n    consume(payload=payload)\n",
            1,
            id="subscript-mutation",
        ),
        pytest.param(
            "def render(item):\n    payload = item[0]\n    consume(payload=payload)\n", 0, id="subscript-read"
        ),
        pytest.param(
            "def render(item):\n    self.payload = item\n    consume(payload=self.payload)\n", 0, id="attribute-target"
        ),
        pytest.param(
            "def render():\n    item, other = make_pair()\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="source-destructure",
        ),
        pytest.param(
            "def render():\n    item = other = make_item()\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="source-chain",
        ),
        pytest.param(
            "def render():\n    item = make_item()\n    intermediate = item\n    payload = intermediate\n    consume(payload=payload)\n",
            0,
            id="alias-chain",
        ),
        pytest.param("def render(item):\n    payload = item\n    consume(**payload)\n", 0, id="keyword-unpack"),
        pytest.param(
            "def render(item):\n    payload = item  # Explain the caller contract.\n    consume(payload=payload)\n",
            1,
            id="normal-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    # retain(payload)\n    consume(payload=payload)\n",
            1,
            id="comment-only-read",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    text = "# type: Value"\n    consume(payload=payload)\n',
            1,
            id="comment-string",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    record = item\n    consume(payload=payload, record=record)\n",
            2,
            id="two-aliases",
        ),
        pytest.param(
            "def render(item):\n    payload_context = item\n    consume(payload=payload_context)\n",
            0,
            id="nonmatching-suffix",
        ),
        pytest.param("def render(item):\n    q = item\n    consume(q=q)\n", 1, id="arbitrary-matching-name"),
    ],
)
def test_adversarial_bindings(source: str, expected: int) -> None:
    diagnostics = NoRedundantLocalAlias().check(Path("case.py"), source)
    assert len(diagnostics) == expected
    assert len({(diagnostic.line, diagnostic.col) for diagnostic in diagnostics}) == len(diagnostics)


@pytest.mark.parametrize(
    "reader",
    [
        pytest.param('getattr(frame, "f_locals")', id="dynamic-frame-member"),
        pytest.param('operator.attrgetter("f_locals")(frame)', id="attribute-getter"),
    ],
)
def test_reflective_getter(reader: str) -> None:
    source = (
        "import operator\n"
        "def render(item, frame):\n"
        "    payload = item\n"
        f"    namespace = {reader}\n"
        "    consume(payload=payload)\n"
        "    return namespace\n"
    )
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def render(item):\n    payload = (item)\n    consume(payload=(((payload))))\n", id="parenthesized"
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload=(  # Keep the call comment.\n        payload\n    ))\n",
            id="commented-keyword",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    consume(payload \\\n        = \\\n        payload)\n",
            id="line-continuations",
        ),
        pytest.param("def render(item):\n    donnée = item\n    consume(donnée=donnée)\n", id="unicode-identifier"),
        pytest.param("def render(item):\n    a̶ = item\n    consume(a̶=a̶)\n", id="combining-identifier"),
        pytest.param(
            "def render(item):\n    𝚙𝚊𝚢𝚕𝚘𝚊𝚍 = item\n    consume(payload=𝚙𝚊𝚢𝚕𝚘𝚊𝚍)\n", id="normalized-identifier"
        ),
    ],
)
def test_keyword_syntax(source: str) -> None:
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == 1


def test_unrelated_quoted_name_does_not_capture_local() -> None:
    source = (
        "async def metadata():\n"
        '    return {"payload": None}\n'
        "async def resources():\n"
        "    item = make_item()\n"
        "    payload = item\n"
        "    manager: Manager = make_manager()\n"
        "    async with manager:\n"
        "        result = build(payload=payload, manager=manager)\n"
        "        yield (result, item)\n"
    )
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == 1


@pytest.mark.parametrize(
    ("alias", "quoted"),
    [
        pytest.param("a̶", "a̶", id="combining-quoted-type"),
        pytest.param("é", "é", id="normalize-whole-quoted-type"),
        pytest.param("a‿", "a‿", id="connector-quoted-type"),
        pytest.param("l·l", "l·l", id="middle-dot-quoted-type"),
    ],
)
def test_unicode_quoted_type(alias: str, quoted: str) -> None:
    source = (
        "from typing import NewType\n"
        "from pydantic import TypeAdapter\n"
        "def render():\n"
        '    Item = NewType("Item", int)\n'
        f"    {alias} = Item\n"
        f'    adapter = TypeAdapter("{quoted}")\n'
        f"    consume({alias}={alias})\n"
        '    return adapter.validate_python("1")\n'
    )
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'def render(item):\n    a̶ = item\n    metadata = "a"\n    consume(a̶=a̶)\n',
            id="unicode-quoted-distinct-name",
        ),
        pytest.param(
            'def metadata():\n    return "a̶"\ndef render(item):\n    a̶ = item\n    consume(a̶=a̶)\n',
            id="unicode-quoted-distinct-scope",
        ),
    ],
)
def test_unicode_quote_near_miss(source: str) -> None:
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == 1


def test_comment_before_keyword_equals() -> None:
    source = (
        "def render(item):\n"
        "    payload = item\n"
        "    consume(\n"
        "        payload  # Keep the role comment.\n"
        "        = payload,\n"
        "    )\n"
    )
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def render(item):\n    payload = item\n    consume(marker=isinstance(item, int) or fail(), payload=payload)\n",
            id="earlier-argument-type-guard",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    marker = isinstance(item, int) or fail()\n    consume(marker=marker, payload=payload)\n",
            id="separate-boolean-type-guard",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    marker = True if isinstance(item, int) else fail()\n    consume(marker=marker, payload=payload)\n",
            id="separate-conditional-type-guard",
        ),
    ],
)
def test_conditional_source_type(source: str) -> None:
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def render(item):\n    payload = item\n    is_integer = isinstance(item, int)\n    consume(marker=is_integer or fail(), payload=payload)\n",
            id="indirect-boolean-type-guard",
        ),
        pytest.param(
            "def render(item, enabled):\n    payload = item\n    enabled = isinstance(item, int)\n    marker = True if enabled else fail()\n    consume(marker=marker, payload=payload)\n",
            id="rebound-parameter-type-guard",
        ),
    ],
)
def test_indirect_conditional_type(source: str) -> None:
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


def test_unrelated_parameter_choice() -> None:
    source = (
        "def render(item, enabled):\n"
        "    payload = item\n"
        '    options = {"enabled": True} if enabled else None\n'
        "    consume(options=options, payload=payload)\n"
    )
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == 1


@pytest.mark.parametrize(
    ("imports", "factory", "expression"),
    [
        pytest.param("from pydantic import TypeAdapter\n", "TypeAdapter", '"pay" + "load"', id="computed-type-name"),
        pytest.param(
            "from pydantic import TypeAdapter as Adapter\n", "Adapter", '"pay" + "load"', id="aliased-type-adapter"
        ),
        pytest.param("import pydantic\n", "pydantic.TypeAdapter", 'f"{prefix}load"', id="formatted-type-name"),
    ],
)
def test_computed_type_namespace(imports: str, factory: str, expression: str) -> None:
    source = (
        "from typing import NewType\n"
        f"{imports}"
        "def render():\n"
        '    Item = NewType("Item", int)\n'
        "    payload = Item\n"
        '    prefix = "pay"\n'
        f"    adapter = {factory}({expression})\n"
        "    consume(payload=payload)\n"
        '    return adapter.validate_python("1")\n'
    )
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


@pytest.mark.parametrize(
    ("alias", "quoted"),
    [
        pytest.param("a̶", "a̶", id="combining-annotation"),
        pytest.param("é", "é", id="normalized-annotation"),
        pytest.param("a‿", "a‿", id="connector-annotation"),
        pytest.param("l·l", "l·l", id="middle-dot-annotation"),
    ],
)
def test_unicode_quoted_annotation(alias: str, quoted: str) -> None:
    source = f'def render(item):\n    {alias} = item\n    reference: "list[{quoted}]"\n    consume({alias}={alias})\n'
    assert NoRedundantLocalAlias().check(Path("case.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from pydantic import BaseModel\nclass Model(BaseModel):\n    value: 'payload'\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    Model.model_rebuild()\n    consume(payload=payload)\n    return Model(value='1').value\nresult = render(int)\n",
            0,
            id="namespace-model-rebuild",
        ),
        pytest.param(
            "from pydantic import BaseModel\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    model = type('Model', (BaseModel,), {'__module__': __name__, '__annotations__': {'value': 'pay' + 'load'}})\n    consume(payload=payload)\n    return model(value='1').value\nresult = render(int)\n",
            0,
            id="namespace-dynamic-model-type",
        ),
        pytest.param(
            "from pydantic import validate_call\ndef consume(*, payload):\n    return None\ndef echo(value: 'payload'):\n    return value\ndef render(item):\n    payload = item\n    checked = validate_call(echo)\n    consume(payload=payload)\n    return checked('1')\nresult = render(int)\n",
            0,
            id="namespace-validate-call",
        ),
        pytest.param(
            "from pydantic import create_model\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    model = create_model('Model', value=('pay' + 'load', ...))\n    consume(payload=payload)\n    return model(value='1').value\nresult = render(int)\n",
            0,
            id="namespace-create-model-candidate",
        ),
        pytest.param(
            "from pydantic import create_model as build_model\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    model = build_model('Model', value=('pay' + 'load', ...))\n    consume(payload=payload)\n    return model(value='1').value\nresult = render(int)\n",
            0,
            id="namespace-import-alias",
        ),
        pytest.param(
            "import pydantic as models\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    model = models.create_model('Model', value=('pay' + 'load', ...))\n    consume(payload=payload)\n    return model(value='1').value\nresult = render(int)\n",
            0,
            id="namespace-qualified-module",
        ),
        pytest.param(
            "def consume(*, payload):\n    return None\ndef render(item, model_base):\n    payload = item\n    model = type('Model', (model_base,), {'__module__': __name__, '__annotations__': {'value': 'pay' + 'load'}})\n    consume(payload=payload)\n    return model(value='1').value\nresult = render(int, framework_base)\n",
            0,
            id="namespace-dynamic-parameter-base",
        ),
        pytest.param(
            'from typing import NewType, TypeVar, TypeAliasType\ndef consume(*, payload: object) -> None:\n    pass\ndef render() -> None:\n    Item = NewType("Item", int)\n    payload = Item\n    values = []  # type: list[payload]\n    consume(payload=payload)\n',
            0,
            id="separate-newtype-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    count = 1  # type: int\n    consume(payload=payload, count=count)\n",
            0,
            id="unrelated-type-comment",
        ),
        pytest.param(
            "def other():\n    count = 1  # type: int\n    return count\ndef render(item):\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="other-scope-type-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    kind = type(item)\n    consume(payload=payload, kind=kind)\n",
            1,
            id="unary-type-query",
        ),
        pytest.param(
            "from dataclasses import dataclass\n@dataclass\nclass Record:\n    value: int\ndef render(item):\n    payload = item\n    consume(payload=payload)\n",
            1,
            id="stdlib-dataclass",
        ),
        pytest.param(
            'def render(item):\n    note = "#"; payload = item; consume(payload=payload, note=note)\n',
            1,
            id="hash-string-inline",
        ),
        pytest.param(
            "# x\n" * 500 + "def render(item):\n    payload = item\n    consume(payload=payload)\n",
            1,
            id="comment-prefix-positive",
        ),
        pytest.param("# x\n" * 500, 0, id="comment-only-input"),
        pytest.param(
            "def consume(*, payload):\n    return None\ndef render(item, type):\n    payload = item\n    adapter = type('pay' + 'load')\n    consume(payload=payload)\n    return adapter.validate_python('1')\nresult = render(int, framework_adapter)\n",
            0,
            id="shadowed-type-namespace-reader",
        ),
    ],
)
def test_independent_review_regressions(source: str, expected: int) -> None:
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from adapter_exports import *\ndef consume(*, payload):\n    return None\ndef render(item):\n    payload = item\n    adapter = type('pay' + 'load')\n    consume(payload=payload)\n    return adapter.validate_python('1')\nresult = render(int)\n",
            0,
            id="wildcard-shadows-type",
        ),
        pytest.param(
            "from math import *\ndef render(item):\n    payload = item\n    consume(payload=payload)\n",
            0,
            id="wildcard-benign-local",
        ),
        pytest.param(
            "from math import sqrt\ndef render(item):\n    payload = item\n    consume(payload=payload)\n",
            1,
            id="explicit-benign-import",
        ),
    ],
)
def test_wildcard_namespace(source: str, expected: int) -> None:
    assert len(NoRedundantLocalAlias().check(Path("case.py"), source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="guard-before-fresh-call",
        ),
        pytest.param(
            "def render(left, right):\n    if left and right:\n        return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="bool-test-in-prefix",
        ),
        pytest.param(
            "def render(left, right):\n    if left:\n        if right:\n            return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="nested-prefix-guards",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        marker = 1\n    else:\n        marker = 2\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="prefix-else",
        ),
        pytest.param(
            "def render(left, right):\n    if left:\n        return None\n    if right:\n        return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="multiple-prefix-guards",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item: object = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="typed-fresh-source",
        ),
        pytest.param(
            "class Renderer:\n    def render(self, flag):\n        if flag:\n            return None\n        item = object()\n        payload = item\n        return dict(payload=payload)\n",
            1,
            id="method-prefix",
        ),
        pytest.param(
            "from contextlib import asynccontextmanager\n@asynccontextmanager\nasync def resources(flag):\n    if flag:\n        return\n    item = make_item()\n    payload = item\n    async with manager():\n        result = build(payload=payload)\n        yield (result, item)\n",
            1,
            id="async-prefix-manager",
        ),
        pytest.param(
            "def resources(flag):\n    if flag:\n        return\n    item = make_item()\n    payload = item\n    with manager():\n        yield from build(payload=payload)\n    retain(item)\n",
            1,
            id="prefix-yield-from-with",
        ),
        pytest.param(
            "def render(item):\n    if not isinstance(item, str):\n        return None\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="parameter-after-narrowing",
        ),
        pytest.param(
            "def render(flag):\n    item = object()\n    if flag:\n        return None\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="fresh-before-prefix",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload = item\n    item = object()\n    return dict(payload=payload)\n",
            0,
            id="later-source-rebinding",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    index = 0\n    start = index\n    while index < 3:\n        index += 1\n    return dict(start=start, end=index)\n",
            0,
            id="cursor-snapshot",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        item = object()\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-source-binding",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        payload = object()\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-alias-binding",
        ),
        pytest.param(
            "def render(flags):\n    for flag in flags:\n        pass\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-loop",
        ),
        pytest.param(
            "def render(flag):\n    try:\n        marker = flag\n    finally:\n        marker = None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-try",
        ),
        pytest.param(
            "def render(flag):\n    assert flag\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-assert",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload = item\n    if not flag:\n        return dict(payload=payload)\n",
            0,
            id="suffix-if",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload = item\n    return flag and dict(payload=payload)\n",
            0,
            id="suffix-bool",
        ),
        pytest.param(
            "def render(left, right):\n    left and right\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="standalone-prefix-bool",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        marker = lambda: flag\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-lambda",
        ),
        pytest.param(
            "def render(flags):\n    if flags:\n        marker = [x for x in flags]\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-comprehension",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        def nested():\n            return flag\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-nested-definition",
        ),
        pytest.param(
            'def render(flag):\n    if flag:\n        marker = "payload"\n    item = object()\n    payload = item\n    return dict(payload=payload)\n',
            0,
            id="quoted-alias",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload: object = item\n    return dict(payload=payload)\n",
            0,
            id="alias-annotated",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    payload = item\n    marker = payload\n    return dict(payload=payload)\n",
            0,
            id="multiple-alias-reads",
        ),
        pytest.param(
            "def render(flag):\n    with manager():\n        if flag:\n            marker = 1\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="guard-in-with-prefix",
        ),
        pytest.param(
            "def render(left, right):\n    if left:\n        marker = left and right\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="boolean-in-prefix-body",
        ),
        pytest.param(
            "def render(flag):\n    if flag:\n        return None\n    item = object()\n    with manager():\n        payload = item\n        return dict(payload=payload)\n",
            0,
            id="alias-nested-in-with-after-prefix",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = object(); payload = item\n    return dict(payload=payload)\n",
            1,
            id="same-line-fresh-source-and-alias",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = []\n    payload = item\n    item.append(1)\n    return dict(payload=payload)\n",
            1,
            id="nonmutating-mutable-source",
        ),
        pytest.param(
            "def run(flag):\n    if flag: yield None\n    item = object()\n    payload = item\n    yield dict(payload=payload)\n",
            1,
            id="prefix-generator-suspension",
        ),
        pytest.param(
            "async def run(flag):\n    if await gate(flag): return None\n    item = await create()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="source-await-after-guard",
        ),
        pytest.param(
            "def run(flag):\n    if flag:\n        factory = make_first\n    else:\n        factory = make_second\n    item: object = factory()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="typed-branch-factory-selection",
        ),
        pytest.param(
            "def run(left, right):\n    if left: return None\n    elif right and left: return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            1,
            id="elif-tests-complete-before-source",
        ),
        pytest.param(
            "def run(flag):\n    if flag:\n        item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="source-only-in-guard",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    with manager():\n        item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="source-in-with-after-guard",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = object()\n    with manager():\n        payload = item\n        return dict(payload=payload)\n",
            0,
            id="alias-in-with-after-guard",
        ),
        pytest.param(
            "def run(flag):\n    item = object()\n    with manager():\n        if flag: return None\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="guard-in-with-after-source",
        ),
        pytest.param(
            "def run(left, right):\n    if left: pass\n    else: marker = left or right\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="boolean-in-else-body",
        ),
        pytest.param(
            "def run(flag):\n    if (lambda: flag)(): return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="lambda-in-prefix-test",
        ),
        pytest.param(
            "def run(flag):\n    if flag:\n        def capture(): return flag\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="nested-definition-in-prefix",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = object()\n    payload = item\n    note = (item := object())\n    return dict(payload=payload)\n",
            0,
            id="source-rebound-by-walrus",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = object()\n    payload = item\n    del item\n    return dict(payload=payload)\n",
            0,
            id="source-deletion-snapshot",
        ),
        pytest.param(
            "def run(flag):\n    if flag: return None\n    item = object()\n    payload: object = item\n    return dict(payload=payload)\n",
            0,
            id="alias-widening-annotation",
        ),
        pytest.param(
            "def run(flag):\n    item: object = object()\n    if flag: return None\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="source-before-guard-type-narrowing",
        ),
        pytest.param(
            "def run(item):\n    if not isinstance(item, str): return None\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="parameter-after-type-guard",
        ),
        pytest.param(
            "def run(flags):\n    for flag in flags: pass\n    if flag: return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-loop-even-if-complete",
        ),
        pytest.param(
            "def run(flag):\n    try: marker = flag\n    finally: marker = None\n    if flag: return None\n    item = object()\n    payload = item\n    return dict(payload=payload)\n",
            0,
            id="prefix-try-even-if-complete",
        ),
        pytest.param(
            "def run(flag, enabled):\n    if flag: return None\n    item = object()\n    payload = item\n    return dict(payload=payload) if enabled else None\n",
            0,
            id="conditional-use-remains-blocked",
        ),
        pytest.param(
            'def run(flag):\n    if flag: marker = "payload"\n    item = object()\n    payload = item\n    return dict(payload=payload)\n',
            0,
            id="quoted-target-in-prefix",
        ),
    ],
)
def test_completed_guard_prefix(source: str, expected: int) -> None:
    diagnostics = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert len(diagnostics) == expected
    assert all(diagnostic.severity is Severity.WARNING and not diagnostic.fixes for diagnostic in diagnostics)
