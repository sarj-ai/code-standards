// vitest: shared-module-graph
import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION,
} from "../../src/rules/prefer-await-in-async-return.js";
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
RULE_TESTER.run("prefer-await-in-async-return", rule, {
  valid: [
    {
      name: "accepts the documented explicit await",
      code: PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION.examples[0].files[0]
        .source,
    },
    {
      name: "allows a dynamic import adapter in a non-async function",
      code: `const load = () => import("./component").then((module) => module.default);`,
    },
    {
      name: "allows Promise callbacks inside a synchronous React-style effect",
      code: `
        declare function useEffect(callback: () => void): void;
        declare function consume(value: number): void;
        useEffect(() => {
          Promise.resolve(1).then((value) => consume(value));
        });
      `,
    },
    {
      name: "allows a standalone fire-and-forget transform in async code",
      code: `async function load() {
        void Promise.resolve(1).then((value) => value + 1);
      }`,
    },
    {
      name: "allows fire-and-forget error handling",
      code: `async function dispatch() {
        Promise.resolve(1).catch((error: unknown) => console.error(error));
      }`,
    },
    {
      name: "allows Promise callbacks in constructors",
      code: `class Loader {
        constructor() { Promise.resolve(1).then((value) => value + 1); }
      }`,
    },
    {
      name: "allows a non-Promise object with a then method",
      code: `
        const value = { then(callback: (input: number) => number) { return callback(1); } };
        async function load() { return value.then((input) => input + 1); }
      `,
    },
    {
      name: "allows an already awaited then transform",
      code: `async function load() {
        return await Promise.resolve(1).then((value) => value + 1);
      }`,
    },
    {
      name: "allows a then chain with catch recovery",
      code: `async function load() {
        return Promise.resolve(1).then((value) => value + 1).catch(() => 0);
      }`,
    },
    {
      name: "allows a two-handler then call whose rejection semantics need care",
      code: `async function load() {
        return Promise.resolve(1).then((value) => value + 1, () => 0);
      }`,
    },
    {
      name: "allows a named transform because rewriting its call contract is less local",
      code: `
        declare function transform(value: number): number;
        async function load() { return Promise.resolve(1).then(transform); }
      `,
    },
    {
      name: "allows an async generator return",
      code: `async function* values() {
        return Promise.resolve(1).then((value) => value + 1);
      }`,
    },
    {
      name: "allows a resolved React lazy named-export adapter",
      code: `
        import { lazy as reactLazy } from "react";
        reactLazy(async () => Promise.resolve({ Page: 1 }).then((module) => ({ default: module.Page })));
      `,
    },
    {
      name: "allows a resolved next dynamic named-export adapter",
      code: `
        import loadDynamic from "next/dynamic";
        loadDynamic(async () => Promise.resolve({ Page: 1 }).then((module) => module.Page));
      `,
    },
  ],
  invalid: [
    {
      name: "reports the documented direct async return",
      code: PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION.examples[1].files[0]
        .source,
      errors: [{ messageId: "preferAwait" }],
    },
    {
      name: "reports an async expression-bodied arrow",
      code: `const load = async () => Promise.resolve(1).then((value) => value + 1);`,
      errors: [{ messageId: "preferAwait" }],
    },
    {
      name: "reports an async method's direct return",
      code: `class Loader {
        async load() { return Promise.resolve(1).then((value) => value + 1); }
      }`,
      errors: [{ messageId: "preferAwait" }],
    },
    {
      name: "reports a direct PromiseLike transform",
      code: `
        declare const value: PromiseLike<number>;
        async function load() { return value.then((input) => input + 1); }
      `,
      errors: [{ messageId: "preferAwait" }],
    },
    {
      name: "reports an unrelated local lazy helper",
      code: `
        declare function lazy(loader: () => Promise<number>): void;
        lazy(async () => Promise.resolve(1).then((value) => value + 1));
      `,
      errors: [{ messageId: "preferAwait" }],
    },
    {
      name: "reports a shadowed next dynamic binding",
      code: `
        import dynamic from "next/dynamic";
        function configure(): void {
          const dynamic = (loader: () => Promise<number>): void => { void loader; };
          dynamic(async () => Promise.resolve(1).then((value) => value + 1));
        }
      `,
      errors: [{ messageId: "preferAwait" }],
    },
  ],
});

RULE_TESTER.run("prefer-await-in-async-return with all Promise calls", rule, {
  valid: [
    {
      name: "does not treat an async generator result as a Promise",
      code: "async function* values() { yield 1; } values().then(handle);",
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not trust a reassigned inferred async function",
      code: "let load = async () => 1; load = () => ({then(callback) {return callback(1)}}); load().then(handle);",
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not trust a reassigned inferred Promise binding",
      code: "let value = Promise.resolve(1); value = {then(callback) {return callback(1)}}; value.then(handle);",
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not invent the return type of an imported function",
      code: "import {load} from './external'; load().then(handle);",
      options: [{ scope: "all-promise-calls" }],
    },

    {
      name: "reads JSON Schema conditional data",
      code: `const schema = { then: { type: "string" } }; const type = schema.then.type;`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "destructures JSON Schema conditional data",
      code: `const schema = { then: { type: "string" } }; const { then: branch } = schema;`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "allows a synchronous API with a then method",
      code: `const flow = { then(value: number) { return value + 1; } }; flow.then(1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not guess from an unknown receiver or computed property",
      code: `declare const value: any; value.then(handle); declare const key: string; Promise.resolve(1)[key](handle);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "leaves Promise catch and finally available",
      code: `Promise.resolve(1).catch(() => 0).finally(() => {});`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "ignores a union with a custom synchronous then method",
      code: `declare const value: Promise<number> | { then(callback: () => void): number }; value.then(() => {});`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not treat a custom async thenable as built-in Promise",
      code: `interface Thenable { then(callback: (value: number) => number): Promise<number>; }
        declare const value: Thenable; value.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not infer a Promise from an unknown receiver",
      code: `declare const value: unknown; value.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not infer a Promise from a never receiver",
      code: `declare const value: never; value.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not borrow built-in identity for a custom then intersection",
      code: `declare const value: Promise<number> & { then(value: number): number }; value.then(1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not follow an extracted Promise method",
      code: `const continuePromise = Promise.resolve(1).then; continuePromise((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
    },
    {
      name: "does not follow a destructured Promise method",
      code: `const { then: continuePromise } = Promise.resolve(1); continuePromise((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
    },
  ],
  invalid: [
    {
      name: "keeps explicitly annotated mutable Promise owners",
      code: "let value: Promise<number> = Promise.resolve(1); value = Promise.resolve(2); value.then(handle);",
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      name: "proves a Promise parameter without a fabricated checker",
      code: "function load(value: Promise<number>) {value.then(handle)}",
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      name: "keeps static template-computed chains proven",
      code: "Promise.resolve(1)[`then`](handle)[`then`](handle)",
      options: [{ scope: "all-promise-calls" }],
      errors: [
        { messageId: "preferAwaitCall" },
        { messageId: "preferAwaitCall" },
      ],
    },

    {
      code: `Promise.resolve(1).then((value) => value + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `Promise.resolve(1)?.then((value) => value + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `Promise.resolve(1).then?.((value) => value + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `Promise.resolve(1)["then"]((value) => value + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `Promise.resolve(1)[\`then\`]((value) => value + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `declare const value: Promise<number> | undefined; value?.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `declare const value: PromiseLike<number>; value.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `declare function handle(value: number): number; Promise.resolve(1).then(handle);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `Promise.resolve(1).then((value) => value + 1, () => 0);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `async function load() { return Promise.resolve(1).then((value) => value + 1); }`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      code: `async function load() { return await Promise.resolve(1).then((value) => value + 1); }`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      name: "proves every member of an ordinary Promise union",
      code: `declare const value: Promise<number> | Promise<string>; value.then((input) => input);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      name: "keeps inherited built-in Promise method identity",
      code: `class Task extends Promise<number> {} declare const task: Task; task.then((input) => input + 1);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [{ messageId: "preferAwaitCall" }],
    },
    {
      name: "reports each Promise call exactly once in a chain",
      code: `Promise.resolve(1).then((value) => value + 1).then((value) => value * 2);`,
      options: [{ scope: "all-promise-calls" }],
      errors: [
        { messageId: "preferAwaitCall" },
        { messageId: "preferAwaitCall" },
      ],
    },
  ],
});
