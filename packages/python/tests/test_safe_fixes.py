from pathlib import Path

import pytest

from sarj_python_lint.__main__ import check_source
from sarj_python_lint._fixes import apply_fixes
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rule_base import AutofixPolicy
from sarj_python_lint.rules.no_redundant_local_alias import NoRedundantLocalAlias


@pytest.mark.parametrize(
    ("source", "expected_diagnostics", "expected"),
    [
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render(item):\n    return dict(payload=item)\n",
            id="dict-tail",
        ),
        pytest.param(
            'def render(item):\n    """Build a mapping."""\n    payload = item\n    return dict(payload=payload)\n',
            1,
            'def render(item):\n    """Build a mapping."""\n    return dict(payload=item)\n',
            id="existing-docstring",
        ),
        pytest.param(
            "async def render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "async def render(item):\n    return dict(payload=item)\n",
            id="async-dict-tail",
        ),
        pytest.param(
            "def render(*, item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render(*, item):\n    return dict(payload=item)\n",
            id="keyword-only-parameter",
        ),
        pytest.param(
            "def render(item, /):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render(item, /):\n    return dict(payload=item)\n",
            id="positional-only-parameter",
        ),
        pytest.param(
            "def render(\xe9l\xe9ment):\n    payload = \xe9l\xe9ment\n    return dict(payload=payload)\n",
            1,
            "def render(\xe9l\xe9ment):\n    return dict(payload=\xe9l\xe9ment)\n",
            id="unicode-source",
        ),
        pytest.param(
            "def render(\uff49\uff54\uff45\uff4d):\n    payload = \uff49\uff54\uff45\uff4d\n    return dict(payload=payload)\n",
            1,
            "def render(\uff49\uff54\uff45\uff4d):\n    return dict(payload=\uff49\uff54\uff45\uff4d)\n",
            id="nfkc-source",
        ),
        pytest.param(
            "def render(item):\r\n    payload = item\r\n    return dict(payload=payload)\r\n",
            1,
            "def render(item):\r\n    return dict(payload=item)\r\n",
            id="crlf",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return consume(payload=payload)\n",
            1,
            "def render(item):\n    payload = item\n    return consume(payload=payload)\n",
            id="unknown-callee",
        ),
        pytest.param(
            "def render(item, other):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render(item, other):\n    payload = item\n    return dict(payload=payload)\n",
            id="other-parameter",
        ),
        pytest.param(
            "@register\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "@register\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            id="decorated",
        ),
        pytest.param(
            "class Renderer:\n    def render(item):\n        payload = item\n        return dict(payload=payload)\n",
            1,
            "class Renderer:\n    def render(item):\n        payload = item\n        return dict(payload=payload)\n",
            id="method",
        ),
        pytest.param(
            "def render(item):\n    payload = item  # Keep this role.\n    return dict(payload=payload)\n",
            1,
            "def render(item):\n    payload = item  # Keep this role.\n    return dict(payload=payload)\n",
            id="assignment-comment",
        ),
        pytest.param(
            "def render(item):\n    # Keep the reviewed boundary.\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render(item):\n    # Keep the reviewed boundary.\n    payload = item\n    return dict(payload=payload)\n",
            id="preceding-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload)  # Keep this mapping.\n",
            1,
            "def render(item):\n    payload = item\n    return dict(payload=payload)  # Keep this mapping.\n",
            id="return-comment",
        ),
        pytest.param(
            "def render(item):\n    payload = item  # sarj-noqa: SARJ531 -- Keep the reviewed boundary.\n    return dict(payload=payload)\n",
            0,
            "def render(item):\n    payload = item  # sarj-noqa: SARJ531 -- Keep the reviewed boundary.\n    return dict(payload=payload)\n",
            id="suppression",
        ),
        pytest.param(
            'def render(item):\n    payload = item\n    "Ready."\n    return dict(payload=payload)\n',
            1,
            'def render(item):\n    payload = item\n    "Ready."\n    return dict(payload=payload)\n',
            id="docstring-promotion",
        ),
        pytest.param(
            'def render(item):\n    alpha = item\n    beta = item\n    "Ready."\n    return dict(alpha=alpha, beta=beta)\n',
            2,
            'def render(item):\n    alpha = item\n    beta = item\n    "Ready."\n    return dict(alpha=alpha, beta=beta)\n',
            id="joint-docstring-promotion",
        ),
        pytest.param(
            "def render(dict):\n    payload = dict\n    return dict(payload=payload)\n",
            1,
            "def render(dict):\n    payload = dict\n    return dict(payload=payload)\n",
            id="shadowed-dict",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload, detail=item.detail)\n",
            1,
            "def render(item):\n    payload = item\n    return dict(payload=payload, detail=item.detail)\n",
            id="attribute-keyword",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload, other=item)\n",
            1,
            "def render(item):\n    payload = item\n    return dict(payload=payload, other=item)\n",
            id="second-keyword",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(*items, payload=payload)\n",
            1,
            "def render(item):\n    payload = item\n    return dict(*items, payload=payload)\n",
            id="starred-argument",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload, **other)\n",
            1,
            "def render(item):\n    payload = item\n    return dict(payload=payload, **other)\n",
            id="unpacked-keywords",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    with manager():\n        return dict(payload=payload)\n",
            1,
            "def render(item):\n    payload = item\n    with manager():\n        return dict(payload=payload)\n",
            id="context-manager",
        ),
        pytest.param(
            "async def render(item):\n    payload = item\n    await pause()\n    return dict(payload=payload)\n",
            1,
            "async def render(item):\n    payload = item\n    await pause()\n    return dict(payload=payload)\n",
            id="await-before-return",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    yield None\n    return dict(payload=payload)\n",
            1,
            "def render(item):\n    payload = item\n    yield None\n    return dict(payload=payload)\n",
            id="yield-before-return",
        ),
        pytest.param(
            "def render(item):\n    payload: object = item\n    return dict(payload=payload)\n",
            0,
            "def render(item):\n    payload: object = item\n    return dict(payload=payload)\n",
            id="typed-alias",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    item = replacement()\n    return dict(payload=payload)\n",
            0,
            "def render(item):\n    payload = item\n    item = replacement()\n    return dict(payload=payload)\n",
            id="snapshot",
        ),
        pytest.param(
            "# coding: latin-1\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "# coding: latin-1\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            id="non-utf8-cookie",
        ),
        pytest.param(
            "from factory import replacement\n__builtins__ = replacement\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "from factory import replacement\n__builtins__ = replacement\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            id="custom-builtins",
        ),
        pytest.param(
            "import builtins\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "import builtins\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n",
            id="builtins-import",
        ),
        pytest.param(
            "def render[T](item: T):\n    payload = item\n    return dict(payload=payload)\n",
            1,
            "def render[T](item: T):\n    payload = item\n    return dict(payload=payload)\n",
            id="generic-type-parameter",
        ),
        pytest.param(
            "def render(item):\n    payload = item\n    return dict(payload=payload)\nnames = render.__code__.co_varnames\n",
            0,
            "def render(item):\n    payload = item\n    return dict(payload=payload)\nnames = render.__code__.co_varnames\n",
            id="code-metadata-observer",
        ),
        pytest.param(
            "def render(\uff49\uff46):\n    payload = \uff49\uff46\n    return dict(payload=payload)\n",
            1,
            "def render(\uff49\uff46):\n    return dict(payload=\uff49\uff46)\n",
            id="nfkc-keyword-\uff49\uff46",
        ),
        pytest.param(
            "def render(\uff46\uff4f\uff52):\n    payload = \uff46\uff4f\uff52\n    return dict(payload=payload)\n",
            1,
            "def render(\uff46\uff4f\uff52):\n    return dict(payload=\uff46\uff4f\uff52)\n",
            id="nfkc-keyword-\uff46\uff4f\uff52",
        ),
        pytest.param(
            "def render(\uff43\uff4c\uff41\uff53\uff53):\n    payload = \uff43\uff4c\uff41\uff53\uff53\n    return dict(payload=payload)\n",
            1,
            "def render(\uff43\uff4c\uff41\uff53\uff53):\n    return dict(payload=\uff43\uff4c\uff41\uff53\uff53)\n",
            id="nfkc-keyword-\uff43\uff4c\uff41\uff53\uff53",
        ),
    ],
)
def test_safe_alias_fix(source: str, expected_diagnostics: int, expected: str) -> None:
    diagnostics = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert len(diagnostics) == expected_diagnostics
    fixes = tuple(fix for diagnostic in diagnostics for fix in diagnostic.fixes)
    assert all(fix.safety is AutofixPolicy.SAFE for fix in fixes)
    assert apply_fixes(source, fixes) == expected
    if expected != source:
        assert fixes
        assert not check_source([NoRedundantLocalAlias()], Path("case.py"), expected)
        assert apply_fixes(expected, ()) == expected
    else:
        assert not fixes


def test_fix_retains_warning_level() -> None:
    documentation = NoRedundantLocalAlias.documentation
    assert documentation is not None
    assert documentation.default_level.value == "warning"
    assert documentation.autofix is AutofixPolicy.SAFE


@pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_nonphysical_line_separators_preserve_value(separator: str) -> None:
    source = f'"prefix{separator}suffix"\ndef render(item):\n    "aaaaaaa" "xx"\n    payload = item\n    return dict(payload=payload)\n'
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    fixed = apply_fixes(source, diagnostic.fixes)
    assert fixed == f'"prefix{separator}suffix"\ndef render(item):\n    "aaaaaaa" "xx"\n    return dict(payload=item)\n'
    assert diagnostic.message.startswith("Local `payload` only forwards `item`")


@pytest.mark.parametrize(
    "prefix",
    [
        "from library_a import dict\nfrom library_b import dict\n",
        "from .library import dict\n",
        "if True:\n    from library import dict\n",
    ],
)
def test_imported_constructor_is_not_safe_builtin(prefix: str) -> None:
    source = f"{prefix}def render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert not diagnostic.fixes


@pytest.mark.parametrize("invalid", ["break\n", "return 1\n", "await pause()\n"])
def test_compiler_invalid_source_is_excluded(invalid: str) -> None:
    source = f"{invalid}def render(item):\n    payload = item\n    return dict(payload=payload)\n"
    assert not check_source([NoRedundantLocalAlias()], Path("case.py"), source)


@pytest.mark.parametrize(
    "mutation", ["runtime.dict = replacement", 'table["dict"] = replacement', 'setattr(runtime, "dict", replacement)']
)
def test_visible_namespace_mutation_prevents_fix(mutation: str) -> None:
    source = f"from library import runtime, table, replacement\n{mutation}\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert not diagnostic.fixes


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("table.update(dict=replacement)", id="mapping-update"),
        pytest.param('table.pop("dict"); table.setdefault("dict", replacement)', id="pop-setdefault"),
        pytest.param("table.__init__(dict=replacement)", id="mapping-init"),
        pytest.param('table.__ior__({"dict": replacement})', id="mapping-ior"),
        pytest.param('table |= {"dict": replacement}', id="mapping-union-assignment"),
        pytest.param(
            'from operator import setitem as replace_item\nreplace_item(table, "dict", replacement)',
            id="imported-setitem-alias",
        ),
        pytest.param('import operator\noperator.ior(table, {"dict": replacement})', id="operator-ior"),
        pytest.param(
            'from operator import ior as merge\nmerge(table, {"dict": replacement})',
            id="imported-ior-alias",
        ),
        pytest.param(
            'import operator\noperator.methodcaller("update", dict=replacement)(table)',
            id="operator-methodcaller",
        ),
        pytest.param(
            'from operator import methodcaller as invoke\ninvoke("update", dict=replacement)(table)',
            id="imported-methodcaller-alias",
        ),
        pytest.param(
            'from unittest.mock import patch\npatch.dict(table, {"dict": replacement}).start()',
            id="patch-mapping",
        ),
        pytest.param(
            'from unittest.mock import patch as replace\nreplace.dict(table, {"dict": replacement}).start()',
            id="imported-patch-alias",
        ),
        pytest.param(
            'from unittest.mock import patch\npatch("builtins.dict", replacement).start()',
            id="patch-builtin-target",
        ),
        pytest.param(
            'from unittest.mock import _patch_dict as replace_mapping\nreplace_mapping(table, {"dict": replacement}).start()',
            id="private-mapping-patch",
        ),
    ],
)
def test_mapping_mutation_prevents_fix(mutation: str) -> None:
    source = f"from library import table, replacement\n{mutation}\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert not diagnostic.fixes


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param("table.update(dict=None)", id="ordinary-update"),
        pytest.param('import operator\noperator.ior(table, {"dict": None})', id="ordinary-ior"),
        pytest.param('import operator\noperator.methodcaller("copy")(table)', id="dynamic-copy"),
        pytest.param(
            'from unittest.mock import patch\npatch.dict(table, {"value": None}).start()',
            id="ordinary-mapping-patch",
        ),
    ],
)
def test_guarded_mapping_operation_retains_manual_diagnostic(operation: str) -> None:
    source = f"table = {{}}\n{operation}\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert not diagnostic.fixes


@pytest.mark.parametrize(
    "prefix",
    [
        "import unittest\n",
        "import unittest.mock as testing\n",
        "from unittest import TestCase\n",
        "from unittest.mock import Mock\n",
    ],
)
def test_unittest_import_retains_manual_diagnostic(prefix: str) -> None:
    source = f"{prefix}def render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert not diagnostic.fixes


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param("table.copy()", id="direct-copy"),
        pytest.param('import operator\noperator.or_(table, {"dict": None})', id="nonmutating-union"),
    ],
)
def test_mapping_read_preserves_safe_fix(operation: str) -> None:
    source = f"from library import table\n{operation}\ndef render(item):\n    payload = item\n    return dict(payload=payload)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], Path("case.py"), source)
    assert diagnostic.fixes
    assert apply_fixes(source, diagnostic.fixes) == source.replace("    payload = item\n", "").replace(
        "payload=payload", "payload=item"
    )


_PATH = Path("app/records.py")
_RULE = "no-redundant-local-alias"
_PUBLIC = "def render(item):\n    payload = item\n    return dict(payload=payload)\n"
_CLOSED = (
    "def render(item):\n"
    "    def _record(value):\n"
    "        payload = value\n"
    "        return dict(payload=payload)\n"
    "    return _record(item)\n"
)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_PUBLIC, id="public-builtin-tail"),
        pytest.param(_PUBLIC.replace("def render", "async def render"), id="async-builtin-tail"),
        pytest.param(_PUBLIC.replace("(item)", "(*, item)"), id="keyword-only"),
        pytest.param(_PUBLIC.replace("(item)", "(item, /)"), id="positional-only"),
        pytest.param(_PUBLIC.replace("item", "élément"), id="unicode-parameter"),
        pytest.param(_PUBLIC.replace("item", "ｃｌａｓｓ"), id="nfkc-keyword-parameter"),
        pytest.param(
            _PUBLIC.replace("(item)", "(item: object) -> dict[str, object]"),
            id="annotation-contract",
        ),
        pytest.param(
            _PUBLIC.replace("    payload = item", '    """Build a mapping."""\n    payload = item'),
            id="existing-docstring",
        ),
    ],
)
def test_native_payload_uses_one_public_contract_path(body: str, separator: str, newline: str) -> None:
    prefix = f'_BANNER = "left{separator}right"\n'
    source = (prefix + body).replace("\n", newline)
    expected = (prefix + body).replace("\n", newline)
    assignment = next(line for line in body.split("\n") if line.startswith("    payload = "))
    original = assignment.removeprefix("    payload = ")
    expected = expected.replace(assignment + newline, "").replace("payload=payload", "payload=" + original)
    findings = check_source([NoRedundantLocalAlias()], _PATH, source)
    assert len(findings) == 1
    assert findings[0].fixes
    assert apply_fixes(source, findings[0].fixes) == expected
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert fix_source(_PATH, expected, rule_ids=[_RULE]) == expected
    assert not check_source([NoRedundantLocalAlias()], _PATH, expected)


def test_native_payload_mixed_physical_endings_match_contract_offsets() -> None:
    source = "def render(item):\r\n    payload = item\r    return dict(payload=payload)\n"
    expected = "def render(item):\r\n    return dict(payload=item)\n"
    [diagnostic] = check_source([NoRedundantLocalAlias()], _PATH, source)
    assert diagnostic.fixes
    assert apply_fixes(source, diagnostic.fixes) == expected
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected


def test_absent_native_payload_keeps_the_existing_closed_handler() -> None:
    expected = _CLOSED.replace("        payload = value\n", "").replace("payload=payload", "payload=value")
    [diagnostic] = check_source([NoRedundantLocalAlias()], _PATH, _CLOSED)
    assert diagnostic.fixes == ()
    assert fix_source(_PATH, _CLOSED, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, expected, rule_ids=[_RULE]) == expected


@pytest.mark.parametrize("reader", ["coro.cr_frame.f_code.co_varnames", "coro.cr_code.co_varnames"])
def test_visible_coroutine_code_metadata_retains_a_manual_finding(reader: str) -> None:
    source = (
        _PUBLIC.replace("def render", "async def render")
        + "coro = render(object())\n"
        + f"names = {reader}\n"
        + "coro.close()\n"
    )
    direct = source.replace("    payload = item\n", "").replace("payload=payload", "payload=item")
    [diagnostic] = check_source([NoRedundantLocalAlias()], _PATH, source)
    assert diagnostic.fixes == ()
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    exec(  # ruff: ignore[exec-builtin] -- trusted fixture observes the visible coroutine code metadata.
        compile(source, str(_PATH), "exec", dont_inherit=True), before
    )
    exec(  # ruff: ignore[exec-builtin] -- compare the same visible observer after a naive alias deletion.
        compile(direct, str(_PATH), "exec", dont_inherit=True), after
    )
    assert before["names"] == ("item", "payload")
    assert after["names"] == ("item",)
