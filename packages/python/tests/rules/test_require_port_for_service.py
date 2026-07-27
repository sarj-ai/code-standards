"""Tests for SARJ071 require-port-for-service."""

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
    assert diags[0].code == "SARJ071"
    assert diags[0].line == 2
    assert diags[0].col == 1


def test_message_is_exactly_the_shipped_text() -> None:
    # Pins the whole message, not a substring: mutation testing showed the constants
    # could be replaced wholesale without a single test noticing.
    assert _check(_SERVICE)[0].message == (
        "`ThingService` injects `ThingStore` and exposes 2 public methods, but has no abstract base, "
        "so every consumer has to name the concrete class and the only way to test one is to patch or "
        "mock it. Extract the public methods onto an `abc.ABC` (or a `Protocol`) and have "
        "`ThingService` implement it, so consumers depend on the port and tests can pass a real or "
        "purpose-built implementation instead of a mock."
    )


def test_message_does_not_cite_another_repos_class_names() -> None:
    # The fix instruction has to be readable in any repository the rule runs in.
    message = _check(_SERVICE)[0].message
    assert "TaskStore" not in message
    assert "this codebase" not in message


def test_message_reports_the_public_method_count() -> None:
    assert "exposes 2 public methods" in _check(_SERVICE)[0].message


def test_message_counts_only_the_public_methods() -> None:
    message = _check(
        """
        class ThingService:
            def __init__(self, store: ThingStore) -> None:
                self.store = store

            def read(self) -> str: ...

            def write(self) -> None: ...

            def wipe(self) -> None: ...

            def _helper(self) -> None: ...
        """
    )[0].message
    assert "exposes 3 public methods" in message


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


# ---- route-handler guard ----


def _handler_service(parameter: str) -> str:
    return f"""
        class ThingService:
            def __init__(self, store: ThingStore) -> None:
                self.store = store

            def read(self, {parameter}) -> str: ...

            def write(self) -> None: ...
        """


@pytest.mark.parametrize(
    "parameter",
    [
        "request: Request",
        "request: fastapi.Request",
        "response: Response",
        "background_tasks: BackgroundTasks",
        "websocket: WebSocket",
        "file: UploadFile",
        "x_mock: Annotated[list[str] | None, Header()] = None",
        "page: Annotated[int, Query()] = 1",
        "store: Annotated[ThingStore, Depends(get_store)]",
        "payload: Annotated[dict[str, str], Body()]",
        "thing_id: Annotated[str, Path()]",
        "name: Annotated[str, Form()]",
        "upload: Annotated[bytes, File()]",
        "session: Annotated[str, Cookie()]",
        "scopes: Annotated[str, Security(oauth)]",
        "store: ThingStore = Depends(get_store)",
        "x_mock: str = Header(None)",
    ],
    ids=[
        "Request",
        "dotted-Request",
        "Response",
        "BackgroundTasks",
        "WebSocket",
        "UploadFile",
        "Annotated-Header",
        "Annotated-Query",
        "Annotated-Depends",
        "Annotated-Body",
        "Annotated-Path",
        "Annotated-Form",
        "Annotated-File",
        "Annotated-Cookie",
        "Annotated-Security",
        "default-Depends",
        "default-Header",
    ],
)
def test_route_handler_signatures_suppress(parameter: str) -> None:
    # summer's `ReceiptService` is `ReceiptRouter`'s body: a router that happens to be
    # named `*Service`, so the name gate cannot see it. An ABC over an HTTP boundary
    # substitutes nothing.
    assert _check(_handler_service(parameter)) == []


def test_the_same_class_without_the_web_parameter_fires() -> None:
    # The other direction of the guard above: strip the framework vocabulary and the
    # class is an ordinary unsubstitutable service again.
    assert len(_check(_handler_service("key: str"))) == 1


def test_pathlib_path_parameter_is_not_a_route_marker() -> None:
    # `Path` is a FastAPI marker only in its call form; `path: Path` is pathlib.
    assert len(_check(_handler_service("path: Path"))) == 1


def test_private_method_taking_a_request_does_not_suppress() -> None:
    # Only the public surface decides whether the class is a transport boundary.
    assert (
        len(
            _check(
                """
                class ThingService:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...

                    def _log(self, request: Request) -> None: ...
                """
            )
        )
        == 1
    )


def test_domain_type_ending_in_request_is_not_a_route_marker() -> None:
    assert len(_check(_handler_service("args: ExtractFromUrlRequest"))) == 1


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


def test_name_containing_a_service_tail_mid_word_is_silent() -> None:
    # The gate is a tail, not a substring: `BigThingServiceRunner` contains `Service`
    # but does not end in it. (The conjunct that the *port suffix* must itself be
    # service-shaped is pinned separately, below.)
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
        == 0
    )


def test_port_suffix_must_start_at_a_camel_case_boundary() -> None:
    # `ationService` is a suffix of `NotificationService` and is service-shaped, but it
    # starts mid-word, so it is a coincidence rather than a qualified port name. Without
    # the `name[index].isupper()` conjunct any such import would silence the rule.
    assert (
        len(
            _check(
                """
                from app.legacy import ationService


                class NotificationService:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
                """
            )
        )
        == 1
    )


def test_uppercase_suffix_that_is_not_service_shaped_does_not_exempt() -> None:
    # `AO` starts at a capital and is in scope, but it is not a port name — this is the
    # conjunct that stops a partial token from acting as one.
    assert (
        len(
            _check(
                """
                from app.legacy import AO


                class PaymentDAO:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
                """
            )
        )
        == 1
    )


def test_port_suffix_may_start_one_character_in() -> None:
    # `PTokenStore` qualifies `TokenStore` with a single letter; the suffix scan has to
    # start at index 1, not 2.
    assert (
        _check(
            """
            from app.ports import TokenStore


            class PTokenStore:
                def __init__(self, inner: TokenStore) -> None:
                    self.inner = inner

                def fetch(self) -> str: ...

                def invalidate(self) -> None: ...
            """
        )
        == []
    )


def test_the_whole_class_name_is_not_its_own_port() -> None:
    # The scan must stay on *proper* suffixes: a class is never exempted by itself.
    assert (
        len(
            _check(
                """
                class TokenStore:
                    def __init__(self, inner: ThingGateway) -> None:
                        self.inner = inner

                    def fetch(self) -> str: ...

                    def invalidate(self) -> None: ...
                """
            )
        )
        == 1
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


def test_main_guard_must_be_top_level() -> None:
    # A `__name__` check buried inside a function does not make the module a program.
    nested = f'{_SERVICE}\n\ndef main() -> None:\n    if __name__ == "__main__":\n        pass\n'
    assert len(_check(nested)) == 1


def test_a_top_level_if_that_is_not_a_main_guard_does_not_exempt() -> None:
    # The `if` has to test `__name__`; any other module-level branch is ordinary code.
    guarded = f"{_SERVICE}\n\nif TYPE_CHECKING:\n    from app.stores import ThingStore\n"
    assert len(_check(guarded)) == 1


def test_generated_source_is_exempt() -> None:
    assert _check(f'"""@generated by protoc - do not edit."""\n{_SERVICE}') == []


def test_near_identical_source_without_the_generated_header_fires() -> None:
    assert len(_check(f'"""Thing services."""\n{_SERVICE}')) == 1


# ---- robustness ----


def test_syntax_error_source_yields_nothing() -> None:
    assert _check("class ThingService(:\n    def (") == []


def test_empty_source_yields_nothing() -> None:
    assert _check("") == []


def test_unparseable_forward_reference_is_ignored() -> None:
    assert _check(_SERVICE.replace("store: ThingStore", 'store: "Thing Store"')) == []


def test_non_string_constant_annotation_is_ignored() -> None:
    assert _check(_SERVICE.replace("store: ThingStore", "store: None")) == []


@pytest.mark.parametrize(
    "annotation",
    ["Awaitable[ThingStore]", "Final[ThingStore]", "ClassVar[ThingStore]"],
    ids=["Awaitable", "Final", "ClassVar"],
)
def test_transparent_generics_are_unwrapped(annotation: str) -> None:
    assert len(_check(_SERVICE.replace("store: ThingStore", f"store: {annotation}"))) == 1


def test_only_the_first_argument_of_a_transparent_generic_is_read() -> None:
    # Known limit, pinned so it is a decision rather than a surprise: unwrapping takes
    # `elts[0]`, so `Coroutine[Any, Any, ThingStore]` reduces to `Any` and reads as a
    # value. No constructor in any measured corpus is annotated this way.
    assert _check(_SERVICE.replace("store: ThingStore", "store: Coroutine[Any, Any, ThingStore]")) == []


def test_subscripted_project_type_keeps_the_container_name() -> None:
    # `stores.Registry[Row]` is a project type, so the outer name is the collaborator.
    assert len(_check(_SERVICE.replace("store: ThingStore", "store: stores.Registry[Row]"))) == 1


@pytest.mark.parametrize(
    "annotation",
    ["dict[str, ThingStore]", "list[ThingStore]", "tuple[ThingStore, ...]"],
    ids=["dict", "list", "tuple"],
)
def test_subscripted_builtin_container_is_still_a_value(annotation: str) -> None:
    # A collection of collaborators is a collection, not one injected port: only the
    # container's own name is read, so these must not unwrap to `ThingStore`.
    assert _check(_SERVICE.replace("store: ThingStore", f"store: {annotation}")) == []


def test_nested_class_is_reached() -> None:
    nested = f"class Outer:\n{textwrap.indent(_SERVICE, '    ')}"
    assert len(_check(nested)) == 1


def test_nested_finding_reports_its_real_line_and_column() -> None:
    # Both coordinates non-1, so a hardcoded `col=1` (or `col_offset` without the +1)
    # cannot pass. The class sits at indentation 8 on line 5.
    diags = _check(
        """
        class Outer:
            class Middle:

                class ThingService:
                    def __init__(self, store: ThingStore) -> None:
                        self.store = store

                    def read(self) -> str: ...

                    def write(self) -> None: ...
        """
    )
    assert [(d.line, d.col) for d in diags] == [(5, 9)]


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
    assert rule.code == "SARJ071"
    assert len(rule.description) >= 10
