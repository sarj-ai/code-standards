// vitest: shared-module-graph
import rule from "../../src/rules/no-declaration-comment-wall.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-declaration-comment-wall", rule, {
  valid: [
    {
      filename: "/repo/src/fixture/client.ts",
      code: "interface Client {\n  /** Read user. */\n  readUser(): void;\n  /** Write user. */\n  writeUser(): void;\n  /** Delete user. */\n  deleteUser(): void;\n}",
    },
    {
      name: "preserves behavioral relation comments",
      code: "interface Client {\n  // must be non-empty\n  nonEmpty: string;\n  // only set after login\n  setAfterLogin: string;\n  // never null\n  nullable: string;\n}",
    },

    { code: "enum Status { Pending = 'pending', Finished = 'finished', Failed = 'failed' }" },
    {
      name: "preserves rationale in consecutive line-comment blocks",
      code: [
        "class Connection {",
        "  // selected after a regional failover",
        "  // Host name.",
        "  hostName = '';",
        "  // reserved by the network control plane",
        "  // Port number.",
        "  portNumber = 443;",
        "  // rotated whenever an operator leaves",
        "  // User name.",
        "  userName = '';",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Status {",
        "  /** the queue has accepted it but no worker has claimed it */",
        "  Pending = 'pending',",
        "  /** a worker claimed it and then died without releasing the lease */",
        "  Orphaned = 'orphaned',",
        "  /** terminal, and the payload has already been purged */",
        "  Finished = 'finished',",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum TargetMode {",
        "  WindowsIntegration = 1, // windows",
        "  NetworkIntegration = 2, // network",
        "  PosixIntegration = 3, // posix",
        "  NoTargets = 4, // coverage",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "class Store {",
        "  /** @ignore */",
        "  private client: Client;",
        "  /** @ignore */",
        "  private cache: Cache;",
        "  /** @ignore */",
        "  private clock: Clock;",
        "}",
      ].join("\n"),
    },

    {
      name: "preserves machine-consumed type tags even when their prose restates members",
      code: [
        "class Store {",
        "  /** The client. @type {Client} */",
        "  client = createClient();",
        "  /** The cache. @type {Cache} */",
        "  cache = createCache();",
        "  /** The clock. @type {Clock} */",
        "  clock = createClock();",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "class Theme {",
        "  // Hover background",
        "  before = { background: controlItemBgHover };",
        "  // Drag spinner",
        "  after = { background: colorFillDrag, cursor: 'spinner' };",
        "  // Focus outline",
        "  focus = { outline: colorFocus };",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "class Ledger {",
        "  /** posts the ledger entry */",
        "  post() { const ledgerEntry = 1; return ledgerEntry; }",
        "  /** voids the ledger entry */",
        "  void_() { const ledgerEntry = 1; return ledgerEntry; }",
        "  /** replays the ledger entry */",
        "  replay() { const ledgerEntry = 1; return ledgerEntry; }",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "  Queued = 'queued',",
        "  Running = 'running',",
        "  Paused = 'paused',",
        "  Retried = 'retried',",
        "  Cancelled = 'cancelled',",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** set by the reaper when a lease expires under a live worker */",
        "  Orphaned = 'orphaned',",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "class Config {",
        "  // transport",
        "  host = 'localhost';",
        "  portNumber = 5432;",
        "  socketPath = null;",
        "  // credentials",
        "  userName = 'a';",
        "  passWord = 'b';",
        "  tokenValue = 'c';",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Code {",
        "  /** The ok code, 200. */",
        "  Ok = 'ok',",
        "  /** The missing code, 404. */",
        "  Missing = 'missing',",
        "  /** The failed code, 500. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
      filename: "src/status.test.ts",
    },
    {
      code: [
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
      filename: "src/status.stories.tsx",
    },
    {
      code: [
        "// Code generated by protoc-gen-ts. DO NOT EDIT.",
        "enum Status {",
        "  /** The pending status. */",
        "  Pending = 'pending',",
        "  /** The finished status. */",
        "  Finished = 'finished',",
        "  /** The failed status. */",
        "  Failed = 'failed',",
        "}",
      ].join("\n"),
    },

    {
      code: "class Row { id = ''; label = ''; href = ''; } // Shared field",
      options: [{ maxNovelWords: 2 }],
    },

    {
      code: [
        "class Registry {",
        "  // Retry backup handlers",
        "  retries = [retryHandler, backupHandler];",
        "  // Build retry handler",
        "  fallback = () => buildRetryHandler();",
        "  // Primary color palette",
        "  theme = { palette: primaryPalette };",
        "}",
      ].join("\n"),
    },

    {
      name: "ignores object-literal tables",
      code: [
        "const status = {",
        "  // The pending status",
        "  pendingStatus: 'pending',",
        "  // The running status",
        "  runningStatus: 'running',",
        "  // The finished status",
        "  finishedStatus: 'finished',",
        "};",
      ].join("\n"),
    },

  ],

  invalid: [
    ...["external", "fixture", "stories"].map(tree => ({
      filename: `/repo/src/${tree}/status.ts`,
      code: "enum Status {\n  /** The pending status. */\n  Pending = 'pending',\n  /** The finished status. */\n  Finished = 'finished',\n  /** The failed status. */\n  Failed = 'failed',\n}",
      errors: [{ messageId: "commentWall" as const }],
    })),
    ...["external", "fixture", "stories"].map(tree => ({
      filename: `/repo/src/${tree}/client.ts`,
      code: "class Client {\n  /** Read user. */\n  readUser() {}\n  /** Write user. */\n  writeUser() {}\n  /** Delete user. */\n  deleteUser() {}\n}",
      output: "class Client {\n\n  readUser() {}\n\n  writeUser() {}\n\n  deleteUser() {}\n}",
      errors: [{ messageId: "commentWall" as const }],
    })),
    {
      name: "preserves single-word enum labels alongside a type-member wall",
      code: "enum Status {\n  // active\n  Active,\n  // inactive\n  Inactive,\n  // pending\n  Pending,\n}\ninterface Client {\n  // read user\n  readUser(): void;\n  // write user\n  writeUser(): void;\n  // delete user\n  deleteUser(): void;\n}",
      output: "enum Status {\n  // active\n  Active,\n  // inactive\n  Inactive,\n  // pending\n  Pending,\n}\ninterface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}",
      errors: [
        { messageId: "typeMemberCommentWall", data: { restated: "3", commented: "3" }, line: 9, column: 18, endLine: 9, endColumn: 19 },
      ],
    },
    {
      name: "reports both declaration kinds in one file",
      code: "enum Status {\n  // Active status\n  Active,\n  // Inactive status\n  Inactive,\n  // Pending status\n  Pending,\n}\ninterface Client {\n  // read user\n  readUser(): void;\n  // write user\n  writeUser(): void;\n  // delete user\n  deleteUser(): void;\n}",
      output: "enum Status {\n  // Active status\n  Active,\n  // Inactive status\n  Inactive,\n  // Pending status\n  Pending,\n}\ninterface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}",
      errors: [
        { messageId: "commentWall", data: { restated: "3", commented: "3" }, line: 1, column: 1, endLine: 1, endColumn: 2 },
        { messageId: "typeMemberCommentWall", data: { restated: "3", commented: "3" }, line: 9, column: 18, endLine: 9, endColumn: 19 },
      ],
    },
    ...["\n", "\r\n"].map(ending => ({
      name: "shared guarded deletion retains normal terminators " + JSON.stringify(ending),
      code: "class Client {\n  /** Read user. */\n  readUser() {}\n  /** Write user. */\n  writeUser() {}\n  /** Delete user. */\n  deleteUser() {}\n}".replaceAll("\n", ending),
      output: "class Client {\n\n  readUser() {}\n\n  writeUser() {}\n\n  deleteUser() {}\n}".replaceAll("\n", ending),
      errors: [{ messageId: "commentWall" as const }],
    })),
    { name: "automatically removes only exact multiword member names (distinct filename: Oxlint's RuleTester rejects duplicate code)", filename: "src/client.ts", code: "class Client {\n  /** Read user. */\n  readUser() {}\n  /** Write user. */\n  writeUser() {}\n  /** Delete user. */\n  deleteUser() {}\n}", output: "class Client {\n\n  readUser() {}\n\n  writeUser() {}\n\n  deleteUser() {}\n}", errors: [{ messageId: "commentWall" }] },

    {
      code: "enum Status {\n  /** The pending status. */\n  Pending = 'pending',\n  /** The finished status. */\n  Finished = 'finished',\n  /** The failed status. */\n  Failed = 'failed',\n}",
      errors: [{ messageId: "commentWall" }],
    },

    {
      code: [
        "class Server {",
        "  // The server host",
        "  host: string;",
        "  // The server port",
        "  port: string;",
        "  // The server region",
        "  region: string;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },

    {
      code: [
        "enum Status {",
        "  Pending = 'pending', // The pending state",
        "  Running = 'running', // The running state",
        "  Blocked = 'blocked', // The blocked state",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },

    {
      code: [
        "class Config {",
        "  // The retry count",
        "  retryCount = 4;",
        "  // The base url",
        "  baseUrl = 'https://x';",
        "  // The user agent",
        "  userAgent = 'y';",
        "",
        "  // transport",
        "  socketPath = null;",
        "",
        "  // credentials",
        "  tokenValue = 'c';",
        "}",
      ].join("\n"), output: "class Config {\n\n  retryCount = 4;\n\n  baseUrl = 'https://x';\n\n  userAgent = 'y';\n\n  // transport\n  socketPath = null;\n\n  // credentials\n  tokenValue = 'c';\n}",
      errors: [{ messageId: "commentWall" }],
    },

    {
      code: [
        "enum Match {",
        "  // Partial name match",
        "  Name = 'name',",
        "  // Exact slug match",
        "  Slug = 'slug',",
        "  // Fuzzy title match",
        "  Title = 'title',",
        "}",
      ].join("\n"),
      options: [{ maxNovelWords: 2 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minCommentedMembers",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "}",
      ].join("\n"),
      options: [{ minCommentedMembers: 2 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minCommentedRatio",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "  // The failed status",
        "  Failed = 'failed',",
        "  Queued = 'queued',",
        "  Running = 'running',",
        "  Paused = 'paused',",
        "  Retried = 'retried',",
        "  Cancelled = 'cancelled',",
        "}",
      ].join("\n"),
      options: [{ minCommentedRatio: 0.3 }],
      errors: [{ messageId: "commentWall" }],
    },

    {
      name: "honors minRestatedRatio",
      code: [
        "enum Status {",
        "  // The pending status",
        "  Pending = 'pending',",
        "  // The finished status",
        "  Finished = 'finished',",
        "  // set by the reaper when a live worker loses its lease",
        "  Orphaned = 'orphaned',",
        "}",
      ].join("\n"),
      options: [{ minRestatedRatio: 0.6 }],
      errors: [{ messageId: "commentWall" }],
    },
  ],
});

RULE_TESTER.run("no-declaration-comment-wall (no-type-member-comment-wall)", rule, {
  valid: [
    {
      name: "preserves fixed boolean contracts",
      code: "interface Flags {\n// Enabled is false.\nenabled: boolean;\n// Active is true.\nactive: boolean;\n// Ready is false.\nready: boolean;\n}",
    },
    {
      name: "preserves negated member behavior",
      code: "interface Flags {\n// Not enabled.\nenabled: boolean;\n// Not active.\nactive: boolean;\n// Not ready.\nready: boolean;\n}",
    },
    {
      name: "preserves requirements absent from optional members",
      code: "interface Request {\n// Required host.\nhost?: string;\n// Required port.\nport?: number;\n// Required user.\nuser?: string;\n}",
    },
    {
      name: "preserves conditional member contracts",
      code: "interface Flags {\n// Enabled if active.\nenabled: boolean;\n// Active when ready.\nactive: boolean;\n// Ready unless enabled.\nready: boolean;\n}",
    },

    { code: "interface Credentials { host?: string; port?: number; username?: string; password?: string; }" },
    {
      name: "preserves rationale in consecutive line-comment blocks",
      code: [
        "interface Connection {",
        "  // selected after a regional failover",
        "  // Host name.",
        "  hostName: string;",
        "  // reserved by the network control plane",
        "  // Port number.",
        "  portNumber: number;",
        "  // rotated whenever an operator leaves",
        "  // User name.",
        "  userName: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Credentials {",
        "  // the pooler address, which failover swaps under a live process",
        "  host: string;",
        "  // the pooler listens here; the writer listens elsewhere",
        "  port: number;",
        "  // rotated nightly by the credential vault",
        "  username: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Filters {",
        "  // Partial match",
        "  name?: string;",
        "  // Exact match",
        "  slug?: string;",
        "  // Fuzzy match",
        "  title?: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Session {",
        "  // Session token",
        "  token: string;",
        "  // rotated when the browser fingerprint changes",
        "  fingerprint: string;",
        "  // trimmed to the shortest prefix that stays unique",
        "  prefix: string;",
        "  // sent by the caller on every hop of the redirect chain",
        "  hop: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Pair {",
        "  // Database host.",
        "  host: string;",
        "  // Database port.",
        "  port: number;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface AppState {",
        "  // collaborators",
        "  collaborators: string[];",
        "  collaboratorCursors: number[];",
        "  collaboratorNames: string[];",
        "  // snap lines",
        "  snapLines: string[];",
        "  snapTolerance: number;",
        "  snapEnabled: boolean;",
        "  // cropping",
        "  cropping: boolean;",
        "  croppingElementId: string;",
        "  croppingBounds: number[];",
        "}",
        ].join("\n"),
    },

    {
      code: [
        "type GetAnnotations = {",
        "  // links",
        "  LinkDescriptors: unknown;",
        "  LinksFunction: unknown;",
        "",
        "  // meta",
        "  MetaArgs: unknown;",
        "  MetaDescriptors: unknown;",
        "",
        "  // middleware",
        "  MiddlewareFunction: unknown;",
        "",
        "  // loader",
        "  LoaderArgs: unknown;",
        "};",
      ].join("\n"),
    },

    {
      code: [
        "interface LegacyOptions {",
        "  // The polyfills; defaults to true",
        "  polyfills: boolean;",
        "  // The legacy chunks; defaults to false",
        "  renderLegacyChunks: boolean;",
        "  // The targets; defaults to null",
        "  targets: string;",
        "}",
      ].join("\n"),
    },
    {
      name: "preserves colon-form documented defaults",
      code: [
        "interface LegacyOptions {",
        "  // default: true",
        "  polyfills: boolean;",
        "  // default: false",
        "  renderLegacyChunks: boolean;",
        "  // default: null",
        "  targets: string;",
        "}",
      ].join("\n"),
    },
    {
      name: "honours a stricter commented-member ratio",
      code: [
        "interface PartialWall {",
        "  // Host",
        "  host: string;",
        "  // Port",
        "  port: number;",
        "  // User",
        "  user: string;",
        "  password: string;",
        "  database: string;",
        "}",
      ].join("\n"),
      options: [{ minCommentedRatio: 0.8 }],
    },

    {
      code: [
        "interface Position {",
        "  // The 1-based column number.",
        "  column: number;",
        "  // The 1-based line number.",
        "  line: number;",
        "  // 0..100 (% of width)",
        "  width: number;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Effort {",
        "  // The effort in days",
        "  effort: number;",
        "  // The wait in seconds",
        "  wait: number;",
        "  // The size in bytes",
        "  size: number;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Instrument {",
        '  // "sukuk"',
        "  kind: string;",
        '  // e.g. "murabaha"',
        "  product: string;",
        '  // "Current Account"',
        "  account: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Surface {",
        "  /** The host. @alpha */",
        "  host: string;",
        "  /** The port. @beta */",
        "  port: number;",
        "  /** The user. @internal */",
        "  user: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface ReadonlySurface {",
        "  /** @readonly */",
        "  host: string;",
        "  /** @readonly */",
        "  port: number;",
        "  /** @readonly */",
        "  user: string;",
        "}",
      ].join("\n"),
    },
    {
      name: "preserves custom JSDoc tags that may be consumed by downstream tooling",
      code: [
        "interface ApiSurface {",
        "  /** The host. @customApiTag host */",
        "  host: string;",
        "  /** The port. @customApiTag port */",
        "  port: number;",
        "  /** The user. @customApiTag user */",
        "  user: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Section {",
        "  // --- header ---",
        "  header: string;",
        "  // --- body ---",
        "  body: string;",
        "  // --- footer ---",
        "  footer: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Retry {",
        "  // The deadline; must be monotonic",
        "  deadline: number;",
        "  // The counter; must be atomic",
        "  counter: number;",
        "  // The handler; must be idempotent",
        "  handler: () => void;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface TransactionEntityMetadataArgs {",
        "  /** Target class on which decorator is used. */",
        "  readonly target: Function;",
        "  /** Method on which decorator is used. */",
        "  readonly methodName: string;",
        "  /** Index of the parameter on which decorator is used. */",
        "  readonly index: number;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "declare const resultType: unique symbol;",
        "declare const argType: unique symbol;",
        "declare const metaType: unique symbol;",
        "interface Phantom {",
        "  // phantom type",
        "  [resultType]?: string;",
        "  // phantom type",
        "  [argType]?: string;",
        "  // phantom type",
        "  [metaType]?: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Bill {",
        "  // اسم الشركة",
        "  company: string;",
        "  // رقم الاشتراك",
        "  subscription: string;",
        "  // المبلغ المستحق",
        "  amount: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Voice {",
        "  // Voice Id",
        "  voiceId: string;",
        "  // Persona Prompt",
        "  personaPrompt: string;",
        "  // App Settings",
        "  appSettings: string;",
        "}",
      ].join("\n"),
      filename: "src/api/types.gen.ts",
    },
    {
      code: [
        "// @generated by openapi-typescript",
        "interface Voice {",
        "  // Voice Id",
        "  voiceId: string;",
        "  // Persona Prompt",
        "  personaPrompt: string;",
        "  // App Settings",
        "  appSettings: string;",
        "}",
      ].join("\n"),
      filename: "src/api/schema.ts",
    },

    {
      code: [
        "interface MqttWill {",
        "  /** the topic to publish */",
        "  topic: string;",
        "  /** the QoS */",
        "  qos: number;",
        "  /** the retain flag */",
        "  retain: boolean;",
        "}",
      ].join("\n"),
      filename: "packages/microservices/external/mqtt-options.interface.ts",
    },

    {
      code: [
        "interface Cases {",
        "  // The label.",
        "  label: string;",
        "  // The expected.",
        "  expected: string;",
        "  // The actual.",
        "  actual: string;",
        "}",
      ].join("\n"),
      filename: "src/table.test.ts",
    },

    {
      code: [
        "interface TextInputProps {",
        "  /** Input label */",
        "  label: string;",
        "  /** Placeholder text */",
        "  placeholder?: string;",
        "  /** Change handler */",
        "  onChange?: (value: string) => void;",
        "}",
      ].join("\n"),
      filename: "src/componentManifest/__testfixtures__/ForwardRef.tsx",
    },

    {
      code: [
        "interface CardProps {",
        "  /** Card title */",
        "  title: string;",
        "  /** Image URL */",
        "  imageUrl: string;",
        "  /** Image alt text */",
        "  imageAlt?: string;",
        "}",
      ].join("\n"),
      filename: "src/stories/other/card/Card.tsx",
    },

    {
      code: [
        "interface Mixed {",
        "  host: string; // resolved from the VPC DNS name",
        "  port: number;",
        "  user: string;",
        "  pass: string;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "interface Doc {",
        "  alpha: string; // alpha",
        "  beta: string; // beta",
        "  /* gamma */ gamma: string;",
        "}",
      ].join("\n"),
    },

    {
      code: "type Row = { id: string; label: string; href: string }; // the record",
    },

    {
      code: [
        "/** A logo. */",
        "export default function Logo({ d, cids, styles }: { d: LogoData; cids: string[]; styles: LogoStyles }) {",
        "  return null;",
        "}",
      ].join("\n"),
    },

    {
      code: [
        "/** The row. */",
        "type Row = { id: string;",
        "  // The label.",
        "  label: string;",
        "  // The href.",
        "  href: string;",
        "};",
      ].join("\n"),
    },

    {
      code: [
        "// Row shape.",
        "type Row = { id: string; label: string; href: string };",
      ].join("\n"),
    },
  ],
  invalid: [
    ...["\n", "\r\n"].map(ending => ({
      name: "shared guarded deletion retains normal terminators " + JSON.stringify(ending),
      code: "interface Client {\n  /** Read user. */\n  readUser(): void;\n  /** Write user. */\n  writeUser(): void;\n  /** Delete user. */\n  deleteUser(): void;\n}".replaceAll("\n", ending),
      output: "interface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}".replaceAll("\n", ending),
      errors: [{ messageId: "typeMemberCommentWall" as const }],
    })),
    { name: "automatically removes only exact multiword member names (own filename: Oxlint rejects the duplicate code of the LF case)", filename: "src/client.ts", code: "interface Client {\n  /** Read user. */\n  readUser(): void;\n  /** Write user. */\n  writeUser(): void;\n  /** Delete user. */\n  deleteUser(): void;\n}", output: "interface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}", errors: [{ messageId: "typeMemberCommentWall" }] },

    {
      code: "interface Credentials {\n  // Database host.\n  host?: string;\n  // Database host port.\n  port?: number;\n  // Database username.\n  username?: string;\n  // Database password.\n  password?: string;\n}",
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "type RouteModule = {",
        "  // links",
        "  links: unknown;",
        "",
        "  // meta",
        "  meta: unknown;",
        "",
        "  // clientLoader",
        "  clientLoader: unknown;",
        "",
        "  // errorBoundary",
        "  errorBoundary: unknown;",
        "}",
      ].join("\n"),
      output: "type RouteModule = {\n  // links\n  links: unknown;\n\n  // meta\n  meta: unknown;\n\n\n  clientLoader: unknown;\n\n\n  errorBoundary: unknown;\n}",
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "interface Cart {",
        "  // count",
        "  itemCount: number;",
        "  // total",
        "  itemTotal: number;",
        "  // label",
        "  itemLabel: string;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "interface CordovaOptions {",
        "  /** Database type. */",
        "  type: string;",
        "",
        "  /** Database name. */",
        "  database: string;",
        "",
        "  /** Storage Location */",
        "  location: string;",
        "",
        "  /** The driver object, which the platform resolves lazily at connect time. */",
        "  driver: unknown;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "interface ArgumentsHost {",
        "  // Returns the data object.",
        "  getData(): unknown;",
        "  // Returns the client object.",
        "  getClient(): unknown;",
        "  // Returns the pattern",
        "  getPattern(): string;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "interface Doc {",
        "  employee: string; // employee",
        "  employer: string; // employer",
        "  retiree: string; // retiree",
        "}",
      ].join("\n"),
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      code: [
        "interface Outer {",
        "  id: string;",
        "  meta: {",
        "    // Meta name.",
        "    name: string;",
        "    // Meta title.",
        "    title: string;",
        "    // Meta description.",
        "    description: string;",
        "  };",
        "}",
      ].join("\n"),
      errors: [{ messageId: "typeMemberCommentWall" }],
    },

    {
      name: "honours a higher novel-word allowance",
      code: [
        "interface Timestamps {",
        "  // Time that the latest query started",
        "  startedTimeStamp: number;",
        "  // Time that the latest query was fulfilled",
        "  fulfilledTimeStamp: number;",
        "  // Name of the endpoint associated with the query",
        "  endpointName: string;",
        "}",
      ].join("\n"),
      options: [{ maxNovelWords: 2 }],
      errors: [{ messageId: "typeMemberCommentWall" }],
    },
    {
      name: "honours a two-member wall minimum",
      code: [
        "interface Pair {",
        "  // Database host.",
        "  host: string;",
        "  // Database port.",
        "  port: number;",
        "}",
      ].join("\n"),
      options: [{ minCommentedMembers: 2 }],
      errors: [{ messageId: "typeMemberCommentWall" }],
    },
    {
      name: "honours a lower restatement ratio",
      code: [
        "interface MixedDocumentation {",
        "  // Host",
        "  host: string;",
        "  // Port",
        "  port: number;",
        "  // resolved from the control plane during failover",
        "  user: string;",
        "  // rotated nightly by the credential vault",
        "  password: string;",
        "}",
      ].join("\n"),
      options: [{ minRestatedRatio: 0.5 }],
      errors: [{ messageId: "typeMemberCommentWall" }],
    },
  ],
});
