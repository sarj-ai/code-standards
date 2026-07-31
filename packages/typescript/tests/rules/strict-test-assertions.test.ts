import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/strict-test-assertions.js";

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

ruleTester.run("strict-test-assertions", rule, {
  valid: [
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
  ],
  invalid: [
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
describe("strict-test-assertions autofix soundness", () => {
  const linter = new Linter();
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { local: { rules: { "strict-test-assertions": rule } } },
      rules: { "local/strict-test-assertions": "error" },
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

  it("still merges the runs it can merge exactly", () => {
    expect(fix(`expect(o.a).toBe(1);\nexpect(o.b).toBe(2);\n`)).toBe(
      `expect(o).toMatchObject({ a: 1, b: 2 });\n\n`,
    );
  });
});
