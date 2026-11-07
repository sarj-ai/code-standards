// vitest: shared-module-graph
import rule from "../../src/rules/prefer-dependency-interface.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const PREFIX = "interface Store { read(): string } class SqlStore implements Store { private value = 'ok'; read() { return this.value; } pool() { return this.value; } } ";

RULE_TESTER.run("prefer-dependency-interface", rule, {
  valid: [
    "interface Store { read(): string } class Service { constructor(private readonly store: Store) {} run() { return this.store.read(); } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.pool(); } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { return this.store; } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) {} run() { this.store.read = replacement; } }",
    PREFIX + "@Injectable() class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service<T> { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service { constructor(private store: SqlStore) {} run() { return this.store.read(); } }",
    PREFIX + "class Service { constructor(private readonly store: SqlStore) { store.pool(); } run() { return this.store.read(); } }",
    "import { SqlStore } from './store'; class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }",
  ],
  invalid: ["interface Store { read(): string } class SqlStore implements Store { private value = 'ok'; read() { return this.value; } } class Service { constructor(private readonly store: SqlStore) {} run() { return this.store.read(); } }"].map(code => ({ code, errors: [{ messageId: "interface" as const }] })),
});
