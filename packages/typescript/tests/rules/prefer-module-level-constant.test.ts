// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION,
} from "../../src/rules/prefer-module-level-constant.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

RULE_TESTER.run("prefer-module-level-constant", rule, {
  valid: [
    {
      name: "does not assume a parameter Object.keys is non-retaining",
      code: "function count(Object) { const values = [1, 2, 3]; return Object.keys(values).length; }",
    },
    {
      name: "preserves mutation through a local Object.keys",
      code: "function count() { const Object = { keys(values) { values.push(4); return values; } }; const values = [1, 2, 3]; return Object.keys(values).length; }",
    },
    {
      name: "does not assume a parameter Array.from is non-retaining",
      code: "function copy(Array) { const values = [1, 2, 3]; return Array.from(values).length; }",
    },
    {
      name: "does not assume a parameter JSON.stringify is non-retaining",
      code: "function encode(JSON) { const values = [1, 2, 3]; return JSON.stringify(values); }",
    },
    {
      name: "does not assume a parameter structuredClone is non-retaining",
      code: "function copy(structuredClone) { const values = [1, 2, 3]; return structuredClone(values).length; }",
    },
    {
      name: "does not hoist construction through a local Set parameter",
      code: "function count(Set) { const values = new Set([1, 2, 3]); return values.size; }",
    },
    {
      name: "does not hoist construction through a local Map class",
      code: "class Map { constructor(entries) { this.size = entries.length; } } function count() { const values = new Map([['a', 1], ['b', 2], ['c', 3]]); return values.size; }",
    },
    {
      name: "preserves an imported Object contract",
      code: "import Object from 'custom-objects'; function count() { const values = [1, 2, 3]; return Object.keys(values).length; }",
    },
    {
      name: "resolves a hoisted function binding for structuredClone",
      code: "function count() { const values = [1, 2, 3]; return structuredClone(values).length; function structuredClone(values) { values.push(4); return values; } }",
    },
    {
      name: "does not call a module IIFE allocation repeated work",
      code: "const encode = (() => { const table = {a: 1, b: 2, c: 3}; return (key) => table[key]; })();",
    },
    {
      name: "excludes a directly invoked typed function expression",
      code: "const encode = ((function () { const table = {a: 1, b: 2, c: 3}; return (key) => table[key]; }) as () => unknown)();",
    },
    {
      name: "preserves nested property mutation per invocation",
      code: "function f() { const values = {a: {count: 0}, b: 1, c: 2}; values.a.count++; return values.a.count; }",
    },
    {
      name: "preserves nested array mutation per invocation",
      code: "function f() { const values = [[1], [2], [3]]; values[0].push(4); return values[0].length; }",
    },
    {
      name: "preserves computed mutator calls",
      code: "function f() { const values = [1, 2, 3]; values['push'](4); return values.length; }",
    },
    {
      name: "preserves escaped nested mutable values",
      code: "function f() { const values = {a: {count: 0}, b: 1, c: 2}; const child = values.a; child.count++; return child.count; }",
    },
    {
      name: "public no-match example",
      filename:
        PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION.examples[0].focusPath,
      code: PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION.examples[0].files[0]
        .source,
    },

    {
      code: 'const KEYS = ["a", "b", "c"];\nfunction f(k: string) { return KEYS.includes(k); }',
    },


    {
      code: 'function f(prefix: string) { const KEYS = [prefix, "b", "c"]; return KEYS.length; }',
    },
    {
      code: "function f(userId: string) { const M = new Map([[userId, 1], ['b', 2], ['c', 3]]); return M.size; }",
    },

    {
      code: "const BASE = 'x';\nfunction f() { const KEYS = [BASE, 'b', 'c']; return KEYS.length; }",
    },

    {
      code: "function f() { const A = [Date.now(), 1, 2]; return A.length; }",
    },

    {
      code: "function f(x: string) { const A = [`a-${x}`, 'b', 'c']; return A.length; }",
    },
    {
      name: "ignores a collection containing a member access",
      code: "function f(config: { value: string }) { const A = [config.value, 'b', 'c']; return A.length; }",
    },


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


    { code: "function f() { const A = ['a']; return A.length; }" },
    { code: "function f() { const A = ['a', 'b']; return A.length; }" },
    { code: "function f() { const O = { a: 1 }; return O.a; }" },

    {
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      options: [{ minElements: 4 }],
    },


    {
      code: "function f(s: string) { const RE = /ab+c/g; return RE.test(s); }",
    },
    {
      code: "function f(s: string) { const RE = /ab+c/y; return RE.test(s); }",
    },




    {
      code: "function f(s: string) { const RES = [/a/g, /b/, /c/]; return RES.some((r) => r.test(s)); }",
    },
    {
      code: "function f(s: string) { const RES = { a: /a/y, b: /b/, c: /c/ }; return RES.a.test(s); }",
    },

    {
      code: "function f(s: string) { const RE = /ab+c/i; return RE.test(s); }",
      options: [{ checkRegex: false }],
    },


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


    {
      code: "function f() { const CASES = ['a', 'b', 'c']; return CASES.length; }",
      filename: "/repo/src/Button.stories.tsx",
    },

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


    { code: "function f() { let a = ['a', 'b', 'c']; return a.length; }" },


    {
      code: "function f() { const [a, b] = ['x', 'y', 'z']; return a + b; }",
    },


    {
      code: "function f(v: number) { const O = { a: 1, b: 2, c: { d: v } }; return O.a; }",
    },

    {
      code: "const BASE = ['a'];\nfunction f() { const A = [...BASE, 'b', 'c']; return A.length; }",
    },

    {
      code: "function f(a: number, b: number, c: number) { const O = { a, b, c }; return O.a; }",
    },

    {
      code: "function f(k: string) { const O = { [k]: 1, b: 2, c: 3 }; return O.b; }",
    },

    {
      code: "function f(xs: string[]) { const S = new Set(xs); return S.size; }",
    },
  ],

  invalid: [
    {
      name: "preserves static computed native lookup access",
      code: "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS['includes'](key); }",
      output:
        "const KEYS: readonly string[] = ['a', 'b', 'c'];\nexport function isAllowed(key: string) { return KEYS['includes'](key); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "preserves CRLF while hoisting a readonly literal lookup",
      code: "export function isAllowed(key: string) {\r\n  const KEYS: readonly string[] = ['a', 'b', 'c'];\r\n  return KEYS.includes(key);\r\n}",
      output:
        "const KEYS: readonly string[] = ['a', 'b', 'c'];\r\nexport function isAllowed(key: string) {\r\n  return KEYS.includes(key);\r\n}",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 1",
      code: "export function isAllowed(key: string) { const KEYS: string[] = ['a', 'b', 'c']; return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 2",
      code: "import './register.js'; export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 3",
      code: "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS.join(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 4",
      code: "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; observe(); return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 5",
      code: "export function isAllowed(key: string) { const KEYS: readonly (string | number)[] = ['a', 'b', 3]; return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 6",
      code: "export function KEYS(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "retains unsupported boundary 7",
      code: "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; /* keep local */ return KEYS.includes(key); }",
      output: null,
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "applies the source-owned exact correction",
      code: "export function isAllowed(key: string) { const KEYS: readonly string[] = ['a', 'b', 'c']; return KEYS.includes(key); }",
      output:
        "const KEYS: readonly string[] = ['a', 'b', 'c'];\nexport function isAllowed(key: string) { return KEYS.includes(key); }",
      errors: [{ messageId: "hoistCollection" }],
    },
    {
      name: "public match example",
      filename:
        PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION.examples[1].focusPath,
      code: PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION.examples[1].files[0]
        .source,
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      name: "reports literal boolean null and number leaves",
      code: "function f() { const VALUES = [true, null, 1]; return VALUES.length; }",
      errors: [
        {
          messageId: "hoistCollection",
          data: { name: "VALUES", kind: "array" },
        },
      ],
    },
    {
      name: "reports an interpolation-free template literal",
      code: "function f() { const VALUES = [`a`, `b`, `c`]; return VALUES.length; }",
      errors: [
        {
          messageId: "hoistCollection",
          data: { name: "VALUES", kind: "array" },
        },
      ],
    },
    {
      name: "reports an object with literal computed keys",
      code: "function f() { const VALUES = { ['a']: 1, ['b']: 2, ['c']: 3 }; return VALUES.a; }",
      errors: [
        {
          messageId: "hoistCollection",
          data: { name: "VALUES", kind: "object" },
        },
      ],
    },
    {
      code: "function isAllowed(k: string) { const KEYS = ['a', 'b', 'c']; return KEYS.includes(k); }",
      errors: [
        { messageId: "hoistCollection", data: { name: "KEYS", kind: "array" } },
      ],
      output: null,
    },

    {
      code: "function label(k: string) { const LABELS = { a: 'A', b: 'B', c: 'C' }; return LABELS[k]; }",
      errors: [
        {
          messageId: "hoistCollection",
          data: { name: "LABELS", kind: "object" },
        },
      ],
    },

    {
      code: "function isStop(w: string) { const STOP = new Set(['a', 'b', 'c']); return STOP.has(w); }",
      errors: [
        { messageId: "hoistCollection", data: { name: "STOP", kind: "Set" } },
      ],
    },

    {
      code: "function code(k: string) { const M = new Map([['a', 1], ['b', 2], ['c', 3]]); return M.get(k); }",
      errors: [
        { messageId: "hoistCollection", data: { name: "M", kind: "Map" } },
      ],
    },

    {
      code: "function isEmail(s: string) { const RE = /^[^@]+@[^@]+$/; return RE.test(s); }",
      errors: [{ messageId: "hoistRegex", data: { name: "RE" } }],
    },


    {
      code: "function f(s: string) { const RES = [/a/i, /b/, /c/]; return RES.some((r) => r.test(s)); }",
      errors: [
        { messageId: "hoistCollection", data: { name: "RES", kind: "array" } },
      ],
    },

    {
      code: "function f(k: string) { const KEYS = ['a', 'b', 'c'] as const; return KEYS.includes(k as never); }",
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const O = Object.freeze({ a: 1, b: 2, c: 3 }); return O.a; }",
      errors: [
        { messageId: "hoistCollection", data: { name: "O", kind: "object" } },
      ],
    },

    {
      code: "const C = () => { const OPTIONS = [{ v: 1 }, { v: 2 }, { v: 3 }]; return OPTIONS.map((o) => o.v); };",
      errors: [
        {
          messageId: "hoistCollection",
          data: { name: "OPTIONS", kind: "array" },
        },
      ],
    },

    {
      code: "class A { m(k: string) { const KEYS = ['a', 'b', 'c']; return KEYS.indexOf(k); } }",
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const KEYS = ['a', 'b', 'c']; for (const k of KEYS) { use(k); } }",
      errors: [{ messageId: "hoistCollection" }],
    },

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

    {
      code: "function f() { const KEYS = ['a', 'b', 'c']; return (k: string) => KEYS.includes(k); }",
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const ROWS = [{ id: 1, tags: ['x'] }, { id: 2, tags: ['y'] }, { id: 3, tags: [] }]; return ROWS.length; }",
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const OFFSETS = [-1, 0, 1]; return OFFSETS.length; }",
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const A = ['a', 'b']; return A.length; }",
      options: [{ minElements: 2 }],
      errors: [{ messageId: "hoistCollection" }],
    },

    {
      code: "function f() { const A = ['a', 'b', 'c']; return A.length; }",
      filename: "src/thing.spec.ts",
      options: [{ ignoreTestFiles: false }],
      errors: [{ messageId: "hoistCollection" }],
    },
  ],
});
