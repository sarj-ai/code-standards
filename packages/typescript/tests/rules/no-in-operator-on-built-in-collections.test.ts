import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION,
} from "../../src/rules/no-in-operator-on-built-in-collections.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

RULE_TESTER.run("no-in-operator-on-built-in-collections", rule, {
  valid: [
    {
      name: "accepts the documented object narrowing example",
      code: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION.examples[1].files[0].source,
    },
    "declare const object: Record<string, unknown>; declare const key: string; if (key in object) use(key);",
    "declare const values: string[]; declare const index: number; if (index in values) use(index);",
    "declare const value: unknown; class Box { #brand = true; accepts(input: object) { return #brand in input; } }",
    "declare const value: Map<string, object> | Record<string, object>; declare const key: string; if (key in value) use(key);",
    "declare const value: Map<string, object> & { owner: string }; if ('owner' in value) use(value.owner);",
    "declare function check<T extends Map<string, object>>(value: T, key: string): boolean;",
    "class NamedMap<K, V> extends Map<K, V> { owner = 'app'; } declare const value: NamedMap<string, object>; if ('owner' in value) use(value.owner);",
    "declare namespace Domain { interface Map<K, V> { has(key: K): boolean } } declare const value: Domain.Map<string, object>; if ('owner' in value) use(value);",
    "declare const value: any; declare const key: string; if (key in value) use(key);",
    "declare const value: unknown; if (typeof value === 'object' && value !== null && 'id' in value) use(value.id);",
    {
      name: "excludes generated source",
      filename: "generated/client.ts",
      code: "declare const value: globalThis.Map<string, object>; if ('id' in value) use(value);",
    },
  ],
  invalid: [
    {
      name: "reports the documented Map entry check",
      code: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION.examples[0].files[0].source,
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports ReadonlyMap entry checks",
      code: "declare const collection: ReadonlyMap<string, object>; declare const key: string; if (key in collection) use(key);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports Set entry checks",
      code: "declare const collection: Set<string>; declare const key: string; if (key in collection) use(key);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports ReadonlySet entry checks",
      code: "declare const collection: ReadonlySet<string>; declare const key: string; if (key in collection) use(key);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports WeakMap property checks",
      code: "declare const collection: WeakMap<object, object>; if ('has' in collection) use(collection);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports WeakSet property checks",
      code: "declare const collection: WeakSet<object>; if ('has' in collection) use(collection);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "does not autofix intentional property lookup",
      code: "declare const cache: Map<string, object>; if ('size' in cache) use(cache.size);",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
  ],
});
