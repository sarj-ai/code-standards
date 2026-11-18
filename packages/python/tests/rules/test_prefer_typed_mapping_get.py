from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, SourceCatalog
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Rule, Severity
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._local_source import LOCAL_SOURCE_CACHE_LIMIT, unshadowed_import_namespace
from sarj_python_lint.rules.prefer_precise_object_contract import PreferPreciseObjectContract
from sarj_python_lint.rules.prefer_typed_mapping_get import PreferTypedMappingGet
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import (
    MappingShapeFacts,
    RequirePydanticForMappingShape,
)


if TYPE_CHECKING:
    import ast
    from collections.abc import Callable


@dataclass(slots=True)
class _CallbackState:
    entries: int = 0


def _mapping_receiver_queries(monkeypatch: pytest.MonkeyPatch) -> Callable[[], int]:
    callback_state = _CallbackState(entries=0)
    original = MappingShapeFacts.mapping

    def counted(
        facts: MappingShapeFacts,
        node: ast.expr,
        *,
        seen: frozenset[ast.AST] = frozenset(),
    ) -> bool:
        callback_state.entries += 1
        return original(facts, node, seen=seen)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count delegated real proof entries without replacing inference or diagnostics.
        MappingShapeFacts, "mapping", counted
    )

    def count() -> int:
        return callback_state.entries

    return count


@pytest.mark.parametrize("depth", [4, 6, 8], ids=["four-levels", "six-levels", "eight-levels"])
def test_shared_return_proofs_avoid_repeated_branch_expansion(monkeypatch: pytest.MonkeyPatch, depth: int) -> None:
    entries = _mapping_receiver_queries(monkeypatch)
    definitions = ["import json\ndef f0(payload): return json.loads(payload)\n"]
    definitions.extend(
        f"def f{index}(payload):\n"
        f"    if payload:\n        return f{index - 1}(payload)\n"
        f"    return f{index - 1}(payload)\n"
        for index in range(1, depth + 1)
    )
    source = "".join(definitions) + f"def read(payload): return f{depth}(payload).get('name')\n"
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    assert [finding.code for finding in findings] == ["SARJ535"]
    assert entries() <= 2 * depth + 2


def test_repeated_negative_return_proofs_preserve_cycle_abstention(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = _mapping_receiver_queries(monkeypatch)
    source = (
        "def loop(payload): return loop(payload)\n"
        "def read(payload):\n"
        "    first = loop(payload).get('first')\n"
        "    second = loop(payload).get('second')\n"
        "    return loop(payload).get('third')\n"
    )
    assert PreferTypedMappingGet().check(Path("app/state.py"), source) == []
    assert entries() <= 4


@pytest.mark.parametrize("deep_first", [False, True], ids=["shallow-first", "deep-first"])
def test_return_proofs_preserve_the_exact_active_depth_budget(deep_first: bool) -> None:
    definitions = ["import json\ndef f0(payload): return json.loads(payload)\n"]
    definitions.extend(f"def f{index}(payload): return f{index - 1}(payload)\n" for index in range(1, 32))
    calls = ["    shallow = f0(payload).get('name')", "    deep = f31(payload).get('name')"]
    if deep_first:
        calls.reverse()
    source = "".join(definitions) + "def read(payload):\n" + "\n".join(calls) + "\n"
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    shallow_line = source.splitlines().index("    shallow = f0(payload).get('name')") + 1
    assert [(finding.line, finding.code) for finding in findings] == [(shallow_line, "SARJ535")]


@pytest.mark.parametrize("precise_first", [False, True], ids=["raw-first", "precise-first"])
def test_identical_helper_asts_keep_their_source_owner(tmp_path: Path, precise_first: bool) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("")
    bridge = "from .producer import parse\ndef decoded(payload): return parse(payload)\n"
    for name, producer in [
        ("raw", "import json\ndef parse(payload): return json.loads(payload)\n"),
        ("precise", "def parse(payload) -> dict[str, str]: return {'name': payload}\n"),
    ]:
        package = app / name
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "bridge.py").write_text(bridge)
        (package / "producer.py").write_text(producer)
    calls = ["    raw_value = raw(payload).get('name')", "    precise_value = precise(payload).get('name')"]
    if precise_first:
        calls.reverse()
    source = (
        "from .raw.bridge import decoded as raw\n"
        "from .precise.bridge import decoded as precise\n"
        "def read(payload):\n" + "\n".join(calls) + "\n"
    )
    consumer = app / "consumer.py"
    consumer.write_text(source)
    findings = analyze([PreferTypedMappingGet.id], [consumer], jobs=1)
    raw_line = source.splitlines().index("    raw_value = raw(payload).get('name')") + 1
    assert [(finding.line, finding.code) for finding in findings] == [(raw_line, "SARJ535")]


@pytest.mark.parametrize("awaited_first", [True, False], ids=["awaited-first", "unawaited-first"])
def test_cached_async_return_proofs_still_require_await(awaited_first: bool) -> None:
    calls = ["    awaited = (await parse(payload)).get('name')", "    unawaited = parse(payload).get('name')"]
    if not awaited_first:
        calls.reverse()
    source = (
        "import json\nasync def parse(payload): return json.loads(payload)\n"
        "async def read(payload):\n" + "\n".join(calls) + "\n"
    )
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    awaited_line = source.splitlines().index("    awaited = (await parse(payload)).get('name')") + 1
    assert [(finding.line, finding.code) for finding in findings] == [(awaited_line, "SARJ535")]


@pytest.mark.parametrize(
    ("body", "count"),
    [
        ("    def inner(): return {'name': 'precise'}\n    return json.loads(payload)\n", 1),
        ("    def inner(): return json.loads(payload)\n    return {'name': 'precise'}\n", 0),
        ("    return json.loads(payload)\n    return {'name': 'precise'}\n", 0),
    ],
    ids=["raw-outer-precise-inner", "precise-outer-raw-inner", "unreachable-precise-return"],
)
def test_return_node_index_preserves_scope_and_conservative_returns(body: str, count: int) -> None:
    source = "import json\ndef parse(payload):\n" + body + "def read(payload): return parse(payload).get('name')\n"
    assert len(PreferTypedMappingGet().check(Path("app/state.py"), source)) == count


def test_return_proof_cache_overflow_recomputes_without_losing_findings() -> None:
    count = 513
    definitions = [f"def parse_{index}(payload): return json.loads(payload)\n" for index in range(count)]
    calls = [f"    value_{index} = parse_{index}(payload).get('name')\n" for index in range(count)]
    source = "import json\n" + "".join(definitions) + "def read(payload):\n" + "".join(calls)
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    assert len(findings) == count
    assert len({(finding.line, finding.col) for finding in findings}) == count


def test_documented_examples() -> None:
    verify_native_rule(PreferTypedMappingGet, analyze)


CASES = (
    ("opaque", "def f(raw: dict[str, object]): return raw.get('name')", 1),
    ("any-values", "from typing import Any\ndef f(raw: dict[str, Any]): return raw.get('name')", 1),
    ("json-values", "from pydantic import JsonValue\ndef f(raw: dict[str, JsonValue]): return raw.get('name')", 1),
    ("mapping", "from collections.abc import Mapping\ndef f(raw: Mapping[str, object]): return raw.get('name')", 1),
    ("bare-dict", "def f(raw: dict): return raw.get('name')", 1),
    ("bare-mapping", "from typing import Mapping\ndef f(raw: Mapping): return raw.get('name')", 1),
    ("any-receiver", "from typing import Any as Unknown\ndef f(raw: Unknown): return raw.get('name')", 1),
    ("object-receiver", "def f(raw: object): return raw.get('name')", 1),
    ("quoted", "def f(raw: 'dict[str, object]'): return raw.get('name')", 1),
    ("type-alias", "type Raw = dict[str, object]\ndef f(raw: Raw): return raw.get('name')", 1),
    ("local-alias", "def f(raw: dict[str, object]):\n    alias = raw\n    return alias.get('name')", 1),
    ("dynamic-key", "def f(raw: dict[str, object], key: str): return raw.get(key)", 1),
    ("default", "def f(raw: dict[str, object]): return raw.get('name', '')", 1),
    ("json-loads", "import json\ndef f(text: str):\n    raw = json.loads(text)\n    return raw.get('name')", 1),
    ("json-direct", "from json import loads as parse\ndef f(text: str): return parse(text).get('name')", 1),
    ("json-load", "import json\ndef f(stream):\n    raw = json.load(stream)\n    return raw.get('name')", 1),
    ("nested-get", "def f(raw: dict[str, object]): return raw.get('state').get('name')", 1),
    ("nested-index", "def f(raw: dict[str, object]): return raw['state'].get('name')", 1),
    ("typed-map", "def f(raw: dict[str, str]): return raw.get('name')", 0),
    ("typed-union", "def f(raw: dict[str, str | int]): return raw.get('name')", 0),
    (
        "typed-dict",
        "from typing import TypedDict\nclass State(TypedDict):\n    name: str\ndef f(raw: State): return raw.get('name')",
        0,
    ),
    ("unknown-parameter", "def f(raw): return raw.get('name')", 0),
    (
        "application-get",
        "class Cache:\n    def get(self, key): return key\ndef f(raw: Cache): return raw.get('name')",
        0,
    ),
    ("reassigned", "def f(raw: dict[str, object]):\n    raw = other\n    return raw.get('name')", 0),
    ("shadowed-dict", "class dict: pass\ndef f(raw: dict[str, object]): return raw.get('name')", 0),
    ("shadowed-any", "from typing import Any\ndef f[Any](raw: Any): return raw.get('name')", 0),
    ("json-hook", "import json\ndef f(text): return json.loads(text, object_hook=Record).get('name')", 0),
    ("shadowed-json", "import json\ndef f(json, text): return json.loads(text).get('name')", 0),
    ("custom-loads", "from app import loads\ndef f(text): return loads(text).get('name')", 0),
    (
        "precise-local",
        "import json\nfrom app import State\ndef f(text):\n    raw: State = json.loads(text)\n    return raw.get('name')",
        0,
    ),
    (
        "validation-callback",
        "from pydantic import BaseModel, model_validator\nclass State(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, raw: dict[str, object]):\n        return {'name': raw.get('name', '')}",
        0,
    ),
    ("wildcard", "from app import *\ndef f(raw: dict[str, object]): return raw.get('name')", 0),
    ("malformed", "def f(:", 0),
    (
        "local-class-shadows-alias",
        "type Raw = dict\ndef outer():\n    class Raw: pass\n    def f(raw: Raw): return raw.get('name')",
        0,
    ),
    (
        "local-value-shadows-alias",
        "type Raw = dict[str, object]\ndef outer():\n    Raw: type[str] = str\n    def f(raw: Raw): return raw.get('name')",
        0,
    ),
    ("alias-definition-scope", "type Raw = dict\ndef f[dict](raw: Raw): return raw.get('name')", 1),
    ("shadowed-type-alias", "type Raw = dict\ndef f[Raw](raw: Raw): return raw.get('name')", 0),
    (
        "local-return",
        "def parse(text: str) -> dict[str, object]: ...\ndef f(text: str): return parse(text).get('name')",
        1,
    ),
    (
        "typed-local-return",
        "def parse(text: str) -> dict[str, str]: ...\ndef f(text: str): return parse(text).get('name')",
        0,
    ),
    (
        "decorated-local-return",
        "@decorate\ndef parse(text: str) -> dict[str, object]: ...\ndef f(text: str): return parse(text).get('name')",
        0,
    ),
)


@pytest.mark.parametrize(("label", "source", "count"), CASES, ids=[case[0] for case in CASES])
def test_mapping_contracts(label: str, source: str, count: int) -> None:
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    assert len(findings) == count, label
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)


_SDK_METADATA_CASES = (
    (
        "annotated",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "quoted-annotation",
        'from livekit.agents.llm import ChatMessage\ndef read(message: "ChatMessage"):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "class-import-alias",
        'from livekit.agents.llm import ChatMessage as Message\ndef read(message: Message):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "module-import-alias",
        'import livekit.agents.llm as llm\ndef read(message: llm.ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "canonical-submodule",
        'from livekit.agents.llm.chat_context import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "assert-narrowed",
        'from livekit.agents.llm import ChatMessage\ndef read(message):\n    assert isinstance(message, ChatMessage)\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "loop-assert-narrowed",
        'from livekit.agents.llm import ChatMessage\ndef read(context):\n    for message in context.items:\n        assert isinstance(message, ChatMessage)\n        if message.extra.get("flag"):\n            return 1\n    return 0\n',
        1,
    ),
    (
        "default-false",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag", False):\n        return 1\n    return 0\n',
        1,
    ),
    (
        "unknown-class",
        'from custom import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "shadowed-class",
        'from livekit.agents.llm import ChatMessage\nclass ChatMessage:\n    extra: dict[str, bool]\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "shadowed-isinstance",
        'from livekit.agents.llm import ChatMessage\ndef read(message, isinstance):\n    assert isinstance(message, ChatMessage)\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "class-patched",
        'from livekit.agents.llm import ChatMessage\nChatMessage.extra = typed_metadata\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "receiver-reassigned",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    message = replacement\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "dynamic-key",
        "from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage, key: str):\n    if message.extra.get(key):\n        return 1\n    return 0\n",
        0,
    ),
    (
        "transport-return",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    return message.extra.get("trace_id")\n',
        0,
    ),
    (
        "transport-log",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    logger.info(message.extra.get("trace_id"))\n',
        0,
    ),
    (
        "normalization",
        'from livekit.agents.llm import ChatMessage\nfrom pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    flag: bool\n    @model_validator(mode="before")\n    @classmethod\n    def normalize(cls, message: ChatMessage):\n        if message.extra.get("flag"):\n            return {"flag": True}\n        return {"flag": False}\n',
        0,
    ),
    (
        "suppressed",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):  # sarj-noqa: SARJ535 -- SDK owns this raw transport flag.\n        return 1\n    return 0\n',
        0,
    ),
    (
        "generated",
        '# Generated by tool. Do not edit.\nfrom livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "assert-not-dominating",
        'from livekit.agents.llm import ChatMessage\ndef read(message, other):\n    if other:\n        assert isinstance(message, ChatMessage)\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "assert-other-object",
        'from livekit.agents.llm import ChatMessage\ndef read(message, other):\n    assert isinstance(other, ChatMessage)\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "precise-subclass",
        'from livekit.agents.llm import ChatMessage\nfrom typing import TypedDict\nclass Flags(TypedDict):\n    flag: bool\nclass Message(ChatMessage):\n    extra: Flags\ndef read(message: Message):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "unregistered-attribute",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.custom_data.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "class-escaped",
        'from livekit.agents.llm import ChatMessage\nregister(ChatMessage)\ndef read(message: ChatMessage):\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "receiver-escaped",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    mutate(message)\n    if message.extra.get("flag"):\n        return 1\n    return 0\n',
        0,
    ),
    (
        "parsed-model",
        "from livekit.agents.llm import ChatMessage\nfrom pydantic import BaseModel\nclass Flags(BaseModel):\n    flag: bool = False\ndef read(message: ChatMessage):\n    if Flags.model_validate(message.extra).flag:\n        return 1\n    return 0\n",
        0,
    ),
    (
        "duplicate-flag-reads",
        'from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get("flag") and message.extra.get("other_flag"):\n        return 1\n    return 0\n',
        1,
    ),
)


@pytest.mark.parametrize(
    ("case_id", "source", "count"), _SDK_METADATA_CASES, ids=[row[0] for row in _SDK_METADATA_CASES]
)
def test_sdk_metadata_contracts(case_id: str, source: str, count: int) -> None:
    findings = PreferTypedMappingGet().check(Path("app/messages.py"), source)
    assert len(findings) == count, case_id
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("layout", ["package", "namespace", "ambiguous"], ids=["package", "namespace", "ambiguous"])
def test_sdk_metadata_local_modules_keep_their_own_contract(tmp_path: Path, layout: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='local-sdk-contract'\nversion='0.0.0'\n")
    sources = ["livekit/agents/llm.py"]
    if layout == "package":
        sources.extend(["livekit/__init__.py", "livekit/agents/__init__.py"])
    elif layout == "ambiguous":
        sources.append("src/livekit/agents/llm.py")
    for name in sources:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("class ChatMessage:\n    extra: dict[str, bool]\n")
    source = _SDK_METADATA_CASES[0][1]
    focus = tmp_path / "messages.py"
    focus.write_text(source)
    assert PreferTypedMappingGet().check(focus, source) == []


def test_sdk_metadata_relative_source_path_retains_local_module_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='local-sdk-contract'\nversion='0.0.0'\n")
    local = tmp_path / "livekit" / "agents" / "llm.py"
    local.parent.mkdir(parents=True)
    local.write_text("class ChatMessage:\n    extra: dict[str, bool]\n")
    monkeypatch.chdir(tmp_path)
    source = _SDK_METADATA_CASES[0][1]
    Path("messages.py").write_text(source, encoding="utf-8")
    assert PreferTypedMappingGet().check(Path("messages.py"), source) == []


@pytest.mark.parametrize(
    ("extra", "conversion"),
    [
        ("from builtins import int as convert\n", "convert"),
        ("import builtins\n", "builtins.int"),
        ("from builtins import int\n", "int"),
    ],
    ids=["alias", "qualified", "imported-name"],
)
def test_http_scalar_prefilter_preserves_existing_builtin_import_abstention(extra: str, conversion: str) -> None:
    source = (
        "from fastapi import Request\n"
        + extra
        + "def read(request: Request):\n    return "
        + conversion
        + "(request.headers.get('attempt', '1'))\n"
    )
    assert PreferTypedMappingGet().check(Path("app/router.py"), source) == []


def test_sdk_metadata_conditions_report_once_per_observed_message() -> None:
    source = "from livekit.agents.llm import ChatMessage\ndef read(first: ChatMessage, second: ChatMessage):\n    if first.extra.get('enabled') and first.extra.get('active'):\n        return 1\n    if second.extra.get('enabled'):\n        return 2\n    return 0\n"
    assert len(PreferTypedMappingGet().check(Path("app/messages.py"), source)) == 2


def test_sdk_metadata_fields_keep_mapping_shape_precedence_distinct() -> None:
    source = _SDK_METADATA_CASES[0][1]
    rules: list[Rule] = [PreferTypedMappingGet(), RequirePydanticForMappingShape()]
    assert [finding.code for finding in check_source(rules, Path("app/messages.py"), source)] == ["SARJ535"]


def test_sdk_metadata_malformed_source_and_calls_abstain() -> None:
    assert PreferTypedMappingGet().check(Path("app/messages.py"), "def read(:\n") == []
    source = "from livekit.agents.llm import ChatMessage\ndef read(message: ChatMessage):\n    if message.extra.get():\n        return 1\n    return 0\n"
    assert PreferTypedMappingGet().check(Path("app/messages.py"), source) == []


@pytest.mark.parametrize("namespace", ["", "../outside", "dotted.name"], ids=["empty", "traversal", "qualified"])
def test_native_namespace_ownership_rejects_non_top_level_inputs(tmp_path: Path, namespace: str) -> None:
    assert not unshadowed_import_namespace(tmp_path / "module.py", namespace, facts=FirstPartyFacts())


def test_native_namespace_ownership_abstains_without_a_project_root(tmp_path: Path) -> None:
    assert not unshadowed_import_namespace(tmp_path / "module.py", "livekit", facts=FirstPartyFacts())


def test_native_namespace_ownership_rejects_dangling_module_symlinks(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='namespace-contract'\nversion='0.0.0'\n")
    (tmp_path / "livekit.py").symlink_to(tmp_path / "missing.py")
    assert not unshadowed_import_namespace(tmp_path / "module.py", "livekit", facts=FirstPartyFacts())


def test_shape_diagnostic_precedence_and_selection() -> None:
    source = "def f(raw: dict[str, object]): return isinstance(raw.get('name'), str)"
    rules: list[Rule] = [PreferTypedMappingGet(), RequirePydanticForMappingShape()]
    assert [finding.code for finding in check_source(rules, Path("app/state.py"), source)] == ["SARJ521"]
    assert [finding.code for finding in check_source(rules[:1], Path("app/state.py"), source)] == ["SARJ535"]


def test_exact_suppression_and_generated_source() -> None:
    source = CASES[0][1] + "  # sarj-noqa: SARJ535 -- open plugin metadata is intentionally opaque\n"
    assert check_source([PreferTypedMappingGet()], Path("app/state.py"), source) == []
    assert PreferTypedMappingGet().check(Path("vendor/state.py"), CASES[0][1]) == []


_PARSER_SOURCE = """
import json
from typing import TypedDict

type Raw = dict[str, object]

def decode(text: str) -> Raw:
    return json.loads(text)

def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError
    return {str(key): item for key, item in value.items()}

def inferred(text: str):
    return json.loads(text)

def forwarded(text: str):
    return inferred(text)

def precise(text: str) -> dict[str, str]:
    return {"name": text}

class State(TypedDict):
    name: str

def record(text: str) -> State:
    return {"name": text}

def unknown(text: str):
    return custom_parser(text)

async def async_decode(text: str) -> Raw:
    return json.loads(text)

def hooked(text: str):
    return json.loads(text, object_hook=State)

def mixed(text: str, flag: bool):
    if flag:
        return {}
    return json.loads(text)

def recursive(text: str):
    return recursive(text)
"""

_IMPORTED_CASES = (
    ("direct", "from app.parser import decode\ndef read(text): return decode(text).get('name')", True),
    ("alias", "from app.parser import decode as parse\ndef read(text): return parse(text).get('name')", True),
    ("qualified", "import app.parser as wire\ndef read(text): return wire.decode(text).get('name')", True),
    ("relative", "from .parser import decode\ndef read(text): return decode(text).get('name')", True),
    ("reexport", "from app.api import decode\ndef read(text): return decode(text).get('name')", True),
    ("module", "import app.parser\ndef read(text): return app.parser.decode(text).get('name')", True),
    ("from-module", "from app import parser\ndef read(text): return parser.decode(text).get('name')", True),
    ("relative-module", "from . import parser\ndef read(text): return parser.decode(text).get('name')", True),
    (
        "callable-alias",
        "from app.parser import decode\ndef read(text):\n    parse = decode\n    return parse(text).get('name')",
        True,
    ),
    ("inferred", "from app.parser import inferred\ndef read(text): return inferred(text).get('name')", True),
    ("forwarded", "from app.parser import forwarded\ndef read(text): return forwarded(text).get('name')", True),
    (
        "value-alias",
        "from app.parser import decode\ndef read(text):\n    raw = decode(text)\n    alias = raw\n    return alias.get('name', '')",
        True,
    ),
    ("precise", "from app.parser import precise\ndef read(text): return precise(text).get('name')", False),
    ("record", "from app.parser import record\ndef read(text): return record(text).get('name')", False),
    ("unknown", "from app.parser import unknown\ndef read(text): return unknown(text).get('name')", False),
    ("hook", "from app.parser import hooked\ndef read(text): return hooked(text).get('name')", False),
    ("mixed", "from app.parser import mixed\ndef read(text): return mixed(text, True).get('name')", False),
    ("recursive", "from app.parser import recursive\ndef read(text): return recursive(text).get('name')", False),
    (
        "awaited",
        "from app.parser import async_decode\nasync def read(text): return (await async_decode(text)).get('name')",
        True,
    ),
    (
        "coroutine",
        "from app.parser import async_decode\ndef read(text): return async_decode(text).get('name')",
        False,
    ),
    ("unresolved", "from external import decode\ndef read(text): return decode(text).get('name')", False),
    (
        "shadowed",
        "from app.parser import decode\ndef read(decode, text): return decode(text).get('name')",
        False,
    ),
    (
        "rebound-module",
        "import app.parser as wire\nwire = application\ndef read(text): return wire.decode(text).get('name')",
        False,
    ),
    (
        "mutated-import",
        "import app.parser as wire\nwire.decode = application\ndef read(text): return wire.decode(text).get('name')",
        False,
    ),
)


def _write_parser_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    package = root / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "parser.py").write_text(_PARSER_SOURCE)
    (package / "api.py").write_text("from .parser import decode\n")
    return package / "consumer.py"


@pytest.mark.parametrize(("case_id", "source", "expected"), _IMPORTED_CASES, ids=[row[0] for row in _IMPORTED_CASES])
def test_imported_mapping_contracts(tmp_path: Path, case_id: str, source: str, *, expected: bool) -> None:
    case = EvaluationCase(
        case_id, Language.PYTHON, source, ExpectedOutcome.MATCH if expected else ExpectedOutcome.NO_MATCH
    )
    consumer = _write_parser_project(tmp_path)
    consumer.write_text(case.source)
    findings = analyze([PreferTypedMappingGet.id], [consumer])
    assert len(findings) == int(expected), case.case_id
    assert all(finding.path == consumer and finding.code == "SARJ535" for finding in findings)


def test_imported_decoder_and_object_narrowing_keep_wire_fields_unvalidated(tmp_path: Path) -> None:
    consumer = _write_parser_project(tmp_path)
    source = (
        "from app.parser import decode, object_value\n"
        "def ready(payload: str):\n"
        "    deployment = decode(payload)\n"
        "    status = object_value(deployment.get('status', {}))\n"
        "    return str(status.get('availableReplicas', '')) == '2'\n"
    )
    consumer.write_text(source)
    findings = analyze([PreferTypedMappingGet.id], [consumer])
    assert [(finding.line, finding.code) for finding in findings] == [(4, "SARJ535"), (5, "SARJ535")]


@pytest.mark.parametrize("jobs", [1, 2])
def test_prepared_sources_preserve_imported_return_contracts(tmp_path: Path, jobs: int) -> None:
    first = _write_parser_project(tmp_path)
    first.write_text("from app.parser import decode\ndef read(text): return decode(text).get('name')\n")
    second = first.with_name("second.py")
    second.write_text(first.read_text())
    catalog = SourceCatalog()
    helper = first.with_name("parser.py")
    catalog.capture(helper)
    helper.write_text("def decode(text: str) -> dict[str, str]: return {'name': text}\n")
    findings = analyze([PreferTypedMappingGet.id], [first, second, helper], sources=catalog, jobs=jobs)
    assert [(finding.path, finding.line, finding.code) for finding in findings] == [
        (first, 2, "SARJ535"),
        (second, 2, "SARJ535"),
    ]


@pytest.mark.parametrize(
    "helper",
    [
        "from .api import decode\n",
        "@decorate\ndef decode(text: str) -> dict[str, object]: ...\n",
        "def decode(text: str) -> dict[str, object]: ...\ndecode = application\n",
        "def decode(text: str) -> dict[str, object]: ...\ndef decode(text: str) -> dict[str, str]: ...\n",
        "def decode(:\n",
    ],
    ids=["reexport-cycle", "decorated", "rebound", "duplicate", "malformed"],
)
def test_imported_uncertain_sources_abstain(tmp_path: Path, helper: str) -> None:
    consumer = _write_parser_project(tmp_path)
    consumer.with_name("parser.py").write_text(helper)
    consumer.write_text("from app.api import decode\ndef read(text): return decode(text).get('name')\n")
    assert analyze([PreferTypedMappingGet.id], [consumer]) == []


def test_imported_mapping_exact_suppression_and_validated_model(tmp_path: Path) -> None:
    consumer = _write_parser_project(tmp_path)
    consumer.write_text(
        "from app.parser import decode\ndef read(text):\n"
        "    return decode(text).get('name')  # sarj-noqa: SARJ535 -- opaque plugin metadata\n"
    )
    assert analyze([PreferTypedMappingGet.id], [consumer]) == []
    consumer.with_name("parser.py").write_text(
        "from pydantic import BaseModel\nclass State(BaseModel):\n    labels: dict[str, str]\n"
        "def decode(text: str) -> State:\n    return State.model_validate_json(text)\n"
    )
    consumer.write_text("from app.parser import decode\ndef read(text): return decode(text).labels.get('name')\n")
    assert analyze([PreferTypedMappingGet.id], [consumer]) == []


@pytest.mark.parametrize("jobs", [1, 2])
def test_imported_contracts_preserve_other_rules_source_budget(tmp_path: Path, jobs: int) -> None:
    first = _write_parser_project(tmp_path)
    readers = [first.with_name(f"consumer_{index:04}.py") for index in range(LOCAL_SOURCE_CACHE_LIMIT + 1)]
    for reader in readers:
        reader.write_text("from app.parser import decode\ndef read(text): return decode(text).get('name')\n")
    first.with_name("guard.py").write_text(
        "from typing import TypeGuard\n"
        "def is_mapping(value: object) -> TypeGuard[dict[object, object]]:\n"
        "    return isinstance(value, dict)\n"
    )
    last = first.with_name("z_validation.py")
    last.write_text(
        "from app.parser import decode\nfrom app.guard import is_mapping\n"
        "def raw(value: object) -> dict[object, object]:\n"
        "    assert is_mapping(value)\n    return value\n"
        "def read(text): return decode(text).get('name')\n"
    )
    findings = analyze([PreferPreciseObjectContract.id, PreferTypedMappingGet.id], [*readers, last], jobs=jobs)
    assert [(finding.path, finding.line, finding.code) for finding in findings] == [
        *((reader, 2, "SARJ535") for reader in readers),
        (last, 6, "SARJ535"),
    ]


_HTTP_HEADER_CASES = (
    (
        "fastapi-int",
        'from fastapi import Request\ndef f(request: Request): return int(request.headers.get("count", "0"))\n',
        1,
    ),
    (
        "starlette-float",
        'from starlette.requests import Request as Incoming\ndef f(r: Incoming): return float(r.headers.get("ratio", "0"))\n',
        1,
    ),
    (
        "header-alias",
        'from fastapi import Request\ndef f(r: Request):\n    headers = r.headers\n    return int(headers.get("count", "0"))\n',
        1,
    ),
    (
        "request-alias",
        'from fastapi import Request\ndef f(r: Request):\n    req = r\n    return int(req.headers.get("count", "0"))\n',
        1,
    ),
    (
        "legacy-fallback",
        'from fastapi import Request\ndef f(r: Request):\n    return int(r.headers.get("attempt") or str(int(r.headers.get("retry", "0")) + 1))\n',
        1,
    ),
    (
        "two-fields",
        'from fastapi import Request\ndef f(r: Request):\n    a = int(r.headers.get("a", "0"))\n    b = float(r.headers.get("b", "0"))\n    return a, b\n',
        2,
    ),
    (
        "quoted-request",
        'from fastapi import Request\ndef f(r: "Request"): return int(r.headers.get("count", "0"))\n',
        1,
    ),
    (
        "boolean-coercion",
        'from fastapi import Request\ndef f(r: Request): return bool(r.headers.get("active", "false"))\n',
        1,
    ),
    ("plain-text", 'from fastapi import Request\ndef f(r: Request): return r.headers.get("accept")\n', 0),
    ("signature", 'from fastapi import Request\ndef f(r: Request): return verify(r.headers.get("signature"))\n', 0),
    ("text-display", 'from fastapi import Request\ndef f(r: Request): return str(r.headers.get("trace", ""))\n', 0),
    ("typed-mapping", 'def f(headers: dict[str, str]): return int(headers.get("count", "0"))\n', 0),
    (
        "unresolved-request",
        'from application import Request\ndef f(r: Request): return int(r.headers.get("count", "0"))\n',
        0,
    ),
    ("unannotated", 'def f(r): return int(r.headers.get("count", "0"))\n', 0),
    (
        "shadowed-request",
        'from fastapi import Request\ndef f[Request](r: Request): return int(r.headers.get("count", "0"))\n',
        0,
    ),
    (
        "shadowed-int",
        'from fastapi import Request\ndef f(r: Request, int): return int(r.headers.get("count", "0"))\n',
        0,
    ),
    (
        "dynamic-field",
        'from fastapi import Request\ndef f(r: Request, key: str): return int(r.headers.get(key, "0"))\n',
        0,
    ),
    (
        "opaque-parse-call",
        'from fastapi import Request\ndef f(r: Request): return int(parse(r.headers.get("count", "0")))\n',
        0,
    ),
    (
        "reassigned-request",
        'from fastapi import Request\ndef f(r: Request):\n    r = trusted\n    return int(r.headers.get("count", "0"))\n',
        0,
    ),
    (
        "mutated-headers",
        'from fastapi import Request\ndef f(r: Request):\n    r.headers = trusted\n    return int(r.headers.get("count", "0"))\n',
        0,
    ),
    ("malformed", "def f(:\n", 0),
    (
        "suppressed",
        'from fastapi import Request\ndef f(r: Request):\n    return int(r.headers.get("count", "0"))  # sarj-noqa: SARJ535 -- owned transport adapter\n',
        0,
    ),
)


@pytest.mark.parametrize(("case_id", "source", "count"), _HTTP_HEADER_CASES, ids=[row[0] for row in _HTTP_HEADER_CASES])
def test_http_header_contracts(case_id: str, source: str, count: int) -> None:
    findings = PreferTypedMappingGet().check(Path("app/router.py"), source)
    assert len(findings) == count, case_id
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    ("local_module", "imported", "count"),
    [
        (None, "fastapi", 1),
        ("fastapi.py", "fastapi", 0),
        ("fastapi/__init__.py", "fastapi", 0),
        ("starlette/requests.py", "starlette.requests", 0),
    ],
)
def test_header_framework_namespace_ownership(
    tmp_path: Path, local_module: str | None, imported: str, count: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='header-owner'\nversion='0.0.0'\n")
    if local_module is not None:
        module = tmp_path / local_module
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("class Request:\n    headers: dict[str, str]\n")
        if imported == "starlette.requests":
            (module.parent / "__init__.py").write_text("")
    source = (
        f"from {imported} import Request\n"
        "def read(request: Request):\n    return int(request.headers.get('count', '0'))\n"
    )
    focus = tmp_path / "app.py"
    focus.write_text(source)
    assert len(PreferTypedMappingGet().check(focus, source)) == count
