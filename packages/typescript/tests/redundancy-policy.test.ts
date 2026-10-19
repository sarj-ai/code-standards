import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_ROOT = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
type ConfigFactory = (options: { tsconfigRootDir: string; projectService?: boolean }) => Linter.Config[];
const STRICT_CONFIG_FACTORY = createConfig as ConfigFactory;
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", STRICT_CONFIG_FACTORY],
  ["application", createApplicationConfig as ConfigFactory],
];
const ASSERTION = "@typescript-eslint/no-unnecessary-type-assertion";
const NESTED_CONST = "no-restricted-syntax";
const EXTRA_LABEL = "no-extra-label";
const UNUSED_LABEL = "no-unused-labels";
const ASSIGNMENT = "no-useless-assignment";
const REDUNDANT_UNION = "@typescript-eslint/no-redundant-type-constituents";
const DUPLICATE_TYPE = "@typescript-eslint/no-duplicate-type-constituents";
const TYPE_ARGUMENT = "@typescript-eslint/no-unnecessary-type-arguments";
const TYPE_CONSTRAINT = "@typescript-eslint/no-unnecessary-type-constraint";
const TYPE_PARAMETER = "@typescript-eslint/no-unnecessary-type-parameters";
const CONVERSION = "@typescript-eslint/no-unnecessary-type-conversion";
const TEMPLATE = "@typescript-eslint/no-unnecessary-template-expression";
const BOOLEAN_COMPARISON = "@typescript-eslint/no-unnecessary-boolean-literal-compare";
const SELECTED_RULES = new Set([
  ASSERTION, NESTED_CONST, EXTRA_LABEL, UNUSED_LABEL, ASSIGNMENT,
  REDUNDANT_UNION, DUPLICATE_TYPE, TYPE_ARGUMENT, TYPE_CONSTRAINT,
  TYPE_PARAMETER, CONVERSION, TEMPLATE, BOOLEAN_COMPARISON,
]);

type ReviewCase = readonly [name: string, code: string, expected: readonly string[], fixed?: string];

const REVIEW_CASES: readonly ReviewCase[] = [
  ["original Group has five redundant member assertions", 'export const Group = { CALLER: "caller" as const, EDITOR: "editor" as const, ORG_ADMIN: "org_admin" as const, SARJ_SUPER_ADMIN: "sarj_super_admin" as const, VIEWER: "viewer" as const } as const;', [NESTED_CONST, NESTED_CONST, NESTED_CONST, NESTED_CONST, NESTED_CONST]],
  ["object string member", 'export const group = { caller: "caller" as const } as const;', [NESTED_CONST]],
  ["object numeric member", "export const group = { count: 1 as const } as const;", [NESTED_CONST]],
  ["object boolean member", "export const group = { active: true as const } as const;", [NESTED_CONST]],
  ["object bigint member", "export const group = { count: 1n as const } as const;", [NESTED_CONST]],
  ["object negative member", "export const group = { offset: -1 as const } as const;", [NESTED_CONST]],
  ["object static template member", "export const group = { kind: `caller` as const } as const;", [NESTED_CONST]],
  ["object nested object assertion", 'export const group = { role: { kind: "caller" } as const } as const;', [NESTED_CONST]],
  ["object nested tuple assertion", 'export const group = { roles: ["caller", "editor"] as const } as const;', [NESTED_CONST]],
  ["object parenthesized member", 'export const group = ({ role: (("caller" as const)) }) as const;', [NESTED_CONST]],
  ["object static computed key", 'export const group = { ["role"]: "caller" as const } as const;', [NESTED_CONST]],
  ["object quoted key", 'export const group = { "role-name": "caller" as const } as const;', [NESTED_CONST]],
  ["mutable binding retains readonly object", 'let group = { role: "caller" as const } as const; export { group };', [NESTED_CONST]],
  ["outer satisfies retains const context", 'export const group = { role: "caller" as const } as const satisfies { readonly role: string };', [NESTED_CONST]],
  ["object multiple assertions", 'export const group = { role: "caller" as const, count: 1 as const } as const;', [NESTED_CONST, NESTED_CONST]],
  ["array string element", 'export const roles = ["caller" as const] as const;', [NESTED_CONST]],
  ["array numeric element", "export const values = [1 as const] as const;", [NESTED_CONST]],
  ["array boolean element", "export const values = [false as const] as const;", [NESTED_CONST]],
  ["array nested object assertion", 'export const roles = [{ kind: "caller" } as const] as const;', [NESTED_CONST]],
  ["array nested tuple assertion", 'export const roles = [["caller"] as const] as const;', [NESTED_CONST]],
  ["array multiple assertions", 'export const roles = ["caller" as const, "editor" as const] as const;', [NESTED_CONST, NESTED_CONST]],
  ["array parenthesized element", 'export const roles = [("caller" as const)] as const;', [NESTED_CONST]],
  ["array element before a spread", 'declare const extra: string[]; export const roles = ["caller" as const, ...extra] as const;', [NESTED_CONST]],
  ["angle assertion around object", 'export const group = <const>{ role: "caller" as const };', [NESTED_CONST]],
  ["angle assertion around array", 'export const roles = <const>["caller" as const];', [NESTED_CONST]],
  ["angle assertion on member", 'export const group = { role: <const>"caller" } as const;', [NESTED_CONST]],
  ["single object const assertion is useful", 'export const group = { role: "caller" } as const;', []],
  ["single tuple const assertion is useful", 'export const roles = ["caller", "editor"] as const;', []],
  ["mutable object member needs literal assertion", 'export const group = { role: "caller" as const };', []],
  ["mutable array element needs literal assertion", 'export const roles = ["caller" as const];', []],
  ["let binding needs literal assertion", 'export let role = "caller" as const;', []],
  ["var binding needs literal assertion", 'export var role = "caller" as const;', []],
  ["arrow return needs literal assertion", 'export const role = () => "caller" as const;', []],
  ["method return needs literal assertion", 'export const group = { role() { return "caller" as const; } } as const;', []],
  ["getter return needs literal assertion", 'export const group = { get role() { return "caller" as const; } } as const;', []],
  ["call argument needs literal assertion", 'declare function wrap<T>(value: T): T; export const group = { role: wrap("caller" as const) } as const;', []],
  ["new argument needs literal assertion", 'declare class Box<T> { constructor(value: T); value: T; } export const group = { role: new Box("caller" as const) } as const;', []],
  ["conditional branch retains explicit narrowing", 'declare const enabled: boolean; export const group = { role: enabled ? "caller" as const : "editor" as const } as const;', []],
  ["function body breaks outer const context", 'export const group = { make: () => ({ role: "caller" as const }) } as const;', []],
  ["satisfies alone does not imply const context", 'export const group = { role: "caller" as const } satisfies { role: string };', []],
  ["intervening satisfies keeps its own context", 'export const group = { role: ("caller" as const) satisfies string } as const;', []],
  ["referenced object keeps independent inference", 'const member = { role: "caller" as const }; export const group = { member } as const;', []],
  ["spread source keeps independent inference", 'export const group = { ...{ role: "caller" as const } } as const;', []],
  ["spread array keeps independent inference", 'export const group = [...["caller" as const]] as const;', []],
  ["computed key is not a property value", 'export const group = { ["caller" as const]: 1 } as const;', []],
  ["ordinary assertion is not const context", 'export const group = { role: "caller" as const } as { role: string };', []],
  ["type named constant is not const context", 'type constant = { role: string }; export const group = { role: "caller" as const } as constant;', []],
  ["comments do not create assertions", 'export const group = { role: "caller" /* as const */ } as const;', []],
  ["strings do not create assertions", 'export const group = { description: "role: caller as const" } as const;', []],
  ["unrelated object assertion is opaque", 'declare const role: unknown; export const group = { role: role as string } as const;', []],
  ["template interpolation can need assertion", 'declare const role: "caller" | "editor"; export const key = `role:${role}` as const;', []],
  ["const string binding is already literal", 'export const role = "caller" as const;', [ASSERTION], 'export const role = "caller";'],
  ["const number binding is already literal", "export const count = 1 as const;", [ASSERTION], "export const count = 1;"],
  ["const boolean binding is already literal", "export const active = true as const;", [ASSERTION], "export const active = true;"],
  ["const bigint binding is already literal", "export const count = 1n as const;", [ASSERTION], "export const count = 1n;"],
  ["const negative binding is already literal", "export const offset = -1 as const;", [ASSERTION], "export const offset = -1;"],
  ["const static template binding is already literal", "export const role = `caller` as const;", [ASSERTION], "export const role = `caller`;"],
  ["readonly string field is already literal", 'export class Group { readonly role = "caller" as const; }', [ASSERTION], 'export class Group { readonly role = "caller"; }'],
  ["readonly number field is already literal", "export class Group { readonly count = 1 as const; }", [ASSERTION], "export class Group { readonly count = 1; }"],
  ["static readonly field is already literal", 'export class Group { static readonly role = "caller" as const; }', [ASSERTION], 'export class Group { static readonly role = "caller"; }'],
  ["readonly object field needs const assertion", 'export class Group { readonly group = { role: "caller" } as const; }', []],
  ["mutable field needs literal assertion", 'export class Group { role = "caller" as const; }', []],
  ["string assertion does not change type", "export function copy(value: string) { return value as string; }", [ASSERTION], "export function copy(value: string) { return value; }"],
  ["numeric assertion does not change type", "export function copy(value: number) { return value as number; }", [ASSERTION], "export function copy(value: number) { return value; }"],
  ["array assertion does not change type", "export function copy(value: string[]) { return value as string[]; }", [ASSERTION], "export function copy(value: string[]) { return value; }"],
  ["non-null assertion does not change type", "export function copy(value: string) { return value!; }", [ASSERTION], "export function copy(value: string) { return value; }"],
  ["unknown narrowing remains useful", "export function copy(value: unknown) { return value as string; }", []],
  ["nullable narrowing remains useful", "export function copy(value: string | undefined) { return value!; }", []],
  ["break label on current while is redundant", "export function run(ready: boolean) { outer: while (ready) { break outer; } }", [EXTRA_LABEL], "export function run(ready: boolean) { while (ready) { break; } }"],
  ["continue label on current while is redundant", "export function run(ready: boolean) { outer: while (ready) { continue outer; } }", [EXTRA_LABEL]],
  ["break label on current for is redundant", "export function run() { outer: for (;;) { break outer; } }", [EXTRA_LABEL]],
  ["continue label on current for is redundant", "export function run() { outer: for (;;) { continue outer; } }", [EXTRA_LABEL]],
  ["break label on current do loop is redundant", "export function run(ready: boolean) { outer: do { break outer; } while (ready); }", [EXTRA_LABEL]],
  ["break label on current switch is redundant", "export function run(value: number) { outer: switch (value) { case 0: break outer; } }", [EXTRA_LABEL]],
  ["break across nested loops needs label", "export function run(ready: boolean) { outer: while (ready) { while (ready) { break outer; } } }", []],
  ["continue across nested loops needs label", "export function run(ready: boolean) { outer: while (ready) { while (ready) { continue outer; } } }", []],
  ["break from a block needs label", "export function run() { outer: { break outer; } }", []],
  ["unlabeled loop has no extra label", "export function run(ready: boolean) { while (ready) { break; } }", []],
  ["overwritten compound assignment is useless", "export function count() { let value = 0; value += 1; value = 2; return value; }", [ASSIGNMENT]],
  ["overwritten initializer can have side effects", "declare function compute(): number; export function count() { let value = compute(); value = 1; return value; }", [ASSIGNMENT]],
  ["closure reads before overwrite preserve initializer", "export function count() { let value = 0; const get = () => value; const first = get(); value = 1; return [first, get()]; }", []],
  ["destructured initializer is overwritten", "export function count(input: { value: number }) { let { value } = input; value = 1; return value; }", [ASSIGNMENT]],
  ["property writes can invoke setters", "export function reset(box: { value: number }) { box.value = 0; box.value = 1; }", []],
  ["incremented constructor parameter needs assignment", "export class Counter { constructor(public count: number) { count++; this.count = count; } }", []],
  ["constructor property restoration is necessary", "export class Counter { constructor(public count: number) { this.count = 0; this.count = count; } }", []],
  ["returned increment stores an unused value", "export function count() { let value = 0; return ++value; }", [ASSIGNMENT]],
  ["overwritten initializer is useless", "export function count() { let value = 0; value = 1; return value; }", [ASSIGNMENT]],
  ["overwritten intermediate assignment is useless", "export function count() { let value: number; value = 0; value = 1; return value; }", [ASSIGNMENT]],
  ["read initializer is useful", "export function count() { let value = 0; consume(value); value = 1; return value; } declare function consume(value: number): void;", []],
  ["conditional fallback initializer is useful", "export function count(enabled: boolean) { let value = 0; if (enabled) value = 1; return value; }", []],
  ["redundant literal union is inherited", 'export type Role = string | "caller";', [REDUNDANT_UNION]],
  ["duplicate union member is inherited", "export type Role = string | string;", [DUPLICATE_TYPE]],
  ["defaulted type argument is inherited", "interface Box<T = string> { value: T } export type Value = Box<string>;", [TYPE_ARGUMENT]],
  ["unknown generic constraint is inherited", "export function identity<T extends unknown>(value: T): T { return value; }", [TYPE_CONSTRAINT]],
  ["single-use generic is inherited", "export function length<T extends string>(value: T): number { return value.length; }", [TYPE_PARAMETER]],
  ["redundant string conversion is inherited", "export function copy(value: string) { return String(value); }", [CONVERSION]],
  ["redundant template wrapper is inherited", "export function copy(value: string) { return `${value}`; }", [TEMPLATE]],
  ["redundant boolean comparison is inherited", "export function ready(value: boolean) { return value === true; }", [BOOLEAN_COMPARISON]],
  ["distinct literal union remains useful", 'export type Role = "caller" | "editor";', []],
  ["generic relationship remains useful", "export function identity<T>(value: T): T { return value; }", []],
];

function focusedConfig(typed: boolean): Linter.Config[] {
  return STRICT_CONFIG_FACTORY({ tsconfigRootDir: FIXTURE_ROOT, projectService: typed }).map((entry) => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => SELECTED_RULES.has(id))),
  }));
}

function linter(typed: boolean, fix = false): ESLint {
  return new ESLint({ cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: focusedConfig(typed), fix });
}

describe("upstream redundancy policy", () => {
  const eslint = linter(true);
  const fixer = linter(true, true);

  it.each(REVIEW_CASES)("%s", async (_name, code, expected, fixed) => {
    const [result] = await eslint.lintText(code, { filePath: "typed-concision-probe.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(expected);
    if (fixed !== undefined) {
      const [first] = await fixer.lintText(code, { filePath: "typed-concision-probe.ts" });
      expect(first?.output).toBe(fixed);
      expect(first?.messages).toEqual([]);
      const [second] = await fixer.lintText(fixed, { filePath: "typed-concision-probe.ts" });
      expect(second?.output).toBeUndefined();
      expect(second?.messages).toEqual([]);
    }
  });

  it.each(CONFIG_FACTORIES)("%s keeps typed options and warning-first adoption", async (_name, factory) => {
    const eslint = new ESLint({ cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: factory({ tsconfigRootDir: FIXTURE_ROOT }) });
    const config = await eslint.calculateConfigForFile("typed-concision-probe.ts") as Linter.Config;
    expect(config?.rules?.[ASSERTION]).toEqual([2, { checkLiteralConstAssertions: true }]);
    expect(config?.rules?.[EXTRA_LABEL]).toEqual([1]);
    expect(config?.rules?.[ASSIGNMENT]).toEqual([1]);
    expect(config?.rules?.["@typescript-eslint/no-inferrable-types"]).toEqual([0]);
  });

  it("keeps syntax guards available without a type project", async () => {
    const eslint = linter(false);
    const [result] = await eslint.lintText('export const group = { role: "caller" as const } as const; export const role = "caller" as const;', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([NESTED_CONST]);
  });

  it("supports an exact local suppression", async () => {
    const [result] = await eslint.lintText('// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- preserve an intentionally explicit literal\nexport const role = "caller" as const;', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ ruleId }) => ruleId)).toEqual([ASSERTION]);
  });
});
