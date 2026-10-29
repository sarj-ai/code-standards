// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_TYPE_MEMBER_COMMENT_WALL_DOCUMENTATION,
} from "../../src/rules/no-type-member-comment-wall.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-type-member-comment-wall", rule, {
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

    { code: NO_TYPE_MEMBER_COMMENT_WALL_DOCUMENTATION.examples[0].files[0].source },
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
    { name: "automatically removes only exact multiword member names", code: "interface Client {\n  /** Read user. */\n  readUser(): void;\n  /** Write user. */\n  writeUser(): void;\n  /** Delete user. */\n  deleteUser(): void;\n}", output: "interface Client {\n\n  readUser(): void;\n\n  writeUser(): void;\n\n  deleteUser(): void;\n}", errors: [{ messageId: "commentWall" }] },


    {
      code: NO_TYPE_MEMBER_COMMENT_WALL_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
    },

    {
      code: [
        "interface Doc {",
        "  employee: string; // employee",
        "  employer: string; // employer",
        "  retiree: string; // retiree",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
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
      errors: [{ messageId: "commentWall" }],
    },
  ],
});
