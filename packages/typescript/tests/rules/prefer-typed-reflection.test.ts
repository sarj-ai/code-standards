import { RuleTester } from "@typescript-eslint/rule-tester";
import * as parser from "@typescript-eslint/parser";
import { afterAll, describe, it } from "vitest";
import { join } from "node:path";
import rule from "../../src/rules/prefer-typed-reflection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({
  languageOptions: {
    parser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});
TESTER.run("prefer-typed-reflection", rule, {
  valid: [
    { name: "preserves Reflect.get on a primitive", code: 'declare const target: string; Reflect.get(target, "length");' },
    { name: "keeps interpolated property keys dynamic", code: 'declare const target: { id: string }; declare const suffix: string; Reflect.get(target, `id${suffix}`);' },
    { name: "keeps open dictionaries with a wrapped literal outside the rule", code: 'declare const target: Record<string, unknown>; Reflect.get(target, ("id" as const));' },
    { name: "keeps a shadowed Reflect with a template key outside the rule", code: 'function read(Reflect: {get(target: object, key: string): unknown}, target: object) { return Reflect.get(target, `id`); }' },

    'function read(Reflect: { get(target: object, key: string): unknown }, target: object) { return Reflect.get(target, "id"); }',
    'declare const target: Record<string, unknown>; Reflect.get(target, "id");',
    "declare const target: { id: string }; declare const key: string; Reflect.get(target, key);",
    'declare const target: { id: string }; Reflect.get(target, "id", other);',
    'declare const target: any; Reflect.get(target, "id");',
    "declare const args: unknown[]; function run(n: number) {} Reflect.apply(run, undefined, args);",
    '// @generated\ndeclare const target: { id: string }; Reflect.get(target, "id");',
    'function read<T extends object>(target: T) { return Reflect.get(target, "id"); }',
    'Reflect.ownKeys({ id: "a" });',
  ],
  invalid: [
    { name: "preserves delete of a call result", code: 'declare const target: { id: string }; delete Reflect.get(target, "id");', output: null, errors: [{ messageId: "avoid" }] },
    { name: "preserves delete through an erased wrapper", code: 'declare const target: { id: string }; delete (Reflect.get(target, "id") as unknown);', output: null, errors: [{ messageId: "avoid" }] },
    { name: "preserves a detached method invocation", code: 'declare const target: { run(): string }; Reflect.get(target, "run")();', output: null, errors: [{ messageId: "avoid" }] },
    { name: "preserves method tags", code: 'declare const target: { tag(strings: TemplateStringsArray): string }; Reflect.get(target, "tag")`value`;', output: null, errors: [{ messageId: "avoid" }] },
    { name: "retains a no-substitution template key", code: 'declare const target: { id: string }; Reflect.get(target, `id`);', output: "declare const target: { id: string }; (target)[`id`];", errors: [{ messageId: "avoid" }] },
    { name: "retains a const assertion around a literal key", code: 'declare const target: { id: string }; Reflect.get(target, ("id" as const));', output: "declare const target: { id: string }; (target)[\"id\" as const];", errors: [{ messageId: "avoid" }] },
    { name: "retains a satisfies wrapper around a literal key", code: 'declare const target: { id: string }; Reflect.get(target, ("id" satisfies string));', output: "declare const target: { id: string }; (target)[\"id\" satisfies string];", errors: [{ messageId: "avoid" }] },

    {
      code: 'declare const target: { id: string }; Reflect.get(target, "id");', output: "declare const target: { id: string }; (target)[\"id\"];",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'declare const target: { id: string }; Reflect["get"](target, "missing");',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "function send(id: string) {} Reflect.apply(send, undefined, [42]);",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'function send(id: string) {} globalThis.Reflect.apply(send, undefined, ["a"]);',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'declare const target: { id: string }; globalThis.Reflect.get(target, "id");', output: "declare const target: { id: string }; (target)[\"id\"];",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
  ],
});
const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("without type information", rule, {
  valid: ['declare const target: { id: string }; Reflect.get(target, "id");'],
  invalid: [],
});

TESTER.run("prefer-typed-reflection retained extensions", rule, {
  valid: [
    { name: "preserves a mutated Reflect alias", code: "const target = { id: 'a' }; const reflection = Reflect; reflection.get = customGet; reflection.get(target, 'id');" },
    { name: "preserves a globally replaced Reflect method", code: "const target = { id: 'a' }; const reflection = Reflect; Reflect.get = customGet; reflection.get(target, 'id');" },
    { name: "preserves an escaping Reflect alias", code: "const target = { id: 'a' }; const reflection = Reflect; mutate(reflection); reflection.get(target, 'id');" },
    { name: "preserves a shadowed Reflect origin", code: "const Reflect = { get(target: object, key: string) { return key; } }; const reflection = Reflect; reflection.get({}, 'id');" },
    { name: "preserves an explicit receiver through an alias", code: "const target = { id: 'a' }; const reflection = Reflect; reflection.get(target, 'id', receiver);" },
    { name: "preserves a mutated tuple container", code: "function send(id: string) {} const args: [string] = ['a']; args.push('b'); Reflect.apply(send, undefined, args);" },
    { name: "preserves an escaping tuple container", code: "function send(id: string) {} const args: [string] = ['a']; mutate(args); Reflect.apply(send, undefined, args);" },
  ],
  invalid: [
    { name: "recognizes a global Reflect alias", code: "const target = { id: 'a' }; const reflection = Reflect; const id = reflection.get(target, 'id');", output: null, errors: [{ messageId: "avoid" }] },
    { name: "recognizes a Reflect alias chain", code: "const target = { id: 'a' }; const first = Reflect; const reflection = first; const id = reflection.get(target, 'id');", output: null, errors: [{ messageId: "avoid" }] },
    { name: "recognizes an aliased globalThis Reflect", code: "const target = { id: 'a' }; const reflection = globalThis.Reflect; const id = reflection.get(target, 'id');", output: null, errors: [{ messageId: "avoid" }] },
    { name: "keeps detached calls manual through aliases", code: "const target = { read() { return this; } }; const reflection = Reflect; reflection.get(target, 'read')();", output: null, errors: [{ messageId: "avoid" }] },
    { name: "checks a definite argument tuple", code: "function send(id: string) {} const args: [number] = [42]; Reflect.apply(send, undefined, args);", output: null, errors: [{ messageId: "avoid" }] },
    { name: "checks tuple arguments through a Reflect alias", code: "function send(id: string) {} const args: [string] = ['a']; const reflection = Reflect; reflection.apply(send, undefined, args);", output: null, errors: [{ messageId: "avoid" }] },
  ],
});
TESTER.run("prefer-typed-reflection audited boundaries", rule, {
  valid: [
    { name: "preserves cross-spelling Reflect mutations", code: "declare const target: { id: string }; const r = Reflect; globalThis.Reflect.get = custom; r.get(target, 'id');" },
    { name: "preserves inverse cross-spelling Reflect mutations", code: "declare const target: { id: string }; const r = globalThis.Reflect; Reflect.get = custom; r.get(target, 'id');" },
    { name: "preserves destructuring Reflect mutations", code: "declare const target: { id: string }; const r = Reflect; ({ get: globalThis.Reflect.get } = replacement); r.get(target, 'id');" },
    { name: "preserves opaque variadic tuple calls", code: "declare const invoke: (...args: unknown[]) => unknown; const args: [string] = ['u1']; Reflect.apply(invoke, undefined, args);" },
    { name: "preserves opaque dictionary tuple calls", code: "declare const invoke: (value: Record<string, unknown>) => unknown; const args: [{ id: string }] = [{ id: 'u1' }]; Reflect.apply(invoke, undefined, args);" },
  ],
  invalid: [
    { name: "retains typed variadic tuple contracts", code: "declare const invoke: (...args: string[]) => string; const args: [string] = ['u1']; Reflect.apply(invoke, undefined, args);", output: null, errors: [{ messageId: "avoid" }] },
  ],
});
TESTER.run("prefer-typed-reflection tuple wrappers and type references", rule, {
  valid: [],
  invalid: [
    { name: "supports readonly const tuples", code: "declare function lookup(id: string): string; const args = ['u1'] as const; Reflect.apply(lookup, undefined, args);", output: null, errors: [{ messageId: "avoid" }] },
    { name: "supports satisfies tuples", code: "declare function lookup(id: string): string; const args = ['u1'] satisfies [string]; Reflect.apply(lookup, undefined, args);", output: null, errors: [{ messageId: "avoid" }] },
    { name: "ignores type-only global references", code: "declare const target: { id: string }; const r: typeof Reflect = Reflect; r.get(target, 'id');", output: null, errors: [{ messageId: "avoid" }] },
  ],
});
