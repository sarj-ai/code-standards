from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
import sys
from types import FunctionType
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import apply_edits

from sarj_python_lint._autofix_aliases import AliasFixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Callable


_RULE = "no-redundant-local-alias"
_PATH = Path("app/records.py")
_SOURCE = (
    "def render(item):\n"
    "    def _record(value):\n"
    "        payload = value\n"
    "        return dict(payload=payload)\n"
    "    return _record(item)\n"
)
_FIXED = _SOURCE.replace("        payload = value\n", "").replace("payload=payload", "payload=value")
_PUBLIC_SOURCE = "def render(item):\n    payload = item\n    return consume(payload=payload)\n"
_PUBLIC_DIRECT = _PUBLIC_SOURCE.replace("    payload = item\n", "").replace("payload=payload", "payload=item")


def _fixed(source: str) -> str:
    context = PythonFileContext(_PATH, source)
    fixer = AliasFixes(context)
    edits = [edit for finding in REGISTRY[_RULE]().check_context(context) for edit in fixer.fixes(finding)]
    return apply_edits(source, edits)


def _runtime(
    source: str,
    item: object,
    consume: Callable[..., object] | None = None,
    *,
    transform: Callable[[object], object] | None = None,
) -> object:
    namespace: dict[str, object] = {"item": item}
    if consume is not None:
        namespace["consume"] = consume
    if transform is not None:
        namespace["transform"] = transform
    program = source + "\nresult = render(item)\n"
    exec(  # ruff: ignore[exec-builtin] -- trusted declarations exercise real call and value semantics.
        compile(program, str(_PATH), "exec", dont_inherit=True), namespace
    )
    return namespace["result"]


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_closed_dict_alias_has_native_finding_exact_output_and_convergence(newline: str) -> None:
    source = ("# Unicode 😀\n" + _SOURCE).replace("\n", newline)
    expected = ("# Unicode 😀\n" + _FIXED).replace("\n", newline)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == expected
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert not REGISTRY[_RULE]().check(_PATH, expected)
    assert _fixed(expected) == expected
    compile(expected, str(_PATH), "exec", dont_inherit=True)
    before = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)]
    after = [node for node in ast.walk(ast.parse(expected)) if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in before] == [node.name for node in after]
    assert [ast.dump(node.args) for node in before] == [ast.dump(node.args) for node in after]
    assert [node.returns for node in before] == [node.returns for node in after]


def test_canonical_dict_preserves_value_identity_without_inspecting_it() -> None:
    item = object()
    suffix = (
        "\nresult = render(item)\n"
        "assert type(result) is dict\n"
        "assert list(result) == ['payload']\n"
        "assert result['payload'] is item\n"
    )
    for source in (_SOURCE, _FIXED):
        namespace: dict[str, object] = {"item": item}
        exec(  # ruff: ignore[exec-builtin] -- the closed fixture proves real constructor and identity behavior.
            compile(source + suffix, str(_PATH), "exec", dont_inherit=True), namespace
        )
    assert _runtime(_SOURCE, item) == {"payload": item}
    assert _runtime(_FIXED, item) == {"payload": item}


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("_record", "record"),
        ("    return _record(item)", "    return _record"),
        ("    return _record(item)", "    escaped = _record\n    return escaped(item)"),
        ("    return _record(item)", "    observe(_record)\n    return _record(item)"),
        ("    return _record(item)", "    return _record(transform(item))"),
        ("    return _record(item)", "    marker = observe()\n    return _record(item)"),
        ("    def _record", "    @decorate\n    def _record"),
        ("def render(item)", "@decorate\ndef render(item)"),
        ("def render(item)", "async def render(item)"),
        ("    return _record(item)", "    yield _record(item)"),
        ("_record(value)", "_record(value: object)"),
        ("_record(value):", "_record(value) -> dict[str, object]:"),
        ("        payload = value", "        payload: object = value"),
        ("        payload = value", "        payload = value.attribute"),
        ("dict(payload=payload)", "dict(payload=observe(payload))"),
        ("dict(payload=payload)", "dict(payload=payload, extra=1)"),
        ("dict(payload=payload)", "dict({}, payload=payload)"),
        ("dict(payload=payload)", "dict(**{'payload': payload})"),
        ("dict(payload=payload)", "dict(payload=payload, other=payload)"),
        ("dict(payload=payload)", "other(payload=payload)"),
        ("        payload = value\n", "        payload = value; "),
        ("        payload = value", "        payload = value  # preserve this explanation"),
        ("        payload = value", "        payload = (\n            value  # keep this\n        )"),
        ("        payload = value", "        (\n            payload  # keep this\n        ) = value"),
        ("        return dict(payload=payload)", "        return dict(payload=payload)  # caller contract"),
        ("        payload = value", "        'authored documentation'\n        payload = value"),
        ("    return _record(item)", "    metadata = _record.__code__\n    return _record(item)"),
        ("    return _record(item)", "    aliases = locals()\n    return _record(item)"),
        ("def render(item):", "dict = observe\ndef render(item):"),
        ("def render(item):", "from factory import *\ndef render(item):"),
        ("def render(item):", "import builtins\nbuiltins.dict = observe\ndef render(item):"),
        ("def render(item):", "# type: ignore\ndef render(item):"),
    ],
)
def test_uncertain_alias_or_callable_domains_preserve_source(before: str, after: str) -> None:
    source = _SOURCE.replace(before, after)
    assert _fixed(source) == source
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


def test_wrong_diagnostic_position_or_owner_never_authorizes_an_edit() -> None:
    context = PythonFileContext(_PATH, _SOURCE)
    finding = REGISTRY[_RULE]().check_context(context)[0]
    fixer = AliasFixes(context)
    assert fixer.fixes(replace(finding, line=finding.line + 1)) == []
    assert fixer.fixes(replace(finding, code="SARJ530")) == []


def _caller_local_count(*, payload: object) -> int:
    assert sys._getframe(1).f_locals["item"] is payload  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- the counterexample explicitly observes the caller frame and payload identity.
    return len(sys._getframe(1).f_locals)  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- the counterexample counts caller-local bindings.


def _reference_count(*, payload: object) -> int:
    caller_locals: dict[str, object] = dict(sys._getframe(1).f_locals)  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- retain a real caller-locals snapshot to observe owned references at this opaque boundary.
    count = sys.getrefcount(payload)
    assert caller_locals["item"] is payload
    return count


@pytest.mark.parametrize(
    "observer",
    [_caller_local_count, _reference_count],
    ids=["caller-locals", "frame-backed-refcount"],
)
def test_genuine_external_consumer_findings_stay_manual_with_observable_counterexamples(
    observer: Callable[..., int],
) -> None:
    findings = REGISTRY[_RULE]().check(_PATH, _PUBLIC_SOURCE)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(_PUBLIC_SOURCE) == _PUBLIC_SOURCE
    assert fix_source(_PATH, _PUBLIC_SOURCE, rule_ids=[_RULE]) == _PUBLIC_SOURCE
    item = object()
    before = _runtime(_PUBLIC_SOURCE, item, observer)
    after = _runtime(_PUBLIC_DIRECT, item, observer)
    assert isinstance(before, int)
    assert isinstance(after, int)
    assert before == after + 1


@pytest.mark.parametrize(
    "statement",
    ["    return _record(transform(item))", "    marker = observe()\n    return _record(item)"],
)
def test_unknown_outer_calls_refuse_genuine_native_alias_findings(statement: str) -> None:
    source = _SOURCE.replace("    return _record(item)", statement)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == source
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


def _metadata_transform(
    _item: object,  # sarj-noqa: SARJ528 -- exec callback observes caller metadata and ignores its input value.
) -> bool:
    function: object = sys._getframe(1).f_locals["_record"]  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage, reportAny] -- stdlib f_locals is untyped; this frame observer immediately narrows its value with isinstance(FunctionType).
    assert isinstance(function, FunctionType)
    return "payload" in function.__code__.co_varnames


def test_unknown_outer_transform_can_observe_the_private_alias_binding() -> None:
    source = _SOURCE.replace("    return _record(item)", "    return _record(transform(item))")
    naive = _FIXED.replace("    return _record(item)", "    return _record(transform(item))")
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == source
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    item = object()
    assert _runtime(source, item, transform=_metadata_transform) == {"payload": True}
    assert _runtime(naive, item, transform=_metadata_transform) == {"payload": False}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(_SOURCE.replace("value", "δεδομένα"), _FIXED.replace("value", "δεδομένα"), id="greek-source"),
        pytest.param(_SOURCE.replace("payload", "δεδομένα"), _FIXED.replace("payload", "δεδομένα"), id="greek-alias"),
        pytest.param(
            _SOURCE.replace("value", "cafe\u0301"), _FIXED.replace("value", "cafe\u0301"), id="combining-source"
        ),
        pytest.param(
            _SOURCE.replace("payload", "cafe\u0301"), _FIXED.replace("payload", "cafe\u0301"), id="combining-alias"
        ),
        pytest.param(_SOURCE.replace("value", "ｖalue"), _FIXED.replace("value", "ｖalue"), id="nfkc-source"),
        pytest.param(_SOURCE.replace("payload", "ｐayload"), _FIXED.replace("payload", "ｐayload"), id="nfkc-alias"),
        pytest.param(
            _SOURCE.replace("value", "ｃｌａｓｓ"), _FIXED.replace("value", "ｃｌａｓｓ"), id="nfkc-class-source"
        ),
        pytest.param(_SOURCE.replace("value", "ｄｅｆ"), _FIXED.replace("value", "ｄｅｆ"), id="nfkc-def-source"),
        pytest.param(
            _SOURCE.replace("payload", "ｃｌａｓｓ"), _FIXED.replace("payload", "ｃｌａｓｓ"), id="nfkc-class-alias"
        ),
        pytest.param(
            _SOURCE.replace("_record", "_καταγραφή"), _FIXED.replace("_record", "_καταγραφή"), id="greek-helper"
        ),
        pytest.param(_SOURCE.replace("dict(", "ｄict("), _FIXED.replace("dict(", "ｄict("), id="nfkc-builtin"),
        pytest.param(
            _SOURCE.replace("payload = value", "payload = (\n            value\n        )"),
            _FIXED,
            id="multiline-value",
        ),
        pytest.param(
            _SOURCE.replace("payload = value", "(\n            payload\n        ) = value"),
            _FIXED,
            id="multiline-target",
        ),
        pytest.param(
            _SOURCE.replace("payload = value", "(\n            payload\n        ) = (\n            value\n        )"),
            _FIXED,
            id="multiline-both",
        ),
        pytest.param(
            _SOURCE.replace("payload = value", "payload = \\\n            value"),
            _FIXED,
            id="backslash-value",
        ),
        pytest.param(
            _SOURCE.replace("dict(payload=payload)", "dict(\n            payload=payload\n        )"),
            _FIXED.replace("dict(payload=value)", "dict(\n            payload=value\n        )"),
            id="multiline-keyword-call",
        ),
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_practical_raw_name_and_multiline_aliases_preserve_every_other_byte(
    source: str, expected: str, newline: str
) -> None:
    source = ("# Unicode prefix 😀 café\n" + source).replace("\n", newline)
    expected = ("# Unicode prefix 😀 café\n" + expected).replace("\n", newline)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == expected
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert not REGISTRY[_RULE]().check(_PATH, expected)
    assert _fixed(expected) == expected
    compile(expected, str(_PATH), "exec", dont_inherit=True)
    item = object()
    assert _runtime(source, item) == _runtime(expected, item)


@pytest.mark.parametrize(
    "separator",
    [
        pytest.param("\u2028", id="line-separator"),
        pytest.param("\u0085", id="next-line"),
        pytest.param("\f", id="form-feed"),
        pytest.param("\u2029", id="paragraph-separator"),
        pytest.param("\v", id="vertical-tab"),
        pytest.param("\x1c", id="file-separator"),
        pytest.param("\x1d", id="group-separator"),
        pytest.param("\x1e", id="record-separator"),
    ],
)
@pytest.mark.parametrize(
    "endings",
    [
        pytest.param(("\n",) * 6, id="lf"),
        pytest.param(("\r\n",) * 6, id="crlf"),
        pytest.param(("\r",) * 6, id="cr"),
        pytest.param(("\r\n", "\r", "\n", "\r\n", "\r", "\n"), id="mixed"),
    ],
)
def test_nonphysical_separators_in_module_data_never_redirect_alias_edits(
    separator: str, endings: tuple[str, ...]
) -> None:
    data = separator.join(["a", "b", "c", "        payload = value", "        return dict(payload=payload)", "z"])
    prefix = f'_BANNER = "{data}"' + endings[0]
    body = "".join(line + ending for line, ending in zip(_SOURCE.splitlines(), endings[1:], strict=True))
    expected_body = body.replace("        payload = value" + endings[3], "").replace("payload=payload", "payload=value")
    source = prefix + body
    expected = prefix + expected_body
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == expected
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert expected.startswith(prefix)
    assert ast.dump(ast.parse(source).body[0]) == ast.dump(ast.parse(expected).body[0])
    assert not REGISTRY[_RULE]().check(_PATH, expected)
    assert _fixed(expected) == expected
    compile(expected, str(_PATH), "exec", dont_inherit=True)
    item = object()
    assert _runtime(source, item) == _runtime(expected, item)
    other_rule = "no-delete-statement"
    other_source = (
        "def ready():\n"
        "    def _ready():\n"
        "        unused = None\n"
        "        del unused\n"
        "        return True\n"
        "    return _ready()\n"
    )
    other_fixed = other_source.replace("        del unused\n", "\n")
    assert other_fixed != other_source
    assert len(REGISTRY[other_rule]().check(_PATH, other_source)) == 1
    assert fix_source(_PATH, other_source, rule_ids=[other_rule]) == other_fixed
    assert not REGISTRY[other_rule]().check(_PATH, other_fixed)
    guarded_prefix = prefix + "".join(
        line + ending for line, ending in zip(other_source.splitlines(), endings, strict=True)
    )
    source = guarded_prefix + body
    mixed_expected = guarded_prefix + expected_body
    deletion_findings = REGISTRY[other_rule]().check(_PATH, source)
    assert len(deletion_findings) == 1
    assert deletion_findings[0].code == "SARJ442"
    for selection in (None, [_RULE, other_rule], [other_rule, _RULE]):
        updated = fix_source(_PATH, source, rule_ids=selection)
        assert updated == mixed_expected
        assert REGISTRY[other_rule]().check(_PATH, updated) == deletion_findings
        assert not REGISTRY[_RULE]().check(_PATH, updated)
        assert fix_source(_PATH, updated, rule_ids=selection) == updated
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert fix_source(_PATH, source, rule_ids=[other_rule]) == source


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        pytest.param("payload = value", "payload = value  # retain alias rationale", id="alias-comment"),
        pytest.param(
            "return dict(payload=payload)",
            "return dict(payload=payload)  # retain result rationale",
            id="return-comment",
        ),
        pytest.param(
            "payload = value",
            "payload = (\n            value  # retain multiline rationale\n        )",
            id="multiline-comment",
        ),
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_physical_owner_comments_are_preserved_with_lone_carriage_returns(
    original: str, replacement: str, newline: str
) -> None:
    source = _SOURCE.replace(original, replacement).replace("\n", newline)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ531"
    assert _fixed(source) == source
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_ordinary_newlines_keep_other_selected_builders_enabled(newline: str) -> None:
    source = ("# --------\n" + _SOURCE).replace("\n", newline)
    expected = ("\n" + _FIXED).replace("\n", newline)
    assert len(REGISTRY["no-comment-cruft"]().check(_PATH, source)) == 1
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 1
    assert fix_source(_PATH, source, rule_ids=["no-comment-cruft", _RULE]) == expected
    assert not REGISTRY["no-comment-cruft"]().check(_PATH, expected)
    assert not REGISTRY[_RULE]().check(_PATH, expected)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_PUBLIC_SOURCE, id="opaque-consumer"),
        pytest.param(_SOURCE.replace("_record(value)", "_record(value: object)"), id="annotation"),
        pytest.param(_SOURCE.replace("payload = value", "payload = value; pass"), id="semicolon"),
        pytest.param(_SOURCE.replace("payload = value", "payload = value  # keep rationale"), id="comment"),
        pytest.param(
            _SOURCE.replace("    return _record(item)", "    return _record(transform(item))"),
            id="opaque-outer-call",
        ),
        pytest.param(
            _SOURCE.replace("    return _record(item)", "    return _record"),
            id="escaped-helper",
        ),
    ],
)
def test_exceptional_public_dispatch_preserves_uncertain_alias_domains(body: str) -> None:
    source = '_BANNER = "left\u2028right"\r' + body.replace("\n", "\r")
    assert _fixed(source) == source
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    assert fix_source(_PATH, source) == source


def test_unknown_rule_key_still_fails_before_exceptional_source_filtering() -> None:
    source = '_BANNER = "left\u2028right"\n' + _SOURCE
    with pytest.raises(KeyError):
        fix_source(_PATH, source, rule_ids=["unknown-native-rule"])
