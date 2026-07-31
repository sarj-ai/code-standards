import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-type-member-comment-wall.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester();

ruleTester.run("no-type-member-comment-wall", rule, {
  valid: [
    // No member comments at all — 79% of the OSS corpus.
    { code: "interface Credentials { host: string; port: number; username: string; }" },
    // Every comment says something the name and the type cannot.
    {
      code: [
        "interface Credentials {",
        "  // resolved from the VPC DNS name, not the public one",
        "  host: string;",
        "  // the pooler port, not the direct one",
        "  port: number;",
        "  // rotated nightly by the secret manager",
        "  username: string;",
        "}",
      ].join("\n"),
    },
    // Fewer than `minCommentedMembers` rows is not a wall.
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
    // GROUP LABELS: a minority of members commented, each introducing a run.
    // `excalidraw/packages/excalidraw/types.ts:221` and `typescript-eslint`'s
    // `BinaryOperatorToText.ts:4` are this shape, and deleting the labels loses
    // the grouping.
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
    // A documented default is the one fact an optional member's type cannot
    // hold — `vite/packages/plugin-legacy/src/types.ts:1` is eight of these.
    {
      code: [
        "interface LegacyOptions {",
        "  // default: true",
        "  polyfills: boolean;",
        "  // default: false",
        "  renderLegacyChunks: boolean;",
        "  // defaults to the browserslist query",
        "  targets: string;",
        "}",
      ].join("\n"),
    },
    // A digit is a bound, a base or an index origin.
    // `typescript-eslint/packages/utils/src/ts-eslint/Linter.ts:200`.
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
    // A unit word is the same fact spelled without a digit.
    {
      code: [
        "interface Effort {",
        "  // Estimated effort in days",
        "  effort: number;",
        "  // Elapsed time in seconds",
        "  elapsed: number;",
        "  // Payload size in bytes",
        "  size: number;",
        "}",
      ].join("\n"),
    },
    // Quoted example values and `e.g.` enumerate what the type only bounds.
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
    // A JSDoc value tag means the block is doing something else.
    {
      code: [
        "interface Legacy {",
        "  /** Database host. @deprecated use `endpoint` */",
        "  host: string;",
        "  /** Database port. @see https://example.com/ports */",
        "  port: number;",
        "  /** Database user. @example admin */",
        "  user: string;",
        "}",
      ].join("\n"),
    },
    // The nine-signal protected class is an exemption floor here as everywhere.
    {
      code: [
        "interface Retry {",
        "  // Retry count — otherwise the queue redelivers forever",
        "  retries: number;",
        "  // Backoff base (RFC 9110)",
        "  backoff: number;",
        "  // Deadline; must be monotonic",
        "  deadline: number;",
        "}",
      ].join("\n"),
    },
    // Computed members have no readable name to re-spell — the
    // `// phantom type` shape in redux-toolkit's `endpointDefinitions.ts`.
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
    // Non-ASCII prose the tokenizer cannot read.
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
    // Generated output is rewritten by its generator — 79% of the first-party
    // raw findings were one `types.gen.ts` per repo.
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
    // Test files: a table of identical case labels is not a documentation wall.
    {
      code: [
        "interface Cases {",
        "  // it should return the numeric keys",
        "  a: string;",
        "  // it should return the numeric keys",
        "  b: string;",
        "  // it should return the numeric keys",
        "  c: string;",
        "}",
      ].join("\n"),
      filename: "src/path.test.ts",
    },
    // A TRAILING comment belongs to its own member, not to the one below it.
    // Without the standalone check this reads as three commented members.
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
    // A one-line type literal under a doc block: the three members do NOT each
    // own that block. This shape was 100% of the first-party findings before
    // `documentingComment` required the member to start its own line — a React
    // component's inline props type sitting under the component's own JSDoc.
    {
      code: [
        "/** A logo. */",
        "export default function Logo({ d, cids, styles }: { d: LogoData; cids: string[]; styles: LogoStyles }) {",
        "  return null;",
        "}",
      ].join("\n"),
    },
    // The same shape with a block comment that really does precede a one-line
    // type alias — one comment, one claim, not three.
    {
      code: [
        "// Row shape.",
        "type Row = { id: string; label: string; href: string };",
      ].join("\n"),
    },
  ],
  invalid: [
    // typeorm/src/driver/sap/SapConnectionCredentialsOptions.ts:4 — ten members,
    // ten comments, every one "Database <the member's name>."
    {
      code: [
        "interface SapCredentials {",
        "  // Database host.",
        "  host?: string;",
        "  // Database host port.",
        "  port?: number;",
        "  // Database username.",
        "  username?: string;",
        "  // Database password.",
        "  password?: string;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },
    // react-router/packages/react-router/lib/types/route-module-annotations.ts:212
    // — the comment IS the member's name.
    {
      code: [
        "type RouteModule = {",
        "  // links",
        "  links: unknown;",
        "  // meta",
        "  meta: unknown;",
        "  // clientLoader",
        "  clientLoader: unknown;",
        "  // errorBoundary",
        "  errorBoundary: unknown;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },
    // JSDoc form, and the whole-type report survives one substantive row:
    // three of four comments restate, which is exactly `minRestatedRatio`.
    // typeorm/src/driver/cordova/CordovaDataSourceOptions.ts:6 is this shape.
    {
      code: [
        "interface CordovaOptions {",
        "  /** Database type. */",
        "  type: string;",
        "  /** Database name. */",
        "  database: string;",
        "  /** Storage Location */",
        "  location: string;",
        "  /** The driver object, which the platform resolves lazily at connect time. */",
        "  driver: unknown;",
        "}",
      ].join("\n"),
      errors: [{ messageId: "commentWall" }],
    },
    // Method signatures count too — nest/packages/common/interfaces/features/
    // arguments-host.interface.ts:25.
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
    // Trailing comments, one per member.
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
    // A nested type literal is judged on its own members.
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
    // The option loosens the per-comment test for a team that wants it. Every
    // row here adds exactly two words beyond its member.
    {
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
  ],
});
