import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noTypeMemberCommentWallDocumentation,
} from "../../src/rules/no-type-member-comment-wall.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester();

ruleTester.run("no-type-member-comment-wall", rule, {
  valid: [
    // No member comments at all — 79% of the OSS corpus.
    { code: noTypeMemberCommentWallDocumentation.examples[0].files[0].source },
    // Every comment says something the name and the type cannot. Nothing here
    // is protected, quoted, numbered or tagged: the ONLY thing keeping this
    // valid is that each comment adds more than `maxNovelWords` content words,
    // so raising the default makes this case flag.
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
    // Exactly two content words past the member's own text — the boundary the
    // default sits on. `// Partial match` beside `// Exact match` is the pair
    // that kept `maxNovelWords` at 1: the matching MODE is precisely what
    // neither `name` nor `string` can state.
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
    // One substantive row in four is enough: `minRestatedRatio` is 0.75 and
    // this type restates one comment of four.
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
    // GROUP LABELS, minority form: a minority of members commented, each
    // introducing a run. `excalidraw/packages/excalidraw/types.ts:221` and
    // `typescript-eslint`'s `BinaryOperatorToText.ts:4` are this shape, and
    // deleting the labels loses the grouping.
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
    // GROUP LABELS, majority form — `react-router/packages/react-router/lib/
    // types/route-module-annotations.ts:212`, which the first version of this
    // rule flagged. Every label names a ROUTE MODULE EXPORT (`links`, `meta`)
    // and sits over a member named for the TYPE derived from it
    // (`LinkDescriptors`, `MetaArgs`); the comment is heading a region, not
    // describing the row under it, and 13 of the 14 runs are one member long
    // so `minCommentedRatio` never sees them.
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
    // A documented default is the one fact an optional member's type cannot
    // hold — `vite/packages/plugin-legacy/src/types.ts:1` is eight of these.
    // Each row here restates its member apart from the default, so DEFAULT_RE
    // is the only thing keeping the type unflagged.
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
    // A unit word is the same fact spelled without a digit. Strip the unit and
    // every row here is a restatement, so UNIT_WORD_RE is load-bearing.
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
    // A JSDoc value tag means the block is doing something else. The prose is
    // a restatement in all three rows and the tags carry no words the member
    // does not, so VALUE_TAG_RE is what this case turns on. (`@deprecated`,
    // `@see` and `@example` are deliberately absent: each is independently
    // exempt through `isProtected` or EXAMPLE_RE, so a case built on them
    // tests those instead.)
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
    // Tag-only blocks are documentation-generator directives, not prose that
    // re-spells a member. Match the declaration-wall rule's ownership.
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
    // A rule of dashes is a banner; `no-comment-cruft` owns that shape. Take
    // the dashes away and each comment is the member's own name.
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
    // The nine-signal protected class is an exemption floor here as everywhere.
    // Each row adds exactly one content word, so without `isProtected` all
    // three would count as restatements.
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
    // Reflection and decorator metadata: "class" and "parameter" are the whole
    // claim, not filler. `typeorm/src/metadata-args/
    // TransactionEntityMetadataArgs.ts:4`, a false positive until those two
    // words came out of STOPWORDS — `Function` cannot say "class" and `number`
    // cannot say "parameter".
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
    // A VENDORED copy of someone else's declarations: the same exemption, by
    // path. `nest/packages/microservices/external/mqtt-options.interface.ts`
    // is the MQTT.js typings with an `@see` back to the upstream repo, and
    // editing its prose desynchronises the copy.
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
    // Test files: a table of identical case labels is not a documentation wall.
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
    // A FIXTURE is the input to a test, and its comments are usually the thing
    // asserted. `storybook/code/renderers/react/src/componentManifest/
    // __testfixtures__/ForwardRef.tsx` documents three props whose exact
    // strings `componentMetaExtractor.qa.test.ts:448` compares against, and
    // `fixtures/` alone did not match that directory.
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
    // A demo story: prop JSDoc in a `stories/` tree is not commentary, it is
    // OUTPUT — docgen renders it as the args-table description.
    // `storybook/test-storybooks/mcp/stories/other/card/Card.tsx`.
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
    // …and a comment that sits BEFORE its member on the member's own line is a
    // leading comment, not that member's trailing one. Count `/* gamma */` as
    // gamma's and this type is three restated rows out of three.
    {
      code: [
        "interface Doc {",
        "  alpha: string; // alpha",
        "  beta: string; // beta",
        "  /* gamma */ gamma: string;",
        "}",
      ].join("\n"),
    },
    // One comment documents ONE member. A trailing comment on a one-line type
    // literal is claimed once, not once per member that ends on its line.
    {
      code: "type Row = { id: string; label: string; href: string }; // the record",
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
    // …and the same rule with the members spread over several lines: `id`
    // shares the type's opening line, so the block above the type is not its
    // documentation. Give it to `id` and this becomes three restated rows.
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
      code: noTypeMemberCommentWallDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "commentWall" }],
    },
    // A comment that IS its member's name, blank-line separated exactly like
    // the react-router valid case above. The difference is the only thing the
    // label exemption turns on: there the comment named a different identifier
    // from the member it preceded, here it names the member.
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
      errors: [{ messageId: "commentWall" }],
    },
    // A one-word restatement per row is still a wall: no blank lines, no runs,
    // nothing heading a region — just `count` written over `itemCount`.
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
    // JSDoc form, blank-line separated as typeorm writes it, and the
    // whole-type report survives one substantive row: three of four comments
    // restate, which is exactly `minRestatedRatio`.
    // typeorm/src/driver/cordova/CordovaDataSourceOptions.ts:6 is this shape.
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
    // row here adds exactly two words beyond its member — the same shape as
    // the `// Partial match` valid case, which is what the default protects.
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
