# SARJ071 `require-port-for-service` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_require_port_for_service.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`class TicketingService:` that takes a `TicketingDAO` in its constructor and exposes
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
number was one repo's — repo C in the table below — and the convention it
describes is repo C's. Counting public,
non-test classes whose name ends in a service-family token (`*Service`, `*Store`,
`*DAO`, `*Gateway`, `*Provider`) and asking how many have no base class at all, across
every first-party Python repo on the machine:

| repo | service-family classes | no base | already have a base |
|---|---|---|---|
| repo A | 16 | 0 | 100% |
| repo B | 12 | 0 | 100% |
| repo C | 140 | 8 | 94% |
| repo D | 18 | 1 | 94% |
| repo E | 23 | 4 | 83% |
| repo F | 14 | 3 | 79% |
| repo G | 26 | 8 | 69% |
| repo H | 4 | 2 | 50% |
| repo I | 26 | 16 | 38% |

(Repo labels are stable within this docstring only. A tenth first-party repo,
repo J, is absent from the table because it has no service-family classes at all.)

repo C is where the convention is strongest and where the rule was written; it is not
where the findings are. **repo I alone accounts for 15 of the 30 first-party
findings** — eight feature modules, each a `class XStore: def __init__(self, pool:
AsyncConnectionPool)` paired with a `class XService: def __init__(self, store: XStore)`,
no base anywhere. Every one is a true positive by this rule's definition — nothing in
that service layer is substitutable, and its tests can only mock — but they are not
stragglers behind a local convention. They are the repo's architecture.

So the framing the data supports is: **this rule reports service layers with no seam.**
Where ports are already the norm (repos A, B, C and D) the output is a short
list of exceptions and reads as "you missed these". Where they are not (repos I,
H and G) the output is a description of the design, and the response owed is a
decision about the design, not eight small refactors. Turning the rule on in a new repo
should start with the count, not with the diff.

**Why the message carves out persistence ports.** The advice "tests can pass a
purpose-built implementation" is wrong for two of this rule's own name tails. Take the
service this rule reports and do exactly what it asks:

```python
class InMemoryUserStore(UserStore):    # the port SARJ071 asked for
    def upsert(self, user: User) -> None: self._rows[user.id] = user
    def get(self, user_id: str) -> User | None: return self._rows.get(user_id)
```

and SARJ058 `prefer-real-store-in-tests` fires on the class definition and forbids it,
because a dict diverges from the backend on unique and foreign-key constraints, `ON
CONFLICT` upserts, transaction rollback, `ORDER BY` and NULL ordering. Both rules are
right in their own domain: a purpose-built double is the whole point of a port, *except*
where a real implementation plus a test database already exists. SARJ058 is unchanged;
the contradiction is resolved here, in one clause of this rule's message. Note the
carve-out is advice only — it changes no finding in any corpus.

The port mechanism these repos reach for is `abc.ABC` rather than `typing.Protocol`, by
150 classes to 23 (repo C 117/13, repo G 33/10), so the message names `abc.ABC`
first. It names `Protocol` as the alternative and cites no repo's class names: the rule
also runs on code that has never seen this codebase, and "follow the convention used for
`OrderStore` / `PsqlOrderStore`" is not an instruction litellm can act on.

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
first-party — repo C (1,179), repo G (502), repo I (267), repo J (194), repo F
(179), repo H (88), repo D (81), repo B (76), repo A (67), repo E (42), 2,675 files — and
fourteen open-source: airflow (7,655), dagster (5,982), litellm (5,054), saleor (4,301),
django (2,927), mlflow (2,594), langchain (2,536), superset (2,440), zulip (2,012),
prefect (1,887), fastapi (1,130), warehouse (888), sentry-python (498), celery (417),
40,321 files.

**Thirty-two findings**: 30 first-party — repo I 15, repo C 5, repo E 4, repo G 3,
repo F 3, and zero in repos J, A, B, H and D — and **2 in the 40,321
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
  first-party one-method wrappers — `TranslationService` in both repo G and
  repo I, repo G's `EmailService`, repo C's `MediaPreviewService`, repo H's
  `ModelService` — and five are OSS. A one-method class is a function in a trenchcoat
  and an ABC over it is ceremony,
* public-method floor **2** (shipped): 32 findings,
* floor **3**: 32 -> 23, +0 and -9. It removes the one known false positive
  (`LazyPerUserOAuthTokenStore`) at a cost of eight true positives: all four of repo E's
  `*ProvisioningService`s, repo I's `AuthService` and `MfaService`, and repo C's
  `ReportGenerationService` and `VendorOAuthService`. Not a trade worth making,
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
  `SipConnectionRouter`, `PhoneNumberRouter`, `CommerceRouter`, `CustomRecordRouter`), a
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
  corpus that reach every other gate (`Client` and `AuthenticatedClient`, in a
  first-party generated OpenAPI client package) are generated OpenAPI
  transport structs,
* **FastAPI routers, middleware, and DI wiring.** One first-party
  `OrganizationRouter` injects seven stores and its
  `SipConnectionRouter`
  injects seven services — they are the composition root, the place concrete types are
  *supposed* to be named, and putting an ABC over an HTTP router substitutes nothing.
  Same for the same repo's `AuthorizationMiddleware`. The name gate
  excludes all six routers plus the middleware,
* **routers that call themselves services**, which the name gate cannot help with.
  repo D's `ReceiptService` is `ReceiptRouter`'s body: its
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
* **entry-point scripts.** One first-party `AdminApiClient`
  in a provisioning script passes every shape test — an
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
  `fakes/`, `mock*.py`), which is what keeps the rule off a first-party
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
  way this codebase spells `PsqlOrderStore` : `OrderStore` — `CachedOAuthTokenStore`
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

## Implementation notes

### `_annotation_tail`

Unwraps string forward references, `X | None`, `Optional[X]` and
`Annotated[X, ...]`; a subscripted container keeps the container's name, so
`dict[str, Row]` reads as `dict` and is treated as a value.

### `_public_method_count`

Properties, `staticmethod`s and `classmethod`s do not count: a property is
state and a classmethod is a factory, and neither is behaviour a substitute
would need to reimplement. Dunders do not count either, which is what exempts
`__call__`-only strategy objects.

### `_has_base`

Any base — abstract, framework, data or first-party — either supplies the
substitution point already or puts the class outside this rule's scope.

### `_names_a_port_in_scope`

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

### `_handles_http_requests`

The name gate can exclude `*Router`, but not a router that calls itself a
service — one first-party `ReceiptService` is `ReceiptRouter`'s body,
and its two public methods take `Request`, `BackgroundTasks` and
`Annotated[..., Header()]`. A signature written in a web framework's vocabulary
is a transport boundary, not a port: an ABC over it substitutes nothing, because
the thing on the other side is the framework.

### `_has_main_guard`

A top-level `if __name__ == "__main__":` marks a program. Its classes are
wiring for one process, not a seam other modules depend on — the rule's one
measured false positive, `AdminApiClient`, was exactly this.

### `_is_library_source`

Excludes tests, shared test-double modules and program directories
(`scripts/`, `bin/`, `migrations/`), none of which have consumers that need
a port to depend on.
