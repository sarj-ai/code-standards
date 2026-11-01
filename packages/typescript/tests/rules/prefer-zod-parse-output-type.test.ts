import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { TSESLint } from "@typescript-eslint/utils";
import { ESLint, Linter, type Rule } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import plugin from "../../src/index.js";
import { retainsNamedTypeUses } from "../../src/rules/_type-binding.js";
import rule, {
  PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION,
} from "../../src/rules/prefer-zod-parse-output-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

function retainedTypeResults(body: string): readonly boolean[] {
  const results: boolean[] = [];
  const probe: TSESLint.RuleModule<"probe", []> = {
    meta: { type: "problem", schema: [], messages: { probe: "Probe." } },
    defaultOptions: [],
    create(context) {
      return {
        TSAsExpression(node) { results.push(retainsNamedTypeUses(context.sourceCode, node.typeAnnotation)); },
        TSTypeAliasDeclaration(node) { results.push(retainsNamedTypeUses(context.sourceCode, node)); },
      };
    },
  };
  const messages = new Linter().verify(`export {}; declare const value: unknown; ${body}`, {
    files: ["**/*.ts"],
    languageOptions: { parser: tsParser, sourceType: "module", parserOptions: { lib: ["esnext"] } },
    plugins: { proof: { rules: { retained: probe as unknown as Rule.RuleModule } } },
    rules: { "proof/retained": "error" },
  }, { filename: "liveness.ts" });
  expect(messages).toEqual([]);
  expect(results.length).toBeGreaterThan(0);
  return results;
}

function retainedTypeResult(body: string): boolean {
  return retainedTypeResults(body).at(-1) ?? false;
}

describe("named reads surviving erased type regions", () => {
  it.each([
    ["exported alias", "interface Target { id: string } export type Kept = Target; value as Target;", true],
    ["explicit type export", "interface Target { id: string } export type { Target }; value as Target;", true],
    ["all generic arguments", "interface Target { id: string } type Box<T> = T; export type Kept = Box<Target>; value as Box<Target>;", true],
    ["qualified namespace root", "namespace Models { export interface Target { id: string } } export type Kept = Models.Target; value as Models.Target;", true],
    ["typeof value read", "const factory = () => 1; export type Kept = typeof factory; value as typeof factory;", true],
    ["resolved global without a local declaration", "value as Promise<string>;", true],
    ["no named read", "value as number;", true],
    ["sole interface use", "interface Target { id: string } value as Target;", false],
    ["own exported definition", "export type Target = Target; value as Target;", false],
    ["mutually recursive private definitions", "type Target = Other; type Other = Target; value as Target;", false],
    ["value-only use cannot retain the merged type", "interface Target { id: string } const Target = 1; export type Kept = typeof Target; value as Target;", false],
    ["variable annotation", "interface Target { id: string } declare const witness: Target; value as Target;", false],
    ["exported variable annotation", "interface Target { id: string } export const witness: Target = { id: 'a' }; value as Target;", false],
    ["return annotation", "interface Target { id: string } function witness(): Target { return { id: 'a' }; } value as Target;", false],
    ["union parameter annotation", "interface Target { id: string } function witness(p: Target | string) {} value as Target;", false],
    ["predicate annotation", "interface Target { id: string } function witness(p: unknown): p is Target { return true; } value as Target;", false],
    ["other assertion", "interface Target { id: string } const witness = value as Target; value as Target;", false],
    ["angle assertion", "interface Target { id: string } const witness = <Target>value; value as Target;", false],
    ["interface property annotation", "interface Target { id: string } interface Other { child: Target } value as Target;", false],
    ["unresolved name", "value as Missing;", false],
  ] as const)("%s", (_name, code, expected) => {
    expect(retainedTypeResult(code)).toBe(expected);
  });

  it("keeps each removed range independent of cached binding facts", () => {
    expect(retainedTypeResults("interface Target { id: string } export type Kept = Target; value as Target;"))
      .toEqual([false, true]);
    expect(retainedTypeResults("interface Target { id: string } export type First = Target; value as Target; export type Last = Target; value as Target;"))
      .toEqual([true, true, true, true]);
  });

  it("keeps public value reads distinct from public type reads", () => {
    expect(retainedTypeResults("interface Target { id: string } const Target = 1; export type Kept = typeof Target; value as Target; value as typeof Target;"))
      .toEqual([false, false, true]);
  });

  it("distinguishes shadowed bindings with the same name", () => {
    expect(retainedTypeResults("interface Target { id: string } export type Kept = Target; function inner() { interface Target { name: string } value as Target; } value as Target;"))
      .toEqual([false, false, true]);
  });

  it("rebuilds source facts when another source uses the same filename", () => {
    const retained = "interface Target { id: string } export type Kept = Target; value as Target;";
    const soleUse = "interface Target { id: string } value as Target;";
    expect(retainedTypeResults(retained)).toEqual([false, true]);
    expect(retainedTypeResults(soleUse)).toEqual([false]);
    expect(retainedTypeResults(retained)).toEqual([false, true]);
  });
});

const TYPED_RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: {
        allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"],
        maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 40,
      },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

const IMPORT = 'import { z } from "zod";\n';

function nestedContract(declarations: string, profile: string, schema: string): string {
  return `${IMPORT}${declarations}\ninterface DeepView { profile: ${profile} }\nconst RowSchema = z.object({ profile: ${schema} });\nfunction load(): DeepView { return RowSchema.parse({}); }`;
}

const PRESERVED_NESTED_CONTRACTS = [
  ["inline readonly", nestedContract("", "{ readonly id: string }", "z.object({ id: z.string() })")],
  ["readonly alias", nestedContract("type Profile = Readonly<{ id: string }>;", "Profile", "z.object({ id: z.string() })")],
  ["mapped readonly", nestedContract("type Frozen<T> = { readonly [K in keyof T]: T[K] };", "Frozen<{ id: string }>", "z.object({ id: z.string() })")],
  ["readonly preserved through Pick", nestedContract("type Profile = Pick<Readonly<{ id: string; extra: number }>, 'id'>;", "Profile", "z.object({ id: z.string() })")],
  ["inherited readonly", nestedContract("interface Base { readonly id: string } interface Profile extends Base {}", "Profile", "z.object({ id: z.string() })")],
  ["generic readonly", nestedContract("interface Profile<T> { readonly id: T }", "Profile<string>", "z.object({ id: z.string() })")],
  ["intersection readonly", nestedContract("", "{ id: string } & { readonly label: string }", "z.object({ id: z.string(), label: z.string() })")],
  ["readonly inside mutable array", nestedContract("", "{ readonly id: string }[]", "z.array(z.object({ id: z.string() }))")],
  ["readonly inside mutable tuple", nestedContract("", "[{ readonly id: string }]", "z.tuple([z.object({ id: z.string() })])")],
  ["readonly inside nullable union", nestedContract("", "{ readonly id: string } | null", "z.object({ id: z.string() }).nullable()")],
  ["readonly inside tagged union", nestedContract("", "{ kind: 'a'; readonly id: string } | { kind: 'b'; id: string }", "z.discriminatedUnion('kind', [z.object({ kind: z.literal('a'), id: z.string() }), z.object({ kind: z.literal('b'), id: z.string() })])")],
  ["schema readonly must not rewrite a mutable view", nestedContract("", "{ id: string }", "z.object({ id: z.string() }).readonly()")],
  ["additional optional nested property", nestedContract("", "{ id: string; label?: string }", "z.object({ id: z.string() })")],
  ["omitted optional nested property", nestedContract("", "{ id: string }", "z.object({ id: z.string(), label: z.string().optional() })")],
  ["nested optionality", nestedContract("", "{ id?: string }", "z.object({ id: z.string().optional() }).transform(value => ({ id: value.id }))")],
  ["nested readonly class", nestedContract("class Profile { readonly id = ''; }", "Profile", "z.object({ id: z.string() })")],
  ["distinct mutable class ownership", nestedContract("class Profile { id: string = ''; }", "Profile", "z.object({ id: z.string() })")],
  ["nested getter with a broader setter", nestedContract("interface Profile { get id(): string; set id(value: unknown) }", "Profile", "z.object({ id: z.string() })")],
  ["nested getter with matching setter", nestedContract("interface Profile { get id(): string; set id(value: string) }", "Profile", "z.object({ id: z.string() })")],
  ["mapped accessor write capability", nestedContract("interface Accessors { get id(): string; set id(value: unknown) } type Profile = Pick<Accessors, 'id'>;", "Profile", "z.object({ id: z.string() })")],
  ["nested getter", nestedContract("interface Profile { get id(): string }", "Profile", "z.object({ id: z.string() })")],
  ["nested index signature", nestedContract("interface Profile { id: string; [key: string]: string }", "Profile", "z.object({ id: z.string() })")],
  ["nested opaque any", nestedContract("", "{ id: any }", "z.object({ id: z.any() })")],
  ["nested unknown", nestedContract("", "{ id: unknown }", "z.object({ id: z.unknown() })")],
  ["recursive readonly", nestedContract("interface WireNode { id: string; next?: WireNode } interface Profile { readonly id: string; next?: Profile } const NodeSchema: z.ZodType<WireNode> = z.object({ id: z.string(), next: z.lazy(() => NodeSchema).optional() });", "Profile", "NodeSchema")],
] as const;

const EQUIVALENT_NESTED_CONTRACTS = [
  ["mutable inline record", nestedContract("", "{ id: string }", "z.object({ id: z.string() })")],
  ["mutable alias", nestedContract("interface Profile { id: string }", "Profile", "z.object({ id: z.string() })")],
  ["mutable inheritance", nestedContract("interface Base { id: string } interface Profile extends Base {}", "Profile", "z.object({ id: z.string() })")],
  ["instantiated mutable generic", nestedContract("interface Profile<T> { id: T }", "Profile<string>", "z.object({ id: z.string() })")],
  ["removed mapped readonly", nestedContract("interface Frozen { readonly id: string } type Mutable<T> = { -readonly [K in keyof T]: T[K] };", "Mutable<Frozen>", "z.object({ id: z.string() })")],
  ["mutable array", nestedContract("", "{ id: string }[]", "z.array(z.object({ id: z.string() }))")],
  ["mutable tuple", nestedContract("", "[{ id: string }, number]", "z.tuple([z.object({ id: z.string() }), z.number()])")],
  ["nullable nested record", nestedContract("", "{ id: string } | null", "z.object({ id: z.string() }).nullable()")],
  ["matching optional nested property", nestedContract("", "{ id: string; label?: string }", "z.object({ id: z.string(), label: z.string().optional() })")],
  ["matching nested readonly", nestedContract("", "Readonly<{ id: string }>", "z.object({ id: z.string() }).readonly()")],
  ["matching tagged union", nestedContract("", "{ kind: 'a'; id: string } | { kind: 'b'; id: string }", "z.discriminatedUnion('kind', [z.object({ kind: z.literal('a'), id: z.string() }), z.object({ kind: z.literal('b'), id: z.string() })])")],
  ["mutable recursive aliases", nestedContract("interface WireNode { id: string; next?: WireNode } interface Profile { id: string; next?: Profile } const NodeSchema: z.ZodType<WireNode> = z.object({ id: z.string(), next: z.lazy(() => NodeSchema).optional() });", "Profile", "NodeSchema")],
  ["shared validated class identity", nestedContract("class Profile { constructor(readonly id: string) {} }", "Profile", "z.instanceof(Profile)")],
] as const;

const PORT_IMPORT = 'import type { DomainView, ReadPort, AsyncReadPort, ReadPropertyPort, GenericReadPort, ReadCallable, ViewPort, AdapterPort } from "./zod-output-port-contracts.js"; import { ReadBase, ViewBase } from "./zod-output-port-contracts.js";';
const PORT_SCHEMA = `${IMPORT}${PORT_IMPORT} const RowSchema = z.object({ id: z.string() });`;
const PRESERVED_PORT_CONTRACTS = [
  ["explicit imported callable binding", `${PORT_SCHEMA} export const read: ReadCallable = (): DomainView => RowSchema.parse({});`],
  ["explicit function expression callable binding", `${PORT_SCHEMA} const read: ReadCallable = function(): DomainView { return RowSchema.parse({}); };`],
  ["explicit inline callable binding", `${PORT_SCHEMA} const read: () => DomainView = (): DomainView => RowSchema.parse({});`],
  ["explicit generic callable binding", `${PORT_SCHEMA} interface Callable<T> { (): T } const read: Callable<DomainView> = (): DomainView => RowSchema.parse({});`],
  ["readonly property callable binding", `${PORT_SCHEMA} class Adapter { readonly read: ReadCallable = (): DomainView => RowSchema.parse({}); }`],
  ["contextual callback contract", `${PORT_SCHEMA} declare function consume(read: ReadCallable): void; consume((): DomainView => RowSchema.parse({}));`],
  ["contextual inline callback contract", `${PORT_SCHEMA} declare function consume(read: () => DomainView): void; consume((): DomainView => RowSchema.parse({}));`],
  ["contextual readonly object property", `${PORT_SCHEMA} const adapter: AdapterPort = { read: (): DomainView => RowSchema.parse({}) };`],
  ["contextual object method", `${PORT_SCHEMA} const adapter: ReadPort = { read(): DomainView { return RowSchema.parse({}); } };`],
  ["contextual returned callable", `${PORT_SCHEMA} function adapter(): ReadCallable { return (): DomainView => RowSchema.parse({}); }`],
  ["implemented getter property", `${PORT_SCHEMA} class Adapter implements ViewPort { get view(): DomainView { return RowSchema.parse({}); } }`],
  ["inherited getter contract", `${PORT_SCHEMA} class Adapter extends ViewBase { override get view(): DomainView { return RowSchema.parse({}); } }`],
  ["contextual object getter", `${PORT_SCHEMA} const adapter: ViewPort = { get view(): DomainView { return RowSchema.parse({}); } };`],
  ["implemented imported method contract", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return RowSchema.parse({}); } }`],
  ["implemented asynchronous contract", `${PORT_SCHEMA} class Adapter implements AsyncReadPort { async read(): Promise<DomainView | null> { return RowSchema.parse({}); } }`],
  ["implemented arrow property contract", `${PORT_SCHEMA} class Adapter implements ReadPropertyPort { read = (): DomainView => RowSchema.parse({}); }`],
  ["implemented function property contract", `${PORT_SCHEMA} class Adapter implements ReadPropertyPort { read = function(): DomainView { return RowSchema.parse({}); }; }`],
  ["instantiated generic port contract", `${PORT_SCHEMA} class Adapter implements GenericReadPort<DomainView> { read(): DomainView { return RowSchema.parse({}); } }`],
  ["inherited interface port contract", `${PORT_SCHEMA} interface InheritedPort extends ReadPort {} class Adapter implements InheritedPort { read(): DomainView { return RowSchema.parse({}); } }`],
  ["inherited abstract class contract", `${PORT_SCHEMA} class Adapter extends ReadBase { override read(): DomainView { return RowSchema.parse({}); } }`],
  ["class expression implementing a port", `${PORT_SCHEMA} const Adapter = class implements ReadPort { read(): DomainView { return RowSchema.parse({}); } };`],
] as const;
const INDEPENDENT_HELPERS = [
  ["own return annotation alone is not an external callable contract", `${PORT_SCHEMA} const read = (): DomainView => RowSchema.parse({});`],
  ["inferred generic callback does not establish ownership", `${PORT_SCHEMA} declare function consume<T>(read: () => T): T; consume((): DomainView => RowSchema.parse({}));`],
  ["uncontextualized object method", `${PORT_SCHEMA} const adapter = { read(): DomainView { return RowSchema.parse({}); } };`],
  ["uncontextualized object getter", `${PORT_SCHEMA} const adapter = { get view(): DomainView { return RowSchema.parse({}); } };`],
  ["unrelated getter on implementing class", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return { id: "known" }; } get view(): DomainView { return RowSchema.parse({}); } }`],
  ["private getter remains independent", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return { id: "known" }; } private get view(): DomainView { return RowSchema.parse({}); } }`],
  ["static getter does not fulfill instance port", `${PORT_SCHEMA} class Adapter implements ViewPort { get view(): DomainView { return { id: "known" }; } static get view(): DomainView { return RowSchema.parse({}); } }`],
  ["class without a port", `${PORT_SCHEMA} class Adapter { read(): DomainView { return RowSchema.parse({}); } }`],
  ["unrelated member of implementing class", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return { id: "known" }; } load(): DomainView { return RowSchema.parse({}); } }`],
  ["private helper of implementing class", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return { id: "known" }; } private load(): DomainView { return RowSchema.parse({}); } }`],
  ["static member does not fulfill instance port", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return { id: "known" }; } static read(): DomainView { return RowSchema.parse({}); } }`],
  ["independent function beside a port implementation", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { return RowSchema.parse({}); } } function load(): DomainView { return RowSchema.parse({}); }`],
  ["nested helper does not fulfill enclosing method contract", `${PORT_SCHEMA} class Adapter implements ReadPort { read(): DomainView { function load(): DomainView { return RowSchema.parse({}); } return load(); } }`],
  ["same shape does not establish named ownership", `${PORT_SCHEMA} interface OtherView { id: string } interface OtherPort { read(): OtherView } class Adapter implements OtherPort { read(): DomainView { return RowSchema.parse({}); } }`],
] as const;

new RuleTester({ languageOptions: { parser: tsParser } }).run(
  "prefer-zod-parse-output-type without type information",
  rule,
  {
    valid: [
      PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[1].files[0].source,
      {
        name: "requires type information before reporting or fixing a private parsed return",
        filename: "zod-output-private.ts",
        code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }",
      },
    ],
    invalid: [],
  },
);

TYPED_RULE_TESTER.run("prefer-zod-parse-output-type", rule, {
  valid: [
    ...PRESERVED_PORT_CONTRACTS.map(([name, code]) => ({ name, filename: "zod-parse-output-port-owner.ts", code })),
    ...PRESERVED_NESTED_CONTRACTS.map(([name, code]) => ({ name, filename: "zod-parse-output-deep-contract.ts", code })),
    {
      name: "unknown member access does not establish parse identity",
      filename: "zod-parse-output-dynamic-member.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        declare const method: string;
        function get(): TrialChannelRecord { return RowSchema[method]({}); }`,
    },
    {
      name: "accepts the documented schema-derived return",
      filename: "zod-parse-output-derived.ts",
      code: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "allows a domain contract with an additional optional property",
      filename: "zod-parse-output-optional-domain.ts",
      code: `${IMPORT}
        import type { OptionalDomainRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): OptionalDomainRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "leaves same-module twins to prefer-zod-infer",
      filename: "zod-parse-output-same-module.ts",
      code: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() });
        function get(): Row { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a wider property type with the same property keys",
      filename: "zod-parse-output-wider-property.ts",
      code: `${IMPORT}
        interface DomainRecord { status: string }
        const RowSchema = z.object({ status: z.literal("ok") });
        function get(): DomainRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a schema intentionally constrained by the contract",
      filename: "zod-parse-output-constrained.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema: z.ZodType<TrialChannelRecord> = z.object({
          applicationId: z.string(), channelId: z.string().nullable(),
        });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a readonly domain contract",
      filename: "zod-parse-output-readonly.ts",
      code: `${IMPORT}
        import type { ReadonlyRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string() });
        function get(): ReadonlyRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a generic domain contract",
      filename: "zod-parse-output-generic.ts",
      code: `${IMPORT}
        import type { GenericRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ data: z.string() });
        function get(): GenericRecord<string> { return RowSchema.parse({}); }`,
    },
    {
      name: "does not trust an unrelated parse method",
      filename: "zod-parse-output-unrelated-parser.ts",
      code: `import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const parser = { parse(): TrialChannelRecord { return { applicationId: "a", channelId: null }; } };
        function get(): TrialChannelRecord { return parser.parse(); }`,
    },
    {
      name: "does not follow a second local alias",
      filename: "zod-parse-output-second-alias.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord {
          const parsed = RowSchema.parse({});
          const alias = parsed;
          return alias;
        }`,
    },
    {
      name: "does not follow a mutable parse binding",
      filename: "zod-parse-output-mutable-binding.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord {
          let parsed = RowSchema.parse({});
          parsed = { applicationId: "replacement", channelId: null };
          return parsed;
        }`,
    },
    {
      name: "does not treat a safeParse success check as returning normalized output",
      filename: "zod-parse-output-safe-raw.ts",
      code: `${IMPORT}
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(raw: unknown): unknown {
          const parsed = RowSchema.safeParse(raw);
          return parsed.success ? raw : null;
        }`,
    },
    {
      name: "allows an augmented interface whose ownership is split",
      filename: "zod-parse-output-augmented.ts",
      code: `${IMPORT}
        import type { AugmentedRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): AugmentedRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "does not follow a schema composed from another local schema",
      filename: "zod-parse-output-composed.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const WireSchema = z.object({ application_id: z.string(), channel_id: z.string().nullable() });
        const RowSchema = WireSchema.transform((row) => ({
          applicationId: row.application_id, channelId: row.channel_id,
        }));
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "honors an exact rule suppression",
      filename: "zod-parse-output-suppressed.ts",
      code: `/* eslint-disable @rule-tester/prefer-zod-parse-output-type */
        ${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "does not report parsed return contracts in tests",
      filename: "zod-parse-output-return.test.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "skips a contract produced by multiple distinct schemas",
      filename: "zod-parse-output-ambiguous-owner.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const PrimarySchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const LegacySchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function primary(): TrialChannelRecord { return PrimarySchema.parse({}); }
        function legacy(): TrialChannelRecord { return LegacySchema.parse({}); }`,
    },
  ],
  invalid: [
    {name: "derives a private return with an independently exported type use", filename: "zod-output-private.ts",
      code: "import { z } from \"zod\"; interface ParsedRow { id: string } export type KeptParsedRow = ParsedRow; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }",
      output: "import { z } from \"zod\"; interface ParsedRow { id: string } export type KeptParsedRow = ParsedRow; const RowSchema = z.object({ id: z.string() }); function load(): z.output<typeof RowSchema> { return RowSchema.parse({}); }", errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "keeps an imported contract live through an independently exported alias", filename: "zod-output-private.ts",
      code: `${IMPORT}import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js"; export type KeptRecord = TrialChannelRecord; const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() }); function load(): TrialChannelRecord { return RowSchema.parse({}); }`,
      output: `${IMPORT}import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js"; export type KeptRecord = TrialChannelRecord; const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() }); function load(): z.output<typeof RowSchema> { return RowSchema.parse({}); }`, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "other return annotations cannot keep a contract live", filename: "zod-output-private.ts",
      code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function other(): ParsedRow { return { id: \"known\" }; } function load(): ParsedRow { return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "other assertions cannot keep a contract live", filename: "zod-output-private.ts",
      code: "import { z } from \"zod\"; interface ParsedRow { id: string } const witness = {} as ParsedRow; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "private variable annotations cannot keep a contract live", filename: "zod-output-private.ts",
      code: "import { z } from \"zod\"; interface ParsedRow { id: string } const witness: ParsedRow = { id: \"known\" }; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "preserves a sole-use private parsed return contract", filename: "zod-output-private.ts", code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "preserves a consumed parser return contract", filename: "zod-output-private.ts", code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); } consume(load);", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "preserves an exported parser return contract", filename: "zod-output-private.ts", code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); export function load(): ParsedRow { return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "preserves dynamic parser references", filename: "zod-output-private.ts", code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); } eval(\"load\");", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    {name: "preserves comments in the parser body", filename: "zod-output-private.ts", code: "import { z } from \"zod\"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { /* retain contract ownership */ return RowSchema.parse({}); }", output: null, errors: [{messageId: "handWrittenParsedOutput"}]},
    ...INDEPENDENT_HELPERS.map(([name, code]) => ({ name, filename: "zod-parse-output-port-owner.ts", code, output: null, errors: [{ messageId: "handWrittenParsedOutput" as const }] })),
    ...EQUIVALENT_NESTED_CONTRACTS.map(([name, code]) => ({ name, filename: "zod-parse-output-deep-contract.ts", code, output: null, errors: [{ messageId: "handWrittenParsedOutput" as const }] })),
    {
      name: "preserves outcomes for static member access",
      filename: "zod-parse-output-static-member.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z["object"]({ applicationId: z["string"](), channelId: z["string"]()["nullable"]() });
        function get(): TrialChannelRecord { return RowSchema["parse"]({}); }`,
      output: null,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports the documented hand-written parsed return",
      filename: "zod-parse-output-documented.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
      output: null,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports the cross-module nullable return that motivated the rule",
      filename: "zod-parse-output-trial-channel.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        declare const row: unknown;
        async function get(): Promise<null | TrialChannelRecord> {
          return row ? RowSchema.parse(row) : null;
        }`,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: {
            methodName: "parse",
            schemaName: "RowSchema",
            typeName: "TrialChannelRecord",
          },
        },
      ],
    },
    {
      name: "reports a renamed schema because return data flow proves the relationship",
      filename: "zod-parse-output-renamed.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const ValidatedDatabaseOutput = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return ValidatedDatabaseOutput.parse({}); }`,
      output: null,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: {
            methodName: "parse",
            schemaName: "ValidatedDatabaseOutput",
            typeName: "TrialChannelRecord",
          },
        },
      ],
    },
    {
      name: "reports a renamed same-module schema without overlapping prefer-zod-infer",
      filename: "zod-parse-output-renamed-same-module.ts",
      code: `${IMPORT}
        interface PersistedRow { applicationId: string; channelId: string | null }
        const DatabaseResultSchema = z.object({
          applicationId: z.string(), channelId: z.string().nullable(),
        });
        function get(): PersistedRow { return DatabaseResultSchema.parse({}); }`,
      output: null,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: {
            methodName: "parse",
            schemaName: "DatabaseResultSchema",
            typeName: "PersistedRow",
          },
        },
      ],
    },
    {
      name: "reports a hand-written object type alias",
      filename: "zod-parse-output-alias.ts",
      code: `${IMPORT}
        import type { AliasRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): AliasRecord { return RowSchema.parse({}); }`,
      output: null,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "uses the type checker for nested objects and collections",
      filename: "zod-parse-output-nested.ts",
      code: `${IMPORT}
        import type { NestedRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({
          child: z.object({ value: z.string() }), tags: z.array(z.string()),
        });
        function get(): NestedRecord { return RowSchema.parse({}); }`,
      output: null,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "emits one diagnostic when multiple returns repeat the same contract",
      filename: "zod-parse-output-deduplicated.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function first(): TrialChannelRecord { return RowSchema.parse({}); }
        function second(): TrialChannelRecord { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports a synchronous concise arrow return",
      filename: "zod-parse-output-arrow.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const get = (): TrialChannelRecord => RowSchema.parse({});`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports an asynchronous concise arrow return",
      filename: "zod-parse-output-async-arrow.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const get = async (): Promise<TrialChannelRecord> => RowSchema.parse({});`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports a nullable schema output under the same nullish return envelope",
      filename: "zod-parse-output-nullable-schema.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() }).nullable();
        function get(): TrialChannelRecord | null { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports a parse output returned through one immutable local binding",
      filename: "zod-parse-output-local-binding.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord {
          const parsed = RowSchema.parse({});
          observe(parsed.applicationId);
          return parsed;
        }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports safeParse data returned after a success guard",
      filename: "zod-safe-parse-output-guard.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(raw: unknown): TrialChannelRecord | null {
          const parsed = RowSchema.safeParse(raw);
          if (!parsed.success) return null;
          return parsed.data;
        }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports safeParse data returned from a nullish conditional",
      filename: "zod-safe-parse-output-conditional.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(raw: unknown): TrialChannelRecord | undefined {
          const parsed = RowSchema.safeParse(raw);
          return parsed.success ? parsed.data : undefined;
        }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
  ],
});

describe("prefer-zod-infer precedence", () => {
  const eslint = new TSESLint.ESLint({
    overrideConfigFile: true,
    overrideConfig: [
      {
        files: ["**/*.ts"],
        languageOptions: {
          parser: tsParser,
          parserOptions: {
            projectService: {
              allowDefaultProject: ["audit/*.ts"],
              maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 10,
            },
            tsconfigRootDir: join(import.meta.dirname, "..", ".."),
          },
        },
        plugins: { "@sarj": plugin },
        rules: {
          "@sarj/prefer-zod-infer": "error",
          "@sarj/prefer-zod-parse-output-type": "warn",
        },
      },
    ],
  });

  it("runs the native ESLint engine through the TypeScript rule interface", () => {
    expect(eslint).toBeInstanceOf(ESLint);
  });

  it.each([
    {
      name: "canonical twins stay with the established rule",
      source: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() });
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-infer"],
    },
    {
      name: "nested twins stay with the type-aware companion",
      source: `${IMPORT}
        interface Row { child: { id: string } }
        const RowSchema = z.object({ child: z.object({ id: z.string() }) });
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-parse-output-type"],
    },
    {
      name: "transformed twins stay with the type-aware companion",
      source: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() }).transform((row) => row);
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-parse-output-type"],
    },
  ])("$name", async ({ name, rules, source }) => {
    const [result] = await eslint.lintText(source, {
      filePath: join(import.meta.dirname, "..", "..", "audit", `${name.replaceAll(" ", "-")}.ts`),
    });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(rules);
  });
});
