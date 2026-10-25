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
      projectService: {
        allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"],
      },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

RULE_TESTER.run("no-in-operator-on-built-in-collections", rule, {
  valid: [
    {
      name: "accepts the documented object narrowing example",
      code: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION.examples[1]
        .files[0].source,
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
      name: "retains an inferred type predicate on an unknown Map property",
      code: "export function hasField(cache: Map<string, object>) { return 'newField' in cache; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 1",
      code: "export function hasSize(cache: Map<string, object>, key: string): boolean { return key in cache; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 2",
      code: "export function hasSize(cache: Map<string, object>): boolean { if ('size' in cache) return cache.size > 0; return false; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 3",
      code: "export function hasSize(Reflect: Map<string, object>): boolean { return 'size' in Reflect; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 4",
      code: "import './patch-reflect.js'; export function hasSize(cache: Map<string, object>): boolean { return 'size' in cache; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 5",
      code: "export function hasSize(cache: Map<string, object>): boolean { /* property policy */ return 'size' in cache; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "retains unsupported boundary 6",
      code: "export function hasSize(cache: Map<string, object>): cache is Map<string, object> { return 'size' in cache; }",
      output: null,
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "applies the source-owned exact correction",
      code: "export function hasSize(cache: Map<string, object>): boolean { return 'size' in cache; }",
      output:
        "export function hasSize(cache: Map<string, object>): boolean { return Reflect.has(cache, 'size'); }",
      errors: [{ messageId: "ambiguousCollectionIn" }],
    },
    {
      name: "reports the documented Map entry check",
      code: NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION.examples[0]
        .files[0].source,
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
