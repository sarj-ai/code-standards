import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { ESLint, Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule, { NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION } from "../../src/rules/no-zod-parse-typed-object.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });
const ROW = 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() });';
const KNOWN = ROW + 'declare const row: { id: string };';
const ERROR = { messageId: "typedObject" } as const;

TESTER.run("no-zod-parse-typed-object", rule, {
  valid: [
    { name: "unknown boundary", code: NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION.examples[1].files[0].source },
    { name: "unknown response", code: ROW + 'declare function load(): Promise<unknown>; async function read() { return RowSchema.parse(await load()); }' },
    { name: "untyped response", code: ROW + 'declare const row: any; const value = RowSchema.parse(row);' },
    { name: "unknown nested property", code: ROW + 'declare const row: { id: unknown }; const value = RowSchema.parse(row);' },
    { name: "any nested property", code: ROW + 'declare const row: { id: any }; const value = RowSchema.parse(row);' },
    { name: "opaque generic", code: ROW + 'function read<T extends { id: string }>(row: T) { return RowSchema.parse(row); }' },
    { name: "empty object annotation", code: ROW + 'declare const row: {}; const value = RowSchema.parse(row);' },
    { name: "incompatible object contract", code: ROW + 'declare const row: { id: number }; const value = RowSchema.parse(row);' },
    { name: "primitive UUID validation", code: 'import { z } from "zod"; declare const id: string; const value = z.uuid().parse(id);' },
    { name: "type-changing transform", code: KNOWN + 'const value = RowSchema.transform(row => row.id).parse(row);' },
    { name: "nested type-changing transform", code: 'import { z } from "zod"; const Schema = z.object({ id: z.string().transform(Number) }); declare const row: { id: string }; const value = Schema.parse(row);' },
    { name: "transform adds a property", code: KNOWN + 'const value = RowSchema.transform(row => ({ ...row, enabled: true })).parse(row);' },
    { name: "union transform changes one output branch", code: 'import { z } from "zod"; const Schema = z.union([z.object({ id: z.string() }), z.object({ id: z.string() })]).transform((row): { id: string } | { count: number } => row.id.length > 0 ? row : { count: 0 }); declare const row: { id: string }; const value = Schema.parse(row);' },
    { name: "tuple transform changes length", code: 'import { z } from "zod"; const Schema = z.tuple([z.string(), z.string()]).transform((pair): [string] => [pair[0]]); declare const pair: [string, string]; const value = Schema.parse(pair);' },
    { name: "tuple transform changes positions", code: 'import { z } from "zod"; const Schema = z.tuple([z.string(), z.number()]).transform(([id, count]): [number, string] => [count, id]); declare const pair: [string, number]; const value = Schema.parse(pair);' },
    { name: "rest tuple transform changes cardinality", code: 'import { z } from "zod"; const Schema = z.tuple([z.string()]).rest(z.number()).transform((pair): [string, number] => [pair[0], pair[1] ?? 0]); declare const pair: [string, ...number[]]; const value = Schema.parse(pair);' },
    { name: "leading rest tuple transform changes suffix type", code: 'import { z } from "zod"; type Input = [...string[], number]; type Output = [...number[], string]; const Schema = z.custom<Input>().transform((value): Output => [...value.slice(0, -1).map(Number), String(value.at(-1))]); declare const row: Input; const value = Schema.parse(row);' },
    { name: "leading rest tuple transform swaps suffix positions", code: 'import { z } from "zod"; type Input = [...string[], number, boolean]; type Output = [...string[], boolean, number]; const Schema = z.custom<Input>().transform((value): Output => [...value.slice(0, -2).map(String), Boolean(value.at(-1)), Number(value.at(-2))]); declare const row: Input; const value = Schema.parse(row);' },
    { name: "empty tuple transform changes cardinality", code: 'import { z } from "zod"; const Schema = z.tuple([]).transform((): [string] => ["added"]); declare const row: []; const value = Schema.parse(row);' },
    { name: "large primitive union transform changes contract", code: 'import { z } from "zod"; const Schema = z.object({ kind: z.enum(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t"]) }).transform(() => ({ kind: "changed" as const })); declare const row: z.input<typeof Schema>; const value = Schema.parse(row);' },
    { name: "coercion owns an unknown input", code: 'import { z } from "zod"; const Schema = z.object({ id: z.coerce.string() }); declare const row: { id: number }; const value = Schema.parse(row);' },
    { name: "brand changes the contract", code: KNOWN + 'const value = RowSchema.brand<"Row">().parse(row);' },
    { name: "nested brand changes the contract", code: 'import { z } from "zod"; const Schema = z.object({ id: z.string().brand<"Id">() }); declare const row: { id: string }; const value = Schema.parse(row);' },
    { name: "legacy brand changes the contract", code: 'import { z } from "zod/v3"; const Schema = z.object({ id: z.string() }).brand<"Row">(); declare const row: { id: string }; const value = Schema.parse(row);' },
    { name: "asserting a type does not prove unknown input", code: ROW + 'declare const raw: unknown; const value = RowSchema.parse(raw as { id: string });' },
    { name: "unrelated parse API", code: 'const RowSchema = { parse(row: { id: string }) { return row; } }; const value = RowSchema.parse({ id: "ok" });' },
    { name: "runtime schema tests may revalidate typed objects", filename: "row.test.ts", code: KNOWN + 'const value = RowSchema.parse(row);' },
    { name: "story fixtures may validate examples", filename: "row.stories.ts", code: KNOWN + 'const value = RowSchema.parse(row);' },
    { name: "generated code is owned by its generator", code: '// @generated\n' + KNOWN + 'const value = RowSchema.parse(row);' },
    { name: "optional call is not a direct parse", code: KNOWN + 'const value = RowSchema.parse?.(row);' },
  ],
  invalid: [
    { name: "documented typed service result", code: NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION.examples[2].files[0].source, output: null, errors: [ERROR] },
    { name: "documented typed result with a default", code: NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION.examples[3].files[0].source, output: null, errors: [ERROR] },
    ...["parse", "safeParse", "parseAsync", "safeParseAsync"].map(method => ({
      name: "known object through " + method, code: KNOWN + "const value = RowSchema." + method + "(row);", output: null, errors: [ERROR],
    })),
    { name: "quoted method and schema alias", code: KNOWN + 'const alias = RowSchema; const value = alias["parse"](row);', output: null, errors: [ERROR] },
    { name: "member-held schema", code: KNOWN + 'const schemas = { row: RowSchema }; const value = schemas.row.parse(row);', output: null, errors: [ERROR] },
    { name: "known array contract", code: 'import { z } from "zod"; declare const rows: { id: string }[]; const value = z.array(z.object({ id: z.string() })).parse(rows);', output: null, errors: [ERROR] },
    { name: "known tuple contract", code: 'import { z } from "zod"; declare const pair: [string, number]; const value = z.tuple([z.string(), z.number()]).parse(pair);', output: null, errors: [ERROR] },
    { name: "known empty tuple contract", code: 'import { z } from "zod"; declare const row: []; const value = z.tuple([]).parse(row);', output: null, errors: [ERROR] },
    { name: "known nested empty tuple contract", code: 'import { z } from "zod"; declare const row: { items: [] }; const value = z.object({ items: z.tuple([]) }).parse(row);', output: null, errors: [ERROR] },
    { name: "unchanged leading rest tuple contract", code: 'import { z } from "zod"; type Row = [...string[], number]; declare const row: Row; const value = z.custom<Row>().parse(row);', output: null, errors: [ERROR] },
    { name: "unchanged multiple trailing tuple positions", code: 'import { z } from "zod"; type Row = [...string[], number, boolean]; declare const row: Row; const value = z.custom<Row>().parse(row);', output: null, errors: [ERROR] },
    { name: "unchanged optional tuple positions", code: 'import { z } from "zod"; declare const row: [string, number?]; const value = z.tuple([z.string(), z.number().optional()]).parse(row);', output: null, errors: [ERROR] },
    { name: "known large primitive union", code: 'import { z } from "zod"; const Schema = z.object({ kind: z.enum(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t"]) }); declare const row: z.input<typeof Schema>; const value = Schema.parse(row);', output: null, errors: [ERROR] },
    { name: "known large primitive union with a default", code: 'import { z } from "zod"; const Schema = z.object({ kind: z.enum(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t"]).default("a") }); declare const row: z.input<typeof Schema>; const value = Schema.parse(row);', output: null, errors: [ERROR] },
    { name: "known object literal", code: ROW + 'const value = RowSchema.parse({ id: "ok" });', output: null, errors: [ERROR] },
    { name: "legacy known object contract", code: 'import { z } from "zod/v3"; const Schema = z.object({ id: z.string() }); declare const row: { id: string }; const value = Schema.parse(row);', output: null, errors: [ERROR] },
    { name: "typed service with nested SDK defaults and refinements", code: 'import { z } from "zod"; const NoticeSchema = z.object({ id: z.string().min(1), title: z.string().trim().min(1), enabled: z.boolean().default(false), messages: z.record(z.string(), z.string()), startsAt: z.iso.datetime(), timezone: z.string().refine(value => value.length > 0) }); const ResultSchema = z.object({ notice: NoticeSchema, revision: z.number().int().positive() }); declare const service: { stop(): Promise<{ notice: { id: string; title: string; enabled?: boolean; messages: { en?: string; ar?: string }; startsAt: string; timezone: string }; revision: number }> }; async function stop() { return { data: ResultSchema.parse(await service.stop()) }; }', output: null, errors: [ERROR] },
    { name: "one diagnostic per parse", code: KNOWN + 'const first = RowSchema.parse(row); const second = RowSchema.safeParse(row);', output: null, errors: [ERROR, ERROR] },
  ],
});

it("executes documented examples with the installed native Zod declarations", async () => {
  await expect(verifyRuleExamples(rule, { installedDependencyRoot: new URL("../../", import.meta.url).pathname })).resolves.toBe(4);
});

it("leaves syntax-only linting available without fabricating a type proof", () => {
  const messages = new Linter().verify(KNOWN + 'const value = RowSchema.parse(row);', {
    files: ["**/*.ts"],
    languageOptions: { parser }, plugins: { test: { rules: { "known-object": rule } } }, rules: { "test/known-object": "error" },
  }, "row.ts");
  expect(messages).toEqual([]);
});

it("honors a documented local suppression for intentional revalidation", async () => {
  const cwd = join(import.meta.dirname, "..", "fixtures");
  const eslint = new ESLint({ cwd, overrideConfigFile: true, overrideConfig: [{
    files: ["**/*.ts"], languageOptions: { parser, parserOptions: { projectService: { allowDefaultProject: ["*.ts"] }, tsconfigRootDir: cwd } },
    plugins: { "@sarj": { rules: { "no-zod-parse-typed-object": rule } } }, rules: { "@sarj/no-zod-parse-typed-object": "warn" },
  }] });
  const results = await eslint.lintText(KNOWN + '\n// eslint-disable-next-line @sarj/no-zod-parse-typed-object -- Revalidate after an external plugin mutates this record.\nconst value = RowSchema.parse(row);', { filePath: join(cwd, "row.ts") });
  expect(results.flatMap(result => result.messages)).toEqual([]);
  expect(results.flatMap(result => result.suppressedMessages).map(message => message.ruleId)).toEqual(["@sarj/no-zod-parse-typed-object"]);
});
