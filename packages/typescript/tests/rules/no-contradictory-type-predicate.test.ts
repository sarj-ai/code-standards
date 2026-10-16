import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION } from "../../src/rules/no-contradictory-type-predicate.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });

TESTER.run("no-contradictory-type-predicate", rule, {
  valid: [
    { name: "public consistent predicate", code: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.examples[0].files[0].source },
    ...[
      ["broad number", 'function check(v: unknown): v is number { return typeof v === "number"; }'],
      ["broad boolean", 'function check(v: unknown): v is boolean { return typeof v === "boolean"; }'],
      ["broad bigint", 'function check(v: unknown): v is bigint { return typeof v === "bigint"; }'],
      ["broad symbol", 'function check(v: unknown): v is symbol { return typeof v === "symbol"; }'],
      ["broad undefined", 'function check(v: unknown): v is undefined { return typeof v === "undefined"; }'],
      ["finite input includes tested kind", 'function check(v: string | number): v is number { return typeof v === "number"; }'],
      ["nullable input permits a string check", 'function check(v: string | null): v is string { return typeof v === "string"; }'],
      ["positive string literal refinement needs richer proof", 'function check(v: unknown): v is "ready" { return typeof v === "string"; }'],
      ["literal number refinement is not broadly primitive", 'function check(v: unknown): v is 42 { return typeof v === "number"; }'],
      ["literal boolean target is intentionally excluded", 'function check(v: unknown): v is true { return typeof v === "boolean"; }'],
      ["unique symbol is not the broad symbol type", 'declare const marker: unique symbol; function check(v: unknown): v is typeof marker { return typeof v === "symbol"; }'],
      ["mixed literal target still needs richer proof", 'function check(v: unknown): v is string | true { return typeof v === "string"; }'],
      ["brands can intentionally share a primitive runtime carrier", 'type Id = string & { readonly role: unique symbol }; function check(v: unknown): v is Id { return typeof v === "string"; }'],
      ["structural target is intentionally excluded", 'function check(v: unknown): v is { id: string } { return typeof v === "object"; }'],
      ["null target is not classified by typeof alone", 'function check(v: unknown): v is null { return typeof v === "object"; }'],
      ["generic validator has an opaque target", 'function check<T>(v: unknown): v is T { return typeof v === "number"; }'],
      ["generic input remains opaque", 'function check<T extends string | number>(v: T): v is T & string { return typeof v === "number"; }'],
      ["structural input has unknown runtime possibilities", 'function check(v: { length: number } | string): v is string { return typeof v === "number"; }'],
      ["any input remains under existing unsafe controls", 'function check(v: any): v is string { return typeof v === "number"; }'],
      ["compiler owns impossible predicate target", 'function check(v: number): v is string { return typeof v === "number"; }'],
      ["unnecessary-condition owns impossible comparison", 'function check(v: string): v is string { return typeof v === "number"; }'],
      ["two-sided boolean condition needs its own analysis", 'function check(v: unknown): v is string | number { return typeof v === "string" || typeof v === "number"; }'],
      ["range constraints are outside primitive equality", 'function check(v: unknown): v is number { return typeof v === "number" && v > 0; }'],
      ["multi-statement validator can have other invariants", 'function check(v: unknown): v is string { inspect(v); return typeof v === "number"; }'],
      ["mutation before test is not inspected", 'function check(v: unknown): v is string { v = parse(v); return typeof v === "number"; }'],
      ["helper validators are opaque", 'function check(v: unknown): v is string { return helper(v); }'],
      ["boolean return carries no type predicate promise", 'function check(v: unknown): boolean { return typeof v === "number"; }'],
      ["inferred predicate is compiler-owned", 'const check = (v: unknown) => typeof v === "number";'],
      ["assertion functions have different semantics", 'function check(v: unknown): asserts v is string { if (typeof v !== "string") throw new Error(); }'],
      ["declaration-only predicate has no implementation", 'declare function check(v: unknown): v is string;'],
      ["this predicate has no named parameter", 'class Value { check(): this is this & { ready: true } { return typeof this === "number"; } }'],
      ["different parameter does not establish target relationship", 'function check(v: unknown, other: unknown): v is string { return typeof other === "number"; }'],
      ["destructured parameter is outside direct binding proof", 'function check({ value }: { value: unknown }): value is string { return typeof value === "number"; }'],
      ["property test is not a direct parameter test", 'function check(v: unknown): v is string { return typeof v.value === "number"; }'],
      ["negative comparison has an open complement", 'function check(v: unknown): v is string { return typeof v !== "number"; }'],
      ["dynamic typeof expectation is opaque", 'function check(v: unknown): v is string { return typeof v === expected; }'],
      ["invalid typeof spelling belongs to valid-typeof", 'function check(v: unknown): v is string { return typeof v === "null"; }'],
      ["alias target retains consistent kind", 'type DomainText = string; function check(v: unknown): v is DomainText { return typeof v === "string"; }'],
    ].map(([name, code]) => ({ name, code })),
    { name: "exact-code suppression", code: '// eslint-disable-next-line @rule-tester/no-contradictory-type-predicate -- external declaration compatibility\nfunction check(v: unknown): v is string { return typeof v === "number"; }' },
    { name: "generated ownership", filename: 'guard.generated.ts', code: 'function check(v: unknown): v is string { return typeof v === "number"; }' },
  ],
  invalid: [
    { name: "public contradictory predicate", code: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "contradictoryPredicate" }] },
    ...[
      ["number promised but string checked", 'function check(v: unknown): v is number { return typeof v === "string"; }'],
      ["boolean promised but number checked", 'function check(v: unknown): v is boolean { return typeof v === "number"; }'],
      ["bigint promised but boolean checked", 'function check(v: unknown): v is bigint { return typeof v === "boolean"; }'],
      ["symbol promised but undefined checked", 'function check(v: unknown): v is symbol { return typeof v === "undefined"; }'],
      ["undefined promised but string checked", 'function check(v: unknown): v is undefined { return typeof v === "string"; }'],
      ["object accepted by a primitive promise", 'function check(v: unknown): v is string { return typeof v === "object"; }'],
      ["function accepted by a primitive promise", 'function check(v: unknown): v is string { return typeof v === "function"; }'],
      ["finite primitive input mismatch", 'function check(v: string | number): v is string { return typeof v === "number"; }'],
      ["nullable input mismatch", 'function check(v: string | null): v is string { return typeof v === "object"; }'],
      ["false branch must not exclude rejected numeric alternatives", 'function check(v: string | number | boolean): v is string | number { return typeof v === "string"; }'],
      ["unknown input still promises all target alternatives", 'function check(v: unknown): v is string | number { return typeof v === "string"; }'],
      ["complete boolean constituent is recognized in wider union", 'function check(v: unknown): v is string | boolean { return typeof v === "string"; }'],
      ["loose equality preserves typeof semantics", 'function check(v: unknown): v is string { return typeof v == "number"; }'],
      ["reversed equality operands", 'function check(v: unknown): v is string { return "number" === typeof v; }'],
      ["no-substitution template typeof kind", 'function check(v: unknown): v is string { return typeof v === `number`; }'],
      ["expression-bodied arrow", 'const check = (v: unknown): v is string => typeof v === "number";'],
      ["function expression", 'const check = function(v: unknown): v is string { return typeof v === "number"; };'],
      ["class method", 'class Guard { check(v: unknown): v is string { return typeof v === "number"; } }'],
      ["object method", 'const guard = { check(v: unknown): v is string { return typeof v === "number"; } };'],
      ["alias target is resolved semantically", 'type DomainText = string; function check(v: unknown): v is DomainText { return typeof v === "number"; }'],
      ["same-spelled outer variable cannot steal parameter identity", 'const v = "outer"; function check(v: unknown): v is string { return typeof v === "number"; }'],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "contradictoryPredicate" as const }] })),
    { name: "type predicates in tests retain their promise", filename: 'guard.test.ts', code: 'function check(v: unknown): v is string { return typeof v === "number"; }', errors: [{ messageId: "contradictoryPredicate" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-contradictory-type-predicate without type information", rule, {
  valid: ['function check(v: unknown): v is string { return typeof v === "number"; }'], invalid: [],
});
