from __future__ import annotations

from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


@pytest.mark.parametrize(
    "rule_id",
    ["prefer-walrus-awaited-none-guard", "prefer-walrus-regex-match", "prefer-walrus-stream-loop"],
)
@pytest.mark.parametrize("requires_python", [">=3.7", ">=3.7,<3.8", "==3.7.*"])
def test_walrus_preferences_preserve_declared_legacy_support(
    tmp_path: Path, rule_id: str, requires_python: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[project]\nname = 'legacy-example'\nversion = '1.0.0'\nrequires-python = '{requires_python}'\n"
    )
    rule_type = REGISTRY[rule_id]
    example = next(example for example in rule_type.public_examples() if example.expected_count)
    assert rule_type().check(tmp_path / example.focus_path, example.focus_file.source) == []


@pytest.mark.parametrize(
    ("rule_id", "blocking", "advisory"),
    [
        (
            "prefer-self-type-annotation",
            "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n",
            "class Builder:\n    def fluent(self) -> 'Builder': return self\n",
        ),
        (
            "require-precise-factory-signature",
            "from collections.abc import Callable\nclass Result: pass\ndef _build(factory: Callable[..., Result]):\n    return factory(size=4)\n_build(Result)\n",
            "from collections.abc import Callable\nclass Result: pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
        ),
        (
            "require-keyword-only-swap-prone-params",
            "def _move(source_id: str, target_id: str): return source_id, target_id\n_move('a', 'b')\n",
            "def move(source_id: str, target_id: str): return source_id, target_id\n",
        ),
        (
            "prefer-monotonic-for-elapsed-time",
            "import time\ndef wait():\n    start = time.time()\n    while time.time() - start < 5:\n        work()\n",
            "import time\ndef measure():\n    start = time.time()\n    work()\n    return time.time() - start\n",
        ),
        (
            "prefer-collection-comprehension",
            "def values(rows):\n    result = {}\n    for key, row in rows:\n        result[key] = row.value\n    return result\n",
            "def values(rows):\n    result = {}\n    for row in rows:\n        result[row.key] = row.value\n    return result\n",
        ),
    ],
)
def test_blocking_proofs_preserve_advisory_compatibility_cases(rule_id: str, blocking: str, advisory: str) -> None:
    rule_type = REGISTRY[rule_id]
    assert [item.severity for item in rule_type().check(Path("service.py"), blocking)] == [Severity.ERROR]
    assert [item.severity for item in rule_type().check(Path("service.py"), advisory)] == [Severity.WARNING]


@pytest.mark.parametrize("rule_id", ["require-precise-factory-signature", "require-keyword-only-swap-prone-params"])
def test_namespace_exports_cannot_prove_closed_callable_ownership(rule_id: str) -> None:
    source = (
        "import sys\n"
        "from collections.abc import Callable\nclass Result: pass\n"
        "def _build(factory: Callable[..., Result]): return factory(size=4)\n_build(Result)\n"
        "def _move(source_id: str, target_id: str): return source_id, target_id\n_move('a', 'b')\n"
        "sink(sys._getframe().f_globals)\n"
    )
    assert [item.severity for item in REGISTRY[rule_id]().check(Path("service.py"), source)] == [Severity.WARNING]


def test_overwritten_final_method_is_not_the_effective_return_contract() -> None:
    source = "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n    def fluent(self) -> 'Builder': return Builder()\n"
    assert REGISTRY["prefer-self-type-annotation"]().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "import typing\ntyping.final = lambda method: lambda self: Builder()\nclass Builder:\n    @typing.final\n    def fluent(self) -> 'Builder': return self\n",
        "from typing import final\nclass Builder(UnknownBase):\n    @final\n    def fluent(self) -> 'Builder': return self\n",
        "from typing import final\n@replace_class\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n",
        "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\ndef replacement(self: Builder) -> Builder: return Builder()\nBuilder.fluent = replacement\n",
        "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\nsetattr(Builder, 'fluent', replacement)\n",
        "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\nreplace_method(Builder)\n",
        "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n    def __init_subclass__(cls): setattr(cls, 'fluent', lambda self: Builder())\n",
        "from typing import final\nclass Descriptor:\n    def __set_name__(self, owner, name): setattr(owner, 'fluent', lambda self: Builder())\nclass Builder:\n    guard = Descriptor()\n    @final\n    def fluent(self) -> 'Builder': return self\n",
        "from typing import final\nclass Descriptor:\n    def __set_name__(self, owner, name): setattr(owner, 'fluent', lambda self: Builder())\nguard = Descriptor()\nclass Builder:\n    marker = guard\n    @final\n    def fluent(self) -> 'Builder': return self\n",
    ],
)
def test_dynamic_final_method_owners_remain_advisory(source: str) -> None:
    assert [item.severity for item in REGISTRY["prefer-self-type-annotation"]().check(Path("service.py"), source)] == [
        Severity.WARNING
    ]


@pytest.mark.parametrize(
    "alias_import",
    [
        "from app.builder import Builder as OwnedBuilder\nreplace_method(OwnedBuilder)\n",
        "import app.builder as owned\nreplace_method(owned.Builder)\n",
        "from app.builder import Builder as OwnedBuilder\nOwnedBuilder = OwnedBuilder\nreplace_method(OwnedBuilder)\n",
        "import app.builder as owned\nowned = owned\nreplace_method(owned.Builder)\n",
        "def alter():\n    from app.builder import Builder as Alias\n    replace_method(Alias)\nalter()\n",
        "def alter():\n    import app.builder as owned\n    replace_method(owned.Builder)\nalter()\n",
        "def replace_module(module): replace_method(module.Builder)\nimport app.builder as owned\nreplace_module(owned)\n",
        "def replace_module(module): replace_method(module.Builder)\nimport app.builder\nreplace_module(app.builder)\n",
        "def replace_module(module): replace_method(module.Builder)\nfrom app import builder as owned\nreplace_module(owned)\n",
        "def types(): yield Builder\nreplace_method(next(types()))\n",
        "if (owned := Builder): replace_method(owned)\n",
        "for owned in (Builder,): replace_method(owned)\n",
        "match Builder:\n    case owned: replace_method(owned)\n",
        "def replace_default(owner=Builder): replace_method(owner)\nreplace_default()\n",
        "class Registry:\n    def __getitem__(self, owner): replace_method(owner)\nRegistry()[Builder]\n",
        "class Registry:\n    def __eq__(self, owner): replace_method(owner); return True\nif Registry() == Builder: pass\n",
    ],
)
@pytest.mark.parametrize("absolute_path", [False, True])
def test_self_module_with_imported_class_alias_remains_advisory(
    tmp_path: Path, alias_import: str, absolute_path: bool
) -> None:
    source = (
        "from typing import final\nclass Builder:\n    @final\n"
        "    def fluent(self) -> 'Builder': return self\n"
        "def replace_method(owner):\n"
        "    def replacement(self): return Builder()\n"
        "    owner.fluent = replacement\n" + alias_import
    )
    path = tmp_path / "app" / "builder.py" if absolute_path else Path("app/builder.py")
    findings = REGISTRY["prefer-self-type-annotation"]().check(path, source)
    assert [item.severity for item in findings] == [Severity.WARNING]


@pytest.mark.parametrize(
    "constructor_call",
    [
        "from app.builder import Builder as Alias\nAlias()\n",
        "import app.builder as owned\nowned.Builder()\n",
    ],
)
def test_known_self_module_direct_imported_constructor_keeps_error(constructor_call: str) -> None:
    source = (
        "from typing import final\nclass Builder:\n    @final\n"
        "    def fluent(self) -> 'Builder': return self\n" + constructor_call
    )
    findings = REGISTRY["prefer-self-type-annotation"]().check(Path("app/builder.py"), source)
    assert [item.severity for item in findings] == [Severity.ERROR]


def test_indirect_clock_provider_mutation_is_not_proven_wall_clock() -> None:
    source = "import time\nimport sys\nsys.modules['time'].time = time.monotonic\ndef wait():\n    start = time.time()\n    while time.time() - start < 5:\n        work()\n"
    assert REGISTRY["prefer-monotonic-for-elapsed-time"]().check(Path("service.py"), source) == []


def test_projection_frame_effects_keep_builder_advisory() -> None:
    source = "import inspect\nclass Row:\n    @property\n    def value(self):\n        inspect.currentframe().f_back.f_locals['key'] = 'changed'\n        return 1\ndef values(rows):\n    result = {}\n    for key, row in rows:\n        result[key] = row.value\n    return result\n"
    assert [
        item.severity for item in REGISTRY["prefer-collection-comprehension"]().check(Path("service.py"), source)
    ] == [Severity.WARNING]


@pytest.mark.parametrize("target", [">=3.10", ">=3.14,<4", "==3.12.*", "~=3.11"])
def test_literal_dispatch_is_blocking_with_a_proven_modern_target(tmp_path: Path, target: str) -> None:
    (tmp_path / "pyproject.toml").write_text(f"[project]\nrequires-python = '{target}'\n")
    source = "def parse(kind):\n    if kind == 'json': return json_parser()\n    elif kind == 'yaml': return yaml_parser()\n    else: return fallback()\n"
    assert [
        item.severity for item in REGISTRY["prefer-match-value-dispatch"]().check(tmp_path / "service.py", source)
    ] == [Severity.ERROR]


@pytest.mark.parametrize("target", [None, "invalid", ">=3.9,!=3.9.*", "===3.14"])
def test_ambiguous_target_keeps_literal_dispatch_advisory(tmp_path: Path, target: str | None) -> None:
    if target is not None:
        (tmp_path / "pyproject.toml").write_text(f"[project]\nrequires-python = '{target}'\n")
    source = "def parse(kind):\n    if kind == 'json': return json_parser()\n    elif kind == 'yaml': return yaml_parser()\n    else: return fallback()\n"
    assert [
        item.severity for item in REGISTRY["prefer-match-value-dispatch"]().check(tmp_path / "service.py", source)
    ] == [Severity.WARNING]


@pytest.mark.parametrize("value", ["True", "False", "None"])
def test_invariant_singleton_options_are_blocking(value: str) -> None:
    source = (
        f"def _widget(*, enabled={value}):\n    return Widget(enabled=enabled)\n_widget()\n_widget(enabled={value})\n"
    )
    assert [
        item.severity for item in REGISTRY["unused-test-factory-option"]().check(Path("tests/test_widget.py"), source)
    ] == [Severity.ERROR]


@pytest.mark.parametrize("value", ["300", "'long default value'", "3.5", "b'default'"])
def test_non_singleton_literal_options_remain_advisory(value: str) -> None:
    source = f"def _widget(*, value={value}):\n    return Widget(value=value)\n_widget()\n_widget(value={value})\n"
    assert [
        item.severity for item in REGISTRY["unused-test-factory-option"]().check(Path("tests/test_widget.py"), source)
    ] == [Severity.WARNING]


def test_captured_class_dispatch_is_advisory(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nrequires-python = '>=3.10'\n")
    source = "def outer(kind):\n    class Inner:\n        if kind == 'json': outcome = json_parser()\n        elif kind == 'yaml': outcome = yaml_parser()\n        else: outcome = fallback()\n"
    assert [
        item.severity for item in REGISTRY["prefer-match-value-dispatch"]().check(tmp_path / "service.py", source)
    ] == [Severity.WARNING]


def test_actual_non_singleton_values_keep_singleton_default_advisory() -> None:
    source = "def _widget(*, enabled=None):\n    return Widget(enabled=enabled)\n_widget(enabled=300)\n_widget(enabled=300)\n"
    assert [
        item.severity for item in REGISTRY["unused-test-factory-option"]().check(Path("tests/test_widget.py"), source)
    ] == [Severity.WARNING]


def test_rebound_nested_factory_option_is_advisory() -> None:
    source = "def test_widgets():\n    def _make_widget(*, enabled=True):\n        enabled = False\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget()\n"
    assert [
        item.severity for item in REGISTRY["unused-test-factory-option"]().check(Path("tests/test_widget.py"), source)
    ] == [Severity.WARNING]


@pytest.mark.parametrize("value", ["True", "False", "None"])
def test_closed_unused_singleton_keyword_blocks(value: str) -> None:
    source = f"def _emit(*, _unused={value}): return 'ready'\n_emit()\n_emit(_unused={value})\n"
    assert [
        item.severity
        for item in REGISTRY["no-unused-underscored-keyword-parameter"]().check(Path("service.py"), source)
    ] == [Severity.ERROR]


@pytest.mark.parametrize(
    "source",
    [
        "def emit(*, _unused=True): return 'ready'\nemit(_unused=True)\n",
        "def _emit(*, _unused=True): return 'ready'\n_emit(_unused=build())\n",
        "def _emit(*, _unused=build()): return 'ready'\n_emit(_unused=True)\n",
        "def _emit(*, _unused: record_annotation()=True): return 'ready'\n_emit(_unused=True)\n",
        "def _emit(*, _unused: bool): return 'ready'\n_emit(_unused=True)\n",
        "async def _emit(*, _unused=True): return 'ready'\n_emit(_unused=True)\n",
        "def _emit(*, _unused=True): return 'ready'\n_emit(_unused=True)\nsink(_emit)\n",
    ],
)
def test_effects_and_external_unused_keyword_contracts_remain_advisory(source: str) -> None:
    assert [
        item.severity
        for item in REGISTRY["no-unused-underscored-keyword-parameter"]().check(Path("service.py"), source)
    ] in ([Severity.WARNING], [])


@pytest.mark.parametrize(
    "alias_use",
    [
        "from app.sink import _emit as send\nsend(_unused=produce())\n",
        "from app.sink import _emit as send\nregister(send)\n",
        "def later():\n    from app.sink import _emit as send\n    register(send)\n",
        "from app.sink import _emit as send\nsend = send\nregister(send)\n",
    ],
)
def test_self_imported_private_function_aliases_keep_unused_keyword_advisory(alias_use: str) -> None:
    source = "def _emit(*, _unused: bool=True): return 'ready'\n_emit()\n_emit()\n" + alias_use
    findings = REGISTRY["no-unused-underscored-keyword-parameter"]().check(Path("app/sink.py"), source)
    assert [item.severity for item in findings] == [Severity.WARNING]


@pytest.mark.parametrize("alias_use", ["build(enabled=False)", "register(build)"])
def test_self_imported_factory_alias_invalidates_complete_caller_inventory(alias_use: str) -> None:
    source = (
        "def _widget(*, enabled=True): return Widget(enabled=enabled)\n_widget()\n_widget()\n"
        "from tests.test_widget import _widget as build\n" + alias_use + "\n"
    )
    assert REGISTRY["unused-test-factory-option"]().check(Path("tests/test_widget.py"), source) == []


@pytest.mark.parametrize("target_only", [False, True])
@pytest.mark.parametrize("mutates", [False, True])
@pytest.mark.parametrize("kind", ["fluent-method", "before-validator"])
def test_import_only_siblings_participate_in_owned_class_inventory(
    tmp_path: Path, target_only: bool, mutates: bool, kind: str
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'inventory-probe'\nversion = '0.0.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    if kind == "fluent-method":
        target = package / "builder.py"
        target.write_text(
            "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n"
        )
        sibling_source = (
            "from .builder import Builder\ndef replacement(self: Builder) -> Builder: return Builder()\n"
            "Builder.fluent = replacement\n"
            if mutates
            else "from .builder import Builder\nBuilder()\n"
        )
        code = "SARJ078"
        expected = [Severity.WARNING] if mutates else [Severity.ERROR]
    else:
        target = package / "records.py"
        target.write_text(
            "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    value: int\n"
            "    @model_validator(mode='before')\n    @classmethod\n"
            "    def clean(cls, data: dict[str, object]) -> dict[str, object]:\n"
            "        data.pop('legacy', None)\n        return data\n"
        )
        sibling_source = (
            "from .records import Record\nRecord.__pydantic_decorators__.model_validators.clear()\n"
            "Record.model_rebuild(force=True)\n"
            if mutates
            else "from .records import Record\nRecord(value=1)\n"
        )
        code = "SARJ482"
        expected = [] if mutates else [Severity.ERROR]
    sibling = package / "sibling.py"
    sibling.write_text(sibling_source)
    diagnostics = analyze(
        [
            "prefer-self-type-annotation",
            "no-before-validator-input-mutation",
            "require-explicit-contract-implementation",
        ],
        [target] if target_only else [target, sibling],
    )
    assert [finding.severity for finding in diagnostics if finding.path == target and finding.code == code] == expected


@pytest.mark.parametrize("target_only", [False, True])
@pytest.mark.parametrize("route", ["named-patch", "namespace-patch", "named-constructor", "qualified-constructor"])
def test_reexported_class_values_preserve_only_closed_constructor_controls(
    tmp_path: Path, target_only: bool, route: str
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'reexport-probe'\nversion = '0.0.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    target = package / "builder.py"
    target.write_text(
        "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n"
    )
    facade = package / "public.py"
    facade.write_text("from .builder import Builder as ExportedBuilder\n")
    sibling = package / "sibling.py"
    match route:
        case "named-patch":
            source = (
                "from .public import ExportedBuilder\n"
                "def replacement(self: ExportedBuilder) -> ExportedBuilder: return ExportedBuilder()\n"
                "ExportedBuilder.fluent = replacement\n"
            )
            expected = Severity.WARNING
        case "namespace-patch":
            source = (
                "from . import public\ndef configure(module):\n"
                "    module.ExportedBuilder.fluent = lambda self: module.ExportedBuilder()\nconfigure(public)\n"
            )
            expected = Severity.WARNING
        case "named-constructor":
            source = "from .public import ExportedBuilder\nExportedBuilder()\n"
            expected = Severity.ERROR
        case _:
            source = "from . import public\npublic.ExportedBuilder()\n"
            expected = Severity.ERROR
    sibling.write_text(source)
    diagnostics = analyze(
        ["prefer-self-type-annotation", "require-explicit-contract-implementation"],
        [target] if target_only else [target, facade, sibling],
    )
    assert [finding.severity for finding in diagnostics if finding.path == target and finding.code == "SARJ078"] == [
        expected
    ]


@pytest.mark.parametrize("target_only", [False, True])
@pytest.mark.parametrize("kind", ["fluent-method", "before-validator"])
@pytest.mark.parametrize("jobs", [1, 2])
def test_dense_wildcard_cycles_cannot_prove_closed_class_ownership(
    tmp_path: Path, target_only: bool, kind: str, jobs: int
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'cyclic-probe'\nversion = '0.0.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    target = package / "owned.py"
    if kind == "fluent-method":
        target.write_text(
            "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n"
        )
        code, expected = "SARJ078", [Severity.WARNING]
    else:
        target.write_text(
            "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    value: int\n"
            "    @model_validator(mode='before')\n    @classmethod\n"
            "    def clean(cls, data: dict[str, object]) -> dict[str, object]:\n"
            "        data.pop('legacy', None)\n        return data\n"
        )
        code, expected = "SARJ482", []
    peers: list[Path] = []
    for index in range(10):
        peer = package / f"peer{index}.py"
        peer.write_text(
            "from .owned import *\n" + "".join(f"from .peer{other} import *\n" for other in range(10) if other != index)
        )
        peers.append(peer)
    consumer = package / "consumer.py"
    name = "Builder" if kind == "fluent-method" else "Record"
    consumer.write_text(f"from .peer0 import {name}\n{name}()\n")
    peers.append(consumer)
    diagnostics = analyze(
        [
            "prefer-self-type-annotation",
            "no-before-validator-input-mutation",
            "require-explicit-contract-implementation",
        ],
        [target] if target_only else [target, *peers],
        jobs=jobs,
    )
    assert [finding.severity for finding in diagnostics if finding.path == target and finding.code == code] == expected


@pytest.mark.parametrize("target_only", [False, True])
@pytest.mark.parametrize("kind", ["fluent-method", "before-validator"])
@pytest.mark.parametrize(
    "context",
    [
        "base-call",
        "annotation-call",
        "base-subscription",
        "annotation-subscription",
        "shadowed-type",
        "wildcard-type",
        "wildcard-typing",
        "mutated-typing",
        "escaped-typing",
        "method-mutated-typing",
        "dict-mutated-typing",
        "nested-mutated-typing",
        "cross-unit-mutated-typing",
        "cross-unit-named-provider",
        "cross-unit-qualified-provider",
        "plain-base",
        "plain-annotation",
        "type-annotation",
        "dict-annotation",
        "typing-annotation",
    ],
)
def test_type_context_runtime_values_cannot_hide_owned_class_mutation(
    tmp_path: Path, target_only: bool, kind: str, context: str
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'type-context-probe'\nversion = '0.0.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    target = package / "owned.py"
    if kind == "fluent-method":
        target.write_text(
            "from typing import final\nclass Builder:\n    @final\n    def fluent(self) -> 'Builder': return self\n"
        )
        name, code = "Builder", "SARJ078"
        setup = (
            "def replacement(self: Builder) -> Builder: return Builder()\n"
            "def change(owner: type[Builder]) -> type[object]:\n"
            "    owner.fluent = replacement\n    return object\n"
        )
    else:
        target.write_text(
            "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    value: int\n"
            "    @model_validator(mode='before')\n    @classmethod\n"
            "    def clean(cls, data: dict[str, object]) -> dict[str, object]:\n"
            "        data.pop('legacy', None)\n        return data\n"
        )
        name, code = "Record", "SARJ482"
        setup = (
            "def change(owner: type[Record]) -> type[object]:\n"
            "    owner.__pydantic_decorators__.model_validators.clear()\n"
            "    owner.model_rebuild(force=True)\n    return object\n"
        )
    ambiguous = context in {
        "base-call",
        "annotation-call",
        "base-subscription",
        "annotation-subscription",
        "shadowed-type",
        "wildcard-type",
        "wildcard-typing",
        "mutated-typing",
        "escaped-typing",
        "method-mutated-typing",
        "dict-mutated-typing",
        "nested-mutated-typing",
        "cross-unit-mutated-typing",
        "cross-unit-named-provider",
        "cross-unit-qualified-provider",
    }
    expected = [Severity.ERROR]
    if ambiguous:
        expected = [Severity.WARNING] if kind == "fluent-method" else []
    sibling = package / "sibling.py"
    sibling.write_text(_type_context_peer(name, context, setup))
    if context.startswith("wildcard"):
        (package / "foreign.py").write_text("from .sibling import registry\ntype = registry\nDict = registry\n")
    if context.startswith("cross-unit"):
        _write_cross_unit_provider(package, kind, context)
    diagnostics = analyze(
        [
            "prefer-self-type-annotation",
            "no-before-validator-input-mutation",
            "require-explicit-contract-implementation",
        ],
        [target] if target_only else [target, sibling],
    )
    assert [finding.severity for finding in diagnostics if finding.path == target and finding.code == code] == expected


def _type_context_peer(name: str, context: str, setup: str) -> str:
    if context.startswith("cross-unit"):
        return (
            f"from . import patch\nfrom .owned import {name}\nimport typing as t\nclass Other(t.Dict[{name}]): pass\n"
        )
    if context in {
        "mutated-typing",
        "escaped-typing",
        "method-mutated-typing",
        "dict-mutated-typing",
        "nested-mutated-typing",
    }:
        return _provider_type_context_peer(name, context, setup)
    expression = name
    if context.endswith("call"):
        expression = f"change({name})"
    elif context.endswith("subscription") or context == "shadowed-type" or context.startswith("wildcard"):
        setup += (
            f"class Registry:\n    def __getitem__(self, owner: type[{name}]) -> type[object]:\n"
            "        return change(owner)\nregistry = Registry()\n"
        )
        if context.startswith("wildcard"):
            setup += "from typing import Dict\nfrom .foreign import *\n"
            expression = f"Dict[{name}]" if context == "wildcard-typing" else f"type[{name}]"
        elif context == "shadowed-type":
            setup += "type = registry\n"
            expression = f"type[{name}]"
        else:
            expression = f"registry[{name}]"
    elif context == "type-annotation":
        expression = f"type[{name}]"
    elif context == "dict-annotation":
        expression = f"dict[str, {name}]"
    elif context == "typing-annotation":
        setup += "import typing as t\n"
        expression = f"t.Sequence[{name}]"
    use = (
        f"class Other({expression}): pass\n"
        if context.startswith("base") or context == "plain-base"
        else f"def marker() -> {expression}: pass\n"
    )
    return f"from .owned import {name}\n" + setup + use


def _write_cross_unit_provider(package: Path, kind: str, context: str) -> None:
    operation = (
        "        owner.fluent = lambda self: owner()\n"
        if kind == "fluent-method"
        else "        owner.__pydantic_decorators__.model_validators.clear()\n        owner.model_rebuild(force=True)\n"
    )
    import_source = "import typing as t\n"
    setter = "t.Dict = Registry()\n"
    if context.endswith("provider"):
        (package / "providers.py").write_text("import typing as t\n")
        if context == "cross-unit-named-provider":
            import_source = "from .providers import t\n"
        else:
            import_source = "import app.providers as provider\n"
            setter = "provider.t.Dict = Registry()\n"
    (package / "patch.py").write_text(
        import_source
        + "class Registry:\n    def __getitem__(self, owner):\n"
        + operation
        + "        return object\n"
        + setter
    )


def _provider_type_context_peer(name: str, context: str, setup: str) -> str:
    setup += (
        "import typing as t\n"
        f"class Registry:\n    def __getitem__(self, owner: type[{name}]) -> type[object]:\n"
        "        return change(owner)\nregistry = Registry()\n"
    )
    match context:
        case "mutated-typing":
            setup += "t.Dict = registry\n"
        case "method-mutated-typing":
            setup += "t.__setattr__('Dict', registry)\n"
        case "dict-mutated-typing":
            setup += "t.__dict__['Dict'] = registry\n"
        case "nested-mutated-typing":
            setup += "def configure():\n    import typing as nested\n    nested.Dict = registry\nconfigure()\n"
        case _:
            setup += "def configure(module): module.Dict = registry\nconfigure(t)\n"
    return f"from .owned import {name}\n" + setup + f"class Other(t.Dict[{name}]): pass\n"
