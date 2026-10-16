from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._type_guard_symbols import guard_symbols_ambiguous, unique_guard_function_names
from sarj_python_lint.rules.no_contradictory_type_guard import NoContradictoryTypeGuard
from sarj_python_lint.rules.no_partial_type_is import NoPartialTypeIs
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


_CASES = (
    (
        NoContradictoryTypeGuard,
        (
            "from typing import TypeGuard\n"
            "def identifies(value: object) -> TypeGuard[str]:\n"
            "    return isinstance(value, int)\n"
        ),
    ),
    (
        NoPartialTypeIs,
        (
            "from typing import TypeIs\n"
            "def identifies(value: object) -> TypeIs[int]:\n"
            "    return isinstance(value, int) and value > 0\n"
        ),
    ),
    (
        NoShallowContainerTypeGuard,
        (
            "from typing import TypeGuard\n"
            "def identifies(value: object) -> TypeGuard[list[str]]:\n"
            "    return isinstance(value, list)\n"
        ),
    ),
)

_NATIVE_NAMESPACE_NAMES = (
    "__build_class__",
    "__import__",
    "__lazy_import__",
    "abs",
    "aiter",
    "all",
    "anext",
    "any",
    "ascii",
    "bin",
    "breakpoint",
    "callable",
    "chr",
    "compile",
    "delattr",
    "dir",
    "divmod",
    "eval",
    "exec",
    "format",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "hex",
    "id",
    "input",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "locals",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "print",
    "repr",
    "round",
    "setattr",
    "sorted",
    "sum",
    "vars",
)


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("module", ["builtins", "typing", "typing_extensions"])
@pytest.mark.parametrize("mutation", ["native.__class__ = Custom", "del native.__class__"])
def test_module_class_replacement_invalidates_namespace_identity(
    rule_type: type[Rule], source: str, module: str, mutation: str
) -> None:
    changed = f"import {module} as native\n{mutation}\n" + source
    assert rule_type().check(Path("app/guards.py"), changed) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("module", ["builtins", "typing", "typing_extensions"])
@pytest.mark.parametrize(
    "rebinding",
    [
        "if condition:\n    native = alternate\n",
        "def configure(value=(native := alternate)):\n    pass\n",
        "import other as native\n",
    ],
)
def test_rebound_namespace_imports_remain_ambiguous(
    rule_type: type[Rule], source: str, module: str, rebinding: str
) -> None:
    changed = f"import {module} as native\n{rebinding}" + source
    assert rule_type().check(Path("app/guards.py"), changed) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("module", ["builtins", "typing", "typing_extensions"])
def test_stable_namespace_import_and_class_read_preserve_diagnostics(
    rule_type: type[Rule], source: str, module: str
) -> None:
    unchanged = f"import {module} as native\nnamespace_type = native.__class__\n" + source
    assert len(rule_type().check(Path("app/guards.py"), unchanged)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("unicode_guard", [False, True])
def test_canonical_guard_import_aliases_survive_normalized_prefilters(
    rule_type: type[Rule], source: str, unicode_guard: bool
) -> None:
    canonical = "TypeIs" if "TypeIs" in source else "TypeGuard"
    imported = {"TypeGuard": "ＴｙｐｅＧｕａｒｄ", "TypeIs": "ＴｙｐｅＩｓ"}[canonical] if unicode_guard else canonical
    aliased = source.replace(f"import {canonical}", f"import {imported} as Guard").replace(
        f"-> {canonical}[", "-> Guard["
    )
    assert len(rule_type().check(Path("app/guards.py"), aliased)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("module", ["builtins", "typing", "typing_extensions"])
@pytest.mark.parametrize("alias", ["", " as namespace"])
@pytest.mark.parametrize("capability", ["__dict__", "__builtins__", "__getattribute__", "__setattr__", "__delattr__"])
def test_direct_namespace_capability_import_invalidates_identity(
    rule_type: type[Rule], source: str, module: str, alias: str, capability: str
) -> None:
    changed = f"from {module} import {capability}{alias}\n" + source
    assert rule_type().check(Path("app/guards.py"), changed) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("module", ["math", ".domain"])
def test_unrelated_namespace_dictionary_import_preserves_diagnostics(
    rule_type: type[Rule], source: str, module: str
) -> None:
    unchanged = f"from {module} import __dict__ as namespace\n" + source
    assert len(rule_type().check(Path("app/guards.py"), unchanged)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("function", _NATIVE_NAMESPACE_NAMES)
@pytest.mark.parametrize("form", ["bare", "module", "import-alias"])
def test_builtin_bound_namespace_identity_excludes_guards(
    rule_type: type[Rule], source: str, function: str, form: str
) -> None:
    prefix, name = {
        "bare": ("", function),
        "module": ("import builtins as native\n", f"native.{function}"),
        "import-alias": (f"from builtins import {function} as native_check\n", "native_check"),
    }[form]
    changed = prefix + f"namespace = {name}.__self__\n" + source
    assert rule_type().check(Path("app/guards.py"), changed) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("function", _NATIVE_NAMESPACE_NAMES)
def test_native_function_value_escape_invalidates_namespace_proof(
    rule_type: type[Rule], source: str, function: str
) -> None:
    changed = f"native_function = {function}\n" + source
    assert rule_type().check(Path("app/guards.py"), changed) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize(
    "function",
    [
        name
        for name in _NATIVE_NAMESPACE_NAMES
        if name not in {"__import__", "__lazy_import__", "eval", "exec", "globals", "locals", "vars"}
    ],
)
def test_imported_native_function_direct_call_preserves_proof(
    rule_type: type[Rule], source: str, function: str
) -> None:
    changed = (
        f"from builtins import {function} as native_call\ndef separate(value):\n    return native_call(value)\n"
        + source
    )
    assert len(rule_type().check(Path("app/guards.py"), changed)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize(
    "prefix", ["namespace = application_check.__self__\n", "from app import len as local\nnamespace = local.__self__\n"]
)
def test_application_bound_method_reference_does_not_erase_guard_diagnostics(
    rule_type: type[Rule], source: str, prefix: str
) -> None:
    assert len(rule_type().check(Path("app/guards.py"), prefix + source)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("member", ["field", "repr"])
def test_deep_unrelated_attribute_chains_preserve_guard_diagnostics(
    rule_type: type[Rule], source: str, member: str
) -> None:
    chain = f".{member}" * 2000
    unrelated = f"def inspect_record(value):\n    return value{chain}\n"
    assert len(rule_type().check(Path("app/guards.py"), unrelated + source)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
def test_deep_native_attribute_chain_retains_the_inner_namespace_escape(rule_type: type[Rule], source: str) -> None:
    chain = ".__call__.__self__" * 1000 + ".__self__"
    escaped = f"import builtins as native\nnamespace = native.repr{chain}\n"
    assert rule_type().check(Path("app/guards.py"), escaped + source) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize("function", _NATIVE_NAMESPACE_NAMES)
@pytest.mark.parametrize(
    "form", ["bare-local", "import-alias-local", "module-alias-local", "bare-later", "import-alias-later"]
)
def test_native_function_binding_ambiguity_preserves_the_possible_namespace_escape(
    rule_type: type[Rule], source: str, function: str, form: str
) -> None:
    prefix = {
        "bare-local": f"def unrelated({function}): pass\nnamespace = {function}.__self__\n",
        "import-alias-local": f"from builtins import {function} as native\ndef unrelated(native): pass\nnamespace = native.__self__\n",
        "module-alias-local": f"import builtins as native\ndef unrelated(native): pass\nnamespace = native.{function}.__self__\n",
        "bare-later": f"namespace = {function}.__self__\n{function} = replacement\n",
        "import-alias-later": f"from builtins import {function} as native\nnamespace = native.__self__\nnative = replacement\n",
    }[form]
    assert rule_type().check(Path("app/guards.py"), prefix + source) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
def test_unrelated_local_application_alias_preserves_guard_diagnostics(rule_type: type[Rule], source: str) -> None:
    prefix = "from app import repr as application\ndef unrelated(application): pass\nnamespace = application.__self__\n"
    assert len(rule_type().check(Path("app/guards.py"), prefix + source)) == 1


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize(
    "prefix",
    [
        'namespace = __lazy_import__("builtins")\n',
        'from builtins import __lazy_import__ as lazy\nnamespace = lazy("builtins")\n',
        'import builtins as native\nnamespace = native.__lazy_import__("builtins")\n',
        'from builtins import __lazy_import__ as lazy\ndef unrelated(lazy): pass\nnamespace = lazy("builtins")\n',
        'namespace = __lazy_import__("builtins")\n__lazy_import__ = replacement\n',
        'import builtins as native\ndef unrelated(native): pass\nnamespace = native.__lazy_import__("builtins")\n',
    ],
)
def test_native_lazy_import_call_withdraws_namespace_proof(rule_type: type[Rule], source: str, prefix: str) -> None:
    assert rule_type().check(Path("app/guards.py"), prefix + source) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize(
    "prefix",
    [
        'from app import __lazy_import__ as application\nnamespace = application("name")\n',
        'import app as application\nnamespace = application.__lazy_import__("name")\n',
    ],
)
def test_nonbuiltin_lazy_import_alias_preserves_diagnostics(rule_type: type[Rule], source: str, prefix: str) -> None:
    assert len(rule_type().check(Path("app/guards.py"), prefix + source)) == 1


@pytest.mark.skipif(sys.version_info < (3, 15), reason="Native lazy import was introduced in CPython3.15")
@pytest.mark.parametrize(
    "prefix",
    [
        'namespace = __lazy_import__("builtins")\n',
        'from builtins import __lazy_import__ as lazy\nnamespace = lazy("builtins")\n',
        'import builtins as native\nnamespace = native.__lazy_import__("builtins")\n',
    ],
)
def test_lazy_import_really_returns_a_mutable_builtin_namespace(prefix: str) -> None:
    source = (
        "from typing import TypeGuard\n"
        + prefix
        + "namespace.int = str\ndef identifies(value: object) -> TypeGuard[str]:\n"
        + '    return isinstance(value, int)\nprint((identifies("text"), identifies(1)))\n'
    )
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, check=True, text=True, timeout=10)
    assert result.stdout.strip() == "(True, False)"
    assert NoContradictoryTypeGuard().check(Path("app/guards.py"), source) == []


_INTERCEPTED_ATTRIBUTE = """from typing import TypeGuard
import builtins as native
from types import ModuleType

class Intercepted(ModuleType):
    def __getattribute__(self, name):
        return lambda value, kind: isinstance(value, str)

native.__class__ = Intercepted
def is_text(value: object) -> TypeGuard[str]:
    return native.isinstance(value, int)
try:
    observations = (is_text("text"), is_text(1))
finally:
    native.__class__ = ModuleType
print(observations)
"""

_REBOUND_MUTATION = """from typing import TypeGuard
import builtins as native
if False:
    native = None
original_check = isinstance
native.isinstance = lambda value, kind: original_check(value, str)
def is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
try:
    observations = (is_text("text"), is_text(1))
finally:
    native.isinstance = original_check
print(observations)
"""


_NAMESPACE_DICTIONARY = """from typing import TypeGuard
from builtins import __dict__ as namespace
original = isinstance
namespace["isinstance"] = lambda value, kind: original(value, str)
def is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
try:
    observations = (is_text("text"), is_text(1))
finally:
    namespace["isinstance"] = original
print(observations)
"""


_NAMESPACE_SETTER = """from typing import TypeGuard
from builtins import __setattr__ as mutate
original = isinstance
mutate("isinstance", lambda value, kind: original(value, str))
def is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
try:
    observations = (is_text("text"), is_text(1))
finally:
    mutate("isinstance", original)
print(observations)
"""

_NAMESPACE_GETTER = """from typing import TypeGuard
from builtins import __getattribute__ as lookup
original = isinstance
lookup("__dict__")["isinstance"] = lambda value, kind: original(value, str)
def is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
try:
    observations = (is_text("text"), is_text(1))
finally:
    lookup("__dict__")["isinstance"] = original
print(observations)
"""

_TYPING_BUILTINS = _NAMESPACE_DICTIONARY.replace(
    "from builtins import __dict__ as namespace", "from typing import __builtins__ as namespace"
)

_BUILTIN_SELF = _NAMESPACE_DICTIONARY.replace(
    "from builtins import __dict__ as namespace", "namespace = isinstance.__self__"
).replace('namespace["isinstance"]', "namespace.isinstance")

_REPR_SELF = """from typing import TypeGuard
namespace = repr.__self__
namespace.isinstance = lambda value, kind: type(value) is str
def is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
print((is_text("text"), is_text(1)))
"""

_DISCARDED_NATIVE_ALIAS = """from typing import TypeGuard
from builtins import repr as native
def unrelated(native: object): pass
native.__self__.int = str
def identifies(value: object) -> TypeGuard[str]:
    return isinstance(value, int)
print((identifies("text"), identifies(1)))
"""

_DISCARDED_BARE_NATIVE = _DISCARDED_NATIVE_ALIAS.replace("from builtins import repr as native\n", "").replace(
    "native", "repr"
)


@pytest.mark.parametrize(
    "source",
    [
        _INTERCEPTED_ATTRIBUTE,
        _REBOUND_MUTATION,
        _NAMESPACE_DICTIONARY,
        _NAMESPACE_SETTER,
        _NAMESPACE_GETTER,
        _TYPING_BUILTINS,
        _BUILTIN_SELF,
        _REPR_SELF,
        _DISCARDED_NATIVE_ALIAS,
        _DISCARDED_BARE_NATIVE,
        pytest.param(
            _DISCARDED_BARE_NATIVE.replace("def unrelated(repr: object): pass\n", "").replace(
                "repr.__self__.int = str", "repr.__self__.int = str\nrepr = object()"
            ),
            id="builtin-escape-before-module-rebind",
        ),
        pytest.param(
            _REPR_SELF.replace("namespace = repr.__self__", "function = repr\nnamespace = function.__self__"),
            id="native-function-alias-namespace",
        ),
        pytest.param(
            _REPR_SELF.replace("repr.__self__", "repr.__call__.__self__.__self__"), id="native-function-dunder-chain"
        ),
        pytest.param(_BUILTIN_SELF.replace("isinstance.__self__", "len.__self__"), id="len-bound-native-namespace"),
        pytest.param(
            _NAMESPACE_DICTIONARY.replace(" as namespace", "").replace("namespace[", "__dict__["),
            id="unaliased-builtins-namespace-dictionary",
        ),
    ],
)
def test_namespace_changes_can_make_the_apparent_contradiction_a_valid_predicate(source: str) -> None:
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, check=True, text=True, timeout=10)
    assert result.stdout.strip() == "(True, False)"
    assert NoContradictoryTypeGuard().check(Path("app/guards.py"), source) == []


@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
@pytest.mark.parametrize("mutation", ["native.Literal = Custom", "del native.Literal"])
def test_additional_typing_symbol_mutations_are_opt_in(module: str, mutation: str) -> None:
    source = f"import {module} as native\n{mutation}\n"
    context = PythonFileContext(Path("app/guards.py"), source)
    assert not guard_symbols_ambiguous(context, frozenset({"str", "object"}))
    assert guard_symbols_ambiguous(
        context, frozenset({"str", "object"}), typing_symbols=frozenset({"TypeIs", "Literal"})
    )


@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
def test_additional_typing_symbol_alias_keeps_canonical_identity(module: str) -> None:
    source = f"from {module} import Literal as Choice\nimport {module} as native\n"
    context = PythonFileContext(Path("app/guards.py"), source)
    assert not guard_symbols_ambiguous(
        context, frozenset({"str", "object"}), typing_symbols=frozenset({"TypeIs", "Literal"})
    )


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
@pytest.mark.parametrize(
    "prefix",
    [
        "def identifies(value): ...\n",
        "async def identifies(value): ...\n",
        "if TYPE_CHECKING:\n    def identifies(value): ...\n",
        "try:\n    pass\nexcept Error:\n    def identifies(value): ...\n",
    ],
)
def test_repeated_function_names_preserve_public_contracts(rule_type: type[Rule], source: str, prefix: str) -> None:
    assert rule_type().check(Path("app/guards.py"), prefix + source) == []


@pytest.mark.parametrize(("rule_type", "source"), _CASES)
def test_unrelated_repeated_names_do_not_hide_the_guard(rule_type: type[Rule], source: str) -> None:
    prefix = "def other(value): ...\ndef other(value): ...\n"
    assert len(rule_type().check(Path("app/guards.py"), prefix + source)) == 1


def test_uniqueness_requires_a_valid_module_and_ignores_nested_names() -> None:
    valid = PythonFileContext(Path("app/guards.py"), "def identifies(value):\n    def identifies(): ...\n")
    assert unique_guard_function_names(valid) == frozenset({"identifies"})
    malformed = PythonFileContext(Path("app/guards.py"), "def broken(")
    assert unique_guard_function_names(malformed) == frozenset()
