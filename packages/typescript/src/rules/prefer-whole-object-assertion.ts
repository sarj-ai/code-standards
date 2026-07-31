/**
 * @fileoverview prefer-whole-object-assertion — a run of `expect`s on one receiver fails on the first mismatch and says nothing about the rest of the value.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-whole-object-assertion.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/prefer-whole-object-assertion.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
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

/**
 * Property names whose meaning as an OBJECT-LITERAL KEY is not "a property of
 * this name". There is exactly one in JavaScript.
 *
 * `__proto__: v` in a literal is the prototype SETTER, so the key never exists
 * and `toMatchObject` never checks it — the fix would DELETE the assertion it
 * claims to be merging. Quoting does not help: `"__proto__": v` is the same
 * production. The whole run is dropped rather than the one key, because there
 * is no `toMatchObject` literal that says what the run says.
 *
 * Audited for siblings: `constructor`, `toString`, `valueOf` and every other
 * inherited name ARE plain own keys in a literal, and jest's `subsetEquality`
 * walks the prototype chain when reading them off the received value, so those
 * merge faithfully. `get x() {}` / `async x() {}` are different PRODUCTIONS,
 * not different key names, and this fixer only ever emits `key: value`.
 */
const LITERAL_KEY_HAZARDS: ReadonlySet<string> = new Set(["__proto__"]);

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

export default createRule<Options, MessageIds>({
  name: "prefer-whole-object-assertion",
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
        if (
          actual.property.type !== AST_NODE_TYPES.Identifier ||
          COLLECTION_PROPERTIES.has(actual.property.name) ||
          LITERAL_KEY_HAZARDS.has(actual.property.name)
        ) {
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
     * True when a comment sits inside the span the fix rewrites — between two
     * statements of the run, or inside one of them.
     *
     * Such a comment cannot survive: the statements after the first are DELETED,
     * so their leading comments are left dangling above the merged assertion,
     * describing a statement that no longer exists. Worst case the dangling line
     * is an `eslint-disable-next-line`, which then becomes a fresh unused-directive
     * error the author did not write. Dropping a comment is also not "exactly
     * equivalent to the code it replaces", so the report stands and the fix is
     * withheld for a human.
     */
    function hasInterveningComment(run: readonly Assertion[]): boolean {
      return run.some(
        (assertion, index) =>
          sourceCode.getCommentsInside(assertion.statement).length > 0 ||
          (index > 0 && sourceCode.getCommentsBefore(assertion.statement).length > 0),
      );
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
        fix: hasInterveningComment(run)
          ? null
          : (fixer) => [
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
