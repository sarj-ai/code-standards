import { RuleTester } from "oxlint/plugins-dev";

import rule, {
  NO_KNOWN_VALUE_WIDENING_DOCUMENTATION as DOC,
} from "../../src/rules/no-known-value-widening.js";
import { describe, it } from "vitest";
RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});

const error = { messageId: "widening" };

const prelude = "type Command = () => void; const startCommand = () => {};";

tester.run("@sarj/no-known-value-widening", rule, {
  valid: [
    "let failure: unknown; try { failure = new Error('response'); } catch (error) { failure = error; }",
    "let failure: unknown = new Error('response'); try { run(); } catch (error) { failure = error; }",
    "declare const external: unknown; let failure: unknown; failure = new Error('response'); failure = external;",
    "declare function read(): unknown; let failure: unknown; failure = new Error('response'); failure = read();",
    "let failure: unknown; try { run(); } catch (error) { failure = error; } function nested() { let failure: unknown; failure = read(); }",
    "function isObject(value: unknown): value is object { return typeof value === 'object'; } declare const values: readonly unknown[]; const [only] = values; isObject(only);",
    "function isString(value: unknown): value is string { return typeof value === 'string'; } const source: { value: unknown } = read(); const { value } = source; isString(value);",
    "declare const values: readonly unknown[]; const [only] = values; const input: unknown = only;",
    "function readJsonc(input: string): unknown { try { return JSON.parse(input); } catch { return null; } }",
    "declare function read(): unknown; function load(): unknown { if (ready) return { id: 'known' }; return read(); }",
    "function load(value: unknown): unknown { if (value) return { id: 'known' }; return value; }",
    "function load(): unknown { if (ready) return { id: 'known' }; return; }",
    "declare function read(): unknown; function load(): unknown { function nested() { return { id: 'known' }; } return read(); }",
    `${prelude} const commands: Record<string, Command> = {};`,
    `${prelude} type Index<T> = Record<string, T>; const commands: Index<Command> = {};`,
    `${prelude} class Registry { commands: Record<string, Command> = {}; }`,
    `${prelude} class Registry { accessor commands: Record<string, Command> = {}; }`,
    `${prelude} let commands: Record<string, Command>; commands = {};`,
    `${prelude} function create(): Record<string, Command> { return {}; }`,
    `${prelude} const create = (): Record<string, Command> => ({});`,
    `${prelude} const commands = {} as Record<string, Command>;`,
    `${prelude} const commands = <Record<string, Command>>{};`,
    `${prelude} const commands = { start: startCommand };`,
    `${prelude} const commands = { start: startCommand } as const;`,
    `${prelude} const commands = { start: startCommand } satisfies Record<string, Command>;`,
    `${prelude} type Commands = Record<string, Command>; const commands = { start: startCommand } as const satisfies Commands;`,
    `${prelude} interface Commands { readonly start: Command } const commands: Commands = { start: startCommand };`,
    `${prelude} type Commands = { readonly start: Command }; const commands: Commands = { start: startCommand };`,
    `${prelude} type PermissionLevels = { readonly [Level in Permission]: number }; const levels: PermissionLevels = { admin: 1 };`,
    `${prelude} function create() { return { start: startCommand }; }`,
    `${prelude} interface Commands { readonly start: Command } function create(): Commands { return { start: startCommand }; }`,
    `${prelude} function create(): { start: Command } { return { start: startCommand }; }`,
    `${prelude} declare function make(): Record<string, Command>; const commands: Record<string, Command> = make();`,
    `${prelude} import { Commands } from './types'; const commands: Commands = { start: startCommand };`,
    `${prelude} type Diet = 'vegan' | 'omnivore'; const labels: Record<Diet, string> = { vegan: 'V', omnivore: 'O' };`,
    `${prelude} type Diet = 'vegan' | 'omnivore'; type Labels = Record<Diet, string>; const labels: Labels = { vegan: 'V', omnivore: 'O' };`,
    `${prelude} type Diet = 'vegan' | 'omnivore'; const labels: Readonly<Record<Diet, string>> = { vegan: 'V', omnivore: 'O' };`,
    `${prelude} const labels: Record<'a' | 'b', number> = { a: 1, b: 2 };`,
    `${prelude} type Index<Key extends PropertyKey, Value> = Record<Key, Value>; const commands: Index<'start', Command> = { start: startCommand };`,
    "function isString(value: unknown): value is string { return true; } declare const input: unknown; isString(input);",
    "function isString(value: string | unknown): value is string { return true; } declare const input: string | unknown; isString(input);",
    "function isString(value: unknown): value is string { return true; } declare function readInput(): unknown; isString(readInput());",
  ],
  invalid: [
    {
      code: "const external: unknown = 1; let failure: unknown; failure = new Error('response'); failure = external;",
      errors: [error],
    },
    {
      code: "const external: unknown = 1; const value: unknown = external;",
      errors: [error, error],
    },
    {
      code: "let failure: unknown; failure = new Error('known');",
      errors: [error],
    },
    {
      code: "let failure: unknown; try { failure = new Error('known'); } catch { failure = new Error('fallback'); }",
      errors: [error, error],
    },
    {
      code: "let failure: unknown; failure = new Error('known'); function nested() { let failure: unknown; failure = read(); }",
      errors: [error],
    },
    {
      code: "function load(): unknown { if (ready) return { id: 'a' }; return { id: 'b' }; }",
      errors: [error, error],
    },
    {
      code: "function load(): unknown { function nested() { return JSON.parse(input); } return { id: 'known' }; }",
      errors: [error],
    },
    { code: "const load = (): unknown => ({ id: 'known' });", errors: [error] },
    { code: "const value: unknown = {};", errors: [error] },
    { code: "const value: object = {};", errors: [error] },
    { code: "let value: unknown; value = {};", errors: [error] },
    { code: "function create(): unknown { return {}; }", errors: [error] },
    {
      code: `${prelude} const commands: Record<string, Command> = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands: { [key: string]: Command } = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands: { [K in string]: Command } = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands: { start: Command } = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands = { start: startCommand } as Record<string, Command>;`,
      errors: [error],
    },
    {
      code: `${prelude} const commands = ({ start: startCommand } as Record<string, Command>) as object;`,
      errors: 1,
    },
    {
      code: `${prelude} class Registry { commands: Record<string, Command> = { start: startCommand }; }`,
      errors: [error],
    },
    {
      code: `${prelude} let commands: Record<string, Command>; commands = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} function create(): Record<string, Command> { return { start: startCommand }; }`,
      errors: [error],
    },
    {
      code: `${prelude} const source = { start: startCommand }; const commands: Record<string, Command> = source;`,
      errors: [error],
    },
    {
      code: `${prelude} type Open = Record<string, Command>; const source = { start: startCommand }; const commands: Open = source;`,
      errors: [error],
    },
    {
      code: `${prelude} type Open = { [key: string]: Command }; const source = { start: startCommand }; const commands: Open = source;`,
      errors: [error],
    },
    {
      code: `${prelude} type Open = { [key in string]: Command }; const source = { start: startCommand }; const commands: Open = source;`,
      errors: [error],
    },
    {
      code: `${prelude} type Open = Readonly<Record<string, Command>>; const source = { start: startCommand }; const commands: Open = source;`,
      errors: [error],
    },
    {
      code: `${prelude} function outer() { type Open = Record<string, Command>; const commands: Open = { start: startCommand }; }`,
      errors: [error],
    },
    {
      code: `${prelude} type Index<T> = Record<string, T>; const commands: Index<Command> = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} type Identity<T> = T; const commands: Identity<Record<string, Command>> = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} type Index<T> = Record<string, T>; type CommandsByName = Index<Command>; const commands: CommandsByName = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} type Index<T = Command> = Record<string, T>; const commands: Index = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} type Key = string; const commands: Record<Key, Command> = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands: Record<PropertyKey, Command> = { start: startCommand };`,
      errors: [error],
    },
    {
      code: `${prelude} const commands: Record<string | 'start', Command> = { start: startCommand };`,
      errors: [error],
    },
    { code: "const value: unknown = 1;", errors: [error] },
    { code: "const value: object = [];", errors: [error] },
    {
      code: "function isString(value: unknown): value is string { return true; } isString('known');",
      errors: [error],
    },
    {
      code: "function isString(value: unknown): value is string { return true; } const known = 'known'; isString(known);",
      errors: [error],
    },
    {
      code: "function isString(value: string | unknown): value is string { return true; } isString('known');",
      errors: [error],
    },
    {
      code: "function isString(value: unknown): value is string { return true; } function check(known: string): boolean { return isString(known); }",
      errors: [error],
    },
    {
      code: "const isString = (value: unknown): value is string => true; const known: string = getValue(); isString(known);",
      errors: [error],
    },
    {
      code: "type User = { readonly id: string }; function isUser(value: unknown): value is User { return true; } function parse(): User { return { id: 'known' }; } const user = parse(); isUser(user);",
      errors: [error],
    },
  ],
});

const authored = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
authored.run("@sarj/no-known-value-widening-authored", rule, {
  valid: [
    { code: DOC.examples[1].files[0].source, filename: "src/example.ts" },
    {
      code: "// @generated\n" + DOC.examples[0].files[0].source,
      filename: "src/generated.ts",
    },
  ],
  invalid: [
    {
      code: DOC.examples[0].files[0].source,
      filename: "src/example.ts",
      errors: [{ messageId: "widening" }],
    },
  ],
});

// Preserve informative local return contracts and detect erased same-file bindings.
tester.run("@sarj/no-known-value-widening-local-contracts", rule, {
  valid: [
    "export function parseLocalHM(s:string): {hour:number;minute:number} { const [h,m]=s.split(':').map(Number);return {hour:h??0,minute:m??0};}",
    "const parse = (value:number): {value:number} => ({value});",
    "type Tool={name:string;enabled:boolean};declare const tool:Tool;const fields=tool;",
    "export function read(input:unknown){const value:unknown=input;return value;}",
    "type Tool=unknown;declare const tool:Tool;function run(){const fields:Record<string,unknown>=tool;return fields;}",
    "import type { Tool } from './external';declare const tool:Tool;function run(){const fields:Record<string,unknown>=tool;return fields;}",
    "type Tool={name:string};function run<Tool>(tool:Tool){const fields:Record<string,unknown>=tool;return fields;}",
  ],
  invalid: [
    {
      code: "type Tool={name:string;enabled:boolean};declare const tool:Tool;function run(){const fields:Record<string,unknown>=tool;return fields;} export {run};",
      errors: [error],
    },
    {
      code: "type Tool={name:string};type Alias=Tool;declare const tool:Alias;const fields:unknown=tool;",
      errors: [error],
    },
    {
      code: "type Tool=unknown;function run(){type Tool={name:string};declare const tool:Tool;const fields:object=tool;return fields;}",
      errors: [error],
    },
    {
      code: "function read(tool:{name:string}){const fields:unknown=tool;return fields;}",
      errors: [error],
    },
  ],
});
