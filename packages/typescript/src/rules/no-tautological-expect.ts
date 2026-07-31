/**
 * @fileoverview TS side of SARJ057 (`no-tautological-expect`). An `expect(...)`
 * whose operands are all literals has already decided its outcome before the
 * test runs: `expect(true).toBe(true)` passes if you delete the entire module
 * under test. It is not a weak assertion, it is a *non*-assertion.
 *
 * This is the placeholder that never got replaced. Every hit found in the
 * first-party sweep is one:
 *
 * - a worker's handler test — `expect(true).toBe(true); // placeholder`, in a
 *   suite whose name promises it disambiguates customer records,
 * - a `dummy.test.ts` in a shared node package — `expect(true).toBe(true)`,
 * - a `dummy.test.ts` in its isomorphic sibling package — `expect(1).toEqual(1)`.
 *
 * The Python side (SARJ043 `zero-assertion-test`) has caught the assertion-free
 * version of this since 0.15.0 and has no TypeScript counterpart, which is
 * precisely why that first placeholder went uncaught for as long as it
 * did: the file *has* an assertion, so nothing was looking at it.
 *
 * Fires on exactly two shapes:
 *
 * 1. `expect(<literal>).toBe|toEqual|toStrictEqual(<textually identical literal>)`;
 * 2. `expect(<literal>).<zero-argument matcher>()` — `toBeDefined`,
 *    `toBeTruthy`, `toBeNull`, `toBeUndefined`, `toBeFalsy`, `toBeNaN`. With a
 *    literal receiver the answer is fixed at parse time either way.
 *
 * **The narrowness is the rule.** The obvious generalisation — "flag a
 * comparison of a thing with itself" — was measured across five repositories
 * and is ~95% false positives. `expect(hash([o])).toEqual(hash([o]))` is a
 * *determinism* test; `expect(memo(x)).toBe(memo(x))` is a *memoization* test;
 * `expect(a).toEqual(a)` on a value with a custom equality is a *reflexivity*
 * test. All three can genuinely fail, and all three are correct code. So an
 * operand that is an identifier, a member expression or a call is never enough:
 * both sides must be literals, and textually identical ones.
 *
 * Deliberately NOT flagged:
 *
 * - any modified chain — `expect(x).not.toBe(...)`, `.resolves`, `.rejects`.
 *   The matcher must hang directly off the `expect(...)` call, which keeps the
 *   rule to the shape it can reason about;
 * - a literal compared with a *different* literal (`expect(1).toBe(2)`) — that
 *   assertion always fails, which is loud on the first run rather than silent;
 * - a spread element anywhere in an array/object literal (`expect([...xs])`),
 *   whose contents come from a runtime value;
 * - a template literal with interpolations, for the same reason;
 * - anything outside a test file.
 *
 * Measured before shipping: 3 hits across 5,819 `.ts`/`.tsx` files (1,003 of
 * them test files, where the rule is active) — six first-party repos plus
 * got / hono / swr / trpc. 3 true positives,
 * 0 false positives; all three are the placeholders listed above.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "tautologicalComparison" | "tautologicalMatcher";
type Options = readonly [];

/** Matchers that take the expected value as their single argument. */
const EQUALITY_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);

/** Matchers that take no argument, so the receiver alone fixes the outcome. */
const ZERO_ARG_MATCHERS: ReadonlySet<string> = new Set([
  "toBeDefined",
  "toBeUndefined",
  "toBeNull",
  "toBeTruthy",
  "toBeFalsy",
  "toBeNaN",
]);

/** Enough of the operand to identify it in the message without pasting a screenful. */
const OPERAND_PREVIEW_CHARS = 40;

/** Sign prefixes: `-1` is a unary expression, not a literal, but it is constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);

/**
 * True when `node` is written entirely out of literals — no identifier, member
 * expression, call or spread anywhere inside it. That exclusion is the whole
 * false-positive guard: a value the code produced is what makes an assertion an
 * assertion.
 */
function isLiteral(node: TSESTree.Node): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return true;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0;
    case AST_NODE_TYPES.UnaryExpression:
      return NUMERIC_SIGNS.has(node.operator) && isLiteral(node.argument);
    case AST_NODE_TYPES.ArrayExpression:
      return node.elements.every((element) => element !== null && isLiteral(element));
    case AST_NODE_TYPES.ObjectExpression:
      return node.properties.every(
        (property) =>
          property.type === AST_NODE_TYPES.Property &&
          !property.computed &&
          isLiteral(property.value),
      );
    default:
      return false;
  }
}

/** The `expect(<single argument>)` call a matcher hangs directly off, if any. */
function expectOperand(callee: TSESTree.MemberExpression): TSESTree.Node | null {
  const receiver = callee.object;
  if (
    receiver.type !== AST_NODE_TYPES.CallExpression ||
    receiver.callee.type !== AST_NODE_TYPES.Identifier ||
    receiver.callee.name !== "expect" ||
    receiver.arguments.length !== 1
  ) {
    return null;
  }
  return receiver.arguments[0] ?? null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-tautological-expect",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow an assertion whose operands are all literals; its outcome is fixed before the code runs, so it can never fail.",
    },
    schema: [],
    messages: {
      tautologicalComparison:
        "`expect({{operand}}).{{matcher}}({{operand}})` compares a literal with an identical literal — it passes even if the code under test is deleted. Assert on a value the code produced, or delete the test.",
      tautologicalMatcher:
        "`expect({{operand}}).{{matcher}}()` asserts on a literal, so its outcome is fixed before the code runs. Assert on a value the code produced, or delete the test.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    /** The operand as written, collapsed to one line and elided for the message. */
    const preview = (node: TSESTree.Node): string => {
      const text = context.sourceCode.getText(node).replaceAll(/\s+/gu, " ");
      return text.length > OPERAND_PREVIEW_CHARS
        ? `${text.slice(0, OPERAND_PREVIEW_CHARS)}…`
        : text;
    };
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const callee = node.callee;
        if (callee.type !== AST_NODE_TYPES.MemberExpression || callee.computed) {
          return;
        }
        if (callee.property.type !== AST_NODE_TYPES.Identifier) {
          return;
        }
        const matcher = callee.property.name;
        const operand = expectOperand(callee);
        if (operand === null || !isLiteral(operand)) {
          return;
        }
        if (ZERO_ARG_MATCHERS.has(matcher) && node.arguments.length === 0) {
          context.report({
            node,
            messageId: "tautologicalMatcher",
            data: { operand: preview(operand), matcher },
          });
          return;
        }
        const expected = node.arguments[0];
        if (
          !EQUALITY_MATCHERS.has(matcher) ||
          node.arguments.length !== 1 ||
          expected === undefined ||
          !isLiteral(expected)
        ) {
          return;
        }
        // Textual identity, not structural: `expect(1).toBe(1.0)` is a
        // deliberate statement about representation and is left alone.
        if (context.sourceCode.getText(operand) !== context.sourceCode.getText(expected)) {
          return;
        }
        context.report({
          node,
          messageId: "tautologicalComparison",
          data: { operand: preview(operand), matcher },
        });
      },
    };
  },
});
