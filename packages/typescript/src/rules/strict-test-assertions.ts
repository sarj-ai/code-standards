/**
 * @fileoverview `strict-test-assertions`. A run of consecutive `expect(...)`
 * statements that all pick at the *same* receiver is usually one assertion
 * written N times: `expect(user.id).toBe(1); expect(user.name).toBe("ada")`
 * fails on the first mismatch and never tells you about the second, and it
 * never says anything about the rest of `user`. Collapsing the run into one
 * `expect(user).toMatchObject({ id: 1, name: "ada" })` reports every mismatch
 * at once and reads as a single statement about the value.
 *
 * ## What the 2026-07 false-positive audit found, and what changed
 *
 * The rule as originally written grouped a run on the receiver text ALONE. It
 * never looked at the matcher, and neither did its autofix. Measured over
 * 25,508 deduped `.ts`/`.tsx`/`.js`/`.jsx` files (six first-party repos plus
 * zod, trpc, dub, openstatus, formbricks, documenso, unkey, midday, papermark,
 * cal.com and hono) it produced 3,148 findings. A seeded read of 37 of them
 * scored 0 true positives, 8 false positives and 29 arguable. Reconstructing
 * the class sizes over the population put the hard-false-positive share at
 * 25.9%, consistent with the 21.6% read rate.
 *
 * Three defects, in descending order of how much damage they did:
 *
 * **1. The autofix was unsound.** It took `arguments[0]` of every assertion in
 * the run and emitted `<property>: <that argument>` into a `toMatchObject`,
 * whatever the matcher had been. Run through `Linter.verifyAndFix`, the shipped
 * build rewrote
 *
 * - `expect(o.name).toContain("ab"); expect(o.items).toHaveLength(3);` into
 *   `expect(o).toMatchObject({ name: "ab", items: 3 })` — substring and length
 *   silently became equality;
 * - `expect(m.get).toHaveBeenCalledWith("k"); expect(m.set).toHaveBeenCalledWith("k", 1);`
 *   into `expect(m).toMatchObject({ get: "k", set: "k" })` — two spy assertions
 *   destroyed and an argument dropped;
 * - `expect(o.a).toBe(1); expect(o.a).toBe(2);` into
 *   `expect(o).toMatchObject({ a: 1, a: 2 })` — a duplicate key, so one
 *   assertion vanished;
 * - `expect(c.auth).toBe(auth); expect(c.zoho).toBe(zoho);` into
 *   `expect(c).toMatchObject({ auth: auth, zoho: zoho })` — `toBe` is
 *   `Object.is`, `toMatchObject` is recursive structural equality, so an
 *   identity check became a much weaker shape check.
 *
 * Any repository that ran `eslint --fix` had its tests quietly weakened. The
 * four rewrites above are pinned as regression tests.
 *
 * **2. It was scoped to neither tests nor hand-written files.** The module
 * imported nothing from `./_paths.js`, so a rule whose name begins "test"
 * happily reported on `export function f(o) { expect(o.a).toBe(1); expect(o.b).toBe(2); }`
 * in production code, and on generated files. This produced no *observed* false
 * positives on this corpus only because every `expect()` in it happens to sit in
 * a test file — it was a latent bug, not a measured win. `isTestFile` and
 * `isGeneratedFile` guards now close it.
 *
 * **3. Runs were grouped across matchers `toMatchObject` cannot express.**
 * Population counts over the 3,141 sequences whose class could be reconstructed:
 *
 * - spy/mock runs (`toHaveBeenCalled`, `toHaveBeenCalledWith`, …) — 238 (7.6%),
 *   e.g. `cal.com/packages/features/cache/decorators/__tests__/Memoize.test.ts:62`;
 * - DOM / testing-library runs — same receiver, same matcher, different
 *   expected values — 64 (2.0%), e.g.
 *   `trpc/packages/react-query/test/invalidateQueries.test.tsx:64`;
 * - runs containing a matcher with no object-literal equivalent (`toBeDefined`
 *   315 on its own, plus `toMatchInlineSnapshot`, `toBeInstanceOf`,
 *   `toHaveProperty`, `toBeGreaterThan`, `toBeCloseTo`, `toMatch`) — 484
 *   (15.4%), e.g. `cal.com/packages/embeds/embed-core/src/embed.test.ts:389`;
 * - a `.length` assertion mixed into element assertions — 26 (0.8%), e.g.
 *   `cal.com/packages/features/schedules/lib/date-ranges.test.ts:646`.
 *
 * ## The invariant the guard establishes
 *
 * **The rule now reports a property run only where its own fix is exactly
 * equivalent to the code it replaces.** Concretely, every statement in the run
 * must be `expect(<pure receiver>.<identifier>).<M>(<primitive literal>)` with
 * `M` in `toBe` / `toEqual` / `toStrictEqual`, or `expect(...).toBeNull()`. On a
 * primitive literal those three matchers and `toMatchObject`'s per-key
 * comparison all agree, so the rewrite cannot change whether the test passes.
 * The property names must also be distinct — a duplicate key is what silently
 * deleted an assertion above — and must not be `length` or `size`, whose
 * receiver is a collection that `toMatchObject` cannot describe.
 *
 * "Pure receiver" means an identifier, `this`, or a chain of member accesses
 * over one, never a call: `expect(getUser().a).toBe(1); expect(getUser().b).toBe(2)`
 * invokes `getUser` twice and the merged form invokes it once.
 *
 * Deliberately dropped, with the recall cost stated rather than hidden:
 *
 * - a run that mixes one un-mergeable matcher (typically `toBeDefined`) into
 *   otherwise mergeable `toBe`s no longer fires at all — part of 344 sequences.
 *   That is the honest price of the invariant, and those are exactly the runs
 *   whose autofix corrupted the suite;
 * - a non-literal expected value — `expect(c.auth).toBe(auth)` — is dropped
 *   even though it looks mergeable, because merging it is the `toBe`-to-
 *   structural-equality downgrade above. It was never a defect: there is no
 *   `toMatchObject` that says what those two statements say.
 *
 * ## Array-indexed runs get different advice, not silence
 *
 * 581 sequences (18.5%) group through an array — `expect(bodies[0]).toEqual(a);
 * expect(bodies[1]).toEqual(b)`, e.g. `hono/src/router/trie-router/node.test.ts:765`.
 * `toMatchObject` was always the wrong advice there. These keep firing under a
 * separate message: a per-element run asserts nothing about the array's
 * *length*, so `bodies` may hold extra elements and the test still passes, and
 * the fix is `expect(bodies).toEqual([a, b])`. That is a real weak-assertion
 * defect on its own terms, independent of the merge argument, which is why it
 * survives rather than being suppressed. It fires only when the indices are
 * exactly `0..n-1` (otherwise the leading elements are unconstrained and the
 * array literal would be a guess) and every matcher is the same `toEqual` or
 * `toStrictEqual`. It is **not** autofixed: the rewrite adds a length
 * assertion, so it is a deliberate strengthening, not an equivalence, and a
 * strengthening must be a human's decision.
 *
 * Only 34 of those 581 survive the "indices are exactly `0..n-1`, one matcher
 * throughout, statements adjacent" predicate. The rest index from 1, skip an
 * index, or interleave another statement, and for those there is no array
 * literal to suggest — so they are dropped rather than given advice the rule
 * cannot substantiate.
 *
 * ## Known false negatives (limits, not guards)
 *
 * The rule only ever recognised the Jest/Vitest `expect(x).matcher(y)` shape
 * hanging directly off `expect`. It silently ignores chai
 * `expect(x).to.equal(y)`, `assert.equal(...)`, `await expect(...)`
 * (Playwright), `expect.soft(...)` and every `.not.` / `.resolves` / `.rejects`
 * chain — and a `.not.` in the middle of a run breaks the run, suppressing the
 * report for the statements around it. These are recorded as limits; none of
 * them is a false positive.
 *
 * Result over the same 25,508-file corpus: 3,148 findings before, 945 after
 * (911 `combineAssertions`, 34 `assertArrayOnce`) — a 70% cut. That is a large
 * number to give up, and it is the right one: the audit's read sample scored
 * **zero** true positives in 37 findings, so what was removed was not a
 * population of caught defects, it was a population of runs the rule could not
 * describe and whose autofix it could not perform. What is left is the subset
 * where the rule's own recommendation is provably the same test.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "combineAssertions" | "assertArrayOnce";
type Options = readonly [];

/**
 * Matchers whose per-key meaning `toMatchObject` reproduces exactly — but only
 * against a primitive literal, where `Object.is`, deep equality and strict deep
 * equality all coincide. See `literalText` for the other half of that pair.
 */
const MERGEABLE_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);

/**
 * Matchers whose whole-array form (`expect(a).toEqual([...])`) preserves the
 * per-element comparison. `toBe` is excluded: element-wise identity is not what
 * `toEqual` on the array would check.
 */
const ARRAY_MATCHERS: ReadonlySet<string> = new Set(["toEqual", "toStrictEqual"]);

/**
 * Properties whose receiver is a collection rather than a record. A run keyed on
 * `length` or `size` describes an array / Map / Set, and `toMatchObject` cannot
 * state a collection's size — this is the `.length`-mixed-with-elements class.
 */
const COLLECTION_PROPERTIES: ReadonlySet<string> = new Set(["length", "size"]);

/** `-1` parses as a unary expression, not a literal, but it is still constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);

/** A run shorter than this is a single assertion; there is nothing to combine. */
const MIN_RUN_LENGTH = 2;

/** How a run reaches into its receiver: `o.name`, or `xs[0]`. */
type AssertionKey =
  | { readonly kind: "property"; readonly name: string }
  | { readonly kind: "index"; readonly index: number };

interface Assertion {
  readonly statement: TSESTree.ExpressionStatement;
  /** The object the asserted member expression hangs off — the run's grouping key. */
  readonly receiver: TSESTree.Expression;
  readonly key: AssertionKey;
  readonly matcher: string;
  /** Source text of the expected value; `"null"` synthesised for `toBeNull()`. */
  readonly expectedText: string;
  /** False when the expected value is not a primitive literal, so cannot be merged. */
  readonly expectedIsLiteral: boolean;
}

/**
 * Source text of `node` when it is a primitive literal, otherwise `null`.
 * Regular expressions are excluded: `toBe(/x/)` is an identity check that
 * `toEqual` and `toMatchObject` do not reproduce.
 */
function literalText(node: TSESTree.Node, getText: (node: TSESTree.Node) => string): string | null {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return "regex" in node ? null : getText(node);
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0 ? getText(node) : null;
    case AST_NODE_TYPES.UnaryExpression:
      return NUMERIC_SIGNS.has(node.operator) && literalText(node.argument, getText) !== null
        ? getText(node)
        : null;
    default:
      return null;
  }
}

/**
 * True for a receiver that can be evaluated twice with the same effect: an
 * identifier, `this`, or a member chain over one. A call anywhere in the chain
 * makes the merged form invoke it fewer times than the run did.
 */
function isPureReceiver(node: TSESTree.Node): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.Identifier:
    case AST_NODE_TYPES.ThisExpression:
      return true;
    case AST_NODE_TYPES.MemberExpression:
      if (node.optional) {
        return false;
      }
      if (node.computed) {
        return node.property.type === AST_NODE_TYPES.Literal && isPureReceiver(node.object);
      }
      return isPureReceiver(node.object);
    default:
      return false;
  }
}

/** A non-negative integer array index written as a literal, else `null`. */
function literalIndex(node: TSESTree.Node): number | null {
  if (node.type !== AST_NODE_TYPES.Literal || typeof node.value !== "number") {
    return null;
  }
  return Number.isInteger(node.value) && node.value >= 0 ? node.value : null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "strict-test-assertions",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Collapse a run of consecutive assertions on the same object into one assertion about the whole object, so every mismatch is reported and nothing outside the asserted keys goes unchecked.",
    },
    fixable: "code",
    messages: {
      combineAssertions:
        "These {{count}} assertions each check one property of `{{receiver}}` against a literal, so the first mismatch hides the rest. Assert the object once: `expect({{receiver}}).toMatchObject({ … })`.",
      assertArrayOnce:
        "These {{count}} assertions check `{{receiver}}[0]`…`{{receiver}}[{{last}}]` one at a time, which never checks how long `{{receiver}}` is — extra elements pass unnoticed. Assert the array once: `expect({{receiver}}).{{matcher}}([ … ])`.",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const { sourceCode } = context;

    /**
     * The statement as a mergeable assertion, or `null` when it is anything
     * else — which also terminates whatever run was in progress. Everything the
     * audit found in the false-positive classes fails here: a spy matcher, a
     * `toBeDefined`, a `.not.` chain, `await expect(...)`, `expect.soft(...)`,
     * chai's `.to.equal`, or an expected value that is not a literal.
     */
    function parseAssertion(statement: TSESTree.Statement): Assertion | null {
      if (statement.type !== AST_NODE_TYPES.ExpressionStatement) {
        return null;
      }
      const call = statement.expression;
      if (call.type !== AST_NODE_TYPES.CallExpression) {
        return null;
      }
      const callee = call.callee;
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.computed ||
        callee.property.type !== AST_NODE_TYPES.Identifier
      ) {
        return null;
      }
      const matcher = callee.property.name;
      const expectCall = callee.object;
      if (
        expectCall.type !== AST_NODE_TYPES.CallExpression ||
        expectCall.callee.type !== AST_NODE_TYPES.Identifier ||
        expectCall.callee.name !== "expect" ||
        expectCall.arguments.length !== 1
      ) {
        return null;
      }
      const actual = expectCall.arguments[0];
      if (actual === undefined || actual.type !== AST_NODE_TYPES.MemberExpression || actual.optional) {
        return null;
      }
      if (!isPureReceiver(actual.object)) {
        return null;
      }

      let key: AssertionKey;
      if (actual.computed) {
        const index = literalIndex(actual.property);
        if (index === null) {
          return null;
        }
        key = { kind: "index", index };
      } else {
        if (actual.property.type !== AST_NODE_TYPES.Identifier || COLLECTION_PROPERTIES.has(actual.property.name)) {
          return null;
        }
        key = { kind: "property", name: actual.property.name };
      }

      if (matcher === "toBeNull" && call.arguments.length === 0) {
        return { statement, receiver: actual.object, key, matcher, expectedText: "null", expectedIsLiteral: true };
      }
      if (!MERGEABLE_MATCHERS.has(matcher)) {
        return null;
      }
      const expected = call.arguments[0];
      if (call.arguments.length !== 1 || expected === undefined || expected.type === AST_NODE_TYPES.SpreadElement) {
        return null;
      }
      const literal = literalText(expected, (node) => sourceCode.getText(node));
      return {
        statement,
        receiver: actual.object,
        key,
        matcher,
        expectedText: literal ?? sourceCode.getText(expected),
        expectedIsLiteral: literal !== null,
      };
    }

    /**
     * A property run is reportable only when the merged `toMatchObject` says
     * exactly what the run says: every matcher mergeable, every expected value a
     * primitive literal, and every key distinct so nothing is lost to a
     * duplicate object property.
     */
    function reportPropertyRun(run: readonly Assertion[]): void {
      const names = new Set<string>();
      for (const assertion of run) {
        if (assertion.key.kind !== "property" || !assertion.expectedIsLiteral) {
          return;
        }
        if (!MERGEABLE_MATCHERS.has(assertion.matcher) && assertion.matcher !== "toBeNull") {
          return;
        }
        if (names.has(assertion.key.name)) {
          return;
        }
        names.add(assertion.key.name);
      }
      const first = run[0];
      if (first === undefined) {
        return;
      }
      const receiverText = sourceCode.getText(first.receiver);
      const properties = run
        .map((assertion) =>
          assertion.key.kind === "property" ? `${assertion.key.name}: ${assertion.expectedText}` : "",
        )
        .join(", ");
      context.report({
        node: first.statement,
        messageId: "combineAssertions",
        data: { count: String(run.length), receiver: receiverText },
        fix: (fixer) => [
          fixer.replaceText(first.statement, `expect(${receiverText}).toMatchObject({ ${properties} });`),
          ...run.slice(1).map((assertion) => fixer.remove(assertion.statement)),
        ],
      });
    }

    /**
     * An indexed run is reportable when the indices cover `0..n-1` exactly and
     * one `toEqual` / `toStrictEqual` runs throughout, so `expect(xs).toEqual([…])`
     * makes the same per-element comparisons plus the length check the run is
     * missing. No fix: that added length check can turn a passing test red.
     */
    function reportIndexRun(run: readonly Assertion[]): void {
      const first = run[0];
      if (first === undefined || !ARRAY_MATCHERS.has(first.matcher)) {
        return;
      }
      const indices = new Set<number>();
      for (const assertion of run) {
        if (assertion.key.kind !== "index" || assertion.matcher !== first.matcher) {
          return;
        }
        indices.add(assertion.key.index);
      }
      if (indices.size !== run.length || Math.max(...indices) !== run.length - 1) {
        return;
      }
      context.report({
        node: first.statement,
        messageId: "assertArrayOnce",
        data: {
          count: String(run.length),
          receiver: sourceCode.getText(first.receiver),
          last: String(run.length - 1),
          matcher: first.matcher,
        },
      });
    }

    function checkBody(body: readonly TSESTree.Statement[]): void {
      let run: Assertion[] = [];

      const flush = (): void => {
        const first = run[0];
        if (first !== undefined && run.length >= MIN_RUN_LENGTH) {
          if (first.key.kind === "property") {
            reportPropertyRun(run);
          } else {
            reportIndexRun(run);
          }
        }
        run = [];
      };

      for (const statement of body) {
        const assertion = parseAssertion(statement);
        const previous = run.at(-1);
        if (
          assertion !== null &&
          previous !== undefined &&
          previous.key.kind === assertion.key.kind &&
          sourceCode.getText(previous.receiver) === sourceCode.getText(assertion.receiver)
        ) {
          run.push(assertion);
          continue;
        }
        flush();
        if (assertion !== null) {
          run = [assertion];
        }
      }
      flush();
    }

    return {
      BlockStatement: (node: TSESTree.BlockStatement): void => {
        checkBody(node.body);
      },
      Program: (node: TSESTree.Program): void => {
        checkBody(node.body);
      },
    };
  },
});
