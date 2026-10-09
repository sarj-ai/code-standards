/**
 * @fileoverview prefer-whole-object-assertion — a run of `expect`s on one receiver fails on the first mismatch and says nothing about the rest of the value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-whole-object-assertion.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "combineAssertions" | "assertArrayOnce";
type Options = readonly [];

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

export const PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Collapse consecutive assertions on one object into a whole-object assertion so related mismatches are reported together.",
  rationale: "One whole-object assertion presents related expectations together and produces a complete structural diff.",
  remediation: "Consider one `toMatchObject` assertion for ordinary data objects. Preserve missing-property checks, identity, and getter or proxy behavior when deciding whether to combine assertions.",
  category: "testing",
  aliases: ["strict-test-assertions"],
  autofix: "none",
  limitations: ["Undefined-property assertions are excluded because whole-object matching can require previously absent properties. No automatic rewrite: grouping can change observable getter or proxy reads."],
  examples: [
    { id: "whole-object", title: "Assert the object once", outcome: "no-match", files: [{ path: "src/user.test.ts", source: "expect(user).toMatchObject({ id: 1, name: 'Ada' });" }], focusPath: "src/user.test.ts", expectedCount: 0, public: true },
    { id: "member-run", title: "Consider grouping related data properties", outcome: "match", files: [{ path: "src/user.test.ts", source: "expect(user.id).toBe(1);\nexpect(user.name).toBe('Ada');" }], focusPath: "src/user.test.ts", expectedCount: 1, public: true },
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
  node = unwrapExpression(node);
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
      node = unwrapExpression(node);
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
  while (current.type === AST_NODE_TYPES.MemberExpression && !current.optional) {
    const name = ASTUtils.getPropertyName(current);
    if (
      name === null || COLLECTION_PROPERTIES.has(name) || LITERAL_KEY_HAZARDS.has(name)
    ) return null;
    path.unshift(name);
    current = unwrapExpression(current.object);
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
    messages: {
      combineAssertions:
        "Consider combining these {{count}} assertions on `{{receiver}}` with `toMatchObject` when structural matching preserves property presence and getter or proxy behavior.",
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

    /** Distinct literal expectations are candidates, not proof of equivalent runtime reads. */
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
      for (let index = 0;;index += 1) {
        const candidate = paths[0]?.[index];
        if (candidate === undefined || paths.some((path) => path[index] !== candidate || path.length === index + 1)) {
          break;
        }
        commonPrefix.push(candidate);
      }
      if (!populateAssertionTree()) return;
      function populateAssertionTree(): boolean {
        for (const [assertionIndex, assertion] of run.entries()) {
          if (assertion.key.kind !== "property") return false;
          let branch = tree;
          const relativePath = paths[assertionIndex]?.slice(commonPrefix.length) ?? [];
          for (const [index, name] of relativePath.entries()) {
            const leaf = index === relativePath.length - 1;
            const existing = branch.get(name);
            if (leaf) {
              if (existing !== undefined) return false;
              branch.set(name, assertion.expectedText);
            } else if (existing === undefined) {
              const nested: ObjectTree = new Map();
              branch.set(name, nested);
              branch = nested;
            } else if (existing instanceof Map) {
              branch = existing;
            } else {
              return false;
            }
          }
        }
        return true;
      }

      const first = run[0];
      if (first === undefined) {
        return;
      }
      const receiverText = `${sourceCode.getText(first.receiver)}${commonPrefix.map((name) => /^[A-Za-z_$][\w$]*$/u.test(name) ? `.${name}` : `[${JSON.stringify(name)}]`).join("")}`;
      context.report({
        node: first.statement,
        messageId: "combineAssertions",
        data: { count: String(run.length), receiver: receiverText },
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

    function parseAssertion(statement: TSESTree.Statement): Assertion | null {
      if (statement.type !== AST_NODE_TYPES.ExpressionStatement) {
        return null;
      }
      const call = statement.expression;
      if (call.type !== AST_NODE_TYPES.CallExpression) {
        return null;
      }
      const callee = unwrapExpression(call.callee);
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return null;
      const matcher = ASTUtils.getPropertyName(callee);
      if (matcher === null) return null;
      const expectCall = calleeReceiver;
      const expectCallee = expectCall.type === AST_NODE_TYPES.CallExpression ? unwrapExpression(expectCall.callee) : null;
      if (
        expectCall.type !== AST_NODE_TYPES.CallExpression ||
        expectCallee?.type !== AST_NODE_TYPES.Identifier ||
        expectCallee.name !== "expect" ||
        expectCall.arguments.length !== 1
      ) {
        return null;
      }
      const actual = expectCall.arguments[0] === undefined ? undefined : unwrapExpression(expectCall.arguments[0]);
      if (!isTestExpect(expectCallee)) return null;
      if (actual === undefined || actual.type !== AST_NODE_TYPES.MemberExpression || actual.optional) {
        return null;
      }
      if (!isPureReceiver(actual.object)) {
        return null;
      }

      let key: AssertionKey;
      let receiver: TSESTree.Expression;
      const index = actual.computed ? literalIndex(actual.property) : null;
      if (index !== null) {
        key = { kind: "index", index };
        receiver = actual.object;
      } else {
        const access = propertyAccess(actual);
        if (access === null) return null;
        key = { kind: "property", path: access.path };
        receiver = access.receiver;
      }

      return assertionExpectation(statement, call, receiver, key, matcher);
    }

    function isTestExpect(callee: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(sourceCode.getScope(callee), callee.name);
      if (variable !== null && variable.defs.some((definition) => {
        if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) return true;
        const declaration = definition.node.parent;
        const imported = definition.node.imported;
        return declaration.type !== AST_NODE_TYPES.ImportDeclaration ||
          !["vitest", "@jest/globals", "@playwright/test", "bun:test"].includes(String(declaration.source.value)) ||
          (imported.type === AST_NODE_TYPES.Identifier ? imported.name : imported.value) !== "expect";
      })) return false;
      return true;
    }

    function assertionExpectation(statement: TSESTree.ExpressionStatement, call: TSESTree.CallExpression, receiver: TSESTree.Expression | TSESTree.Super, key: Assertion["key"], matcher: string): Assertion | null {
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
