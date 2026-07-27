"""Tests for SARJ068 require-port-for-service."""

from __future__ import annotations

from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_port_for_service import RequirePortForService


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/services/thing_service.py") -> list[Diagnostic]:
    return RequirePortForService().check(Path(path), textwrap.dedent(source))


# The canonical offender: a concrete service, an injected first-party port, two public
# methods, no abstract base. Reused as the positive control every guard is measured against.
_SERVICE = textwrap.dedent(
    """
    class ThingService:
        def __init__(self, store: ThingStore) -> None:
            self.store = store

        def read(self, key: str) -> str:
            return self.store.get(key)

        def write(self, key: str, value: str) -> None:
            self.store.put(key, value)
    """
)


def test_flags_concrete_service_with_injected_collaborator() -> None:
    diags = _check(_SERVICE)
    assert len(diags) == 1
    assert diags[0].code == "SARJ068"
    assert diags[0].line == 2
    assert diags[0].col == 1


def test_message_names_the_class_and_the_collaborator() -> None:
    message = _check(_SERVICE)[0].message
    assert "`ThingService`" in message
    assert "`ThingStore`" in message
    assert "abc.ABC" in message


def test_message_reports_the_public_method_count() -> None:
    assert "exposes 2 public methods" in _check(_SERVICE)[0].message


def test_diagnostic_points_at_the_class_not_the_constructor() -> None:
    diags = _check(
        """
        import os


        class ThingService:
            def __init__(self, store: ThingStore) -> None:
                self.store = store

            def read(self) -> str: ...

            def write(self) -> None: ...
        """
    )
    assert [(d.line, d.col) for d in diags] == [(5, 1)]


# ---- name gate ----


@pytest.mark.parametrize(
    "class_name",
    ["ThingService", "ThingStore", "ThingDAO", "ThingDao", "PaymentGateway", "TokenProvider"],
    ids=["Service", "Store", "DAO", "Dao", "Gateway", "Provider"],
)
def test_service_family_names_fire(class_name: str) -> None:
    assert len(_check(_SERVICE.replace("ThingService", class_name))) == 1


@pytest.mark.parametrize(
    "class_name",
    [
        "ThingClient",
        "ThingRepository",
        "ThingRepo",
        "ThingManager",
        "ThingRouter",
        "ThingMiddleware",
        "ThingAdapter",
        "ThingBuilder",
        "ThingHandler",
        "ThingHelper",
        "Restore",
        "Bookstore",
    ],
    ids=[
        "Client-is-a-vendor-wrapper",
        "Repository-is-overloaded",
        "Repo-is-overloaded",
        "Manager",
        "Router-is-the-composition-root",
        "Middleware",
        "Adapter",
        "Builder",
        "Handler",
        "Helper",
        "lowercase-store-tail",
        "compound-word",
    ],
)
def test_names_outside_the_service_family_are_silent(class_name: str) -> None:
    assert _check(_SERVICE.replace("ThingService", class_name)) == []


def test_private_class_is_exempt() -> None:
    assert _check(_SERVICE.replace("ThingService", "_ThingService")) == []


def test_public_twin_of_the_private_class_fires() -> None:
    assert len(_check(_SERVICE.replace("ThingService", "InternalThingService"))) == 1


@pytest.mark.parametrize("class_name", ["BaseThingService", "AbstractThingService"], ids=["Base", "Abstract"])
def test_base_named_class_is_the_port_being_asked_for(class_name: str) -> None:
    assert _check(_SERVICE.replace("ThingService", class_name)) == []


def test_base_prefix_needs_a_capital_to_count() -> None:
    # `Baseline...` is a word beginning with "Base", not a base class.
    assert len(_check(_SERVICE.replace("ThingService", "BaselineService"))) == 1


# ---- inheritance guards ----


@pytest.mark.parametrize(
    "base",
    [
        "ABC",
        "abc.ABC",
        "Protocol",
        "typing.Protocol",
        "ThingStorePort",
        "livekit.agents.Agent",
        "BaseHTTPMiddleware",
        "celery.Task",
        "BaseModel",
        "TypedDict",
        "NamedTuple",
        "Enum",
        "Exception",
        "Generic[T]",
        "LoggingMixin",
        "object, ThingMixin",
    ],
    ids=[
        "ABC",
        "dotted-ABC",
        "Protocol",
        "dotted-Protocol",
        "first-party-port",
        "livekit-Agent",
        "starlette-middleware",
        "celery-Task",
        "pydantic",
        "TypedDict",
        "NamedTuple",
        "Enum",
        "Exception",
        "Generic",
        "mixin",
        "object-plus-mixin",
    ],
)
def test_any_base_class_suppresses(base: str) -> None:
    assert _check(_SERVICE.replace("class ThingService:", f"class ThingService({base}):")) == []


def test_explicit_object_base_still_fires() -> None:
    assert len(_check(_SERVICE.replace("class ThingService:", "class ThingService(object):"))) == 1


def test_metaclass_keyword_suppresses() -> None:
    assert _check(_SERVICE.replace("class ThingService:", "class ThingService(metaclass=ABCMeta):")) == []


def test_abstractmethod_in_body_suppresses() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                @abstractmethod
                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


def test_overload_in_body_suppresses() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                @overload
                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


@pytest.mark.parametrize(
    "decorator",
    ["@implementer(IThingService)", "@zope.interface.implementer(IThingService)", "@runtime_checkable"],
    ids=["zope-implementer", "dotted-implementer", "runtime_checkable"],
)
def test_interface_declaring_class_decorator_suppresses(decorator: str) -> None:
    assert _check(f"{decorator}\n{_SERVICE.lstrip()}") == []


def test_unrelated_class_decorator_still_fires() -> None:
    assert len(_check(f"@final\n{_SERVICE.lstrip()}")) == 1


# ---- data-type guards ----


@pytest.mark.parametrize(
    "decorator",
    ["@dataclass", "@dataclass(frozen=True)", "@dataclasses.dataclass", "@define", "@attrs.define"],
    ids=["dataclass", "frozen-dataclass", "dotted-dataclass", "attrs-define", "dotted-attrs"],
)
def test_record_decorators_suppress(decorator: str) -> None:
    assert _check(f"{decorator}\n{_SERVICE.lstrip()}") == []


def test_parameter_typed_by_a_same_module_data_class_is_not_a_collaborator() -> None:
    assert (
        _check(
            """
            class ThingRow(BaseModel):
                key: str


            class ThingService:
                def __init__(self, row: ThingRow) -> None:
                    self.row = row

                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


def test_parameter_typed_by_a_same_module_service_class_is_a_collaborator() -> None:
    assert (
        len(
            _check(
                """
                class ThingStore:
                    def get(self) -> str: ...


                class ThingService:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
                """
            )
        )
        # Both classes are service-shaped with two public methods, but only the one
        # that injects a collaborator fires.
        == 1
    )


def test_parameter_typed_by_a_same_module_enum_is_not_a_collaborator() -> None:
    assert (
        _check(
            """
            class Theme(Enum):
                DARK = "dark"


            class ThingService:
                def __init__(self, theme: Theme) -> None:
                    self.theme = theme

                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


# ---- collaborator gate ----


@pytest.mark.parametrize(
    "annotation",
    [
        "str",
        "int",
        "bool",
        "float",
        "bytes",
        "Path",
        "UUID",
        "datetime",
        "timedelta",
        "Decimal",
        "list[str]",
        "dict[str, int]",
        "frozenset[str]",
        "Sequence[str]",
        "Callable[[], None]",
        "Dict[str, Any]",
        "List[int]",
        "Optional[Dict[str, Any]]",
        "str | None",
        "Any",
    ],
    ids=[
        "str",
        "int",
        "bool",
        "float",
        "bytes",
        "Path",
        "UUID",
        "datetime",
        "timedelta",
        "Decimal",
        "list",
        "dict",
        "frozenset",
        "Sequence",
        "Callable",
        "typing-Dict",
        "typing-List",
        "Optional-Dict",
        "optional-str",
        "Any",
    ],
)
def test_value_parameters_are_not_collaborators(annotation: str) -> None:
    assert _check(_SERVICE.replace("store: ThingStore", f"store: {annotation}")) == []


@pytest.mark.parametrize(
    "annotation",
    [
        "ServerSettings",
        "AppConfig",
        "Configuration",
        "RetryOptions",
        "Logger",
        "structlog.Logger",
        "Clock",
        "JobContext",
    ],
    ids=["Settings", "Config", "Configuration", "Options", "Logger", "dotted-Logger", "Clock", "Context"],
)
def test_configuration_and_ambient_runtime_are_not_collaborators(annotation: str) -> None:
    assert _check(_SERVICE.replace("store: ThingStore", f"store: {annotation}")) == []


def test_one_real_collaborator_beside_configuration_still_fires() -> None:
    assert (
        len(
            _check(
                """
                class ThingService:
                    def __init__(self, settings: ServerSettings, store: ThingStore) -> None:
                        self.settings = settings
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
                """
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "annotation",
    [
        "ThingStore",
        "stores.ThingStore",
        "'ThingStore'",
        "ThingStore | None",
        "Optional[ThingStore]",
        "Annotated[ThingStore, Dep()]",
    ],
    ids=["plain", "dotted", "forward-ref", "pep604-optional", "Optional", "Annotated"],
)
def test_collaborator_annotation_forms(annotation: str) -> None:
    assert len(_check(_SERVICE.replace("store: ThingStore", f"store: {annotation}"))) == 1


def test_union_of_collaborator_and_value_is_unwrapped() -> None:
    # `Union[...]` must be unwrapped like `X | None`; leaving it wrapped made the
    # literal name `Union` read as a project type (prefect's `GitRepository`).
    assert len(_check(_SERVICE.replace("store: ThingStore", "store: Union[ThingStore, None]"))) == 1


def test_union_of_only_values_is_not_a_collaborator() -> None:
    assert _check(_SERVICE.replace("store: ThingStore", "store: Union[str, int, None]")) == []


def test_unannotated_parameter_is_not_a_collaborator() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store) -> None:
                    self.store = store

                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


def test_collaborator_must_be_stored_on_self() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    store.warm()

                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


def test_collaborator_stored_under_a_private_attribute_counts() -> None:
    assert len(_check(_SERVICE.replace("self.store = store", "self._store = store"))) == 1


def test_collaborator_stored_by_annotated_assignment_counts() -> None:
    assert len(_check(_SERVICE.replace("self.store = store", "self.store: ThingStore = store"))) == 1


def test_keyword_only_collaborator_counts() -> None:
    assert len(_check(_SERVICE.replace("self, store:", "self, *, store:"))) == 1


def test_class_without_init_is_exempt() -> None:
    assert (
        _check(
            """
            class ThingService:
                store: ThingStore

                def read(self) -> str: ...

                def write(self) -> None: ...
            """
        )
        == []
    )


# ---- public-method floor ----


def test_single_public_method_is_a_function_in_a_trenchcoat() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                def read(self) -> str: ...
            """
        )
        == []
    )


def test_call_only_strategy_object_is_exempt() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                def __call__(self) -> str: ...

                def __repr__(self) -> str: ...
            """
        )
        == []
    )


def test_private_methods_do_not_reach_the_floor() -> None:
    assert (
        _check(
            """
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                def read(self) -> str: ...

                def _helper(self) -> None: ...
            """
        )
        == []
    )


@pytest.mark.parametrize(
    "decorator",
    ["@property", "@cached_property", "@staticmethod", "@classmethod", "@functools.cached_property"],
    ids=["property", "cached_property", "staticmethod", "classmethod", "dotted-cached_property"],
)
def test_descriptors_and_factories_do_not_reach_the_floor(decorator: str) -> None:
    assert (
        _check(
            f"""
            class ThingService:
                def __init__(self, store: ThingStore) -> None:
                    self.store = store

                def read(self) -> str: ...

                {decorator}
                def other(self) -> str: ...
            """
        )
        == []
    )


def test_async_public_methods_count() -> None:
    assert (
        len(
            _check(
                """
                class ThingService:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    async def read(self) -> str: ...

                    async def write(self) -> None: ...
                """
            )
        )
        == 1
    )


# ---- the port already exists elsewhere ----


def test_class_named_after_a_port_defined_in_the_module_is_exempt() -> None:
    # litellm's `CachedOAuthTokenStore` beside `class OAuthTokenStore(Protocol)`:
    # structural conformance is still substitutability.
    assert (
        _check(
            """
            class TokenStore(Protocol):
                def fetch(self) -> str: ...


            class CachedTokenStore:
                def __init__(self, inner: TokenStore) -> None:
                    self.inner = inner

                def fetch(self) -> str: ...

                def invalidate(self) -> None: ...
            """
        )
        == []
    )


def test_class_named_after_an_imported_port_is_exempt() -> None:
    assert (
        _check(
            """
            from app.ports import TokenStore


            class CachedTokenStore:
                def __init__(self, inner: TokenStore) -> None:
                    self.inner = inner

                def fetch(self) -> str: ...

                def invalidate(self) -> None: ...
            """
        )
        == []
    )


def test_class_whose_suffix_is_not_in_scope_still_fires() -> None:
    assert (
        len(
            _check(
                """
                from app.ports import SomethingElse


                class CachedTokenStore:
                    def __init__(self, inner: ThingStore) -> None:
                        self.inner = inner

                    def fetch(self) -> str: ...

                    def invalidate(self) -> None: ...
                """
            )
        )
        == 1
    )


def test_suffix_must_itself_be_service_shaped() -> None:
    # `Widget` is in scope and is a suffix of `CacheWidgetService`, but a port name
    # has to look like a port; otherwise any imported noun would silence the rule.
    assert (
        len(
            _check(
                """
                from app.models import ThingService


                class BigThingServiceRunner:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
                """
            )
        )
        # `BigThingServiceRunner` does not end in a service tail at all.
        == 0
    )


def test_import_alias_binds_the_port_name() -> None:
    assert (
        _check(
            """
            from app.ports import Port as TokenStore


            class CachedTokenStore:
                def __init__(self, inner: TokenStore) -> None:
                    self.inner = inner

                def fetch(self) -> str: ...

                def invalidate(self) -> None: ...
            """
        )
        == []
    )


# ---- path and file gates ----


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_thing.py",
        "app/tests/helpers.py",
        "app/conftest.py",
        "app/thing_test.py",
        "common/testing/llm_judge.py",
        "app/fakes/thing.py",
        "app/mocks/thing.py",
        "webserver/test_fakes/stores.py",
        "app/fakes.py",
        "app/mock_thing_store.py",
    ],
    ids=[
        "tests-dir",
        "nested-tests-dir",
        "conftest",
        "test-suffix",
        "testing-dir",
        "fakes-dir",
        "mocks-dir",
        "test_fakes-dir",
        "fakes-stem",
        "mock-stem",
    ],
)
def test_test_and_double_paths_are_exempt(path: str) -> None:
    assert _check(_SERVICE, path=path) == []


@pytest.mark.parametrize(
    "path",
    [
        "webserver/scripts/provision.py",
        "app/bin/run.py",
        "app/tools/backfill.py",
        "db/migrations/0001_init.py",
        "app/management/commands/sync.py",
    ],
    ids=["scripts", "bin", "tools", "migrations", "management-commands"],
)
def test_program_directories_are_exempt(path: str) -> None:
    assert _check(_SERVICE, path=path) == []


def test_library_path_fires() -> None:
    assert len(_check(_SERVICE, path="app/services/thing_service.py")) == 1


def test_module_with_a_main_guard_is_a_program() -> None:
    # bulbul's `LogtoAdminClient` lives in an argparse provisioning script that
    # nothing imports; there is no consumer to decouple.
    program = (
        f'{_SERVICE}\n\ndef main() -> None:\n    ThingService(store=None)\n\n\nif __name__ == "__main__":\n    main()\n'
    )
    assert _check(program) == []


def test_same_module_without_the_main_guard_fires() -> None:
    library = f"{_SERVICE}\n\ndef main() -> None:\n    ThingService(store=None)\n"
    assert len(_check(library)) == 1


def test_generated_source_is_exempt() -> None:
    assert _check(f'"""@generated by protoc - do not edit."""\n{_SERVICE}') == []


def test_near_identical_source_without_the_generated_header_fires() -> None:
    assert len(_check(f'"""Thing services."""\n{_SERVICE}')) == 1


# ---- robustness ----


def test_syntax_error_source_yields_nothing() -> None:
    assert _check("class ThingService(:\n    def (") == []


def test_empty_source_yields_nothing() -> None:
    assert _check("") == []


def test_nested_class_is_reached() -> None:
    nested = f"class Outer:\n{textwrap.indent(_SERVICE, '    ')}"
    assert len(_check(nested)) == 1


def test_multiple_findings_are_sorted_by_position() -> None:
    diags = _check(
        """
        class BService:
            def __init__(self, store: BStore) -> None:
                self.store = store

            def read(self) -> str: ...

            def write(self) -> None: ...


        class AService:
            def __init__(self, store: AStore) -> None:
                self.store = store

            def read(self) -> str: ...

            def write(self) -> None: ...
        """
    )
    assert [d.line for d in diags] == sorted(d.line for d in diags)
    assert len(diags) == 2


def test_rule_metadata() -> None:
    rule = RequirePortForService()
    assert rule.id == "require-port-for-service"
    assert rule.code == "SARJ068"
    assert len(rule.description) >= 10
