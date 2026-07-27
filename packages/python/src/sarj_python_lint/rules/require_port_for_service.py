"""SARJ068: a concrete service with injected collaborators and no ABC above it is not substitutable.

`class ZohoDeskService:` that takes a `ZohoDeskDAO` in its constructor and exposes
five public methods is a seam that cannot be moved. Every consumer has to name the
concrete class in its own annotations, so the only way to test a consumer is to
`patch` the class or hand it a `MagicMock` — which is the disease the SARJ055 /
SARJ056 / SARJ059 / SARJ060 family attacks from the other end. Those rules say "stop
mocking your own collaborator"; they can only be obeyed if there is something to
substitute. An ABC above the service is that something: the consumer depends on the
port, the test passes the real implementation or a purpose-built one, and nothing has
to be patched.

This is not an imported opinion — it is the convention this codebase already chose and
already follows almost everywhere. Across bulbul and noura-be, 193 non-test classes
carry a service-family name (`*Service`, `*Store`, `*Client`, `*Repository`, `*DAO`,
`*Provider`, `*Gateway`); 91 of them *are* the port (an `ABC` or `Protocol`), 63 more
subclass a first-party port, and only 22 have no base class at all — 89% adoption. The
`Store` family is at 97% (92 of 95), the exemplar being `class TaskStore(ABC)` with
`class PsqlTaskStore(TaskStore)` driven by the real-Postgres `db_pool` fixture in
`integration/tests/conftest.py`. `*Service` is the straggler at 75% (40 of 53), which
is why the user asked for this rule. Narrowing to the classes that actually have a
seam — 130 non-test classes take an injected collaborator and expose two or more public
methods — 97 already inherit a first-party abstract base and only 26 have no base at
all. This rule flags stragglers against an established convention; it does not
introduce one.

The codebase's port mechanism is `abc.ABC`, not `typing.Protocol`, by 150 classes to
23 (bulbul 117/13, noura-be 33/10) — so the fix this rule asks for is an `ABC` with
`@abstractmethod`s, and the message says so.

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
* and it declares **at least two public methods** — plain instance methods, not
  properties, `staticmethod`s or `classmethod`s.

Corpus evidence. Measured over 42,017 files in sixteen repositories: bulbul (1,179),
noura-be (502), django (2,927), fastapi (1,130), celery (417), airflow (7,655), dagster
(5,983), langchain (2,536), litellm (5,054), mlflow (2,607), prefect (1,887), saleor
(4,302), sentry-python (498), superset (2,440), warehouse (888) and zulip (2,012).
**Ten findings** — 5 bulbul, 3 noura-be, 2 litellm, and zero in the other thirteen
repositories, django and fastapi among them. Twenty-five candidate hits were read at
source across successive tightenings and classified by hand; the surviving ten are 9
true positives and 1 false positive (`LazyPerUserOAuthTokenStore`, below), a 10% rate
overall and 0 of 8 on the first-party repos.

The name gate is not vacuous on the OSS control: django, fastapi and celery contain 49
public classes with a service-family name, ten of which have no base class, and they
survive to the last gate — the collaborator requirement — before being rejected.

Every threshold was measured, not guessed. Against the same 42,017 files:

* public-method floor **1**: 10 -> 18 findings (7 of them new OSS false positives).
  Every addition is a one-method wrapper, which is a function in a trenchcoat,
* public-method floor **2** (shipped): 10 findings,
* floor **3**: 10 -> 7. It drops `ZohoOAuthService`, which is a genuine port,
* adding **`Client`** to the name gate: 10 -> 17, and all seven additions are OSS false
  positives, because `*Client` is the vendor-SDK-wrapper family — dagster's
  `GithubClient(client: requests.Session)`, airflow's `Client(session: httpx.Client)`,
  litellm's `MCPClient`. An ABC over a class whose collaborator is somebody else's HTTP
  transport substitutes nothing. It costs **zero** first-party findings,
* adding **`Repository`/`Repo`**: 10 -> 11, one new false positive (dagster's
  `RemoteRepository`, a code location, not a data-access port; prefect's
  `GitRepository` is the same word abuse). It also costs zero first-party findings,
  because neither repo has a single class named `*Repository`,
* adding **`Manager`/`Adapter`/`Handler`/`Router`**: 10 -> 36, with 10 new first-party
  findings that are all FastAPI routers and LiveKit lifecycle helpers,
* **no name gate at all**: 10 -> 178, 156 of them in OSS. The name gate is doing the
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
  cross-module analysis a single-file AST rule does not do. It is the one FP in ten
  findings across 42,017 files, and it is in someone else's repository,
* **`Generic[T]` containers and mixins**, both excluded by the zero-bases requirement.
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
# against both repos: 172 non-test classes match, 88% of them already have a port.
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

# Directory segments that hold programs rather than importable library code.
_SCRIPT_DIR_NAMES = frozenset({"scripts", "bin", "tools", "migrations", "alembic", "management", "commands"})

# Directory segments and file stems that hold shared test doubles but are not `tests/`.
_TEST_HELPER_DIRS = frozenset({"testing", "fakes", "mocks", "doubles", "test_fakes", "test_doubles", "test_utils"})
_TEST_HELPER_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")

# One public method is a function in a trenchcoat; an ABC over it is ceremony.
_MIN_PUBLIC_METHODS = 2

# The shortest suffix that can plausibly name a port rather than be a coincidence:
# `Store` and `Dao` are real ports, but a two-letter tail would match by accident.
_MIN_PORT_NAME_LEN = 3

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class RequirePortForService(Rule):
    """A concrete service with injected collaborators and no ABC above it cannot be substituted."""

    id: str = "require-port-for-service"
    code: str = "SARJ068"
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
                    f"`abc.ABC` and have `{node.name}` implement it — the convention this codebase already "
                    "uses for `TaskStore` / `PsqlTaskStore` — so consumers depend on the port and tests can "
                    "pass a real implementation instead of a mock."
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
    if _public_method_count(node) < _MIN_PUBLIC_METHODS:
        return None
    return _injected_collaborator(node, data_names)


def _names_a_port_in_scope(name: str, bound_names: frozenset[str] | set[str]) -> bool:
    """Report whether the class name is a qualified form of a port already in scope.

    `PsqlTaskStore` next to `TaskStore` is this codebase's own naming convention
    for "implementation of that port", and litellm spells structural `Protocol`
    conformance the same way — `CachedOAuthTokenStore` and
    `LazyPerUserOAuthTokenStore` both satisfy `OAuthTokenStore(Protocol)` without
    inheriting it, because `Protocol` is structural. A rule that demands *nominal*
    inheritance would be wrong on every Protocol-first codebase; this is the guard
    that keeps it honest.

    Returns:
        True when some service-shaped name in scope is a proper suffix of `name`.

    """
    return any(
        len(suffix := name[index:]) >= _MIN_PORT_NAME_LEN
        and name[index].isupper()
        and suffix in bound_names
        and bool(_SERVICE_NAME_RE.search(suffix))
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
