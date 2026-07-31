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
  ],

  invalid: [
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
  ],
});
