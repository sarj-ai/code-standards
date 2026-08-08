import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferModuleLevelConstantDocumentation } from "../../src/rules/prefer-module-level-constant.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

ruleTester.run("prefer-module-level-constant", rule, {
  valid: [
    { name: "public no-match example", filename: preferModuleLevelConstantDocumentation.examples[0].focusPath, code: preferModuleLevelConstantDocumentation.examples[0].files[0].source },
    // Already at module scope — the target state.
    { code: 'const KEYS = ["a", "b", "c"];\nfunction f(k: string) { return KEYS.includes(k); }' },

    // FP mode: closes over a parameter, so it cannot be hoisted at all.
    {
      code: 'function f(prefix: string) { const KEYS = [prefix, "b", "c"]; return KEYS.length; }',
    },
    {
      code: "function f(userId: string) { const M = new Map([[userId, 1], ['b', 2], ['c', 3]]); return M.size; }",
    },
    // Closes over an outer binding (not a literal).
    {
      code: "const BASE = 'x';\nfunction f() { const KEYS = [BASE, 'b', 'c']; return KEYS.length; }",
    },
    // Contains a call — evaluated per call on purpose.
    {
      code: "function f() { const A = [Date.now(), 1, 2]; return A.length; }",
    },
    // Template interpolation.
    {
      code: "function f(x: string) { const A = [`a-${x}`, 'b', 'c']; return A.length; }",
    },
    {
      name: "ignores a collection containing a member access",
      code: "function f(config: { value: string }) { const A = [config.value, 'b', 'c']; return A.length; }",
    },

    // FP mode: deliberately fresh per call because the function mutates it.
    {
      code: "function f(x: string) { const parts = ['a', 'b', 'c']; parts.push(x); return parts; }",
    },
    {
      code: "function f() { const s = new Set(['a', 'b', 'c']); s.add('d'); return s; }",
    },
    {
      code: "function f() { const m = new Map([['a', 1], ['b', 2], ['c', 3]]); m.set('d', 4); return m.size; }",
    },
    {
      code: "function f() { const a = ['a', 'b', 'c']; a.sort(); return a.length; }",
    },
    {
      code: "function f() { const o = { a: 1, b: 2, c: 3 }; o.a = 9; return o.a; }",
    },
    {
      code: "function f() { const a = [1, 2, 3]; a[0] = 9; return a.length; }",
    },
    {
      code: "function f() { const o = { a: 1, b: 2, c: 3 }; delete o.a; return o; }",
    },
    {
      code: "function f() { const o = { a: 1, b: 2, c: 3 }; o.a++; return o.a; }",
    },

    // FP mode: the value escapes, so the CALLER may mutate the shared instance.
    {
      code: "function f() { const a = ['a', 'b', 'c']; return a; }",
    },
    {
      code: "function f() { const a = ['a', 'b', 'c']; sink(a); return 1; }",
    },
    {
      code: "function f() { const a = ['a', 'b', 'c']; const b = a; return b.length; }",
    },
    {
      code: "function f() { const a = ['a', 'b', 'c']; return { items: a }; }",
    },
    {
      code: "function f() { const o = { a: 1, b: 2, c: 3 }; Object.assign(o, { d: 4 }); return o; }",
    },

    // FP mode: too small to be worth hoisting (default minElements: 3).
    { code: "function f() { const A = ['a']; return A.length; }" },
    { code: "function f() { const A = ['a', 'b']; return A.length; }" },
    { code: "function f() { const O = { a: 1 }; return O.a; }" },
    // ...and the option can raise the floor.
    {
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      options: [{ minElements: 4 }],
    },

    // FP mode: stateful regexes carry `lastIndex` across calls.
    { code: "function f(s: string) { const RE = /ab+c/g; return RE.test(s); }" },
    { code: "function f(s: string) { const RE = /ab+c/y; return RE.test(s); }" },
    // ...including one buried in a collection. `isLiteralOnly` sees a
    // `RegExpLiteral` as a plain `Literal`, so an ARRAY of regexes bypassed the
    // top-level `g`/`y` check entirely and the recommended hoist would have
    // changed behaviour on the second call.
    {
      code: "function f(s: string) { const RES = [/a/g, /b/, /c/]; return RES.some((r) => r.test(s)); }",
    },
    {
      code: "function f(s: string) { const RES = { a: /a/y, b: /b/, c: /c/ }; return RES.a.test(s); }",
    },
    // ...and regex checking is opt-out-able entirely.
    {
      code: "function f(s: string) { const RE = /ab+c/i; return RE.test(s); }",
      options: [{ checkRegex: false }],
    },

    // FP mode: test files keep their fixture tables next to the assertions.
    {
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "src/thing.test.ts",
    },
    {
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "src/__tests__/thing.ts",
    },
    {
      name: "ignores e2e fixture tables through the shared test-path classifier",
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "/repo/apps/web/playwright/booking-limits.e2e.ts",
    },
    {
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "/repo/integration/single-fetch-test.ts",
    },
    // Story files keep their fixture data next to the story (regression: this
    // came from the rule's own list and must survive the delegation).
    {
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "/repo/src/Button.stories.tsx",
    },
    // Generated files opt out.
    {
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/generated/api.ts",
    },
    {
      name: "ignores .gen.ts files",
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/api.gen.ts",
    },
    {
      name: "ignores .generated.tsx files",
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/api.generated.tsx",
    },
    {
      name: "ignores declaration files",
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/api.d.ts",
    },
    {
      code: "// @generated by codegen\nfunction f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/api.ts",
    },

    // `let` is not a constant binding.
    { code: "function f() { let a = ['a', 'b', 'c']; return a.length; }" },

    // Destructuring is not a hoistable single binding.
    {
      code: "function f() { const [a, b] = ['x', 'y', 'z']; return a + b; }",
    },

    // Not literal-only: nested object holds an identifier.
    {
      code: "function f(v: number) { const O = { a: 1, b: 2, c: { d: v } }; return O.a; }",
    },
    // Not literal-only: spread.
    {
      code: "const BASE = ['a'];\nfunction f() { const A = [...BASE, 'b', 'c']; return A.length; }",
    },
    // Not literal-only: shorthand property.
    {
      code: "function f(a: number, b: number, c: number) { const O = { a, b, c }; return O.a; }",
    },
    // Not literal-only: computed key from a variable.
    {
      code: "function f(k: string) { const O = { [k]: 1, b: 2, c: 3 }; return O.b; }",
    },
    // Not a recognised collection: `new Set(someArray)`.
    {
      code: "function f(xs: string[]) { const S = new Set(xs); return S.size; }",
    },
  ],

  invalid: [
    { name: "public match example", filename: preferModuleLevelConstantDocumentation.examples[1].focusPath, code: preferModuleLevelConstantDocumentation.examples[1].files[0].source, errors: [{ messageId: "hoistCollection" }] },
    // Array allow-list read via a non-mutating method.
    {
      name: "reports literal boolean null and number leaves",
      code: "function f() { const VALUES = [true, null, 1]; return VALUES.length; }",
      errors: [{ messageId: "hoistCollection", data: { name: "VALUES", kind: "array" } }],
    },
    {
      name: "reports an interpolation-free template literal",
      code: "function f() { const VALUES = [`a`, `b`, `c`]; return VALUES.length; }",
      errors: [{ messageId: "hoistCollection", data: { name: "VALUES", kind: "array" } }],
    },
    {
      name: "reports an object with literal computed keys",
      code: "function f() { const VALUES = { ['a']: 1, ['b']: 2, ['c']: 3 }; return VALUES.a; }",
      errors: [{ messageId: "hoistCollection", data: { name: "VALUES", kind: "object" } }],
    },
    {
      code: "function isAllowed(k: string) { const KEYS = ['a', 'b', 'c']; return KEYS.includes(k); }",
      errors: [{ messageId: "hoistCollection", data: { name: "KEYS", kind: "array" } }],
      output: null,
    },
    // Object lookup table read by index.
    {
      code: "function label(k: string) { const LABELS = { a: 'A', b: 'B', c: 'C' }; return LABELS[k]; }",
      errors: [{ messageId: "hoistCollection", data: { name: "LABELS", kind: "object" } }],
    },
    // Set membership.
    {
      code: "function isStop(w: string) { const STOP = new Set(['a', 'b', 'c']); return STOP.has(w); }",
      errors: [{ messageId: "hoistCollection", data: { name: "STOP", kind: "Set" } }],
    },
    // Map lookup.
    {
      code: "function code(k: string) { const M = new Map([['a', 1], ['b', 2], ['c', 3]]); return M.get(k); }",
      errors: [{ messageId: "hoistCollection", data: { name: "M", kind: "Map" } }],
    },
    // Non-global regex.
    {
      code: "function isEmail(s: string) { const RE = /^[^@]+@[^@]+$/; return RE.test(s); }",
      errors: [{ messageId: "hoistRegex", data: { name: "RE" } }],
    },
    // UPPER BOUND on the nested-regex fix: only the STATEFUL flags block the
    // hoist. A table of stateless regexes is exactly what the rule is for.
    {
      code: "function f(s: string) { const RES = [/a/i, /b/, /c/]; return RES.some((r) => r.test(s)); }",
      errors: [{ messageId: "hoistCollection", data: { name: "RES", kind: "array" } }],
    },
    // `as const` wrapper.
    {
      code: "function f(k: string) { const KEYS = ['a', 'b', 'c'] as const; return KEYS.includes(k as never); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // `Object.freeze` wrapper.
    {
      code: "function f() { const O = Object.freeze({ a: 1, b: 2, c: 3 }); return O.a; }",
      errors: [{ messageId: "hoistCollection", data: { name: "O", kind: "object" } }],
    },
    // Arrow function body (React-component shape — identity churn per render).
    {
      code: "const C = () => { const OPTIONS = [{ v: 1 }, { v: 2 }, { v: 3 }]; return OPTIONS.map((o) => o.v); };",
      errors: [{ messageId: "hoistCollection", data: { name: "OPTIONS", kind: "array" } }],
    },
    // Class method body.
    {
      code: "class A { m(k: string) { const KEYS = ['a', 'b', 'c']; return KEYS.indexOf(k); } }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // `for…of` iteration is a read.
    {
      code: "function f() { const KEYS = ['a', 'b', 'c']; for (const k of KEYS) { use(k); } }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // Spread into a NEW object copies, so hoisting stays safe.
    {
      code: "function f(o: object) { const DEFAULTS = { a: 1, b: 2, c: 3 }; return { ...DEFAULTS, ...o }; }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "reports a collection copied by array spread",
      code: "function f() { const VALUES = ['a', 'b', 'c']; return [...VALUES]; }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "reports a collection copied into spread arguments",
      code: "function f() { const VALUES = ['a', 'b', 'c']; return consume(...VALUES); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // `Object.entries` neither mutates nor retains.
    {
      code: "function f() { const M = { a: 1, b: 2, c: 3 }; return Object.entries(M).length; }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "reports a collection passed as an Object.assign source",
      code: "function f() { const M = { a: 1, b: 2, c: 3 }; return Object.assign({}, M); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "reports a collection passed to non-retaining built-ins",
      code: "function f() { const M = { a: 1, b: 2, c: 3 }; return JSON.stringify(structuredClone(M)); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // Read-only capture by a nested closure is unaffected by hoisting.
    {
      code: "function f() { const KEYS = ['a', 'b', 'c']; return (k: string) => KEYS.includes(k); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // Nested literals of literals still qualify.
    {
      code: "function f() { const ROWS = [{ id: 1, tags: ['x'] }, { id: 2, tags: ['y'] }, { id: 3, tags: [] }]; return ROWS.length; }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // Negative numbers are literals.
    {
      code: "function f() { const OFFSETS = [-1, 0, 1]; return OFFSETS.length; }",
      errors: [{ messageId: "hoistCollection" }],
    },
    // Lowered floor via options.
    {
      code: "function f() { const A = ['a', 'b']; return A.length; }",
      options: [{ minElements: 2 }],
      errors: [{ messageId: "hoistCollection" }],
    },
    // Test-file exemption can be turned off.
    {
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/thing.spec.ts",
      options: [{ ignoreTestFiles: false }],
      errors: [{ messageId: "hoistCollection" }],
    },
  ],
});
