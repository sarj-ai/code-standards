/**
 * @fileoverview prefer-whole-object-assertion — a run of `expect`s on one receiver fails on the first mismatch and says nothing about the rest of the value.
 *
 * Port of the 18.x `prefer-whole-object-assertion` rule. Same algorithm;
 * the test-file and generated-file gates run in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { acceptedTestFrameworkName, EXPECT_ASSERTION, type Identifier } from "../utils/test-mock-provenance.js";

const NAME = "prefer-whole-object-assertion";

const MERGEABLE_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);
const SYNTHETIC_LITERAL_MATCHERS: ReadonlyMap<string, string> = new Map([
  ["toBeNull", "null"],
]);

const ARRAY_MATCHERS: ReadonlySet<string> = new Set(["toEqual", "toStrictEqual"]);

const COLLECTION_PROPERTIES: ReadonlySet<string> = new Set(["length", "size"]);

const LITERAL_KEY_HAZARDS: ReadonlySet<string> = new Set(["__proto__"]);

/** `-1` parses as a unary expression, not a literal, but it is still constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);

/** A run shorter than this is a single assertion; there is nothing to combine. */
const MIN_RUN_LENGTH = 2;

/** How a run reaches into its receiver: `o.name`, or `xs[0]`. */
type AssertionKey =
  | { readonly kind: "property"; readonly path: readonly string[] }
  | { readonly kind: "index"; readonly index: number };

interface Assertion {
  readonly statement: ESTree.ExpressionStatement;
  /** The object the asserted member expression hangs off — the run's grouping key. */
  readonly receiver: ESTree.Expression;
  readonly key: AssertionKey;
  readonly matcher: string;
  /** Source text of the expected value, including nullary matcher literals. */
  readonly expectedText: string;
  /** False when the expected value is not a primitive literal, so cannot be merged. */
  readonly expectedIsLiteral: boolean;
}

function literalText(node: Node, getText: (node: Node) => string): string | null {
  node = unwrapExpression(node);
  switch (node.type) {
    case "Literal":
      return "regex" in node ? null : getText(node);
    case "TemplateLiteral":
      return node.expressions.length === 0 ? getText(node) : null;
    case "UnaryExpression":
      return NUMERIC_SIGNS.has(node.operator) && literalText(node.argument, getText) !== null
        ? getText(node)
        : null;
    default:
      return null;
  }
}

function isPureReceiver(node: Node): boolean {
  node = unwrapExpression(node);
  switch (node.type) {
    case "Identifier":
    case "ThisExpression":
      return true;
    case "MemberExpression":
      if (node.optional) {
        return false;
      }
      if (node.computed) {
        return node.property.type === "Literal" && isPureReceiver(node.object);
      }
      return isPureReceiver(node.object);
    default:
      return false;
  }
}

/** A non-negative integer array index written as a literal, else `null`. */
function literalIndex(node: Node): number | null {
  if (node.type !== "Literal" || typeof node.value !== "number") {
    return null;
  }
  return Number.isInteger(node.value) && node.value >= 0 ? node.value : null;
}

function propertyAccess(
  node: ESTree.MemberExpression,
): { readonly receiver: ESTree.Expression; readonly path: readonly string[] } | null {
  const path: string[] = [];
  let current: ESTree.Expression = node;
  while (current.type === "MemberExpression" && !current.optional) {
    const name = getPropertyName(current);
    if (
      name === null || COLLECTION_PROPERTIES.has(name) || LITERAL_KEY_HAZARDS.has(name)
    ) return null;
    path.unshift(name);
    current = unwrapExpression(current.object) as ESTree.Expression;
  }
  return path.length > 0 && isPureReceiver(current) ? { receiver: current, path } : null;
}

/** `expect(actual).matcher(...)` as a statement, before checking where `expect` comes from. */
interface ExpectStatement {
  readonly statement: ESTree.ExpressionStatement;
  readonly call: ESTree.CallExpression;
  readonly matcher: string;
  readonly expect: Identifier;
  /** The single `expect` argument, unwrapped. */
  readonly actual: Node;
}

function expectStatement(statement: ESTree.Statement | undefined): ExpectStatement | null {
  if (statement?.type !== "ExpressionStatement" || statement.expression.type !== "CallExpression") return null;
  const call = statement.expression;
  const callee = unwrapExpression(call.callee);
  if (callee.type !== "MemberExpression") return null;
  const matcher = getPropertyName(callee);
  const expectCall = unwrapExpression(callee.object);
  if (matcher === null || expectCall.type !== "CallExpression" || expectCall.arguments.length !== 1) return null;
  const expect = unwrapExpression(expectCall.callee);
  if (expect.type !== "Identifier") return null;
  return { statement, call, matcher, expect, actual: unwrapExpression(expectCall.arguments[0] as Node) };
}

/** The leading path segments all `paths` share, stopping before any path's last segment. */
/** `receiver` in `expect(receiver.length).toBe(n)` and the other mergeable matchers. */
function lengthReceiver(actual: Node, matcher: string): Node | null {
  if (!MERGEABLE_MATCHERS.has(matcher) || actual.type !== "MemberExpression" || actual.optional ||
    getPropertyName(actual) !== "length") return null;
  return unwrapExpression(actual.object);
}

function commonPathPrefix(paths: readonly (readonly string[])[]): string[] {
  const prefix: string[] = [];
  for (let index = 0; ; index += 1) {
    const candidate = paths[0]?.[index];
    if (candidate === undefined || paths.some((path) => path[index] !== candidate || path.length === index + 1)) return prefix;
    prefix.push(candidate);
  }
}

/** Whether one path repeats another or runs through it, so the two cannot share one object literal. */
function hasOverlappingPaths(paths: readonly (readonly string[])[]): boolean {
  return paths.some((shorter, i) => paths.some((longer, j) =>
    i !== j && shorter.length <= longer.length && shorter.every((name, index) => longer[index] === name)));
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Collapse consecutive assertions on one object into a whole-object assertion so related mismatches are reported together.",
      url: docsUrl(NAME),
    },
    messages: {
      combineAssertions:
        "Consider combining these {{count}} assertions on `{{receiver}}` with `toMatchObject` when structural matching preserves property presence and getter or proxy behavior.",
      assertArrayOnce:
        "These {{count}} assertions check `{{receiver}}[0]`…`{{receiver}}[{{last}}]` separately. If the contract requires the complete array, consider `expect({{receiver}}).{{matcher}}([ … ])`, which also checks for extra elements. Preserve intentional prefix checks and separate length assertions.",
    },
    schema: [],
  },
  createOnce(context) {
    let sourceCode: SourceCode;


    /** Distinct literal expectations are candidates, not proof of equivalent runtime reads. */
    function reportPropertyRun(run: readonly Assertion[]): void {
      const paths: (readonly string[])[] = [];
      for (const assertion of run) {
        if (assertion.key.kind !== "property" || !assertion.expectedIsLiteral) return;
        if (!MERGEABLE_MATCHERS.has(assertion.matcher) && !SYNTHETIC_LITERAL_MATCHERS.has(assertion.matcher)) return;
        paths.push(assertion.key.path);
      }
      const first = run[0];
      if (first === undefined || hasOverlappingPaths(paths)) return;
      const commonPrefix = commonPathPrefix(paths);
      const receiverText = `${sourceCode.getText(first.receiver)}${commonPrefix.map((name) => /^[A-Za-z_$][\w$]*$/u.test(name) ? `.${name}` : `[${JSON.stringify(name)}]`).join("")}`;
      context.report({
        node: first.statement,
        messageId: "combineAssertions",
        data: { count: String(run.length), receiver: receiverText },
      });
    }

    function reportIndexRun(run: readonly Assertion[], before: ESTree.Statement | undefined, after: ESTree.Statement | undefined): void {
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
      if (isExactLengthAssertion(before, first.receiver) || isExactLengthAssertion(after, first.receiver)) return;
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

    function checkBody(body: readonly ESTree.Statement[]): void {
      let run: Assertion[] = [];
      let start = 0;

      const flush = (): void => {
        const first = run[0];
        if (first !== undefined && run.length >= MIN_RUN_LENGTH) {
          if (first.key.kind === "property") {
            reportPropertyRun(run);
          } else {
            reportIndexRun(run, body[start - 1], body[start + run.length]);
          }
        }
        run = [];
      };

      for (const [index, statement] of body.entries()) {
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
          start = index;
        }
      }
      flush();
    }

    function parseAssertion(statement: ESTree.Statement): Assertion | null {
      const expectation = expectStatement(statement);
      if (expectation === null || expectation.expect.name !== "expect" || !isTestExpect(expectation.expect)) return null;
      const { statement: expression, call, matcher, actual } = expectation;
      if (actual.type !== "MemberExpression" || actual.optional || !isPureReceiver(actual.object)) return null;
      const index = actual.computed ? literalIndex(actual.property) : null;
      if (index !== null) return assertionExpectation(expression, call, actual.object, { kind: "index", index }, matcher);
      const access = propertyAccess(actual);
      if (access === null) return null;
      return assertionExpectation(expression, call, access.receiver, { kind: "property", path: access.path }, matcher);
    }

    function isTestExpect(callee: Identifier): boolean {
      return acceptedTestFrameworkName(sourceCode, callee, "assertion", EXPECT_ASSERTION) !== null;
    }

    /** `expect(receiver).toHaveLength(n)` or `expect(receiver.length).toBe(n)` for a literal non-negative integer `n`. */
    function isExactLengthAssertion(statement: ESTree.Statement | undefined, receiver: ESTree.Expression): boolean {
      const expectation = expectStatement(statement);
      if (expectation === null || expectation.call.arguments.length !== 1 || !isTestExpect(expectation.expect)) return false;
      const { call, matcher, actual } = expectation;
      const expected = unwrapExpression(call.arguments[0] as Node);
      if (expected.type !== "Literal" || typeof expected.value !== "number" || !Number.isInteger(expected.value) || expected.value < 0) return false;
      const measured = matcher === "toHaveLength" ? actual : lengthReceiver(actual, matcher);
      return measured !== null && sourceCode.getText(measured) === sourceCode.getText(receiver);
    }

    function assertionExpectation(statement: ESTree.ExpressionStatement, call: ESTree.CallExpression, receiver: ESTree.Expression | ESTree.Super, key: Assertion["key"], matcher: string): Assertion | null {
      const synthetic = SYNTHETIC_LITERAL_MATCHERS.get(matcher);
      if (synthetic !== undefined && call.arguments.length === 0) {
        return { statement, receiver, key, matcher, expectedText: synthetic, expectedIsLiteral: true };
      }
      if (!MERGEABLE_MATCHERS.has(matcher)) {
        return null;
      }
      const expected = call.arguments[0];
      if (call.arguments.length !== 1 || expected === undefined || expected.type === "SpreadElement") {
        return null;
      }
      const literal = literalText(expected, (node) => sourceCode.getText(node));
      return {
        statement,
        receiver,
        key,
        matcher,
        expectedText: literal ?? sourceCode.getText(expected),
        expectedIsLiteral: literal !== null,
      };
    }

    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, sourceCode.text)) {
          return false;
        }
      },
      BlockStatement: (node: ESTree.BlockStatement): void => {
        checkBody(node.body);
      },
      Program: (node: ESTree.Program): void => {
        checkBody(node.body);
      },
    };
  },
});
