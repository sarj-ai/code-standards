# `require-interface-for-injected-service` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/require-interface-for-injected-service.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

An exported concrete class that takes injected collaborators and
has no interface above it is not substitutable. Every consumer must import and
depend on the concrete class, so the only way to test a consumer is to mock the
class — the exact failure the Python side of this standard attacks with
`prefer-real-store-in-tests` / `prefer-library-fake`. An interface (a port),
even a two-method one, lets a consumer's test pass a real alternative
implementation instead of a mock.

The rule fires on an EXPORTED, non-abstract class declaration that
  (a) has no `implements` clause and does not `extend` anything,
  (b) stores >=1 constructor collaborator — either a named parameter whose type
      is a bare type reference (not a primitive, literal, union, or function
      type), or a binding destructured out of an options-object parameter
      (`constructor({ userRepo }: Deps)`) — that is not a config/options/
      callback bag and is not a generic type parameter, a built-in container or
      an in-file alias to a function type, and
  (c) declares >=1 public instance method (a class with only a constructor,
      fields, or getters is a value object / DTO, not a service).

CORPUS SWEEP (2026-07, re-measured over 18 first-party repos, written below
as `repo A` .. `repo R`; one label per repo, stable within this docstring
only). 286 exported class declarations
in non-test / non-generated files; 216 already carry an `implements` clause,
extend a base class, or are themselves abstract. 76% of the population is
ALREADY compliant, which is what makes this a lint rule rather than a design
proposal. 30 fire after the two guards below (35 before them).

The earlier sweep read 82% of 229 because it covered only the first twelve
repos; the six added here are where both false-positive families lived, and
both were invisible to it. Adoption varies far more than the aggregate
suggests: repo C (62/62), repo A (32/32, the flagship product), repo Q
(12/12), repo K and repo D are at 100%; repo N 86%, repo J 83%, repo M 80%,
repo H 71%, repo I 56%, repo L / repo O / repo P 50%, repo B 46% (32 of
69), repo R 29%, repo F 25%. The rule is a ratchet for the low half, not a
description of the high half.

The convention being enforced is `interface`, not `abstract class`, and the
corpus is unambiguous about it: 175 `implements` clauses against exactly ONE
hand-written abstract class in 7,912 files (a lone content-generation helper
in repo K). (A raw grep finds ~220 more `abstract class` tokens in repo D
and repo E; every one is an ambient Cloudflare declaration inside
`worker-configuration.d.ts`, excluded here as generated.) Three impl-naming
conventions coexist — `HttpMessageService implements MessageService`
(repo A), `ApiClient implements IApiClient` (repo B, repo C, repo H), and
`ReportParserImpl` / `ReportParser` (repo J) — so the message names no
interface for you.

FIRING DISTRIBUTION, and why the hits are outliers rather than a house style
(before -> after the two guards below):
  repo B             69 exported classes, 20 -> 20 hits
  repo H             17 exported classes,  3 ->  3 hits
  repo J             24 exported classes,  3 ->  2 hits
  repo M             20 exported classes,  3 ->  2 hits
  repo I              9 exported classes,  2 ->  2 hits
  repo L              2 exported classes,  1 ->  1 hit
  repo N             14 exported classes,  1 ->  0 hits
  repo O              2 exported classes,  1 ->  0 hits
  repo P              2 exported classes,  1 ->  0 hits
  repo A / repo C / repo Q / repo K / repo D / repo E / repo G /
  repo F / repo R: 0 hits

THE FALSE-POSITIVE RATE WAS 14%, NOT 0-3.4%. The earlier claim rested on a
sweep that never reached repo M, repo N, repo O or repo P, and both
false-positive families live only there (plus one instance each already in
repo J and, for the transport family, nowhere the old sweep looked). Of 35
raw hits, 5 were false: three copies of one express router template and two
copies of one `ky` wrapper. The two guards below remove exactly those 5 and
cost 0 true positives — verified hit-by-hit across all 18 repos, 35 -> 30.

The origin case, raised in review on repo B, is a task-runner service:
`class RecordNormalizerService` holds one god-object collaborator
(`svc: ServiceRegistry`), exposes one `run` method, and implements nothing.
Its own test has to build the collaborator with
`{ ... } as unknown as ServiceRegistry` — the cast-mock this rule is trying
to make unnecessary. Its sibling in the same directory tree is the same
shape done right: `class TaskTrackerService implements ITaskTrackerService`.

Two further confirmations that the rule finds real drift rather than taste:

  - The composition root of repo H types 8 of its 11 fields as `I*`
    interfaces and 3 as concrete classes. The rule fires on exactly those
    three — the repo's own composition root already documents which classes
    are missing a port.
  - One site in repo J declares `interface ReportParser` three lines above
    `class ReportParserImpl`, which never says `implements`. The port exists
    and the impl is silently free to drift from it.

NAMED FALSE POSITIVES that shaped the guards (each measured, not imagined):
  - One site in repo B: `JsonHttpClient` takes
    `options: JsonHttpClientOptions`, whose three fields are all
    primitives. A config bag is not a collaborator seam -> config-ish type
    suffixes and parameter names are excluded. Cost: 1 of 32 raw hits.
  - One site in repo F: a realtime-session manager takes
    `callbacks: RealtimeSessionCallbacks`, an OUTBOUND observer bag, not an
    inbound dependency; there is nothing to substitute. -> `Callbacks`
    suffix and `callbacks` parameter name excluded. Cost: 1 of 32.
  - One site in repo H: a `ServiceFactory` receives a `db` and `new`s eleven
    services onto its own fields. That is a composition
    root: it is where concrete types are supposed to be named, and a port
    above it protects nobody. -> a constructor that BUILDS more fields than it
    RECEIVES collaborators is exempt. Cost: 1 of 32.

    The first cut of that guard exempted any constructor containing a `new`
    at all, and the corpus immediately punished it: two sibling message
    handlers in repo B each take `svc: ServiceRegistry` AND build one
    internal `TaskProcessor`, and both silently stopped firing. Constructing
    a helper is not being a wiring class; the ratio is what separates the
    two.

  - FRAMEWORK ROUTERS. Three sites — one each in repo J, repo M and repo N —
    are three copies of one job-runner template:
    `MainRouter(taskStore, taskExecutor)` whose `init()`
    returns an `express.Router()`. The server's bootstrap mounts it; nothing
    injects it, so there is no consumer to hand a port to. -> a class whose
    body manufactures a router (`express.Router()` / `Router()`) or handles
    the framework's own namespaced request/response types
    (`express.Request`) is exempt. The DOM `Request`/`Response` globals a
    Workers `fetch` handler names are unqualified and deliberately do not
    match. Cost: 3 of 35 raw hits, all three false positives, 0 true
    positives lost.

  - TRANSPORT WRAPPERS. Two sites, one in repo O and one in repo P, are two
    copies of `LedgerHttpClient(private readonly client: KyInstance)`. These
    are
    false by this standard's own stated reasoning: the Python twin excludes
    `*Client` precisely because an ABC over a class whose collaborator is
    somebody else's HTTP transport substitutes nothing — a consumer's test
    fakes the transport (`respx`, `nock`, `msw`), not the wrapper. -> a class
    is exempt when its ONLY collaborator is a third-party transport
    (`KyInstance`, `AxiosInstance`, `Session`), it is named `*Client`, AND no
    interface in the same file shares its stem. All three arms are load
    bearing. The `*Client` arm is what keeps the corpus's two
    `AxiosInstance`-only domain wrappers — repo I's `HttpMessageService` and
    repo J's `ReportParserImpl` — firing, because both
    wrap the transport in a domain operation their consumers can substitute.
    The same-file-interface arm has zero measured cost and is kept as a
    precaution: a `FooClient` beside an `IFooClient` it never `implements` is
    exactly the drift this rule exists for, and the corpus cannot prove that
    shape's absence elsewhere. Cost: 2 of 35 raw hits, both false positives,
    0 true positives lost.

GUARDS WITH ZERO MEASURED COST, kept as precautions because the corpus is
first-party and cannot prove their absence elsewhere: decorated classes
(NestJS-style `@Injectable()` providers are instantiated by class token, so
the class IS the contract — 0 decorated classes in the corpus), and a
logger/clock-only dependency (weak evidence of a real seam — 0 such classes).

GUARDS THAT NEED NO CODE, because `extends` already covers them: React class
components (`extends React.Component`), Lexical/editor nodes
(`extends TextNode`, `extends DecoratorNode`), error classes
(`extends Error`), Durable Objects, Workflows and custom elements. Every one
of the 4 exported classes in `.tsx` files across the corpus is such a case
(two editor-node classes in repo A, plus one error-boundary component that
appears once in repo D and once in repo E). Extending a
framework base class is itself a form of port.

THE ONE-METHOD THRESHOLD is the load-bearing difference from the Python
sibling `require_port_for_service` (SARJ063), which demands >=2 public methods
and a `*Service`/`*Store`/`*Client` name. Measured here: 22 of the 29 hits
expose exactly ONE public method (the distribution is 22x1, 1x2, 1x5, 1x6,
1x8, 2x9, 1x12), so a >=2 threshold would discard 76% of them — including the
origin case, whose sole method is `run`. A service-family NAME filter would
cost as much: `TaskProcessor`, `InteractiveActionHandler`,
`ReportParserImpl`, `MainRouter` and every `*Handler` in repo B carry
no such suffix. TypeScript's `export` keyword plus a stored collaborator is
the proxy for "someone depends on this" that Python has to approximate with
naming, so this rule leans on those two instead.

## THE OPTIONS-OBJECT CONSTRUCTOR WAS NOT ABSENT, THE CORPUS WAS (2026-07)

The paragraph this replaces called `constructor({ a, b }: Deps)` a deliberate
false negative "measured at 0 occurrences in the corpus". That was true of the
18 first-party repos it was measured on and false of the language.

Re-measured over 48 public TypeScript repos — 111,477 non-test / non-generated
`.ts` / `.tsx` files, 20 of them NestJS / Angular / DI-heavy (nest, angular,
angular/components, medusa, backstage, novu, twenty, n8n, nocodb, strapi,
directus, vendure, immich, teable, ghostfolio, amplication, remult, inversify,
routing-controllers, Rocket.Chat) precisely because those favour the shape, and
28 general-purpose (cal.com, storybook, playwright, typeorm, trpc, apollo-client,
dub, formbricks, documenso, midday, nuxt, vite, …).

Of **2,174** exported concrete classes that declare a constructor:

| shape | count |
| --- | ---: |
| takes an options-object parameter | 80 |
| …and also declares a public method (the blind spot) | **73** |
| annotation is an inline type literal | 54 |
| annotation is a named bag | 24 |
| has a defaulted binding | 15 |
| has a rest element | 4 |
| has a renamed binding | 0 |
| public API is arrow properties only | 12 |
| …and also stores a typed collaborator | 8 |

The renamed binding is handled anyway: it is the same three lines as the
defaulted one, and 0 occurrences in 48 repos is not proof of 0 everywhere.

### The bag is resolved, not guessed at

A destructured binding's type is what the config-ish guards need, and it lives
in the bag rather than in the parameter. The first cut let the BAG's own name
stand in for every binding's type, and the corpus punished it at once: 4 of the
7 findings that path produced were false — a boolean (`openLinkOnClick`), two
numbers (`maxBlockTokens`, `concurrency`) and a `setState` / `getState` pair.

So an inline `{ userRepo: UserRepo }` is read directly, a named `Deps` is looked
up among this module's own `interface` / `type` declarations (including the
`type Deps = Base & { … }` form), and a bag declared in another module is left
alone.

### Three shapes wear a nominal name without being an implementation

Reading bag members made these visible enough to measure. Each is the inline
shape clause (b) already rejects, renamed:

  - a generic type parameter — `{ value }: { value: T }`, `data: TData`;
  - a built-in container — `Record`, `Map`, `Set`, `Array`, `Pick`, `Required`,
    `ReturnType`, `ReadonlyArray`;
  - an in-file alias to a function type — `type Replayer = (e: E[]) => void`,
    `type TransformFn`, `type WarningFilter`, `type SendCommand`.

Excluding them costs 5 of the 40 options-object findings and retires 48 of the
968 findings the rule already had. All 48 were read and all 48 are false.

### Net effect on the 48-repo corpus: 968 -> 955

**+35 from the options-object walk, every one read at file:line. 27 true:**
backstage `CachedEntityLoader(catalog: CatalogService, cache: CacheService)`,
`DocsBuilder`, `DocsSynchronizer`, `TechDocsCache`, `CookiecutterRunner`,
`RailsNewRunner`; medusa `AnalyticsService`, `LinkService`, `Migrator`, `Query`,
`Configuration`, `RedisCachingProvider`, two `WorkflowOrchestratorService`s;
four novu caches plus `BaseModule`; n8n `CachedMetricQuery`; teable
`TypeCastAndValidate`; Rocket.Chat `SettingsRegistry`; angular `Dispatcher`;
four `twenty` orchestrator steps that hold a real `ApiService` /
`ClientService`.

**8 false**, each a family the rule already had rather than one the walk
introduced: a `test-utils/TestPipeline` harness over Node streams, medusa's
`ApiLoader` (an express bootstrap that the router guard does not recognise
because it takes `app: Express` rather than calling `Router()`), a
`ts.TypeChecker` docs-generator helper, an agenda `Job` holding a back-reference
to its scheduler, two orchestrator steps whose only binding is a state bag, and
two callbacks aliased in ANOTHER module (`BatchLink.BatchHandler`,
cal.com's `OAuthManager` token functions).

**-48 from the three name-hiding guards**, all false: `value: T`, `data: TData`,
`registry: Map`, `nodes: Array`, `compilerHost: Pick`, `versionProvider:
ReturnType`, `transform: TransformFn`, `filter: WarningFilter`,
`sendToExtension: SendCommand`, and 39 more of the same three kinds.

For scale: a random sample of 12 of the 920 findings the rule already produced
reads 7 true / 5 false. The added shape lands at 27/35 — better than the rule's
own baseline — and the guards raise that baseline.

## DELIBERATE FALSE NEGATIVES that remain, each measured rather than assumed

  - **A class whose public methods are all arrow properties**
    (`handle = async () => {}`). 12 of the 2,174 candidate classes, 8 of which
    also store a typed collaborator — 0.37%. All 8 were read and not one is an
    injected service: a Hono request `Context`, two nocodb `HttpClient`s
    generated by swagger-typescript-api, an id-generation helper over a `Record`
    of prefixes, two Angular CDK aria "pattern" objects, a Medusa SDK auth
    facade, and a `twenty` in-memory testing cache. The shape stays out: a
    second walk over every class body is real AST cost, and it would buy a
    population that is mostly false.
  - **An options-object bag declared in another module**
    (`import type { Deps } from "./deps.js"`). Its member types are what the
    config-ish and name-hiding guards test, and this rule does not resolve
    across modules.
  - **A callback or container hiding behind an alias declared in another
    module** (`BatchLink.BatchHandler`), for the same reason. Measured at 2 of
    the 35 added findings.

## Evidence relocated from the source

### `*/`

Type-name suffixes that mark a constructor parameter as configuration rather
than a collaborator. Deliberately short: every entry here is a silent false
negative for anyone who names a real dependency that way, so it lists only
what the corpus proved (`*Options`, `*Callbacks`) plus the immediate synonyms.
`Handler` / `Listener` / `Store` / `Client` are pointedly ABSENT — those are
exactly the collaborators the rule exists to notice.

### `/** Interface declarations at the top level of this module, `

 `IFooClient` / `FooClientImpl` both reduce to `FooClient`, the three impl conventions the corpus uses.

### `other`

Three conditions, all necessary. The class receives exactly ONE collaborator
and that collaborator is a third-party transport, so there is no domain seam
hiding behind it. It is named `*Client`, which is the arm that keeps the
corpus's `HttpMessageService` and `ReportParserImpl` — both `AxiosInstance`-only
— firing, because those wrap a transport in a *domain* operation and their
consumers do have something to substitute. And no interface in the same file
shares its stem, because an in-file port the class silently fails to
`implements` is the drift this rule exists to catch.

