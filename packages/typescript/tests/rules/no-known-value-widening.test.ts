import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-known-value-widening.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser, parserOptions: {
    projectService: { allowDefaultProject: ["*.ts*"] },
    tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
  } },
});

RULE_TESTER.run("no-known-value-widening", rule, {
  valid: [
    "function keep<T>(input: T | undefined) { const output: unknown = input; return output; }",
    "function keep<T>(input: T | null) { const output: unknown = input; return output; }",
    "declare const raw: unknown; const payload: unknown = raw;",
    "declare const raw: any; const payload: unknown = raw;",
    "const fields: Record<string, unknown> = {};",
    "const labels: Record<string, string> = { inbound: 'Inbound' };",
    "declare const tool: { name: string }; const fields = tool;",
    "declare const tool: { name: string }; const fields: { name: string } = tool;",
    "declare const tool: { name: string }; const fields: Record<'name', string> = tool;",
    "declare const tool: { name: string }; export const fields: unknown = tool;",
    "function keep<T>(input: T) { const output: unknown = input; return output; }",
    "declare const tool: { name: string }; const fields = tool satisfies object;",
    { code: "// @generated\ndeclare const tool: { name: string }; const fields: unknown = tool;" },
  ],
  invalid: [
    { name: "preserves the sole named variable annotation binding", code: "export {}; type Opaque = unknown; declare const tool: { name: string }; const fields: Opaque = tool;", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains inference with an independent exported type use", code: "export type Kept = Opaque; type Opaque = unknown; declare const tool: { name: string }; const fields: Opaque = tool;", output: "export type Kept = Opaque; type Opaque = unknown; declare const tool: { name: string }; const fields = tool;", errors: [{ messageId: "widening" }] },
    { name: "does not count a second erasable variable annotation as a witness", code: "export {}; type Opaque = unknown; declare const tool: { name: string }; const first: Opaque = tool; const second: Opaque = tool;", output: null, errors: [{ messageId: "widening" }, { messageId: "widening" }] },
    { name: "retains inference only for an unused private module binding", code: "export {}; declare const tool: { name: string }; const fields: unknown = tool;", output: "export {}; declare const tool: { name: string }; const fields = tool;", errors: [{ messageId: "widening" }] },
    { name: "preserves an exported alias contract", code: "declare const tool: { name: string }; const fields: unknown = tool; export { fields };", output: null, errors: [{ messageId: "widening" }] },
    { name: "preserves explicit annotation comments", code: "export {}; declare const tool: { name: string }; const fields: /* opaque boundary */ unknown = tool;", output: null, errors: [{ messageId: "widening" }] },
    { code: "declare const value: { name: string } | undefined; const output: unknown = value;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; const fields: unknown = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; const fields: object = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; const fields: Record<string, unknown> = tool;", errors: [{ messageId: "widening" }] },
    { code: "type Bag = Readonly<Record<string, unknown>>; declare const tool: { name: string }; const fields: Bag = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; function outer() { const fields: unknown = tool; return fields; }", errors: [{ messageId: "widening" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

SYNTAX_TESTER.run("no-known-value-widening without a type project", rule, {
  valid: ["declare const tool: { name: string }; const fields: unknown = tool;"],
  invalid: [],
});

RULE_TESTER.run("no-known-value-widening retained extensions", rule, {
  valid: [
    { name: "preserves an unknown factory", code: "declare function decode(): unknown; const value: unknown = decode();" },
    { name: "preserves context-dependent generics", code: "declare function create<T>(): T; const value: unknown = create();" },
    { name: "preserves empty local builders", code: "const entries: Record<string, unknown> = {}; const items: unknown = [];" },
    { name: "preserves public literal contracts", code: "export const value: unknown = { id: 'u1' };" },
    { name: "preserves a constructor's unknown replacement", code: "class Store { readonly #value: unknown = { id: 'u1' }; constructor(input: unknown) { this.#value = input; } read() { return this.#value; } }" },
    { name: "preserves heterogeneous private storage", code: "class Store { #value: unknown = { id: 'u1' }; replace(input: unknown) { this.#value = input; } }" },
    { name: "preserves a constructor's different concrete replacement", code: "class Store { readonly #value: unknown = { id: 'u1' }; constructor() { this.#value = 42; } }" },
    { name: "preserves dynamic registration", code: "const handlers: Record<string, () => void> = { start() {} }; handlers.stop = () => {}; handlers.start();" },
    { name: "preserves an escaping registry", code: "const handlers: Record<string, () => void> = { start() {} }; register(handlers); handlers.start();" },
    { name: "preserves a registry whose method mutates its receiver", code: "const handlers: Record<string, () => void> = { start() { this.stop = () => {}; } }; handlers.start();" },
    { name: "preserves computed registry keys", code: "declare const key: string; const handlers: Record<string, () => void> = { [key]() {} }; handlers.start();" },
    { name: "preserves a registry's unknown invocation receiver", code: "declare function external(): void; const handlers: Record<string, () => void> = { start: external }; handlers.start();" },
    { name: "preserves an exported registry alias", code: "const handlers: Record<string, () => void> = { start() {} }; export { handlers }; handlers.start();" },
  ],
  invalid: [
    { name: "retains a nonempty literal contract", code: "const value: unknown = { id: 'u1' }; consume(value);", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains a known factory output", code: "declare function createUser(): { id: string }; const user: unknown = createUser(); consume(user);", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains an awaited factory output", code: "declare function createUser(): Promise<{ id: string }>; async function load() { const user: unknown = await createUser(); return user; }", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains a known array contract", code: "const rows: unknown = ['a', 'b']; consume(rows);", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains an owned readonly field contract", code: "class Store { readonly #user: unknown = { id: 'u1' }; read() { return this.#user; } }", output: null, errors: [{ messageId: "widening" }] },
    { name: "checks compatible constructor writes", code: "class Store { readonly #user: unknown = { id: 'u1' }; constructor() { this.#user = { id: 'u2' }; } read() { return this.#user; } }", output: null, errors: [{ messageId: "widening" }] },
    { name: "preserves closed registry keys", code: "const handlers: Record<string, () => void> = { start() {}, stop() {} }; handlers.start();", output: null, errors: [{ messageId: "registry" }] },
    { name: "preserves closed registry type queries", code: "const handlers: Record<string, () => void> = { start() {}, stop() {} }; type Command = keyof typeof handlers;", output: null, errors: [{ messageId: "registry" }] },
  ],
});
RULE_TESTER.run("no-known-value-widening audited boundaries", rule, {
  valid: [
    { name: "preserves private destructuring replacements", code: "class Store { readonly #value: unknown = { id: 'u1' }; constructor(input: { value: unknown }) { ({ value: this.#value } = input); } read() { return this.#value; } }" },
    { name: "preserves nested private array assignment targets", code: "class Store { readonly #value: unknown = { id: 'u1' }; constructor(input: unknown[]) { [this.#value] = input; } read() { return this.#value; } }" },
    { name: "preserves destructuring registry mutations", code: "const handlers: Record<string, () => void> = { start() {} }; ({ start: handlers.start } = external); handlers.start();" },
  ],
  invalid: [
  ],
});
RULE_TESTER.run("no-known-value-widening wrapped unary private writes", rule, {
  valid: ["class Store { readonly #value: unknown = 1; constructor() { (this.#value as number)++; } read() { return this.#value; } }"],
  invalid: [],
});
RULE_TESTER.run("no-known-value-widening derived SDK contracts", rule, {
  valid: [
    { name: "preserves an unresolved SDK parameter contract", code: "import type { Client } from './missing-client.js'; const payload: Parameters<Client['update']>[0] = { id: 'u1' };" },
    { name: "preserves an aliased SDK parameter contract", code: "import type { Client } from './missing-client.js'; type Request = Parameters<Client['update']>[0]; const payload: Request = { id: 'u1' };" },
    { name: "preserves a named API return contract", code: "declare function boundary(): unknown; const value: ReturnType<typeof boundary> = { id: 'u1' };" },
    { name: "preserves a schema-derived opaque contract", code: "import { z } from 'zod'; declare const Schema: z.ZodType<unknown>; const value: z.infer<typeof Schema> = { id: 'u1' };" },
    { name: "preserves private storage with an SDK contract", code: "import type { Client } from './missing-client.js'; class Store { readonly #payload: Parameters<Client['update']>[0] = { id: 'u1' }; read() { return this.#payload; } }" },
  ],
  invalid: [
    { name: "still recognizes a direct local unknown alias", code: "type Opaque = unknown; const value: Opaque = { id: 'u1' };", output: null, errors: [{ messageId: "widening" }] },
  ],
});
