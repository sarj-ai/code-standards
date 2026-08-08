/**
 * @fileoverview no-repeated-string-literal — the same structured literal in two functions drifts the moment one copy is edited.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-repeated-string-literal.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noRepeatedStringLiteral";
type Options = readonly [];

const MIN_LENGTH = 40;
const MIN_DISTINCT_SCOPES = 2;
const PREVIEW_LENGTH = 40;

/** Case-sensitive on purpose: uppercase keywords mean SQL, lowercase means prose. */
const SQL_KEYWORD_RE =
  /\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|VALUES|ON CONFLICT|RETURNING|GROUP BY|ORDER BY)\b/;
const IDENTIFIER_RE = /^[a-z_][a-z0-9_.]*$/;

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

export const noRepeatedStringLiteralDocumentation = {
  summary: "Disallow a long structured string literal repeated across functions; the copies drift when one is edited. Extract a module-level constant.",
  rationale: "Independent copies of a structured value can diverge and silently change behavior.",
  remediation: "Extract the repeated value to one module-level constant and reference it from each function.",
  category: "maintainability",
  limitations: ["Test files, short strings, prose, substitutions, module sources, JSX attributes, and repetition within one function are excluded."],
  examples: [
    { id: "shared-constant", title: "Share one structured value", outcome: "no-match", files: [{ path: "src/queries.ts", source: "const QUERY = 'SELECT id, status, created_at FROM candidates';\nfunction one() { return QUERY; }\nfunction two() { return QUERY; }" }], focusPath: "src/queries.ts", expectedCount: 0, public: true },
    { id: "repeated-query", title: "Do not copy a structured value across functions", outcome: "match", files: [{ path: "src/queries.ts", source: "function one() { return 'SELECT id, status, created_at FROM candidates'; }\nfunction two() { return 'SELECT id, status, created_at FROM candidates'; }" }], focusPath: "src/queries.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** True when the literal carries structure that rules out coincidental equality. */
function isStructured(value: string): boolean {
  return value.includes("\n") || SQL_KEYWORD_RE.test(value) || IDENTIFIER_RE.test(value);
}

function preview(value: string): string {
  const oneLine = value.replaceAll("\n", " ").trim();
  return oneLine.length <= PREVIEW_LENGTH ? oneLine : `${oneLine.slice(0, PREVIEW_LENGTH)}...`;
}

/** The enclosing function node, or null when the literal sits at module/class scope. */
function enclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current;
    }
  }
  return null;
}

/**
 * True when the literal is scaffolding rather than a reusable value: an
 * import/`require` source (repeating a module path is the point) or a JSX
 * attribute value (styling strings, handled by the styling rules).
 */
function isScaffolding(node: TSESTree.Node): boolean {
  const parent = node.parent;
  if (parent === undefined) {
    return true;
  }
  const isRequireSource =
    parent.type === AST_NODE_TYPES.CallExpression &&
    parent.callee.type === AST_NODE_TYPES.Identifier &&
    parent.callee.name === "require";
  return (
    parent.type === AST_NODE_TYPES.ImportDeclaration ||
    parent.type === AST_NODE_TYPES.ImportExpression ||
    parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    parent.type === AST_NODE_TYPES.ExportAllDeclaration ||
    parent.type === AST_NODE_TYPES.TSImportType ||
    parent.type === AST_NODE_TYPES.JSXAttribute ||
    parent.type === AST_NODE_TYPES.TSLiteralType ||
    isRequireSource
  );
}

export default createRule<Options, MessageIds>({
  name: "no-repeated-string-literal",
  documentation: noRepeatedStringLiteralDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow a long structured string literal repeated across functions; the copies drift when one is edited. Extract a module-level constant.",
    },
    schema: [],
    messages: {
      noRepeatedStringLiteral:
        'Structured string literal "{{preview}}" is repeated across functions (first use on line {{line}}) — extract a module-level constant so the copies cannot drift.',
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }
    const occurrences = new Map<string, TSESTree.Node[]>();
    const scopes = new WeakMap<TSESTree.Node, TSESTree.Node | null>();

    const record = (value: string, node: TSESTree.Node): void => {
      if (value.length < MIN_LENGTH || !isStructured(value) || isScaffolding(node)) {
        return;
      }
      const existing = occurrences.get(value);
      if (existing === undefined) {
        occurrences.set(value, [node]);
      } else {
        existing.push(node);
      }
      scopes.set(node, enclosingFunction(node));
    };

    return {
      Literal(node: TSESTree.Literal): void {
        if (typeof node.value === "string") {
          record(node.value, node);
        }
      },
      TemplateLiteral(node: TSESTree.TemplateLiteral): void {
        // A tagged template (`js`…``, `css`…``, `sql`…``) is a call, not a
        // string value — the tag, not this rule, decides what the text means.
        if (node.parent.type === AST_NODE_TYPES.TaggedTemplateExpression) {
          return;
        }
        const [only] = node.quasis;
        if (node.expressions.length === 0 && only !== undefined) {
          record(only.value.cooked ?? only.value.raw, node);
        }
      },
      "Program:exit": (): void => {
        for (const [value, nodes] of occurrences) {
          const distinctScopes = new Set(
            nodes.map((node) => scopes.get(node)).filter((scope) => scope != null),
          );
          if (distinctScopes.size < MIN_DISTINCT_SCOPES) {
            continue;
          }
          const [first, ...repeats] = nodes;
          if (first === undefined) {
            continue;
          }
          for (const node of repeats) {
            context.report({
              node,
              messageId: "noRepeatedStringLiteral",
              data: { preview: preview(value), line: String(first.loc.start.line) },
            });
          }
        }
      },
    };
  },
});
