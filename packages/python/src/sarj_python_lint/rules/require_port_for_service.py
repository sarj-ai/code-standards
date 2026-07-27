"""SARJ071: a concrete service with injected collaborators and no ABC above it is not substitutable.

`class ZohoDeskService:` that takes a `ZohoDeskDAO` in its constructor and exposes
five public methods is a seam that cannot be moved. Every consumer has to name the
concrete class in its own annotations, so the only way to test a consumer is to
`patch` the class or hand it a `MagicMock` — which is the disease the SARJ058 /
SARJ059 / SARJ062 / SARJ063 family attacks from the other end. Those rules say "stop
mocking your own collaborator"; they can only be obeyed if there is something to
substitute. An ABC above the service is that something: the consumer depends on the
port, the test passes the real implementation or a purpose-built one, and nothing has
to be patched.

**What this rule is, given the evidence.** An earlier version of this docstring said the
rule "flags stragglers against an established convention" and quoted 89% adoption. That
number was bulbul's, and the convention it describes is bulbul's. Counting public,
non-test classes whose name ends in a service-family token (`*Service`, `*Store`,
`*DAO`, `*Gateway`, `*Provider`) and asking how many have no base class at all, across
every first-party Python repo on the machine:

| repo | service-family classes | no base | already have a base |
|---|---|---|---|
| faris | 16 | 0 | 100% |
| docs | 12 | 0 | 100% |
| bulbul | 140 | 8 | 94% |
| summer | 18 | 1 | 94% |
| bell | 23 | 4 | 83% |
| ai | 14 | 3 | 79% |
| noura-be | 26 | 8 | 69% |
| tahded | 4 | 2 | 50% |
| digital-bank | 26 | 16 | 38% |

(submissions is absent because it has no service-family classes at all.)

bulbul is where the convention is strongest and where the rule was written; it is not
where the findings are. **`digital-bank` alone accounts for 15 of the 30 first-party
findings** — `banking_api/modules/{card,auth,bank,transfer,mfa,beneficiary,account,
onboarding}/{store,service}.py`, uniformly `class XStore: def __init__(self, pool:
AsyncConnectionPool)` paired with `class XService: def __init__(self, store: XStore)`,
no base anywhere. Every one is a true positive by this rule's definition — nothing in
that service layer is substitutable, and its tests can only mock — but they are not
stragglers behind a local convention. They are the repo's architecture.

So the framing the data supports is: **this rule reports service layers with no seam.**
Where ports are already the norm (faris, docs, bulbul, summer) the output is a short
list of exceptions and reads as "you missed these". Where they are not (digital-bank,
tahded, noura-be) the output is a description of the design, and the response owed is a
decision about the design, not eight small refactors. Turning the rule on in a new repo
should start with the count, not with the diff.

The port mechanism these repos reach for is `abc.ABC` rather than `typing.Protocol`, by
150 classes to 23 (bulbul 117/13, noura-be 33/10), so the message names `abc.ABC`
first. It names `Protocol` as the alternative and cites no repo's class names: the rule
also runs on code that has never seen this codebase, and "follow the convention used for
`TaskStore` / `PsqlTaskStore`" is not an instruction litellm can act on.

Fires when ALL of these hold:

* the file is production code — not a test path, not a shared test-double module, not
  generated, not under `scripts/`/`bin/`/`migrations/`, and not a module with an
  `if __name__ == "__main__":` entry point,
* the class name is public, ends in a service-family token (`Service`, `Store`, `DAO`,
  `Gateway`, `Provider`), is not `Base*`/`Abstract*`, and is not a qualified form of a
  port already in scope (`CachedTokenStore` beside `TokenStore`),
* the class has **no base class at all** beyond `object`. Any base — an ABC, a
  `Protocol`, a first-party base, a framework base, `Generic[T]`, `BaseModel`,
  `Enum`, `Exception` — means substitutability already exists or is not this rule's
  business. This is deliberately the most conservative form of the check,
* it has an `__init__` that stores **at least one non-primitive collaborator** on
  `self`, where a collaborator is a parameter annotated with a project type — not a
  builtin, not a container, not a `Path`/`UUID`/`datetime`, not a `*Settings` /
  `*Config` / `Logger` / `Clock` / `*Context`, and not a data type defined in the same
  module,
* it declares **at least two public methods** — plain instance methods, not
  properties, `staticmethod`s or `classmethod`s,
* and **none of those public methods is an HTTP route handler** — no parameter
  annotated `Request`/`Response`/`BackgroundTasks`/`WebSocket`/`UploadFile`, and no
  FastAPI-style marker call (`Header()`, `Query()`, `Depends()`, `Body()`, `Path()`,
  `Form()`, `File()`, `Cookie()`, `Security()`) inside an `Annotated[...]` or as a
  default.

Corpus evidence. Measured over **42,996 files in twenty-four repositories**. Ten
first-party — bulbul (1,179), noura-be (502), digital-bank (267), submissions (194), ai
(179), tahded (88), summer (81), docs (76), faris (67), bell (42), 2,675 files — and
fourteen open-source: airflow (7,655), dagster (5,982), litellm (5,054), saleor (4,301),
django (2,927), mlflow (2,594), langchain (2,536), superset (2,440), zulip (2,012),
prefect (1,887), fastapi (1,130), warehouse (888), sentry-python (498), celery (417),
40,321 files.

**Thirty-two findings**: 30 first-party — digital-bank 15, bulbul 5, bell 4, noura-be 3,
ai 3, and zero in submissions, faris, docs, tahded and summer — and **2 in the 40,321
open-source files**, both in litellm, with zero in the other thirteen, django and
fastapi among them. Candidate hits were read at source across successive tightenings and
classified by hand; the survivors are 31 true positives by the rule's own definition and
1 false positive (`LazyPerUserOAuthTokenStore`, below).

That OSS number is the point rather than an embarrassment: **2 hits in 40,321 files
against 30 first-party** says this is a house-convention rule, and the docstring should
say so plainly instead of implying generality. It is not near-dead because the gates are
broken. The fourteen OSS repos contain 291 public non-test classes with a service-family
name, 59 of them with no base class at all, and they survive to the later gates — the
`@implementer` check, the collaborator requirement, the method floor — before being
rejected. warehouse alone contributes 25 of those 59 and loses every one of them to the
`zope.interface` guard.

Every threshold was re-measured against these 42,996 files rather than carried over:

* public-method floor **1**: 32 -> 42 findings, +10 and -0. Five of the additions are
  first-party one-method wrappers — `TranslationService` in both noura-be and
  digital-bank, noura-be's `EmailService`, bulbul's `VoicePreviewService`, tahded's
  `ModelService` — and five are OSS. A one-method class is a function in a trenchcoat
  and an ABC over it is ceremony,
* public-method floor **2** (shipped): 32 findings,
* floor **3**: 32 -> 23, +0 and -9. It removes the one known false positive
  (`LazyPerUserOAuthTokenStore`) at a cost of eight true positives: all four of bell's
  `*ProvisioningService`s, digital-bank's `AuthService` and `MfaService`, and bulbul's
  `ScenarioGenerationService` and `ZohoOAuthService`. Not a trade worth making,
* adding **`Client`** to the name gate: 32 -> 39. All seven additions are OSS and all
  are the vendor-SDK-wrapper family — airflow's `Client`, dagster's `GithubClient`,
  `ClaudeSDKClient` and `DagsterCloudAgentHttpClient`, litellm's `PrismaClient` and
  `MCPClient`. An ABC over a class whose collaborator is somebody else's HTTP transport
  substitutes nothing. It costs **zero** first-party findings,
* adding **`Repository`/`Repo`**: 32 -> 33. The one addition is dagster's
  `RemoteRepository`, a code location rather than a data-access port. Zero first-party
  findings, because no first-party repo names a class `*Repository` at all,
* adding **`Manager`/`Adapter`/`Handler`/`Router`**: 32 -> 58, +26, ten of them
  first-party and every one of those a FastAPI router (`OrganizationRouter`,
  `SipConnectionRouter`, `PhoneNumberRouter`, `SallaRouter`, `CustomScenarioRouter`), a
  lifecycle helper (`IntegrationsManager`, `RunManager`, two `AgentStateManager`s) or
  `ChatAdapter`. This is the widening the route-handler guard below exists to survive,
* adding **`Proposer`/`Processor`**: 32 -> 33 — see the false-negative note at the end,
* **no name gate at all**: 32 -> 206, 156 of them in OSS. The name gate is doing the
  precision work.

Deliberately NOT flagged:

* **anything with a base class.** A `Protocol` or `ABC` subclass already is the port;
  a `BaseModel` / `TypedDict` / `NamedTuple` / `Enum` / `Exception` subclass is data
  or an error, not a service; a framework base — LiveKit's `Agent`, Celery's `Task`,
  Starlette's `BaseHTTPMiddleware`, a Django `Command` — *is* the substitution point
  the framework provides. Rather than enumerate these, the rule requires zero bases.
  It costs recall (a concrete service that subclasses another concrete service is not
  flagged) and buys a whole category of false positives never happening,
* **`@dataclass` and `@attrs.define` classes.** They are records, and the two in the
  corpus that reach every other gate (`Client` and `AuthenticatedClient`,
  `bulbul/python/platform_client/platform_client/client.py:12`) are generated OpenAPI
  transport structs,
* **FastAPI routers, middleware, and DI wiring.** `OrganizationRouter`
  (`webserver/webserver/organization_router.py:54`) injects seven stores and
  `SipConnectionRouter` (`webserver/webserver/routers/sip_connection_router.py:191`)
  injects seven services — they are the composition root, the place concrete types are
  *supposed* to be named, and putting an ABC over an HTTP router substitutes nothing.
  Same for `AuthorizationMiddleware`
  (`webserver/webserver/middleware/authorization_middleware.py:13`). The name gate
  excludes all six routers plus the middleware,
* **routers that call themselves services**, which the name gate cannot help with.
  summer's `ReceiptService`
  (`sarj/applications/receipts/receipt_service.py:42`) is `ReceiptRouter`'s body: its
  two public methods are the route handlers, taking `Request`, `BackgroundTasks`,
  `Annotated[list[str] | None, Header()]` and `Annotated[UploadFile, File()]`, and
  `ReceiptRouter.get_router` forwards to them argument for argument. A signature
  written in a web framework's vocabulary is a transport boundary; an ABC over it
  substitutes nothing, because the thing on the other side is the framework. So a
  class is skipped when any *public* method takes a request/response object or a
  FastAPI-style parameter marker. Measured cost: 31 -> 30 first-party findings and 2 ->
  2 in OSS — it removes exactly that one false positive and no true positive, in any
  repo. Only the *call* form of `Path`/`File` counts, so `path: Path` stays a value and
  `Annotated[str, Path()]` is a route; and only public methods are consulted, so a
  private `_log(self, request: Request)` helper does not exempt a real service,
* **entry-point scripts.** `LogtoAdminClient`
  (`webserver/webserver/scripts/logto_provision.py:139`) passes every shape test — an
  injected `httpx.Client`, four public methods, no base — and was a measured false
  positive. It is a class inside a one-file `argparse` provisioning script that
  nothing imports, so there is no consumer to decouple. A module with a
  top-level `if __name__ == "__main__":`, or one under `scripts/`/`bin/`/`tools/`/
  `migrations/`, is a program, not a library,
* **single-public-method classes and `__call__`-only strategy objects.** One method is
  a function in a trenchcoat; an ABC over it is ceremony. Dunders never count toward
  the floor, so a callable object is exempt by construction,
* **classes injected only with configuration.** A `*Settings`, `*Config`, `Logger`,
  `Clock` or `*Context` parameter is not a collaborator seam — a `JobContext` or a
  pydantic settings object is handed in by the runtime, not swapped in a test. At
  least one *real* collaborator is required,
* **classes whose only injected types are data defined alongside them.** A parameter
  annotated with a `BaseModel` / `Enum` / `NamedTuple` / `TypedDict` / dataclass
  declared in the same module is a value, not a port,
* **private classes.** A leading underscore says nobody outside the module injects it,
* **test files and shared test doubles** (`tests/`, `conftest.py`, `testing/`,
  `fakes/`, `mock*.py`), which is what keeps the rule off noura-be's
  `common/testing/llm_judge.py`, and **generated code**,
* **classes that are already abstract without saying so** — any `@abstractmethod` or
  `@overload` in the body, or a class-level `@implementer(IThingService)`. warehouse
  declares its ports with `zope.interface` and 60 classes carry that decorator; without
  the guard, `IntegrityService` (`warehouse/attestations/services.py:124`) and
  `OIDCPublisherService` (`warehouse/oidc/services.py:37`) both fired despite each
  naming the interface it implements one line above the `class` statement,
* **`Base*` / `Abstract*` classes**, which are the port a family is meant to share.
  sentry-sdk's `BaseClient` (`sentry_sdk/client.py:411`) is subclassed by `Client` and
  `NonRecordingClient`; asking it for a port is asking it to be itself,
* **structural `Protocol` conformance.** `typing.Protocol` is structural, so a class
  can satisfy a port without inheriting it, and a rule that demanded *nominal*
  inheritance would be wrong on every Protocol-first codebase. litellm spells this the
  way this codebase spells `PsqlTaskStore` : `TaskStore` — `CachedOAuthTokenStore`
  satisfies `class OAuthTokenStore(Protocol)` declared in the same module — so a class
  whose name is a qualified form of a service-shaped name already in scope (defined or
  imported) is exempt. This is the rule's known limit: litellm's
  `LazyPerUserOAuthTokenStore`
  (`litellm/proxy/_experimental/mcp_server/outbound_credentials/per_user_oauth_store.py:170`)
  is a real false positive, because its module imports the refinement
  (`InvalidatableOAuthTokenStore`) rather than the base, and resolving that needs
  cross-module analysis a single-file AST rule does not do. It is the one FP in the 32
  findings across 42,996 files, and it is in someone else's repository,
* **`Generic[T]` containers and mixins**, both excluded by the zero-bases requirement.

Known false negatives, considered and declined — recorded here so the measurement is
not re-derived. Dropping the name gate entirely returns 156 OSS findings against the
shipped 2, so **154 OSS classes pass every other gate** — concrete, base-less, an
injected typed collaborator, two or more public methods — and are held out by the name
alone. Nearly all are correctly ignored: contexts (`ScheduleEvaluationContext`),
definitions (`DagsterType`, `ConfigType`), `*Operations` accessors, cursors, resolvers,
generators and routers. Three are genuine misses:

* `StateProposer` (`prefect/src/prefect/runner/_state_proposer.py:23`) — six public
  methods, an injected `PrefectClient`, no ABC. prefect's own suite constructs it as
  `StateProposer(client=AsyncMock())` at `tests/runner/test__state_proposer.py:191`,
  which is precisely the consequence this rule predicts,
* `AirflowInstance`
  (`dagster/.../dagster_airlift/core/airflow_instance.py:62`) — 20 public methods over
  an injected `AirflowAuthBackend`,
* `QueryContextProcessor` (`superset/superset/common/query_context_processor.py:70`).

Adding **`Proposer`/`Processor`** to the name gate was measured against the full 24-repo
corpus: 32 -> 33 findings. The single addition is `StateProposer`, a true positive; no
first-party finding is added and no false positive appears. `QueryContextProcessor` is
*still* not reached, because its only constructor parameter is a `QueryContext` and the
configuration gate rejects `*Context`; `AirflowInstance` needs a fourth token as well.
It is declined anyway, and the reason is not cost but value: 21 first-party and 60 OSS
classes are named `*Processor`/`*Proposer`, and widening the gate over 81 classes buys
exactly one finding, in a repository nobody here owns. The name gate is meant to encode
this codebase's own port vocabulary — `*Service`, `*Store`, `*DAO`, `*Gateway`,
`*Provider` — and `*Processor` is not part of it. Revisit only if a first-party repo
starts naming ports that way.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# Name tails that mark a class as a service in this codebase's own vocabulary. Measured
# across ten first-party repos: 279 public non-test classes match, 42 of them with no
# base class — see the per-repo spread in the module docstring, which varies from 100%
# adoption (faris, docs) to 38% (digital-bank).
# Case-sensitive CamelCase tails, so `Restore`, `Bookstore` and `Rediscover` miss.
# `Manager`, `Adapter`, `Builder`, `Router` and `Middleware` are deliberately absent —
# adding them turned six FastAPI routers and two LiveKit lifecycle helpers into hits.
# `Client` and `Repository` are absent too, and that was measured, not assumed — see
# the module docstring.
_SERVICE_NAME_RE = re.compile(r"(?:Service|Store|DAO|Dao|Gateway|Provider)$")

# Classes named as the base of a family are the port being asked for, not a missing one.
_BASE_NAME_RE = re.compile(r"^(?:Base|Abstract)[A-Z_]")

# Annotations that name a value rather than a collaborator. Anything a service is
# handed that it could equally have been handed as a literal.
_PRIMITIVE_ANNOTATIONS = frozenset(
    {
        "str",
        "int",
        "bool",
        "float",
        "complex",
        "bytes",
        "bytearray",
        "object",
        "None",
        "Any",
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "type",
        # The capitalised `typing` aliases are the same builtins. Omitting them is what
        # made sentry-sdk's `BaseClient(options: "Optional[Dict[str, Any]]")` read as an
        # injected collaborator.
        "List",
        "Dict",
        "Set",
        "FrozenSet",
        "Tuple",
        "Type",
        "Text",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Iterable",
        "Iterator",
        "Collection",
        "Callable",
        "Path",
        "PurePath",
        "UUID",
        "datetime",
        "date",
        "time",
        "timedelta",
        "Decimal",
        "Fraction",
        "Pattern",
        "TextIO",
        "BinaryIO",
    }
)

# Injected types that are configuration or ambient runtime, not a substitutable
# collaborator: nobody swaps a `ServerSettings` or a LiveKit `JobContext` in a test.
_WEAK_COLLABORATOR_RE = re.compile(r"(?:Settings|Config|Configuration|Options|Logger|Log|Clock|Context)$")

# Annotation wrappers that are transparent — the collaborator is inside them. `Union`
# is here for the same reason `X | None` is unwrapped: without it, prefect's
# `Union[GitCredentials, Block, dict[str, Any], None]` reduced to the literal name
# `Union` and passed the non-primitive test.
_TRANSPARENT_GENERICS = frozenset({"Optional", "Union", "Annotated", "Awaitable", "Coroutine", "Final", "ClassVar"})

# Bases that make a same-module class a data type, so a parameter annotated with it is
# a value being passed, not a port being injected.
_DATA_BASES = frozenset(
    {
        "BaseModel",
        "RootModel",
        "TypedDict",
        "NamedTuple",
        "Enum",
        "StrEnum",
        "IntEnum",
        "IntFlag",
        "Flag",
        "Struct",
        "Exception",
        "BaseException",
    }
)

# Decorators that turn a class into a record. `dataclass`/`define` cover stdlib
# dataclasses, attrs and msgspec-style declarations.
_DATA_DECORATORS = frozenset({"dataclass", "dataclasses", "define", "frozen", "mutable", "attrs", "attr", "s"})

# Method decorators that mean the callable is not an instance method a consumer calls
# through the port: descriptors, factories and namespaced helpers.
_NON_METHOD_DECORATORS = frozenset({"property", "cached_property", "staticmethod", "classmethod"})

# Method decorators that declare the class is already an interface without an ABC base.
_INTERFACE_DECORATORS = frozenset({"abstractmethod", "abstractproperty", "overload"})

# Class decorators that bind the class to a declared interface. `zope.interface`'s
# `@implementer(IIntegrityService)` is exactly the port this rule asks for, spelled the
# way pyramid projects spell it.
_IMPLEMENTS_DECORATORS = frozenset({"implementer", "implementer_only", "provider", "runtime_checkable", "register"})

# Parameter types that only appear on an HTTP route handler. A class whose public
# methods take these is the web layer, whatever it calls itself — see the module
# docstring on `ReceiptService`.
_HTTP_PARAM_TYPES = frozenset({"Request", "Response", "BackgroundTasks", "WebSocket", "UploadFile"})

# Callables used as FastAPI/Starlette parameter markers, either inside an `Annotated[...]`
# or as the parameter's default. `Path` and `File` are also stdlib-ish names, which is why
# only the *call* form counts: `Annotated[str, Path()]` is a route, `path: Path` is not.
_HTTP_PARAM_MARKERS = frozenset({"Header", "Query", "Depends", "Body", "Path", "Form", "File", "Cookie", "Security"})

# Directory segments that hold programs rather than importable library code.
_SCRIPT_DIR_NAMES = frozenset({"scripts", "bin", "tools", "migrations", "alembic", "management", "commands"})

# Directory segments and file stems that hold shared test doubles but are not `tests/`.
_TEST_HELPER_DIRS = frozenset({"testing", "fakes", "mocks", "doubles", "test_fakes", "test_doubles", "test_utils"})
_TEST_HELPER_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")

# One public method is a function in a trenchcoat; an ABC over it is ceremony.
_MIN_PUBLIC_METHODS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class RequirePortForService(Rule):
    """A concrete service with injected collaborators and no ABC above it cannot be substituted."""

    id: str = "require-port-for-service"
    code: str = "SARJ071"
    description: str = (
        "Concrete `*Service`/`*Store`/`*Client` with injected collaborators and no ABC — consumers "
        "must depend on the concrete class, so their tests can only mock it."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag service classes that have no abstract base to be substituted through.

        Returns:
            One diagnostic per unsubstitutable service class, sorted by position.

        """
        if not _is_library_source(path) or is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _has_main_guard(tree):
            return []

        classes: list[ast.ClassDef] = []
        bound_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node)
                bound_names.add(node.name)
            elif isinstance(node, ast.ImportFrom | ast.Import):
                bound_names.update(alias.asname or alias.name.rpartition(".")[2] for alias in node.names)
        data_names = {node.name for node in classes if _is_data_type(node)}

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` injects `{collaborator}` and exposes {_public_method_count(node)} public "
                    "methods, but has no abstract base, so every consumer has to name the concrete class and "
                    "the only way to test one is to patch or mock it. Extract the public methods onto an "
                    f"`abc.ABC` (or a `Protocol`) and have `{node.name}` implement it, so consumers depend on "
                    "the port and tests can pass a real or purpose-built implementation instead of a mock."
                ),
            )
            for node in classes
            if (collaborator := _unsubstitutable_service(node, data_names, bound_names)) is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_library_source(path: Path) -> bool:
    """Report whether `path` holds importable production code.

    Excludes tests, shared test-double modules and program directories
    (`scripts/`, `bin/`, `migrations/`), none of which have consumers that need
    a port to depend on.

    Returns:
        True when the file is production library code.

    """
    if is_test_path(path):
        return False
    parts = set(path.parts)
    if parts & _TEST_HELPER_DIRS or parts & _SCRIPT_DIR_NAMES:
        return False
    return not _TEST_HELPER_STEM_RE.search(path.stem)


def _has_main_guard(tree: ast.Module) -> bool:
    """Report whether the module is its own entry point.

    A top-level `if __name__ == "__main__":` marks a program. Its classes are
    wiring for one process, not a seam other modules depend on — the rule's one
    measured false positive, `LogtoAdminClient`, was exactly this.

    Returns:
        True when a top-level `__main__` guard is present.

    """
    return any(
        isinstance(stmt, ast.If)
        and any(isinstance(name, ast.Name) and name.id == "__name__" for name in ast.walk(stmt.test))
        for stmt in tree.body
    )


def _unsubstitutable_service(
    node: ast.ClassDef, data_names: frozenset[str] | set[str], bound_names: frozenset[str] | set[str]
) -> str | None:
    """Decide whether `node` is a service class with no port above it.

    Returns:
        The name of the injected collaborator that motivates the port, or None
        when the class is exempt.

    """
    if node.name.startswith("_") or not _SERVICE_NAME_RE.search(node.name):
        return None
    if _BASE_NAME_RE.match(node.name) or _names_a_port_in_scope(node.name, bound_names):
        return None
    if _has_base(node) or _is_data_type(node) or _declares_interface(node):
        return None
    if _public_method_count(node) < _MIN_PUBLIC_METHODS or _handles_http_requests(node):
        return None
    return _injected_collaborator(node, data_names)


def _handles_http_requests(node: ast.ClassDef) -> bool:
    """Report whether the class's public methods are HTTP route handlers.

    The name gate can exclude `*Router`, but not a router that calls itself a
    service — summer's `ReceiptService`
    (`sarj/applications/receipts/receipt_service.py:42`) is `ReceiptRouter`'s body,
    and its two public methods take `Request`, `BackgroundTasks` and
    `Annotated[..., Header()]`. A signature written in a web framework's vocabulary
    is a transport boundary, not a port: an ABC over it substitutes nothing, because
    the thing on the other side is the framework.

    Returns:
        True when some public method takes a request/response object or a
        FastAPI-style parameter marker.

    """
    return any(
        _is_http_parameter(param, default)
        for method in _methods(node)
        if not method.name.startswith("_")
        for param, default in _params_with_defaults(method)
    )


def _params_with_defaults(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, ast.expr | None]]:
    """Pair every parameter of `method` with its default expression.

    Returns:
        One `(parameter, default or None)` tuple per declared parameter.

    """
    args = method.args
    positional = [*args.posonlyargs, *args.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    return [
        *zip(positional, [*padding, *args.defaults], strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]


def _is_http_parameter(param: ast.arg, default: ast.expr | None) -> bool:
    """Report whether one parameter belongs to a web framework rather than a domain call.

    Returns:
        True for a request/response annotation, or for a marker call such as
        `Header()` in an `Annotated[...]` or as the parameter's default.

    """
    if param.annotation is not None:
        for inner in ast.walk(param.annotation):
            if isinstance(inner, ast.Name | ast.Attribute) and _dotted_tail(inner) in _HTTP_PARAM_TYPES:
                return True
            if isinstance(inner, ast.Call) and _dotted_tail(inner.func) in _HTTP_PARAM_MARKERS:
                return True
    return isinstance(default, ast.Call) and _dotted_tail(default.func) in _HTTP_PARAM_MARKERS


def _names_a_port_in_scope(name: str, bound_names: frozenset[str] | set[str]) -> bool:
    """Report whether the class name is a qualified form of a port already in scope.

    `PsqlTaskStore` next to `TaskStore` is this codebase's own naming convention
    for "implementation of that port", and litellm spells structural `Protocol`
    conformance the same way — `CachedOAuthTokenStore` and
    `LazyPerUserOAuthTokenStore` both satisfy `OAuthTokenStore(Protocol)` without
    inheriting it, because `Protocol` is structural. A rule that demands *nominal*
    inheritance would be wrong on every Protocol-first codebase; this is the guard
    that keeps it honest.

    The suffix has to start at a CamelCase boundary and has to be service-shaped
    itself, or any coincidentally-imported noun would silence the rule. There is no
    separate minimum length: `_SERVICE_NAME_RE` cannot match anything shorter than
    `DAO`, so a length floor was a conjunct no input could ever exercise.

    Returns:
        True when some service-shaped name in scope is a proper suffix of `name`.

    """
    return any(
        name[index].isupper() and (suffix := name[index:]) in bound_names and bool(_SERVICE_NAME_RE.search(suffix))
        for index in range(1, len(name))
    )


def _has_base(node: ast.ClassDef) -> bool:
    """Report whether the class inherits anything at all.

    Any base — abstract, framework, data or first-party — either supplies the
    substitution point already or puts the class outside this rule's scope.

    Returns:
        True when a base beyond `object` or any class keyword is present.

    """
    if node.keywords:
        return True
    return any(_dotted_tail(base) != "object" for base in node.bases)


def _is_data_type(node: ast.ClassDef) -> bool:
    """Report whether the class is a record rather than a service.

    Returns:
        True for dataclass/attrs-decorated classes and for subclasses of a
        pydantic model, `TypedDict`, `NamedTuple`, `Enum` or `Exception`.

    """
    if any(_dotted_tail(dec) in _DATA_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(base) in _DATA_BASES for base in node.bases)


def _declares_interface(node: ast.ClassDef) -> bool:
    """Report whether the class already declares an interface.

    Returns:
        True when a class decorator binds it to one (`@implementer(...)`), or any
        method carries `@abstractmethod` or `@overload`.

    """
    if any(_dotted_tail(dec) in _IMPLEMENTS_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(dec) in _INTERFACE_DECORATORS for method in _methods(node) for dec in method.decorator_list)


def _methods(node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [stmt for stmt in node.body if isinstance(stmt, _FUNC_NODES)]


def _public_method_count(node: ast.ClassDef) -> int:
    """Count the instance methods a consumer would call through a port.

    Properties, `staticmethod`s and `classmethod`s do not count: a property is
    state and a classmethod is a factory, and neither is behaviour a substitute
    would need to reimplement. Dunders do not count either, which is what exempts
    `__call__`-only strategy objects.

    Returns:
        The number of public instance methods.

    """
    return sum(
        1
        for method in _methods(node)
        if not method.name.startswith("_")
        and not any(_dotted_tail(dec) in _NON_METHOD_DECORATORS for dec in method.decorator_list)
    )


def _injected_collaborator(node: ast.ClassDef, data_names: frozenset[str] | set[str]) -> str | None:
    """Find a constructor parameter that is a real collaborator stored on `self`.

    Returns:
        The annotation of the first such parameter, or None when the constructor
        takes only values, configuration and ambient runtime objects.

    """
    init = next((method for method in _methods(node) if method.name == "__init__"), None)
    if init is None:
        return None
    stored = _self_assigned_names(init)
    args = init.args
    for param in [*args.posonlyargs, *args.args[1:], *args.kwonlyargs]:
        annotation = _annotation_tail(param.annotation)
        if annotation is None or annotation in _PRIMITIVE_ANNOTATIONS or annotation in data_names:
            continue
        if _WEAK_COLLABORATOR_RE.search(annotation):
            continue
        if param.arg in stored or f"_{param.arg}" in stored:
            return annotation
    return None


def _self_assigned_names(init: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect the `self.<attr>` names assigned anywhere in the constructor.

    Returns:
        The attribute names bound on `self`.

    """
    names: set[str] = set()
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        else:
            continue
        names.update(
            target.attr
            for target in targets
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
        )
    return names


def _annotation_tail(annotation: ast.expr | None) -> str | None:
    """Reduce an annotation to the identifier that names its type.

    Unwraps string forward references, `X | None`, `Optional[X]` and
    `Annotated[X, ...]`; a subscripted container keeps the container's name, so
    `dict[str, Row]` reads as `dict` and is treated as a value.

    Returns:
        The type's final identifier, or None when it cannot be determined.

    """
    if annotation is None:
        return None
    if isinstance(annotation, ast.Constant):
        if not isinstance(annotation.value, str):
            return None
        try:
            parsed = ast.parse(annotation.value, mode="eval")
        except SyntaxError, ValueError:
            return None
        return _annotation_tail(parsed.body)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        for side in (annotation.left, annotation.right):
            tail = _annotation_tail(side)
            if tail is not None and tail != "None":
                return tail
        return None
    if isinstance(annotation, ast.Subscript):
        outer = _dotted_tail(annotation.value)
        if outer not in _TRANSPARENT_GENERICS:
            return outer
        inner = annotation.slice
        if isinstance(inner, ast.Tuple):
            inner = inner.elts[0] if inner.elts else inner
        return _annotation_tail(inner)
    return _dotted_tail(annotation)


def _dotted_tail(node: ast.expr) -> str | None:
    """Reduce an expression to its final identifier.

    Returns:
        `Store` for `Store`, `stores.Store` and `Store[int]`; None otherwise.

    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _dotted_tail(node.value)
    if isinstance(node, ast.Call):
        return _dotted_tail(node.func)
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return None
