import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-interface-for-injected-service.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

const SRC = "/repo/src/domain/record-normalizer/service.ts";

ruleTester.run("require-interface-for-injected-service", rule, {
  valid: [
    {
      name: "recognizes a service surface inherited by a local port interface",
      filename: SRC,
      code: `
        interface BasePort { handle(): void; }
        interface RequestPort extends BasePort {}
        export class RequestHandler implements RequestPort {
          constructor(private readonly store: TaskStore) {}
          handle(): void {}
        }
      `,
    },
    // The target state, and the corpus's overwhelming convention: 175 of 229
    // exported classes look like this.
    {
      filename: SRC,
      code: `
        export class RecordNormalizerService implements IRecordNormalizerService {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          async run(): Promise<void> {}
        }
      `,
    },
    {
      name: "keeps arbitrary framework-decorated classes conservative",
      filename: SRC,
      code: `
        @sealed
        export class RequestHandler {
          constructor(private readonly store: TaskStore) {}
          handle(): void {}
        }
      `,
    },
    // The port itself. `abstract class X` must never fire.
    {
      filename: SRC,
      code: `
        export abstract class TaskStore {
          protected readonly db: Database;
          constructor(db: Database) { this.db = db; }
          abstract get(id: string): Promise<void>;
          describe(): string { return "store"; }
        }
      `,
    },
    // Extending anything is a form of port: framework base classes, error
    // classes, React components, Lexical nodes, Durable Objects, Workflows.
    {
      filename: SRC,
      code: `
        export class SyncWorkflow extends WorkflowEntrypoint {
          private readonly store: TaskStore;
          constructor(store: TaskStore) { super(); this.store = store; }
          async run(): Promise<void> {}
        }
      `,
    },
    {
      filename: SRC,
      code: `
        export class ApiError extends Error {
          private readonly cause2: HttpResponse;
          constructor(cause2: HttpResponse) { super("boom"); this.cause2 = cause2; }
          describe(): string { return "err"; }
        }
      `,
    },
    {
      filename: "/repo/src/components/boundary.tsx",
      code: `
        export default class WidgetErrorBoundary extends React.Component<Props, State> {
          private readonly reporter: ErrorReporter;
          constructor(reporter: ErrorReporter) { super(reporter); this.reporter = reporter; }
          render(): JSX.Element { return null as never; }
        }
      `,
    },
    // Framework-mandated: NestJS-style providers are instantiated by class
    // token, so the class IS the contract.
    {
      filename: SRC,
      code: `
        @Injectable()
        export class CatsService {
          private readonly repo: CatRepository;
          constructor(repo: CatRepository) { this.repo = repo; }
          findAll(): Promise<Cat[]> { return this.repo.all(); }
        }
      `,
    },
    {
      name: "ignores an anonymous default class because no interface name can be suggested",
      filename: SRC,
      code: `
        export default class {
          constructor(private readonly store: TaskStore) {}
          run(): void {}
        }
      `,
    },
    // Not exported: a module-private helper has no consumer to protect.
    {
      filename: SRC,
      code: `
        class RecordNormalizerService {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          async run(): Promise<void> {}
        }
      `,
    },
    // Value object / DTO: constructor only, no public method.
    {
      filename: SRC,
      code: `
        export class NormalizationPlan {
          private readonly candidates: NormalizationCandidate;
          constructor(candidates: NormalizationCandidate) { this.candidates = candidates; }
        }
      `,
    },
    // Accessors only — `kind === "get"` is not a public method.
    {
      filename: SRC,
      code: `
        export class Money {
          private readonly amount: Decimal;
          constructor(amount: Decimal) { this.amount = amount; }
          get value(): Decimal { return this.amount; }
        }
      `,
    },
    // Only private/protected/static/#private members, so nothing to port.
    {
      filename: SRC,
      code: `
        export class Hidden {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          private helper(): void {}
          protected other(): void {}
          static make(): void {}
          #secret(): void {}
        }
      `,
    },
    // No constructor at all: a zod-schema holder / static namespace class.
    {
      filename: SRC,
      code: `
        export class Schemas {
          static readonly Candidate = z.object({});
          parse(): void {}
        }
      `,
    },
    // Primitive-only constructor: a value object, no collaborator seam.
    {
      filename: SRC,
      code: `
        export class Cursor {
          private readonly token: string;
          private readonly limit: number;
          constructor(token: string, limit: number) { this.token = token; this.limit = limit; }
          encode(): string { return this.token; }
        }
      `,
    },
    // Config bag by TYPE suffix — real FP: one first-party HTTP-client site
    // whose `JsonHttpClient` takes an all-primitive options record.
    {
      filename: SRC,
      code: `
        export class JsonHttpClient {
          private readonly options: JsonHttpClientOptions;
          constructor(options: JsonHttpClientOptions) { this.options = options; }
          async requestJson(): Promise<unknown> { return null; }
        }
      `,
    },
    // Config bag by TYPE suffix where the parameter name is innocent.
    {
      filename: SRC,
      code: `
        export class Runner {
          private readonly tuning: RunnerSettings;
          constructor(tuning: RunnerSettings) { this.tuning = tuning; }
          run(): void {}
        }
      `,
    },
    // Callback/observer bag — real FP: one first-party realtime-session
    // manager that takes an OUTBOUND observer bag.
    {
      filename: SRC,
      code: `
        export class RealtimeSessionManager {
          constructor(private readonly callbacks: RealtimeSessionCallbacks) {}
          async connect(): Promise<void> {}
        }
      `,
    },
    // Logger-only and clock-only dependencies are weak evidence of a seam.
    {
      filename: SRC,
      code: `
        export class Reporter {
          private readonly logger: Logger;
          constructor(logger: Logger) { this.logger = logger; }
          report(): void {}
        }
      `,
    },
    {
      filename: SRC,
      code: `
        export class Ticker {
          constructor(private readonly clock: Clock) {}
          tick(): void {}
        }
      `,
    },
    // Composition root — real FP: one first-party service factory that
    // receives one `db` and `new`s eleven services onto its own fields.
    // A class that BUILDS more than it RECEIVES is where concrete types are
    // supposed to be named.
    {
      filename: SRC,
      code: `
        export class ServiceFactory {
          private readonly sessions: ISessionService;
          private readonly chats: IChatStore;
          private readonly cases: ICaseService;
          constructor(private readonly db: Database) {
            this.sessions = new SessionService(this.db);
            this.chats = new ChatStore(this.db);
            this.cases = new CaseService(this.db);
          }
          session(): ISessionService { return this.sessions; }
        }
      `,
    },
    // Inline object type is data, not a nominal collaborator.
    {
      filename: SRC,
      code: `
        export class Inline {
          private readonly bag: { a: string };
          constructor(bag: { a: string }) { this.bag = bag; }
          run(): void {}
        }
      `,
    },
    // Function-typed parameter is a callback, not a wholesale collaborator.
    {
      filename: SRC,
      code: `
        export class Enqueuer {
          private readonly enqueue: (task: TaskMessage) => Promise<void>;
          constructor(enqueue: (task: TaskMessage) => Promise<void>) { this.enqueue = enqueue; }
          async send(): Promise<void> {}
        }
      `,
    },
    // Taken but never stored: a constructor argument used once and discarded is
    // not a retained collaborator.
    {
      filename: SRC,
      code: `
        export class Eager {
          private readonly rows: number;
          constructor(store: TaskStore) { this.rows = store.count(); }
          run(): void {}
        }
      `,
    },
    // Path gating — the same firing source is silent in a test, a story, a
    // script, and a generated file.
    {
      filename: "/repo/tests/record-normalizer.test.ts",
      code: `
        export class FakeStore {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          run(): void {}
        }
      `,
    },
    {
      filename: "/repo/src/domain/service.stories.ts",
      code: `
        export class StoryHarness {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          run(): void {}
        }
      `,
    },
    {
      filename: "/repo/scripts/backfill.ts",
      code: `
        export class Backfiller {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          run(): void {}
        }
      `,
    },
    {
      filename: "/repo/src/generated/client.ts",
      code: `
        export class GeneratedClient {
          private readonly transport: Transport;
          constructor(transport: Transport) { this.transport = transport; }
          call(): void {}
        }
      `,
    },
    {
      filename: "/repo/src/domain/client.ts",
      code: `
        // @generated by protoc-gen-es. do not edit.
        export class GeneratedClient {
          private readonly transport: Transport;
          constructor(transport: Transport) { this.transport = transport; }
          call(): void {}
        }
      `,
    },
    // FRAMEWORK ROUTERS. Three copies of one job-runner template across three
    // first-party repos — a class the server's bootstrap
    // mounts and nothing ever injects. The original docstring already called the
    // first one its single borderline false positive.
    {
      filename: "/repo/src/router.ts",
      code: `
        export class MainRouter {
          constructor(
            private readonly taskStore: TaskStore,
            private readonly taskExecutor: TaskExecutor,
          ) {}
          init() {
            const router = express.Router();
            router.post("/", async (req, res) => {
              await this.taskExecutor.execute(await this.taskStore.setToInProgress(req.body.id));
            });
            return router;
          }
        }
      `,
    },
    // The bare `Router()` spelling of the same factory.
    {
      filename: "/repo/src/router.ts",
      code: `
        export class MainRouter {
          constructor(private readonly taskStore: TaskStore) {}
          init() {
            const router = Router();
            router.get("/", () => this.taskStore.list());
            return router;
          }
        }
      `,
    },
    // Handling the framework's own namespaced request/response is the same signal.
    {
      filename: "/repo/src/webhook.ts",
      code: `
        export class WebhookController {
          constructor(private readonly taskStore: TaskStore) {}
          handle(req: express.Request, res: express.Response): void {
            void this.taskStore.record(req.body);
            res.status(204).send();
          }
        }
      `,
    },
    // TRANSPORT WRAPPERS. Two first-party `ky`-wrapper sites, verbatim in
    // shape as each other. The Python twin
    // excludes `*Client` for exactly this reason: an ABC over a class whose only
    // collaborator is somebody else's HTTP transport substitutes nothing, and a
    // consumer's test fakes the transport rather than the wrapper.
    {
      filename: "/repo/src/lib/http-client.ts",
      code: `
        export class LedgerHttpClient {
          constructor(private readonly client: KyInstance) {}
          async inbound(input: LedgerCallInput): Promise<ConnectionDetails> {
            return null as never;
          }
        }
      `,
    },
    {
      filename: "/repo/src/lib/http-client.ts",
      code: `
        export class ApiClient {
          constructor(private readonly http: AxiosInstance) {}
          async listJobs(): Promise<Job[]> { return []; }
        }
      `,
    },
    {
      filename: "/repo/src/lib/http-client.ts",
      code: `
        export class WarehouseClient {
          constructor(private readonly session: Session) {}
          async query(sql: string): Promise<Row[]> { return []; }
        }
      `,
    },

    // OPTIONS-OBJECT CONSTRUCTORS — the shapes the walk must NOT fire on.
    //
    // Destructured but never retained: an argument read once is not a
    // collaborator, exactly as for a named parameter.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; syncClient: SyncClient; }
        export class OrgSyncService {
          private readonly count: number;
          constructor({ userRepo, syncClient }: OrgSyncDeps) {
            this.count = userRepo.count() + syncClient.count();
          }
          async sync(): Promise<void> {}
        }
      `,
    },
    // A config bag is a config bag whether it arrives whole or destructured:
    // the `*Options` suffix that filters `options: HttpClientOptions` has to
    // filter every binding pulled out of it too.
    {
      filename: SRC,
      code: `
        interface HttpClientOptions { retries: number; timeoutMs: number; }
        export class HttpClient {
          private readonly retries: number;
          private readonly timeoutMs: number;
          constructor({ retries, timeoutMs }: HttpClientOptions) {
            this.retries = retries;
            this.timeoutMs = timeoutMs;
          }
          async get(url: string): Promise<Response> { return null as never; }
        }
      `,
    },
    // Config-ish BINDING names carry the same signal from the other side.
    {
      filename: SRC,
      code: `
        interface ReporterDeps { logger: Logger; config: ReporterConfig; }
        export class Reporter {
          private readonly logger: Logger;
          private readonly config: ReporterConfig;
          constructor({ logger, config }: ReporterDeps) {
            this.logger = logger;
            this.config = config;
          }
          report(): void {}
        }
      `,
    },
    // Renamed onto a config-ish LOCAL name.
    {
      filename: SRC,
      code: `
        interface RenamedDeps { appLogger: AppLogger; logger: AppLogger; }
        export class RenamedLocal {
          private readonly logger: AppLogger;
          constructor({ appLogger: logger }: RenamedDeps) { this.logger = logger; }
          run(): void {}
        }
      `,
    },
    // Renamed off a config-ish KEY name. Either side reading as config-ish is
    // enough to drop the binding.
    {
      filename: SRC,
      code: `
        interface RenamedDeps { appLogger: AppLogger; logger: AppLogger; }
        export class RenamedKey {
          private readonly appLogger: AppLogger;
          constructor({ logger: appLogger }: RenamedDeps) { this.appLogger = appLogger; }
          run(): void {}
        }
      `,
    },
    // Inline type literal whose members are primitives: a data record, not a
    // set of collaborators. The member types are visible here, so the rule uses
    // them rather than falling back to the annotation's name.
    {
      filename: SRC,
      code: `
        export class Cursor {
          private readonly token: string;
          private readonly limit: number;
          constructor({ token, limit }: { token: string; limit: number }) {
            this.token = token;
            this.limit = limit;
          }
          encode(): string { return this.token; }
        }
      `,
    },
    // A rest element names no single binding a port could protect.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class RestOnly {
          private readonly rest: unknown;
          constructor({ ...rest }: OrgSyncDeps) { this.rest = rest; }
          run(): void {}
        }
      `,
    },
    // A nested pattern is not a single binding either.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { nested: NestedBag; }
        export class NestedOnly {
          private readonly inner: Inner;
          constructor({ nested: { inner } }: OrgSyncDeps) { this.inner = inner; }
          run(): void {}
        }
      `,
    },
    // A computed key names nothing statically.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { KEY: UserRepo; userRepo: UserRepo; }
        export class ComputedKey {
          private readonly value: UserRepo;
          constructor({ [KEY]: value }: OrgSyncDeps) { this.value = value; }
          run(): void {}
        }
      `,
    },
    // A string-literal key is not an identifier the rule can match to a member.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class StringKey {
          private readonly userRepo: UserRepo;
          constructor({ "user-repo": userRepo }: OrgSyncDeps) { this.userRepo = userRepo; }
          run(): void {}
        }
      `,
    },
    // No annotation at all: nothing names the collaborator's type.
    {
      filename: SRC,
      code: `
        export class Untyped {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }) { this.userRepo = userRepo; }
          run(): void {}
        }
      `,
    },
    // A union annotation is not a bare reference, the same rule a named
    // parameter is held to.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        interface LegacyDeps { userRepo: UserRepo; }
        export class UnionBag {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: OrgSyncDeps | LegacyDeps) { this.userRepo = userRepo; }
          run(): void {}
        }
      `,
    },
    // Destructuring changes nothing about the other guards: a class that
    // already implements a port stays silent.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncService implements IOrgSyncService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: OrgSyncDeps) { this.userRepo = userRepo; }
          async sync(): Promise<void> {}
        }
      `,
    },
    // A GENERIC TYPE PARAMETER is a placeholder, not an implementation. Two
    // public-corpus classes were reported for one: a tree node holding
    // `{ value }: { value: T }` and an audit helper holding two
    // `z.ZodTypeAny`-constrained schema parameters.
    {
      filename: SRC,
      code: `
        export class TreeNode<T> {
          public readonly value: T;
          constructor({ value }: { value: T; parent: TreeNode<T> | null }) { this.value = value; }
          addChild(child: TreeNode<T>): void {}
        }
      `,
    },
    // The constructor's own type parameter counts the same way.
    {
      filename: SRC,
      code: `
        export class Boxed {
          private readonly item: unknown;
          constructor<TItem>(item: TItem) { this.item = item; }
          unwrap(): unknown { return this.item; }
        }
      `,
    },
    // A BUILT-IN CONTAINER is the same data an inline `{ … }` annotation is,
    // wearing a nominal name — one public-corpus form model stored three
    // `Record<…>` fields and was reported for them.
    {
      filename: SRC,
      code: `
        interface FormDeps { formState: Record<string, unknown>; columnsById: Map<string, Column>; }
        export class FormFilters {
          private readonly formState: Record<string, unknown>;
          private readonly columnsById: Map<string, Column>;
          constructor({ formState, columnsById }: FormDeps) {
            this.formState = formState;
            this.columnsById = columnsById;
          }
          apply(): void {}
        }
      `,
    },
    {
      filename: SRC,
      code: `
        export class RowCache {
          private readonly rows: Map<string, Row>;
          constructor(rows: Map<string, Row>) { this.rows = rows; }
          get(id: string): Row | undefined { return this.rows.get(id); }
        }
      `,
    },
    // A FUNCTION TYPE behind a nominal alias is still a callback. Three
    // public-corpus classes were reported for one: a timer holding a
    // `type HandlerType = (t: Timer) => Promise<void>`, a manager-api store
    // holding `SetState` / `GetState`, and an event dispatcher holding a
    // `type Replayer = (e: EventInfoWrapper[]) => void`.
    {
      filename: SRC,
      code: `
        type HandlerType = (timer: Timer) => Promise<void>;
        export class Timer {
          private readonly handler: HandlerType;
          constructor({ handler }: { handler: HandlerType; time: number }) { this.handler = handler; }
          start(): void {}
        }
      `,
    },
    {
      filename: SRC,
      code: `
        type SetState = (s: State) => void;
        export class Store {
          private readonly setState: SetState;
          constructor(setState: SetState) { this.setState = setState; }
          update(s: State): void { this.setState(s); }
        }
      `,
    },
    // A bag declared in ANOTHER module cannot be read, and is left alone rather
    // than guessed at — the documented false negative in the header. Guessing
    // here is what a first cut did, and it invented four false positives in the
    // public corpus (a boolean, two numbers and a pair of `setState`/`getState`
    // functions, all of them bindings out of an unresolvable bag).
    {
      filename: SRC,
      code: `
        import type { OrgSyncDeps } from "./deps.js";
        export class OrgSyncService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: OrgSyncDeps) { this.userRepo = userRepo; }
          async sync(): Promise<void> {}
        }
      `,
    },
    // A qualified bag names another module by construction.
    {
      filename: SRC,
      code: `
        export class CatalogFacade {
          private readonly client: catalog.Client;
          constructor({ client }: catalog.Deps) { this.client = client; }
          lookup(id: string): void {}
        }
      `,
    },
    // An alias to something that is not an object literal resolves to no members.
    {
      filename: SRC,
      code: `
        type LooseDeps = Record<string, unknown>;
        export class LooseService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: LooseDeps) { this.userRepo = userRepo; }
          async run(): Promise<void> {}
        }
      `,
    },
    // A bag member that is a FUNCTION type is a callback, not a collaborator —
    // the shape one public-corpus store used for `setState` / `getState`.
    {
      filename: SRC,
      code: `
        interface UpstreamDeps { setState: (s: State) => void; getState: () => State; }
        export class Store {
          private readonly setState: (s: State) => void;
          private readonly getState: () => State;
          constructor({ setState, getState }: UpstreamDeps) {
            this.setState = setState;
            this.getState = getState;
          }
          update(s: State): void { this.setState(s); }
        }
      `,
    },
    // A bag member with a config-ish TYPE keeps the suffix guard.
    {
      filename: SRC,
      code: `
        interface RunnerDeps { tuning: RunnerSettings; }
        export class Runner {
          private readonly tuning: RunnerSettings;
          constructor({ tuning }: RunnerDeps) { this.tuning = tuning; }
          run(): void {}
        }
      `,
    },
    // A bag member the destructuring does not name contributes nothing.
    {
      filename: SRC,
      code: `
        interface PartialDeps { userRepo: UserRepo; retries: number; }
        export class PartialService {
          private readonly retries: number;
          constructor({ retries }: PartialDeps) { this.retries = retries; }
          run(): void {}
        }
      `,
    },
    // Nor does it change the value-object rule: no public method, no report.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncPlan {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: OrgSyncDeps) { this.userRepo = userRepo; }
        }
      `,
    },
  ],

  invalid: [
    {
      name: "recognizes nullish assignment and type-asserted constructor storage",
      filename: SRC,
      code: `
        export class RequestHandler {
          private store?: TaskStore;
          constructor(store: TaskStore) { this.store ??= store as TaskStore; }
          handle(): void {}
        }
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle" } }],
    },
    {
      name: "a local marker interface does not cover the service surface",
      filename: SRC,
      code: `
        interface Serializable { serialize(): string; }
        export class RequestHandler implements Serializable {
          constructor(private readonly store: TaskStore) {}
          handle(): void {}
          serialize(): string { return ""; }
        }
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle, serialize" } }],
    },
    {
      name: "a local concrete superclass is not a service port",
      filename: SRC,
      code: `
        class LocalBase { helper(): void {} }
        export class RequestHandler extends LocalBase {
          constructor(private readonly store: TaskStore) { super(); }
          handle(): void {}
        }
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle" } }],
    },
    {
      name: "recognizes a nullable collaborator stored through a non-null assertion in control flow",
      filename: SRC,
      code: `
        export class RequestHandler {
          private readonly store: TaskStore;
          constructor(store: TaskStore | undefined, enabled: boolean) {
            if (enabled) this.store = store!;
            else this.store = fallbackStore();
          }
          handle(): void {}
        }
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle" } }],
    },
    {
      name: "counts public arrow properties as callable service surface",
      filename: SRC,
      code: `
        export class RequestHandler {
          constructor(private readonly store: TaskStore) {}
          handle = async (): Promise<void> => this.store.run();
        }
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle" } }],
    },
    {
      name: "recognizes a detached named export",
      filename: SRC,
      code: `
        class RequestHandler {
          constructor(private readonly store: TaskStore) {}
          handle(): void {}
        }
        export { RequestHandler };
      `,
      errors: [{ messageId: "requireInterface", data: { name: "RequestHandler", deps: "store: TaskStore", methods: "handle" } }],
    },
    // GROUND TRUTH — the origin case raised in review on a first-party repo,
    // verbatim in shape. Its sibling in the same directory tree does declare an
    // `ITaskTrackerService` port.
    {
      filename: SRC,
      code: `
        export class RecordNormalizerService {
          private readonly svc: ServiceRegistry;

          constructor(svc: ServiceRegistry) {
            this.svc = svc;
          }

          async run(queue: Queue<TaskMessage>, nowMs: number, maxPerRun: number): Promise<RecordNormalizerRunResult> {
            return null as never;
          }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "RecordNormalizerService",
            deps: "svc: ServiceRegistry",
            methods: "run",
          },
        },
      ],
    },
    // Parameter properties are storage too — one first-party service site.
    {
      filename: SRC,
      code: `
        export class ProfileService {
          constructor(private profileStore: ProfileStore) {}
          async getProfileById(id: string): Promise<Profile | null> { return null; }
          async listProfiles(): Promise<Profile[]> { return []; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ProfileService", deps: "profileStore: ProfileStore", methods: "getProfileById, listProfiles" },
        },
      ],
    },
    // `readonly` parameter property with no accessibility keyword — one
    // first-party site where `interface ReportParser` is declared three lines
    // above and the `*Impl` class never says `implements`.
    {
      filename: SRC,
      code: `
        export interface ReportParser { parse(args: ParseArgs): Promise<Parsed>; }
        export class ReportParserImpl {
          constructor(readonly axios: AxiosInstance) {}
          async parse(args: ParseArgs): Promise<Parsed> { return null as never; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ReportParserImpl", deps: "axios: AxiosInstance", methods: "parse" },
        },
      ],
    },
    // A dependency BAG spread onto fields is still a collaborator seam — one
    // first-party reporting site. `Deps` is
    // deliberately not in the config-ish suffix list.
    {
      filename: SRC,
      code: `
        export class DigestReportService {
          private readonly lister: ChannelLister;
          private readonly alerts: AlertsClient;
          constructor(deps: DigestReportDeps) {
            this.lister = deps.lister;
            this.alerts = deps.alerts;
          }
          async runDaily(today: string): Promise<Result> { return null as never; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "DigestReportService", deps: "deps: DigestReportDeps", methods: "runDaily" },
        },
      ],
    },
    // Multiple collaborators, one of which is a config bag: the config bag is
    // dropped from the message but the real dependency still fires.
    {
      filename: SRC,
      code: `
        export class ArtifactSyncHandler {
          private readonly svc: ServiceRegistry;
          private readonly bucket: R2Bucket;
          constructor(services: ServiceRegistry, bucket: R2Bucket, owner: string, tuning: SyncOptions) {
            this.svc = services;
            this.bucket = bucket;
            this.owner = owner;
            this.tuning = tuning;
          }
          async handle(task: SyncTask): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ArtifactSyncHandler", deps: "services: ServiceRegistry, bucket: R2Bucket", methods: "handle" },
        },
      ],
    },
    // A qualified type name (`catalog.Client`) is still a nominal collaborator.
    {
      filename: SRC,
      code: `
        export class CatalogFacade {
          private readonly client: catalog.Client;
          constructor(client: catalog.Client) { this.client = client; }
          lookup(id: string): Promise<void> { return this.client.get(id); }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "CatalogFacade", deps: "client: catalog.Client", methods: "lookup" },
        },
      ],
    },
    // `export default class` is exported too.
    {
      filename: SRC,
      code: `
        export default class TaskProcessor {
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry) { this.svc = svc; }
          async process(): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "TaskProcessor", deps: "svc: ServiceRegistry", methods: "process" },
        },
      ],
    },
    // A defaulted collaborator is still a retained collaborator, and a
    // constructor that ALSO `new`s something that is not stored on a field is
    // not a composition root.
    {
      filename: SRC,
      code: `
        export class Scheduler {
          private readonly store: TaskStore;
          constructor(store: TaskStore = defaultStore) {
            const span = new Span("init");
            this.store = store;
          }
          schedule(): void {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "Scheduler", deps: "store: TaskStore", methods: "schedule" },
        },
      ],
    },
    // Building ONE internal helper while receiving a real collaborator is an
    // ordinary service, not a wiring class. The first cut of the composition-root
    // guard exempted any `new` in a constructor and silently lost two sibling
    // message handlers in one first-party repo.
    {
      filename: SRC,
      code: `
        export class TaskMessageHandler {
          private readonly processor: TaskProcessor;
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry, enqueue: (task: TaskMessage) => Promise<void>) {
            this.svc = svc;
            this.processor = new TaskProcessor(svc, enqueue);
          }
          async handle(task: ProcessTaskMessage): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "TaskMessageHandler", deps: "svc: ServiceRegistry", methods: "handle" },
        },
      ],
    },
    // `.tsx` is not an exemption on its own — only `extends` is. A service that
    // happens to live in a component file still fires.
    {
      filename: "/repo/src/features/panel.tsx",
      code: `
        export class PanelPresenter {
          private readonly store: PanelStore;
          constructor(store: PanelStore) { this.store = store; }
          select(id: string): void {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "PanelPresenter", deps: "store: PanelStore", methods: "select" },
        },
      ],
    },
    // The framework-wiring guard is about routers, not about `express` being in
    // the file. Drop the `Router()` call and the namespaced parameter types and
    // the same shape is an ordinary injected service again.
    {
      filename: "/repo/src/router.ts",
      code: `
        export class MainRouter {
          constructor(
            private readonly taskStore: TaskStore,
            private readonly taskExecutor: TaskExecutor,
          ) {}
          async init(taskId: string) {
            await this.taskExecutor.execute(await this.taskStore.setToInProgress(taskId));
          }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "MainRouter",
            deps: "taskStore: TaskStore, taskExecutor: TaskExecutor",
            methods: "init",
          },
        },
      ],
    },
    // The DOM `Request`/`Response` a Workers `fetch` handler names are unqualified
    // and must not read as express wiring.
    {
      filename: "/repo/src/worker.ts",
      code: `
        export class FetchHandler {
          constructor(private readonly taskStore: TaskStore) {}
          async fetch(request: Request): Promise<Response> {
            return new Response(JSON.stringify(await this.taskStore.list()));
          }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "FetchHandler", deps: "taskStore: TaskStore", methods: "fetch" },
        },
      ],
    },
    // TRUE POSITIVES the transport guard must not swallow. One first-party
    // site wraps an `AxiosInstance`
    // in a DOMAIN operation, and its consumers do have something to substitute —
    // the `*Client` arm of the guard is what keeps it firing.
    {
      filename: "/repo/src/services/message-service.ts",
      code: `
        export class HttpMessageService {
          constructor(private readonly client: AxiosInstance) {}
          async send(body: MessageRequest) { return (await this.client.post("/v1/messages", body)).data; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "HttpMessageService", deps: "client: AxiosInstance", methods: "send" },
        },
      ],
    },
    // Another first-party site — `interface ReportParser` sits three lines
    // above and the class never says `implements`. That is the drift this rule
    // exists for.
    {
      filename: "/repo/src/app/api/report-parser.ts",
      code: `
        export interface ReportParser {
          parse(args: ParseArgs): Promise<ParsedReport>;
        }
        export class ReportParserImpl {
          constructor(readonly axios: AxiosInstance) {}
          async parse(args: ParseArgs): Promise<ParsedReport> { return null as never; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ReportParserImpl", deps: "axios: AxiosInstance", methods: "parse" },
        },
      ],
    },
    // The `unless a same-file interface shares the stem` arm, on a `*Client` name:
    // an in-file `IApiClient` the class fails to implement is real drift.
    {
      filename: "/repo/src/lib/api-client.ts",
      code: `
        export interface IApiClient {
          listJobs(): Promise<Job[]>;
        }
        export class ApiClient {
          constructor(private readonly http: AxiosInstance) {}
          async listJobs(): Promise<Job[]> { return []; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ApiClient", deps: "http: AxiosInstance", methods: "listJobs" },
        },
      ],
    },
    // A transport alongside a real collaborator is not a lone transport.
    {
      filename: "/repo/src/lib/api-client.ts",
      code: `
        export class ApiClient {
          constructor(
            private readonly http: AxiosInstance,
            private readonly cache: JobCache,
          ) {}
          async listJobs(): Promise<Job[]> { return []; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ApiClient", deps: "http: AxiosInstance, cache: JobCache", methods: "listJobs" },
        },
      ],
    },
    // A `*Client` whose single collaborator is a domain port, not a transport.
    {
      filename: "/repo/src/lib/api-client.ts",
      code: `
        export class ApiClient {
          constructor(private readonly jobStore: JobStore) {}
          async listJobs(): Promise<Job[]> { return []; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ApiClient", deps: "jobStore: JobStore", methods: "listJobs" },
        },
      ],
    },

    // OPTIONS-OBJECT CONSTRUCTORS. `constructor({ a, b }: Deps)` is the same
    // seam as `constructor(a: A, b: B)`; the parameter walk used to see only the
    // second spelling.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; syncClient: SyncClient; }
        export class OrgSyncService {
          private readonly userRepo: UserRepo;
          private readonly syncClient: SyncClient;
          constructor({ userRepo, syncClient }: OrgSyncDeps) {
            this.userRepo = userRepo;
            this.syncClient = syncClient;
          }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "OrgSyncService",
            deps: "userRepo: UserRepo, syncClient: SyncClient",
            methods: "syncOrg",
          },
        },
      ],
    },
    // A `#private` field is storage too.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncService {
          readonly #userRepo: UserRepo;
          constructor({ userRepo }: OrgSyncDeps) { this.#userRepo = userRepo; }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "OrgSyncService",
            deps: "userRepo: UserRepo",
            methods: "syncOrg",
          },
        },
      ],
    },
    // A DEFAULTED binding is still a retained collaborator; the default sits
    // between the key and the identifier the body stores.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo = defaultUserRepo }: OrgSyncDeps) { this.userRepo = userRepo; }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "OrgSyncService",
            deps: "userRepo: UserRepo",
            methods: "syncOrg",
          },
        },
      ],
    },
    // A REST element next to a real binding drops only itself.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncService {
          private readonly userRepo: UserRepo;
          private readonly rest: unknown;
          constructor({ userRepo, ...rest }: OrgSyncDeps) {
            this.userRepo = userRepo;
            this.rest = rest;
          }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "OrgSyncService",
            deps: "userRepo: UserRepo",
            methods: "syncOrg",
          },
        },
      ],
    },
    // A RENAMED binding: storage is checked against the local name, the type
    // against the contract's own key.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class OrgSyncService {
          private readonly repository: UserRepo;
          constructor({ userRepo: repository }: OrgSyncDeps) { this.repository = repository; }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "OrgSyncService",
            deps: "repository: UserRepo",
            methods: "syncOrg",
          },
        },
      ],
    },
    // An INLINE TYPE LITERAL annotation names each member's type outright, so
    // the message reports the collaborator's own type rather than the bag's.
    {
      filename: SRC,
      code: `
        export class OrgSyncService {
          private readonly userRepo: UserRepo;
          private readonly limit: number;
          constructor({ userRepo, limit }: { userRepo: UserRepo; limit: number }) {
            this.userRepo = userRepo;
            this.limit = limit;
          }
          async syncOrg(orgId: string): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "OrgSyncService", deps: "userRepo: UserRepo", methods: "syncOrg" },
        },
      ],
    },
    // A `type` alias bag resolves the same way an `interface` bag does, and a
    // member's own namespace qualifier survives into the message.
    {
      filename: SRC,
      code: `
        type CatalogDeps = { client: catalog.Client; pageSize: number };
        export class CatalogFacade {
          private readonly client: catalog.Client;
          constructor({ client }: CatalogDeps) { this.client = client; }
          lookup(id: string): Promise<void> { return this.client.get(id); }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "CatalogFacade", deps: "client: catalog.Client", methods: "lookup" },
        },
      ],
    },
    // An INTERSECTION alias (`type Deps = Base & { … }`) is how a bag is usually
    // extended; the literal arm still resolves.
    {
      filename: SRC,
      code: `
        type SyncDeps = BaseDeps & { userRepo: UserRepo };
        export class IntersectionService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: SyncDeps) { this.userRepo = userRepo; }
          async run(): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "IntersectionService", deps: "userRepo: UserRepo", methods: "run" },
        },
      ],
    },
    // An EXPORTED bag declaration resolves too.
    {
      filename: SRC,
      code: `
        export interface ExportedDeps { userRepo: UserRepo; }
        export class ExportedBagService {
          private readonly userRepo: UserRepo;
          constructor({ userRepo }: ExportedDeps) { this.userRepo = userRepo; }
          async run(): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: { name: "ExportedBagService", deps: "userRepo: UserRepo", methods: "run" },
        },
      ],
    },
    // The three name-hiding guards are narrow, not a blanket. A collaborator
    // whose type merely SHARES a name with a type parameter of a different
    // class, an alias to an object type, and a type whose name only starts with
    // a container's, all still fire.
    {
      filename: SRC,
      code: `
        type UserRepo = { find(id: string): Promise<User | null> };
        export class Unrelated<TResult> {
          private readonly userRepo: UserRepo;
          private readonly records: RecordSet;
          constructor({ userRepo, records }: { userRepo: UserRepo; records: RecordSet }) {
            this.userRepo = userRepo;
            this.records = records;
          }
          async run(): Promise<TResult> { return null as never; }
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "Unrelated",
            deps: "userRepo: UserRepo, records: RecordSet",
            methods: "run",
          },
        },
      ],
    },
    // A destructured bag ALONGSIDE a named parameter: both spellings feed the
    // same list.
    {
      filename: SRC,
      code: `
        interface OrgSyncDeps { userRepo: UserRepo; }
        export class MixedService {
          private readonly userRepo: UserRepo;
          private readonly svc: ServiceRegistry;
          constructor(svc: ServiceRegistry, { userRepo }: OrgSyncDeps) {
            this.svc = svc;
            this.userRepo = userRepo;
          }
          async run(): Promise<void> {}
        }
      `,
      errors: [
        {
          messageId: "requireInterface",
          data: {
            name: "MixedService",
            deps: "svc: ServiceRegistry, userRepo: UserRepo",
            methods: "run",
          },
        },
      ],
    },
  ],
});
