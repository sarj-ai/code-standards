import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  preferAwaitInAsyncReturnDocumentation,
} from "../../src/rules/prefer-await-in-async-return.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const typedRuleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: {
        allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"],
      },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

typedRuleTester.run("prefer-await-in-async-return", rule, {
  valid: [
    {
      name: "accepts the documented explicit await",
      code: preferAwaitInAsyncReturnDocumentation.examples[0].files[0].source,
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
      code: preferAwaitInAsyncReturnDocumentation.examples[1].files[0].source,
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

const untypedRuleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

untypedRuleTester.run("prefer-await-in-async-return without type services", rule, {
  valid: [{
    name: "stays silent when the parser has no type information",
    code: `async function load() {
      return Promise.resolve(1).then((value) => value + 1);
    }`,
  }],
  invalid: [],
});
