from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_keyword_only_swap_prone_params import RequireKeywordOnlySwapProneParams


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "python/app/app/calls/service.py") -> list[Diagnostic]:
    return RequireKeywordOnlySwapProneParams().check(Path(path), source)


_PUBLIC_EXAMPLES = RequireKeywordOnlySwapProneParams.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


# Positive: >=2 positional params sharing one primitive annotation.            #


@pytest.mark.parametrize(
    ("params", "primitive"),
    [
        ("source_id: str, target_id: str", "str"),
        ("parent_id: int, child_id: int", "int"),
        ("old_score: float, new_score: float", "float"),
        ("user_id: str, org_id: str, label: int", "str"),
        ("src_key: str, dst_key: str, c: int", "str"),
    ],
)
def test_flags_same_primitive_positionals(params: str, primitive: str):
    src = f"def f({params}) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ034"
    assert f"`{primitive}`" in diags[0].message
    assert "`f`" in diags[0].message


def test_positional_booleans_are_owned_by_ruff_fbt001() -> None:
    src = "def run(dry_run: bool, force: bool) -> None: ...\n"
    assert _check(src) == []


def test_flags_async_def():
    src = "async def move(src_key: str, dst_key: str) -> None: ...\n"
    assert len(_check(src)) == 1


def test_flags_method_excluding_self():
    src = """
class Store:
    def link(self, parent_id: str, child_id: str) -> None: ...
"""
    assert len(_check(src)) == 1


def test_allows_method_on_subclass_that_may_implement_an_inherited_contract() -> None:
    src = """
class Store(BaseStore):
    def link(self, parent_id: str, child_id: str) -> None: ...
"""
    assert _check(src) == []


def test_flags_classmethod_excluding_cls():
    src = """
class Store:
    @classmethod
    def build(cls, old_key: str, new_key: str) -> "Store": ...
"""
    assert len(_check(src)) == 1


def test_flags_with_defaults():
    src = "def f(source_id: str, target_id: str = 'x') -> None: ...\n"
    assert len(_check(src)) == 1


def test_one_diagnostic_per_function():
    src = "def f(source_id: str, target_id: str, old_key: int, new_key: int) -> None: ...\n"
    assert len(_check(src)) == 1


# Negative: fewer than two shared primitives.                                  #


@pytest.mark.parametrize(
    "params",
    [
        "a: str, b: int",
        "a: str",
        "a: str, b: bytes",
        "a: int, b: float",
        "",
        "a, b",
        "a: str, b",
        "a: int, b: int",
        "a: str, b: str, c: int",
        "base: int, exponent: int",
    ],
)
def test_allows_distinct_or_missing_annotations(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "params",
    [
        "lat: float, lon: float, alt: float",
        "left: int, right: int",
        "lo: int, hi: int",
        "low: float, high: float",
        "source: int, sink: int",
    ],
)
def test_allows_conventional_algorithm_or_coordinate_pairs(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


def test_self_does_not_count():
    src = """
class T:
    def f(self, a: str) -> None: ...
"""
    assert _check(src) == []


# Negative: non-primitive / non-bare-Name annotations never group.             #


@pytest.mark.parametrize(
    "params",
    [
        "a: Money, b: Money",
        "a: UserId, b: UserId",
        "a: str | None, b: str | None",
        "a: Optional[str], b: Optional[str]",
        "a: list[str], b: list[str]",
        "a: Any, b: Any",
        'a: "str", b: "str"',
        "a: Literal['x'], b: Literal['x']",
    ],
)
def test_allows_non_primitive_annotations(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


# Negative: exempt names and decorators.                                       #


@pytest.mark.parametrize(
    "name",
    ["__eq__", "__setitem__", "visit_Call", "visit_node", "test_transfer"],
)
def test_allows_exempt_names(name: str):
    src = f"def {name}(a: str, b: str) -> None: ...\n"
    assert _check(src) == []


def test_flags_swap_prone_constructor_parameters() -> None:
    src = """
class Client:
    def __init__(self, auth_token: str, base_url: str) -> None: ...
"""
    assert len(_check(src)) == 1


def test_allows_constructor_that_forwards_the_inherited_signature() -> None:
    src = """
class Client(BaseClient):
    def __init__(self, auth_token: str, base_url: str) -> None:
        super().__init__(auth_token, base_url)
"""
    assert _check(src) == []


@pytest.mark.parametrize("variadic", ["*args", "**kwargs"])
def test_allows_variadic_constructor_that_may_forward_an_inherited_signature(variadic: str) -> None:
    src = f"""
class Client(BaseClient):
    def __init__(self, auth_token: str, base_url: str, {variadic}) -> None: ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "override",
        "typing.override",
        "overload",
        "typing.overload",
        "abstractmethod",
        "abc.abstractmethod",
    ],
)
def test_allows_exempt_decorators(decorator: str):
    src = f"""
class T:
    @{decorator}
    def f(self, a: str, b: str) -> None: ...
"""
    assert _check(src) == []


def test_non_exempt_decorator_still_fires():
    src = """
@retry(attempts=3)
def f(source_id: str, target_id: str) -> None: ...
"""
    assert len(_check(src)) == 1


# Negative: HTTP route handlers — FastAPI binds params by name.                #


@pytest.mark.parametrize(
    "decorator",
    [
        'app.get("/x")',
        'router.post("/calls/{call_id}")',
        'api.put("/x")',
        'router.patch("/x")',
        'app.delete("/x")',
        'router.head("/x")',
        'app.options("/x")',
        'router.websocket("/ws")',
        "router.get",
    ],
)
def test_allows_http_route_handlers(decorator: str):
    src = f"""
@{decorator}
async def handler(org_id: str, call_id: str) -> None: ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        'get("/x")',  # bare Name, not <name>.<method>
        'self.router.get("/x")',  # receiver is an attribute chain, not a Name
        'app.route("/x")',  # not an HTTP-method attribute
    ],
)
def test_non_route_shaped_decorators_still_fire(decorator: str):
    src = f"""
@{decorator}
def f(source_id: str, target_id: str) -> None: ...
"""
    assert len(_check(src)) == 1


# Negative: test files are exempt.                                             #


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_call_store.py",
        "test_helpers.py",
        "call_store_test.py",
        "python/app/tests/helpers/fakes.py",
        "conftest.py",
    ],
)
def test_skips_test_paths(path: str):
    src = "def fake_transfer(source_id: str, target_id: str) -> None: ...\n"
    assert _check(src, path) == []


def test_fires_in_non_test_paths():
    src = "def transfer(source_id: str, target_id: str) -> None: ...\n"
    assert len(_check(src, "python/app/app/calls/service.py")) == 1


# Marker position: `*` / `/` exempt exactly the params they protect.           #


@pytest.mark.parametrize(
    "params",
    [
        "a: str, *, b: str",  # only one swappable str
        "*, a: str, b: str",  # both keyword-only
        "a: str, b: str, /",  # both positional-only: deliberate API
        "a: str, /, b: str",  # one posonly + one swappable str
    ],
)
def test_allows_params_protected_by_markers(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "params",
    [
        # The same-type pair sits BEFORE the marker and stays swap-prone.
        "source_id: str, target_id: str, *, c: int",
        "source_id: str, target_id: str, *args",
        "x: int, /, source_id: str, target_id: str",
    ],
)
def test_flags_same_type_pair_before_marker(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert len(_check(src)) == 1


def test_kwargs_alone_is_not_a_marker():
    # **kwargs does not protect the positional params from swapping.
    src = "def f(source_id: str, target_id: str, **kwargs) -> None: ...\n"
    assert len(_check(src)) == 1


def test_lambda_never_flagged():
    assert _check("f = lambda a, b: a + b\n") == []


# Ordering, edge cases.                                                        #


def test_multiple_functions_sorted():
    src = """
def f(source_id: str, target_id: str) -> None: ...

def g(org_id: int, call_id: int) -> None: ...
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


def test_line_col_point_at_def():
    diags = _check("def f(source_id: str, target_id: str) -> None: ...\n")
    assert (diags[0].line, diags[0].col) == (1, 1)


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


# FP-hardening (famous-repo sweep): callback values, overload impls,           #
# generated files, symmetric numbering.                                        #


def test_function_referenced_as_value_is_exempt():
    # Minimized from attrs' fmt_setter family: the function is returned as a
    # value, so its signature is a callback protocol shared with other
    # implementations and cannot go keyword-only unilaterally.
    src = """
def _assign(attr_name: str, value: str, has_on_setattr: bool) -> str:
    return f"self.{attr_name} = {value}"

def _determine_setters(frozen: bool):
    return (), _assign
"""
    diags = _check(src)
    assert all("_assign" not in d.message for d in diags)


def test_function_registered_as_handler_is_exempt():
    # Minimized from trio's sphinx conf.py: the signature is pinned by the
    # framework that calls the handler.
    src = """
def autodoc_process_docstring(app, what: str, name: str, obj, options, lines) -> None:
    ...

def setup(app):
    app.connect("autodoc-process-docstring", autodoc_process_docstring)
"""
    assert _check(src) == []


def test_function_only_called_still_fires():
    src = """
def transfer(source_id: str, target_id: str) -> None: ...

def run():
    transfer("a", "b")
"""
    assert len(_check(src)) == 1


def test_nested_closure_still_fires():
    src = """
def build_comparator():
    def compare(old_key: str, new_key: str) -> bool:
        return old_key == new_key

    return compare("old", "new")
"""
    assert len(_check(src)) == 1


def test_overload_implementation_is_exempt():
    # Minimized from trio's _fake_net.getsockopt: the impl's positional shape
    # is pinned by its @overload stubs.
    src = """
from typing import overload

class Sock:
    @overload
    def getsockopt(self, level: int, optname: int) -> int: ...
    @overload
    def getsockopt(self, level: int, optname: int, buflen: int) -> bytes: ...
    def getsockopt(self, level: int, optname: int, buflen: int | None = None) -> int | bytes:
        raise OSError
"""
    assert _check(src) == []


def test_generated_file_is_exempt():
    # Minimized from trio's _generated_io_kqueue.py.
    src = (
        "# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******\n"
        "def monitor_kevent(ident: int, filter: int) -> None: ...\n"
    )
    assert _check(src) == []


def test_symmetric_numeric_suffix_params_are_exempt():
    src = "def same_policy(policy_id_1: str, policy_id_2: str) -> bool: ...\n"
    assert _check(src) == []


def test_symmetric_suffix_without_underscore_is_exempt():
    src = "def midpoint(x1: float, x2: float) -> float: ...\n"
    assert _check(src) == []


def test_distinct_stems_with_numbers_still_fire():
    src = "def link(node1_id: str, parent2_key: str) -> None: ...\n"
    assert len(_check(src)) == 1


# FP-hardening (famous-repo sweep, 2,657 files): signatures that CANNOT go     #
# keyword-only, and vocabularies where position is the notation.               #


@pytest.mark.parametrize(
    "name",
    ["seek", "read", "write", "readinto", "truncate", "recv", "setsockopt", "add_unredirected_header", "get_header"],
)
def test_duck_typed_stdlib_protocol_methods_are_exempt(name: str):
    # The stdlib is the caller and calls these POSITIONALLY (`io` does `f.seek(0, 2)`, `http.cookiejar` does `req.add_unredirected_header(k, v)`) so inserting `*` is a runtime TypeError, not a style change.
    src = f"""
class Stream:
    def {name}(self, first: int, second: int) -> int: ...
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["seek", "add_unredirected_header"])
def test_protocol_names_as_plain_functions_still_fire(name: str):
    # The exemption is for METHODS implementing a protocol — a module-level
    # function that merely shares the name owns its own calling convention.
    src = f"def {name}(source_id: int, target_id: int) -> int: ...\n"
    assert len(_check(src)) == 1


def test_super_call_proves_an_override_and_exempts():
    # Minimized from httpx `_models.py:1257`,
    # `_CookieCompatRequest(urllib.request.Request).add_unredirected_header`:
    # an override cannot narrow the base class's calling convention.
    src = """
class Child(Base):
    def register(self, old_key: str, new_key: str) -> None:
        super().register(key, value)
"""
    assert _check(src) == []


def test_subclass_method_is_exempt_even_when_its_super_call_has_another_name():
    src = """
class Child(Base):
    def register(self, old_key: str, new_key: str) -> None:
        super().__init__()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "click.command()",
        'click.option("--bind-host", type=str)',
        'click.argument("style")',
        "typer.Typer()",
        'main.command("comment-body")',
        "app.command()",
        "cli.group()",
    ],
)
def test_cli_command_handlers_are_exempt(decorator: str):
    # click/typer bind handler parameters by NAME from the declared options; the human call site is a shell command line.
    src = f"""
@{decorator}
def main(bind_host: str, cors_origin: str) -> None: ...
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        'command("x")',  # bare Name, not <name>.<attr>
        'obj.execute("x")',  # not a CLI-registration attribute
        'self.cli.command("x")',  # receiver is an attribute chain, not a Name
    ],
)
def test_non_cli_shaped_decorators_still_fire(decorator: str):
    src = f"""
@{decorator}
def f(source_id: str, target_id: str) -> None: ...
"""
    assert len(_check(src)) == 1


def test_pep484_positional_only_param_names_are_exempt():
    # Minimized from rich `_null_file.py:24`, `NullFile(IO[str]).seek`:
    # PEP 484 spells positional-only parameters `__x`, so they cannot be made
    # keyword-only at all.
    src = """
class NullFile:
    def scroll(self, __offset: int, __whence: int = 1) -> int: ...
"""
    assert _check(src) == []


def test_dunder_suffixed_param_names_are_not_positional_only():
    src = """
class T:
    def scroll(self, __source_id__: int, __target_id__: int) -> int: ...
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "params",
    [
        "x: int, y: int",  # rich/control.py:79 Control.move
        "x: int, y: int, z: int",
        "width: int, height: int",  # rich/segment.py:462 Segment.align_top
        "red: float, green: float, blue: float",  # rich/color.py:409 from_rgb
        "red: float, green: float, blue: float, alpha: float",
        "start: int = 0, step: int = 1",  # anyio/itertools.py:271 count
        "row: int, column: int",
        "top: int, right: int, bottom: int, left: int",
        "year: int, month: int, day: int",
        "hour: int, minute: int, second: int",
    ],
)
def test_conventional_ordered_vocabularies_are_exempt(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "params",
    [
        "x: int, offset: int",  # only half the group is vocabulary
        "width: int, chars_len: int",  # rich/rule.py:105 _rule_line — kept
        "red: float, tint: float",
        "start: int, cursor: int",
        "a: str, b: str",  # single letters are NOT a vocabulary escape
        "s: str, d: str",
    ],
)
def test_groups_only_partly_in_a_vocabulary_are_not_enough_without_risky_names(params: str):
    src = f"def f({params}) -> None: ...\n"
    assert _check(src) == []


def test_vocabularies_do_not_cross_domains():
    # `x`/`y` and `width`/`height` are separate vocabularies; a group spanning
    # both is not one piece of notation.
    src = "def f(x: int, height: int) -> None: ...\n"
    assert _check(src) == []


# FP-hardening (12-repo corpus, 1,405 findings): symmetric letter suffixes,     # test-support trees, numbered migrations.


@pytest.mark.parametrize(
    "params",
    [
        "policy_id_a: str, policy_id_b: str",
        "path_a: str, path_b: str",
        "user_key_a: str, user_key_b: str",
    ],
)
def test_symmetric_letter_suffix_params_are_exempt(params: str):
    # `_a`/`_b` labels the two sides of a commutative helper exactly as `_1`/`_2` does.
    src = f"def compare_versions({params}) -> int: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "params",
    [
        # Different stems: this is the bug class the rule exists for.
        "source_id_a: str, target_id_b: str",
        # Two letters is not a symmetric label.
        "path_ab: str, path_cd: str",
        # The letter must sit behind an underscore to be a label rather than
        # part of the word.
        "key_ida: str, key_idb: str",
    ],
)
def test_near_miss_letter_suffixes_still_fire(params: str):
    src = f"def link({params}) -> None: ...\n"
    assert len(_check(src)) == 1


def test_a_leading_letter_label_is_not_a_symmetric_suffix():
    src = "def link(a_id: str, b_id: str) -> None: ...\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "devel-common/src/tests_common/test_utils/azure_system_helpers.py",
        "provider/system_tests/example_dag.py",
        "src/test_support/fakes.py",
        "src/integration_test/helpers.py",
    ],
)
def test_test_support_directories_are_exempt(path: str):
    # `is_test_path` knows the segments `tests` and `test` only, so a shared
    # test-helper package one directory name away was being linted as
    # production code although the charter already exempts test helpers.
    src = "def create_container(bucket_id: str, blob_id: str) -> None: ...\n"
    assert _check(src, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "src/app/testing_commands.py",  # 3 legitimate findings live in this shape
        "src/app/latest_tester.py",
        "src/contest_service/handlers.py",
    ],
)
def test_names_merely_containing_test_still_fire(path: str):
    # The predicate matches a whole DIRECTORY segment; a module whose name
    # merely contains the letters is production code.
    src = "def transfer(source_id: str, target_id: str) -> None: ...\n"
    assert len(_check(src, path)) == 1


def test_numbered_migration_is_exempt():
    # An append-only historical artifact: it has already run everywhere, so the
    # only edit a finding here can produce is a second migration.
    src = "def rename_emoji(old_name: str, new_name: str) -> None: ...\n"
    assert _check(src, "zerver/migrations/0149_realm_emoji_drop_unique.py") == []


@pytest.mark.parametrize(
    "path",
    [
        "zerver/migrations/helpers.py",  # not numbered: hand-written support code
        "zerver/lib/0149_realm_emoji_drop_unique.py",  # numbered, but not a migration
    ],
)
def test_migration_exemption_needs_both_halves(path: str):
    src = "def rename_emoji(old_name: str, new_name: str) -> None: ...\n"
    assert len(_check(src, path)) == 1


def test_positive_distilled_from_trio_set_result():
    # Distilled TP from trio's _raises_group.ResultHolder.set_result: two
    # same-typed index parameters that are genuinely swap-prone.
    src = """
class ResultHolder:
    def set_result(self, expected: int, actual: int, result: str | None) -> None:
        self.results[actual][expected] = result
"""
    assert len(_check(src)) == 1
