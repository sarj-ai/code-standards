from __future__ import annotations

import ast
from pathlib import Path
import symtable
from types import MappingProxyType
from typing import TYPE_CHECKING
import weakref

import pytest

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint._fixes import apply_fixes
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._binding_inventory import BindingInventory
from sarj_python_lint.rules._closed_helpers import stable_class
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


def test_binding_inventory_and_runtime_tables_are_built_once_per_file(monkeypatch: pytest.MonkeyPatch) -> None:
    context = PythonFileContext(Path("app.py"), 'import re as runtime\npattern = runtime.compile("value")\n')
    inventory_builds = 0
    symbol_table_builds = 0
    build_inventory = BindingInventory.from_context
    build_symbol_table = symtable.symtable

    def counted_inventory(context: PythonFileContext) -> BindingInventory:
        nonlocal inventory_builds
        inventory_builds += 1
        return build_inventory(context)

    def counted_symbol_table(code: str, filename: str, compile_type: str) -> symtable.SymbolTable:
        nonlocal symbol_table_builds
        symbol_table_builds += 1
        return build_symbol_table(code, filename, compile_type)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the real lazy factory; injecting facts would bypass the construction-count contract.
        BindingInventory, "from_context", counted_inventory
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count actual compiler symbol-table work while preserving its results; a fake runtime provider would bypass it.
        symtable, "symtable", counted_symbol_table
    )
    assert "binding_inventory" not in vars(context)
    ordinary = context.resource_provenance
    static = context.static_resource_provenance
    direct = ResourceProvenance(context)
    assert inventory_builds == 1
    assert symbol_table_builds == 0
    assert ordinary.inventory is static.inventory is direct.inventory is context.binding_inventory
    assert ordinary.bindings is static.bindings is context.binding_inventory.bindings
    assert ordinary.reads is static.reads is context.binding_inventory.reads
    assert ordinary.runtime_bindings is static.runtime_bindings is direct.runtime_bindings
    assert ordinary.runtime_bindings is context.runtime_bindings
    assert symbol_table_builds == 1


def test_binding_inventory_containers_are_immutable_and_policy_caches_stay_separate() -> None:
    context = PythonFileContext(Path("app.py"), "import re as runtime\nruntime.custom = provider\n")
    inventory = context.binding_inventory
    ordinary, static = context.resource_provenance, context.static_resource_provenance
    assert isinstance(inventory.bindings, MappingProxyType)
    assert all(isinstance(names, MappingProxyType) for names in inventory.bindings.values())
    assert all(isinstance(sites, tuple) for names in inventory.bindings.values() for sites in names.values())
    assert isinstance(inventory.reads, MappingProxyType)
    assert all(isinstance(reads, tuple) for reads in inventory.reads.values())
    assert inventory.mutated == frozenset({"runtime"})
    assert isinstance(inventory.external_bindings, frozenset)
    assert ordinary.escape_cache is not static.escape_cache
    assert ordinary.async_contract_cache is not static.async_contract_cache
    assert ordinary.import_contract_cache is not static.import_contract_cache
    assert ordinary.runtime_import_cache is not static.runtime_import_cache
    # A consumer may refine its mutation policy without changing another provider's facts.
    ordinary.mutated.clear()
    assert inventory.mutated == frozenset({"runtime"})
    assert static.mutated == {"runtime"}


@pytest.mark.parametrize("static_first", [False, True])
@pytest.mark.parametrize("reverse_rules", [False, True])
@pytest.mark.parametrize("expected_match", [False, True], ids=("no-match", "match"))
@pytest.mark.parametrize(
    "rule_id",
    [
        "async-cleanup-registered-synchronously",
        "no-swallowed-asyncio-cancellation",
        "prefer-direct-import-module",
        "duplicate-closed-pure-helper",
        "prefer-required-constructor-parameters",
        "no-redundant-local-alias",
        "prefer-str-enum",
        "no-repeated-structured-string-literal",
    ],
)
def test_shared_inventory_preserves_diagnostics_in_provider_and_rule_orders(
    rule_id: RuleId,
    *,
    static_first: bool,
    reverse_rules: bool,
    expected_match: bool,
) -> None:
    selected = (
        "async-cleanup-registered-synchronously",
        "no-swallowed-asyncio-cancellation",
        "prefer-direct-import-module",
        "duplicate-closed-pure-helper",
        "prefer-required-constructor-parameters",
        "no-redundant-local-alias",
        "prefer-str-enum",
        "no-repeated-structured-string-literal",
    )
    rules = [REGISTRY[rule_id]() for rule_id in selected]
    rule = REGISTRY[rule_id]()
    example = next(
        example
        for example in rule.public_examples()
        if len(example.files) == 1 and bool(example.expected_count) is expected_match
    )
    path, source = Path(example.focus_path), example.focus_file.source
    assert len(rule.check(path, source)) == example.expected_count
    expected = sorted(finding.format() for item in rules for finding in item.check(path, source))
    context = PythonFileContext(path, source)
    first = context.static_resource_provenance if static_first else context.resource_provenance
    second = context.resource_provenance if static_first else context.static_resource_provenance
    assert first.inventory is second.inventory
    ordered = list(reversed(rules)) if reverse_rules else rules
    actual = sorted(finding.format() for item in ordered for finding in item.check_context(context))
    assert actual == expected


@pytest.mark.parametrize("nonlocal_scope", [False, True], ids=("global", "nonlocal"))
@pytest.mark.parametrize("write", [False, True], ids=("read-only-declaration", "external-write"))
def test_shared_runtime_bindings_preserve_external_write_boundaries(*, nonlocal_scope: bool, write: bool) -> None:
    declaration = "nonlocal" if nonlocal_scope else "global"
    source = f"import re as runtime\ndef use():\n    {declaration} runtime\n    return runtime.compile('value')\n"
    if write:
        source += f"def change():\n    {declaration} runtime\n    runtime = provider\n"
    if nonlocal_scope:
        source = "def outer():\n" + "\n".join(f"    {line}" for line in source.splitlines()) + "\n"
    context = PythonFileContext(Path("app.py"), source)
    reference = context.nodes(ast.Call)[0].func
    assert context.binding_inventory.external_bindings == frozenset({"runtime"})
    for provenance in (context.resource_provenance, context.static_resource_provenance):
        assert provenance.runtime_import_name(reference) == (None if write else "re.compile")
        binding = provenance.runtime_binding("runtime", reference)
        assert (binding is None) is write
        if not write:
            assert isinstance(binding, ast.alias)
            assert binding.name == "re"


@pytest.mark.parametrize(
    ("statement", "bindings"),
    [
        ("[(close := synchronous) for _ in values]", 2),
        ("{(close := synchronous) for _ in values}", 2),
        ("{key: (close := synchronous) for key in values}", 2),
        ("tuple((close := synchronous) for _ in values)", 2),
        ("[[(close := synchronous) for _ in values] for _ in values]", 2),
        ("[close for close in values]", 1),
        ("[lambda: (close := synchronous) for _ in values]", 1),
    ],
    ids=("list", "set", "dict", "generator", "nested", "iteration-local", "lambda-local"),
)
def test_inventory_keeps_comprehension_walrus_and_local_bindings_distinct(statement: str, bindings: int) -> None:
    source = f"async def close():\n    await finish()\n{statement}\nclose()\n"
    context = PythonFileContext(Path("app.py"), source)
    tree = context.tree
    assert tree is not None
    assert len(context.binding_inventory.bindings[tree]["close"]) == bindings
    reference = max(context.nodes(ast.Call), key=lambda call: call.lineno)
    for provenance in (context.resource_provenance, context.static_resource_provenance):
        binding = provenance.binding("close", reference)
        assert isinstance(binding, ast.AsyncFunctionDef) is (bindings == 1)


@pytest.mark.parametrize("static_first", [False, True])
def test_shared_alias_inventory_preserves_scope_shadowing_and_import_equivalence(*, static_first: bool) -> None:
    source = (
        "import re as runtime\n"
        "import re as runtime\n"
        "def outer():\n"
        "    return runtime.compile('outer')\n"
        "def local():\n"
        "    from re import compile as runtime\n"
        "    return runtime('local')\n"
        "def shadowed(runtime):\n"
        "    return runtime.compile('shadowed')\n"
        "def ambiguous():\n"
        "    import re as runtime\n"
        "    import sys as runtime\n"
        "    return runtime.compile('ambiguous')\n"
    )
    context = PythonFileContext(Path("app.py"), source)
    providers = (
        (context.static_resource_provenance, context.resource_provenance)
        if static_first
        else (context.resource_provenance, context.static_resource_provenance)
    )
    calls = sorted(context.nodes(ast.Call), key=lambda call: call.lineno)
    for provenance in providers:
        module_binding, local_binding, parameter_binding, ambiguous_binding = (
            provenance.runtime_binding("runtime", call.func) for call in calls
        )
        assert isinstance(module_binding, ast.alias)
        assert module_binding.name == "re"
        assert isinstance(local_binding, ast.alias)
        assert local_binding.name == "compile"
        assert isinstance(parameter_binding, ast.arg)
        assert parameter_binding.arg == "runtime"
        assert ambiguous_binding is None
        # The static policy abstains for this dynamic namespace while retaining scoped bindings.
        assert provenance.dynamic_namespace is provenance.require_static_namespace
        expected = ["re.compile", "re.compile", None, None]
        if provenance.require_static_namespace:
            expected = [None, None, None, None]
        assert [provenance.runtime_import_name(call.func) for call in calls] == expected


def test_class_uniqueness_consumers_accept_inventory_tuples() -> None:
    context = PythonFileContext(Path("app.py"), "class Record:\n    pass\n")
    [declaration] = context.nodes(ast.ClassDef)
    assert stable_class(context, declaration, context.resource_provenance)
    rebound = PythonFileContext(Path("app.py"), "class Record:\n    pass\nRecord = provider\n")
    [declaration] = rebound.nodes(ast.ClassDef)
    assert not stable_class(rebound, declaration, rebound.resource_provenance)


@pytest.mark.parametrize("static_first", [False, True])
def test_shared_inventory_preserves_local_alias_diagnostics_and_safe_fixes(*, static_first: bool) -> None:
    path = Path("app/records.py")
    source = "def render(item):\n    payload = item\n    return dict(payload=payload)\n"
    expected = source.replace("    payload = item\n", "").replace("payload=payload", "payload=item")
    context = PythonFileContext(path, source)
    if static_first:
        assert context.static_resource_provenance.inventory is context.binding_inventory
    rule = REGISTRY["no-redundant-local-alias"]()
    [finding] = rule.check_context(context)
    assert finding.code == "SARJ531"
    assert finding.fixes
    assert apply_fixes(source, finding.fixes) == expected
    assert fix_source(path, source, rule_ids=[rule.id]) == expected
    assert rule.check(path, expected) == []
    assert fix_source(path, expected, rule_ids=[rule.id]) == expected


@pytest.mark.parametrize("rule_id", ["prefer-str-enum", "no-repeated-structured-string-literal"])
def test_existing_autofix_builders_accept_inventory_tuples(rule_id: RuleId) -> None:
    rule = REGISTRY[rule_id]()
    documentation = rule.documentation
    assert documentation is not None
    example = next(example for example in documentation.examples if example.fixed_files)
    path, source = Path(example.focus_path), example.focus_file.source
    expected = next(file.source for file in example.fixed_files if file.path == example.focus_path)
    context = PythonFileContext(path, source)
    assert context.resource_provenance.inventory is context.static_resource_provenance.inventory
    assert len(rule.check_context(context)) == example.expected_count
    assert fix_source(path, source, rule_ids=[rule.id]) == expected
    assert rule.check(path, expected) == []
    assert fix_source(path, expected, rule_ids=[rule.id]) == expected


def test_retained_inventory_and_shared_runtime_tables_do_not_retain_the_file_context() -> None:
    context = PythonFileContext(Path("app.py"), 'import re\npattern = re.compile("value")\n')
    inventory = context.binding_inventory
    ordinary, static = context.resource_provenance, context.static_resource_provenance
    runtime = ordinary.runtime_bindings
    assert runtime is static.runtime_bindings
    context_ref = weakref.ref(context)
    del context  # sarj-noqa: SARJ442 -- retained immutable facts and borrowed providers must release their owner.
    assert context_ref() is None
    assert inventory.bindings
    assert runtime.module is not None
    for provenance in (ordinary, static):
        with pytest.raises(ReferenceError, match="file context has been released"):
            provenance.context.nodes(ast.AST)
