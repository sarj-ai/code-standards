// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION } from "../../src/rules/prefer-dependency-interface.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });
const PREFIX = "interface Store { read(): string } class SqlStore implements Store { private value = 'ok'; read() { return this.value; } pool() { return this.value; } } ";
TESTER.run("prefer-dependency-interface", rule, {
  valid: [
    PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION.examples[1].files[0].source,
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.pool(); } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { return this.store; } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { this.store.read = replacement; } }",
    PREFIX + "@Injectable() class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service<T> { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service { constructor(private store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) { store.pool(); } run() { return this.store.read(); } }",
    "import { SqlStore } from './store'; class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
  ],
  invalid: [PREFER_DEPENDENCY_INTERFACE_DOCUMENTATION.examples[0].files[0].source].map(code => ({ code, errors: [{ messageId: "interface" as const }] })),
});
