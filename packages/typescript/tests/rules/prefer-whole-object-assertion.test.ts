import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule, { preferWholeObjectAssertionDocumentation } from "../../src/rules/prefer-whole-object-assertion.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

/** The rule only runs in test files, so every case has to look like one. */
const filename = "src/user.test.ts";

ruleTester.run("prefer-whole-object-assertion", rule, {
  valid: [
    { name: "accepts the documented whole-object assertion", filename, code: preferWholeObjectAssertionDocumentation.examples[0].files[0].source },
    // Already the combined form.
    { filename, code: `expect(obj).toMatchObject({ a: 1, b: 2 });` },
    // A single assertion has nothing to combine with.
    { filename, code: `expect(obj.a).toBe(1);` },
    // Different receivers are different assertions.
    {
      filename,
      code: `
        expect(obj1.a).toBe(1);
        expect(obj2.b).toBe(2);
      `,
    },
    // Scope. The rule reported on production code before 2026-07 because it
    // imported nothing from `_paths`; this is that latent bug, pinned.
    {
      filename: "src/user.ts",
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
    },
    {
      filename: "src/generated/user.test.ts",
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
    },
    // --- Matcher allowlist. Each of these was reported AND autofixed before. ---
    // Spy assertions: 238 sequences (7.6%) in the population.
    {
      filename,
      code: `
        expect(mockRedis.get).toHaveBeenCalledWith("test:1");
        expect(mockRedis.set).toHaveBeenCalledWith("test:1", 2);
      `,
    },
    // Matchers with no object-literal equivalent: 484 sequences (15.4%).
    {
      filename,
      code: `
        expect(obj.name).toContain("ab");
        expect(obj.items).toHaveLength(3);
        expect(obj.n).toBeGreaterThan(5);
      `,
    },
    {
      filename,
      code: `
        expect(cal.embedRenderStartTime).toBeGreaterThan(0);
        expect(cal.embedConfig).toBeDefined();
      `,
    },
    // Same receiver, same matcher, different expected values — the DOM /
    // testing-library class, 64 sequences (2.0%).
    {
      filename,
      code: `
        expect(utils.container).toHaveTextContent("a:success");
        expect(utils.container).toHaveTextContent("b:success");
      `,
    },
    // One un-mergeable matcher in the middle kills the whole run. This is the
    // stated recall cost of the equivalence invariant, not an accident.
    {
      filename,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBeDefined();
        expect(obj.c).toBe(3);
      `,
    },
    // Duplicate key: merging produced `{ a: 1, a: 2 }` and silently deleted an
    // assertion.
    {
      filename,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.a).toBe(2);
      `,
    },
    // Non-literal expected value: `toBe` is Object.is, `toMatchObject` is
    // recursive structural equality. There is no equivalent merged form.
    {
      filename,
      code: `
        expect(client.auth).toBe(auth);
        expect(client.zoho).toBe(zoho);
      `,
    },
    {
      filename,
      code: `
        expect(res.body).toEqual({ ok: true });
        expect(res.headers).toEqual({ "content-type": "application/json" });
      `,
    },
    // A collection's size is not a property `toMatchObject` can describe, and
    // `.length` mixed into element assertions was its own FP class (26, 0.8%).
    {
      filename,
      code: `
        expect(results.length).toBe(1);
        expect(results.size).toBe(1);
      `,
    },
    {
      filename,
      code: `
        expect(results.length).toBe(2);
        expect(results[0]).toEqual("a");
      `,
    },
    // Impure receiver: the merged form would call `getUser()` once, not twice.
    {
      filename,
      code: `
        expect(getUser().a).toBe(1);
        expect(getUser().b).toBe(2);
      `,
    },
    // Optional chaining changes what happens when the receiver is nullish.
    {
      filename,
      code: `
        expect(obj?.a).toBe(1);
        expect(obj?.b).toBe(2);
      `,
    },
    // Known false negatives, recorded so a later change notices if they move.
    {
      filename,
      code: `
        expect(obj.a).not.toBe(1);
        expect(obj.b).not.toBe(2);
      `,
    },
    {
      name: "ignores awaited expect calls",
      filename,
      code: `
        await expect(obj.a).toBe(1);
        await expect(obj.b).toBe(2);
      `,
    },
    {
      name: "ignores resolves and rejects chains",
      filename,
      code: `
        expect(obj.a).resolves.toBe(1);
        expect(obj.b).resolves.toBe(2);
        expect(obj.c).rejects.toThrow("nope");
      `,
    },
    {
      filename,
      code: `
        expect.soft(obj.a).toBe(1);
        expect.soft(obj.b).toBe(2);
      `,
    },
    {
      filename,
      code: `
        expect(obj.a).to.equal(1);
        expect(obj.b).to.equal(2);
      `,
    },
    // Indexed runs that do not start at 0 leave the leading elements
    // unconstrained, so there is no array literal to suggest.
    {
      filename,
      code: `
        expect(rows[1]).toEqual("a");
        expect(rows[2]).toEqual("b");
      `,
    },
    {
      name: "ignores indexed runs with gaps",
      filename,
      code: `
        expect(rows[0]).toEqual("a");
        expect(rows[2]).toEqual("c");
      `,
    },
    {
      name: "ignores indexed assertions separated by another statement",
      filename,
      code: `
        expect(rows[0]).toEqual("a");
        observe(rows);
        expect(rows[1]).toEqual("b");
      `,
    },
    // Element-wise `toBe` is identity; `toEqual` on the whole array is not.
    {
      filename,
      code: `
        expect(rows[0]).toBe(a);
        expect(rows[1]).toBe(b);
      `,
    },
    // A statement between the assertions breaks the run.
    {
      filename,
      code: `
        expect(obj.a).toBe(1);
        doSomething();
        expect(obj.b).toBe(2);
      `,
    },

    // --- The `expect(...)` shape itself. Both halves of the callee check are
    // load-bearing and neither was pinned: with the NAME check gone any
    // one-argument call whose result is `.toBe`d would be reported and
    // "fixed" into an `expect(...).toMatchObject`, and with the ARITY check
    // gone a two-argument `expect(actual, message)` would lose its message.
    {
      filename,
      code: `
        foo(obj.a).toBe(1);
        foo(obj.b).toBe(2);
      `,
    },
    {
      filename,
      code: `
        expect(obj.a, "a must be 1").toBe(1);
        expect(obj.b, "b must be 2").toBe(2);
      `,
    },

    // --- Receiver purity, in the two shapes the corpus actually contains ---
    // An optional link anywhere in the chain parses as a ChainExpression, not a
    // MemberExpression, and the merged form would also change what happens when
    // `a` is nullish.
    {
      filename,
      code: `
        expect(a?.b.c).toBe(1);
        expect(a?.b.d).toBe(2);
      `,
    },
    // A computed access through a VARIABLE is not re-evaluable to the same
    // thing: `k` may be reassigned between the statements. Only a literal
    // subscript counts as pure.
    {
      filename,
      code: `
        expect(m[k].c).toBe(1);
        expect(m[k].d).toBe(2);
      `,
    },

    // --- What counts as a primitive literal ---
    // A template literal with a substitution is a computed value, not a literal.
    {
      filename,
      code: "\n        expect(obj.a).toBe(`x${y}`);\n        expect(obj.b).toBe(`z${y}`);\n      ",
    },
    // Only `-` and `+` make a unary expression constant. `!flag` is a computed
    // boolean, and merging it would be the `toBe`-to-structural-equality
    // downgrade.
    {
      filename,
      code: `
        expect(obj.a).toBe(!flag);
        expect(obj.b).toBe(!other);
      `,
    },
    {
      name: "does not replace regular expression identity with structural comparison",
      filename,
      code: `
        expect(obj.a).toBe(/a/);
        expect(obj.b).toBe(/b/);
      `,
    },

    // --- Indexed runs: which subscripts are indices at all ---
    // A fractional subscript is not an array index, so it is not part of a run
    // that `expect(rows).toEqual([…])` could replace. The pair is chosen so the
    // integer check is the ONLY thing suppressing the report: `{0.5, 1}` has as
    // many members as the run has statements and a maximum of `run.length - 1`,
    // so it satisfies the "indices are exactly 0..n-1" test and would be
    // reported — with an array literal missing its first element — the moment
    // 0.5 is allowed to count as an index.
    {
      filename,
      code: `
        expect(rows[0.5]).toEqual("a");
        expect(rows[1]).toEqual("b");
      `,
    },
    // A negative subscript parses as a unary expression rather than a literal,
    // so it never reaches the index test at all.
    {
      filename,
      code: `
        expect(rows[-1]).toEqual("a");
        expect(rows[1]).toEqual("b");
      `,
    },
    // Mixed matchers inside an indexed run: `toEqual` and `toStrictEqual` do not
    // make the same comparison, so neither one describes the whole array.
    {
      filename,
      code: `
        expect(rows[0]).toEqual("a");
        expect(rows[1]).toStrictEqual("b");
      `,
    },
  ],
  invalid: [
    { name: "fixes the documented member assertion run", filename, code: preferWholeObjectAssertionDocumentation.examples[1].files[0].source, output: preferWholeObjectAssertionDocumentation.examples[1].fixedFiles[0].source, errors: [{ messageId: "combineAssertions" }] },
    // The surviving true positive: the exact shape the fixer can rewrite
    // without changing what the test asserts.
    {
      filename,
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
      output: `
        expect(obj).toMatchObject({ a: 1, b: 2 });
        
      `,
      errors: [{ messageId: "combineAssertions" }],
    },
    // Boundary: mixed mergeable matchers and mixed literal kinds still merge,
    // because on a primitive literal toBe / toEqual / toStrictEqual / toBeNull
    // all agree with toMatchObject's per-key comparison.
    {
      filename,
      code: `
        expect(user.id).toBe(1);
        expect(user.name).toEqual("ada");
        expect(user.active).toStrictEqual(true);
        expect(user.deletedAt).toBeNull();
      `,
      output: `
        expect(user).toMatchObject({ id: 1, name: "ada", active: true, deletedAt: null });
        
        
        
      `,
      errors: [{ messageId: "combineAssertions" }],
    },
    // Boundary: a nested but still pure receiver stays in scope.
    {
      filename,
      code: `
        expect(res.body.user.id).toBe(1);
        expect(res.body.user.name).toBe("ada");
      `,
      output: `
        expect(res.body.user).toMatchObject({ id: 1, name: "ada" });
        
      `,
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      name: "merges a property run on a literal computed receiver",
      filename,
      code: `
        expect(registry["user"].id).toBe(1);
        expect(registry["user"].active).toBe(true);
      `,
      output:
        "\n        expect(registry[\"user\"]).toMatchObject({ id: 1, active: true });\n        \n      ",
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      name: "treats inherited names other than __proto__ as ordinary keys",
      filename,
      code: `
        expect(obj.constructor).toBe(null);
        expect(obj.toString).toBe("custom");
      `,
      output:
        "\n        expect(obj).toMatchObject({ constructor: null, toString: \"custom\" });\n        \n      ",
      errors: [{ messageId: "combineAssertions" }],
    },
    // Array-indexed run: different message, deliberately no fix, because
    // `toEqual([…])` adds a length assertion the run never made.
    {
      filename,
      code: `
        expect(bodies[0]).toEqual("a");
        expect(bodies[1]).toEqual({ slug: "b" });
      `,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },
    // Boundary: the receiver of an indexed run may itself be indexed.
    {
      filename,
      code: `
        expect(res[0][0]).toStrictEqual("slug");
        expect(res[0][1]).toStrictEqual({ slug: "b" });
      `,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },

    // --- THE SHAPE THAT ACTUALLY OCCURS ---
    // Every case above states its assertions at module top level, which reaches
    // the rule through the `Program` visitor. Real suites put them in an
    // `it(…, () => { … })` callback, and that path runs only through
    // `BlockStatement` — so the entire `BlockStatement` visitor could be deleted
    // with the whole suite green, and the rule would have reported nothing in
    // any test file ever written. Both run kinds are pinned in that shape.
    {
      filename,
      code: `it("returns the user", () => {
  expect(obj.a).toBe(1);
  expect(obj.b).toBe(2);
});`,
      output: 'it("returns the user", () => {\n  expect(obj).toMatchObject({ a: 1, b: 2 });\n  \n});',
      errors: [{ messageId: "combineAssertions" }],
    },
    {
      filename,
      code: `describe("rows", () => {
  it("returns them in order", () => {
    expect(rows[0]).toEqual("a");
    expect(rows[1]).toEqual("b");
  });
});`,
      output: null,
      errors: [{ messageId: "assertArrayOnce" }],
    },

    // --- Receiver and expected-value shapes that ARE mergeable ---
    // `this.x` inside a class-based test helper. `ThisExpression` is the one
    // pure receiver that is not an identifier or a chain over one.
    {
      filename,
      code: `
        expect(this.a).toBe(1);
        expect(this.b).toBe(2);
      `,
      output: "\n        expect(this).toMatchObject({ a: 1, b: 2 });\n        \n      ",
      errors: [{ messageId: "combineAssertions" }],
    },
    // A template literal with no substitutions is a string literal written with
    // backticks, and merges verbatim.
    {
      filename,
      code: "\n        expect(obj.a).toBe(`x`);\n        expect(obj.b).toBe(`y`);\n      ",
      output: "\n        expect(obj).toMatchObject({ a: `x`, b: `y` });\n        \n      ",
      errors: [{ messageId: "combineAssertions" }],
    },
    // A negative number parses as a unary expression rather than a literal, and
    // is still a constant the merged object can carry.
    {
      filename,
      code: `
        expect(point.x).toBe(-1);
        expect(point.y).toBe(+2);
      `,
      output: "\n        expect(point).toMatchObject({ x: -1, y: +2 });\n        \n      ",
      errors: [{ messageId: "combineAssertions" }],
    },
  ],
});

/**
 * The autofix regression suite.
 *
 * Before 2026-07 the fixer read `arguments[0]` of every assertion in the run and
 * dropped it into a `toMatchObject`, never looking at the matcher. Every input
 * below was silently rewritten into a weaker or broken test by `eslint --fix`.
 * `verifyAndFix` is used rather than the rule tester's `output` field because
 * what is being pinned is the *end state of a real fix pass*: if a future edit
 * reintroduces a matcher-blind fixer, this fails.
 */
describe("prefer-whole-object-assertion autofix soundness", () => {
  const linter = new Linter();
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { local: { rules: { "prefer-whole-object-assertion": rule } } },
      rules: { "local/prefer-whole-object-assertion": "error" },
      // Off so these cases measure THIS fixer. ESLint's own unused-directive
      // fixer deletes a stranded `eslint-disable-next-line` on the next pass,
      // which would hide the orphaning rather than fix it.
      linterOptions: { reportUnusedDisableDirectives: "off" },
    },
  ] as unknown as Linter.Config[];

  const fix = (code: string): string => linter.verifyAndFix(code, config, filename).output;

  it("leaves substring, length and ordering matchers alone", () => {
    const code = `expect(o.name).toContain("ab");\nexpect(o.items).toHaveLength(3);\nexpect(o.n).toBeGreaterThan(5);\n`;
    expect(fix(code)).toBe(code);
  });

  it("leaves spy assertions alone", () => {
    const code = `expect(m.get).toHaveBeenCalledWith("k");\nexpect(m.set).toHaveBeenCalledWith("k", 1);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never emits a duplicate object key", () => {
    const code = `expect(o.a).toBe(1);\nexpect(o.a).toBe(2);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never downgrades toBe on a non-literal to structural equality", () => {
    const code = `expect(c.auth).toBe(auth);\nexpect(c.zoho).toBe(zoho);\n`;
    expect(fix(code)).toBe(code);
  });

  it("never rewrites an indexed run, which would add a length assertion", () => {
    const code = `expect(bodies[0]).toEqual("a");\nexpect(bodies[1]).toEqual("b");\n`;
    expect(fix(code)).toBe(code);
  });

  /**
   * `__proto__` in an object literal is the prototype setter, not a key, so the
   * fixer used to DELETE the assertion it claimed to be merging. Pinned three
   * ways because the original shipped with tests that covered the report and
   * never applied the fix: the language fact, the fixer's output, and the
   * runtime consequence.
   */
  describe("__proto__ is a prototype setter, not a key", () => {
    it("Object.keys drops it — the language fact the guard rests on", () => {
      expect(Object.keys({ __proto__: null, b: 2 })).toStrictEqual(["b"]);
      // The quoted spelling is the same production, so quoting is not a fix.
      expect(Object.keys({ "__proto__": null, b: 2 })).toStrictEqual(["b"]);
    });

    it("the merged form would stop checking the prototype at all", () => {
      const received: Record<string, unknown> = Object.create({ marker: 1 }) as Record<string, unknown>;
      received["b"] = 2;
      // What `expect(o.__proto__).toBe(null)` asserts:
      expect(Object.getPrototypeOf(received)).not.toBeNull();
      // What a merged `toMatchObject({ __proto__: null, b: 2 })` would assert:
      // only `b`. So the failing test would start passing.
      expect(received["b"]).toBe(2);
    });

    it("is never merged or rewritten", () => {
      const code = `expect(o.__proto__).toBe(null);\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("breaks the run rather than poisoning it, so the rest still merges", () => {
      expect(fix(`expect(o.__proto__).toBe(null);\nexpect(o.b).toBe(2);\nexpect(o.c).toBe(3);\n`)).toBe(
        `expect(o.__proto__).toBe(null);\nexpect(o).toMatchObject({ b: 2, c: 3 });\n\n`,
      );
    });
  });

  /**
   * A removed statement takes its own text but not the comment above it. Worst
   * case that comment is an `eslint-disable-next-line`, which then points at the
   * merged assertion and becomes a fresh unused-directive error.
   */
  describe("comments inside the run", () => {
    it("does not orphan a leading comment", () => {
      const code = `expect(o.a).toBe(1);\n// b matters because the API returns it second\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("does not strand an eslint-disable directive", () => {
      const code = `expect(o.a).toBe(1);\n// eslint-disable-next-line local/prefer-whole-object-assertion\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("does not swallow a comment inside a merged statement", () => {
      const code = `expect(o.a /* the a */).toBe(1);\nexpect(o.b).toBe(2);\n`;
      expect(fix(code)).toBe(code);
    });

    it("still fixes when the comment sits outside the span", () => {
      expect(fix(`// setup\nexpect(o.a).toBe(1);\nexpect(o.b).toBe(2); // done\n`)).toBe(
        `// setup\nexpect(o).toMatchObject({ a: 1, b: 2 });\n // done\n`,
      );
    });
  });

  it("still merges the runs it can merge exactly", () => {
    expect(fix(`expect(o.a).toBe(1);\nexpect(o.b).toBe(2);\n`)).toBe(
      `expect(o).toMatchObject({ a: 1, b: 2 });\n\n`,
    );
  });
});
