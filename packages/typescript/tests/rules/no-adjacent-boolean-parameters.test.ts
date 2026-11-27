import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/no-adjacent-boolean-parameters.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

const ERROR = { messageId: "noAdjacentBooleanParameters" } as const;
const TWO_FLAGS = "function f(a: boolean, b: boolean) {}";

ruleTester().run("no-adjacent-boolean-parameters", rule, {
  valid: [
    "function f(flag: boolean, id: string) {}",
    "function f({ a, b }: { a: boolean; b: boolean }) {}",
    "function f([a, b] = [true, false], flag: boolean) {}",
    "function f(flag: boolean, ...flags: [boolean, boolean]) {}",
    "function f(this: boolean, flag: boolean) {}",
    "function f(a: true, b: false) {}",
    "type Flag = boolean; function f(a: Flag, b: boolean | undefined) {}",
    "declare function defaultFlag(): boolean; function f(a = defaultFlag(), b: boolean) {}",
    "function f(value: unknown, a: boolean, b: boolean): value is string { return a && b && value === ''; }",
    "function f(value: unknown, a: boolean, b: boolean): asserts value is string {}",
    "items.filter((value, keep: boolean, all: boolean) => keep);",
    "handlers.register(function (active: boolean, pending: boolean) { return active && pending; });",
    "new Source((enabled: boolean, visible: boolean) => enabled && visible);",
    "class Store { set value(flag: boolean) {} }",
    "export function f(a: boolean): void; export function f(a: boolean, b = false) {}",
    "function f(a: boolean): void; function f(a: string, b: boolean): void; function f(a: string | boolean, b = false, c = true) {}",
    "class Store { update(a: boolean): void; update(a: boolean, b = false) {} }",
    "declare const method: unique symbol; class Store { [method](a: boolean): void; [method](a: boolean, b = false) {} }",
    { filename: "src/generated/client.ts", code: TWO_FLAGS },
    `// @generated\n${TWO_FLAGS}`,
  ],
  invalid: [
    {
      name: "reports only the second flag when more than two are present",
      code: "function change(\n  next: boolean,\n  expected: boolean,\n  offerUndo = true,\n  setup?: string,\n  confirmed = false,\n) {}",
      output: null,
      errors: [{ ...ERROR, line: 3, column: 3 }],
    },
    { code: "function label(requesting: boolean, busy: boolean) {}", errors: [ERROR] },
    { code: "function legs(airborne: boolean, running: boolean, phase: number) {}", errors: [ERROR] },
    { code: "function range(min: number, excludeMin: boolean, max: number, excludeMax: boolean) {}\nrange(1, false, 4, true);", errors: [ERROR] },
    { code: "const f = function (a: boolean, b?: boolean) {};", errors: [ERROR] },
    { code: "const f = (a = true, b = false) => a && b;", errors: [ERROR] },
    { code: "((a: boolean, b: boolean) => a && b)(false, true);", errors: [ERROR] },
    { code: "declare function f(a: boolean, b: boolean): void;", errors: [ERROR] },
    { code: "interface Store { update(a: boolean, b: boolean): void }", errors: [ERROR] },
    { code: "type Update = (a: boolean, b: boolean) => void;", errors: [ERROR] },
    { code: "abstract class Store { abstract update(a: boolean, b: boolean): void; }", errors: [ERROR] },
    { code: "class Store { constructor(public active: boolean, private pending = false) {} }", errors: [ERROR] },
    { code: "class Store { static update(a: boolean, b = false) {} }", errors: [ERROR] },
    { code: "function f(a: boolean, b: boolean): void;\nfunction f(a: boolean, b = false) {}", errors: [{ ...ERROR, line: 1 }, { ...ERROR, line: 2 }] },
    { code: "class Store { update(a: boolean): void; update(a: boolean, b: boolean): void; update(a: boolean, b = false) {} }", errors: [ERROR, ERROR] },
    { code: "class Store { update(a: boolean): void; update(a: boolean) {} other(a: boolean, b: boolean) {} }", errors: [ERROR] },
  ],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["no-adjacent-boolean-parameters"])).resolves.toBeGreaterThan(0);
});
