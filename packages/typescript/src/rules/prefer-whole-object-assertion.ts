/**
 * @fileoverview prefer-whole-object-assertion — a run of `expect`s on one receiver fails on the first mismatch and says nothing about the rest of the value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-whole-object-assertion.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "combineAssertions" | "assertArrayOnce";
type Options = readonly [];

const MERGEABLE_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);
const SYNTHETIC_LITERAL_MATCHERS: ReadonlyMap<string, string> = new Map([
  ["toBeNull", "null"],
  ["toBeUndefined", "undefined"],
]);

const ARRAY_MATCHERS: ReadonlySet<string> = new Set(["toEqual", "toStrictEqual"]);

const COLLECTION_PROPERTIES: ReadonlySet<string> = new Set(["length", "size"]);

const LITERAL_KEY_HAZARDS: ReadonlySet<string> = new Set(["__proto__"]);

/** `-1` parses as a unary expression, not a literal, but it is still constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);

/** A run shorter than this is a single assertion; there is nothing to combine. */
const MIN_RUN_LENGTH = 2;

export const PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION = {
  summary: "Collapse consecutive assertions on one object into a whole-object assertion so related mismatches are reported together.",
  rationale: "One whole-object assertion presents related expectations together and produces a complete structural diff.",
  remediation: "Replace consecutive member assertions with one `toMatchObject` assertion.",
  category: "testing",
  aliases: ["strict-test-assertions"],
  autofix: "safe",
  examples: [
    { id: "whole-object", title: "Assert the object once", outcome: "no-match", files: [{ path: "src/user.test.ts", source: "expect(user).toMatchObject({ id: 1, name: 'Ada' });" }], focusPath: "src/user.test.ts", expectedCount: 0, public: true },
    { id: "member-run", title: "Do not split one object across assertions", outcome: "match", files: [{ path: "src/user.test.ts", source: "expect(user.id).toBe(1);\nexpect(user.name).toBe('Ada');" }], focusPath: "src/user.test.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/user.test.ts", source: "expect(user).toMatchObject({ id: 1, name: 'Ada' });\n" }] },
  ],
} as const satisfies RuleDocumentation;

/** How a run reaches into its receiver: `o.name`, or `xs[0]`. */
type AssertionKey =
  | { readonly kind: "property"; readonly path: readonly string[] }
  | { readonly kind: "index"; readonly index: number };

interface Assertion {
  readonly statement: TSESTree.ExpressionStatement;
  /** The object the asserted member expression hangs off — the run's grouping key. */
  readonly receiver: TSESTree.Expression;
  readonly key: AssertionKey;
  readonly matcher: string;
  /** Source text of the expected value, including nullary matcher literals. */
  readonly expectedText: string;
  /** False when the expected value is not a primitive literal, so cannot be merged. */
  readonly expectedIsLiteral: boolean;
}

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

function propertyAccess(
  node: TSESTree.MemberExpression,
): { readonly receiver: TSESTree.Expression; readonly path: readonly string[] } | null {
  const path: string[] = [];
  let current: TSESTree.Expression = node;
  while (current.type === AST_NODE_TYPES.MemberExpression && !current.computed && !current.optional) {
    if (
      current.property.type !== AST_NODE_TYPES.Identifier ||
      COLLECTION_PROPERTIES.has(current.property.name) ||
      LITERAL_KEY_HAZARDS.has(current.property.name)
    ) return null;
    path.unshift(current.property.name);
    current = current.object;
  }
  return path.length > 0 && isPureReceiver(current) ? { receiver: current, path } : null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-whole-object-assertion",
  documentation: PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Collapse consecutive assertions on one object into a whole-object assertion so related mismatches are reported together.",
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
      let receiver: TSESTree.Expression;
      if (actual.computed) {
        const index = literalIndex(actual.property);
        if (index === null) {
          return null;
        }
        key = { kind: "index", index };
        receiver = actual.object;
      } else {
        const access = propertyAccess(actual);
        if (access === null) return null;
        key = { kind: "property", path: access.path };
        receiver = access.receiver;
      }

      const synthetic = SYNTHETIC_LITERAL_MATCHERS.get(matcher);
      if (synthetic !== undefined && call.arguments.length === 0) {
        return { statement, receiver, key, matcher, expectedText: synthetic, expectedIsLiteral: true };
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
        receiver,
        key,
        matcher,
        expectedText: literal ?? sourceCode.getText(expected),
        expectedIsLiteral: literal !== null,
      };
    }

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
      type ObjectTree = Map<string, string | ObjectTree>;
      const tree: ObjectTree = new Map();
      const paths: string[][] = [];
      for (const assertion of run) {
        if (assertion.key.kind !== "property" || !assertion.expectedIsLiteral) {
          return;
        }
        if (!MERGEABLE_MATCHERS.has(assertion.matcher) && !SYNTHETIC_LITERAL_MATCHERS.has(assertion.matcher)) {
          return;
        }
        paths.push([...assertion.key.path]);
      }
      const commonPrefix: string[] = [];
      for (let index = 0; ; index += 1) {
        const candidate = paths[0]?.[index];
        if (candidate === undefined || paths.some((path) => path[index] !== candidate || path.length === index + 1)) {
          break;
        }
        commonPrefix.push(candidate);
      }
      for (const [assertionIndex, assertion] of run.entries()) {
        if (assertion.key.kind !== "property") return;
        let branch = tree;
        const relativePath = paths[assertionIndex]?.slice(commonPrefix.length) ?? [];
        for (const [index, name] of relativePath.entries()) {
          const leaf = index === relativePath.length - 1;
          const existing = branch.get(name);
          if (leaf) {
            if (existing !== undefined) return;
            branch.set(name, assertion.expectedText);
          } else if (existing === undefined) {
            const nested: ObjectTree = new Map();
            branch.set(name, nested);
            branch = nested;
          } else if (existing instanceof Map) {
            branch = existing;
          } else {
            return;
          }
        }
      }
      const first = run[0];
      if (first === undefined) {
        return;
      }
      const receiverText = `${sourceCode.getText(first.receiver)}${commonPrefix.map((name) => `.${name}`).join("")}`;
      const renderTree = (value: ObjectTree): string => [...value.entries()]
        .map(([name, child]) => `${name}: ${child instanceof Map ? `{ ${renderTree(child)} }` : child}`)
        .join(", ");
      const properties = renderTree(tree);
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
