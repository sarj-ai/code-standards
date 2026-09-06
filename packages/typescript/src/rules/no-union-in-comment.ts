/**
 * @fileoverview no-union-in-comment — a comment listing a field's allowed strings has written a union type the compiler never gets to enforce.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-union-in-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "unionInComment";
type Options = readonly [];

export const NO_UNION_IN_COMMENT_DOCUMENTATION = {
  summary: "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
  rationale: "A broad string annotation does not express a closed set documented beside it.",
  remediation: "If the list is exhaustive, express it as a string-literal union; keep examples and runtime constraints documented separately.",
  category: "maintainability",
  limitations: ["Only bare quoted-value lists directly attached to explicitly annotated string declarations are inspected. Unknown schema builders and runtime validation are not inferred."],
  examples: [
    {
      id: "literal-union",
      title: "Encode allowed values in the type",
      outcome: "no-match",
      files: [{ path: "src/record.ts", source: "interface R { kind: 'aa' | 'bb'; }" }],
      focusPath: "src/record.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "comment-only-union",
      title: "Do not leave allowed values in a comment",
      outcome: "match",
      files: [{ path: "src/record.ts", source: "interface R {\n  kind: string; // 'aa' | 'bb'\n}" }],
      focusPath: "src/record.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

// A literal long enough to be a sentence is an example, a message or a format
// string — not an enum member.
const MAX_LITERAL_LENGTH = 28;

const LITERAL = String.raw`(?:'[^'\n]*'|"[^"\n]*"|\`[^\`\n]*\`)`;

const LEAD_IN_RE =
  /^(?:one of|either|values?|allowed(?: values)?|options?|possible(?: values)?)\s*[:=-]?\s*/i;
const UNION_BODY_RE = new RegExp(String.raw`^${LITERAL}(?:\s*[|,/]\s*${LITERAL})+\.?$`);
const LITERAL_G = new RegExp(LITERAL, "g");

/** True when a type annotation is an unconstrained `string` after all. */
function isBareString(node: TSESTree.TypeNode | undefined): boolean {
  if (node === undefined) return false;
  switch (node.type) {
    case AST_NODE_TYPES.TSStringKeyword:
      return true;
    // `string[]` holds members of the same closed set, one element at a time.
    case AST_NODE_TYPES.TSArrayType:
      return isBareString(node.elementType);
    // `string | null` is still an unconstrained string, and so is `string | "a"`
    // — the checker collapses that one to `string`.
    case AST_NODE_TYPES.TSUnionType:
      return node.types.some((member) => isBareString(member));
    default:
      return false;
  }
}

function targetOf(node: TSESTree.Node): Target | null {
  switch (node.type) {
    case AST_NODE_TYPES.TSPropertySignature:
    case AST_NODE_TYPES.PropertyDefinition: {
      const name = node.computed ? null : nameOf(node.key);
      if (name === null || !isBareString(node.typeAnnotation?.typeAnnotation)) return null;
      return { node, name };
    }
    case AST_NODE_TYPES.VariableDeclarator: {
      if (node.id.type !== AST_NODE_TYPES.Identifier) return null;
      if (!isBareString(node.id.typeAnnotation?.typeAnnotation)) return null;
      return { node, name: node.id.name };
    }
    default:
      return null;
  }
}

/** A declaration this rule can judge: a named one that holds a bare string. */
interface Target {
  readonly node: TSESTree.Node;
  readonly name: string;
}

function nameOf(key: TSESTree.Node): string | null {
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
}

/** The literals a comment lists, or null when its body is not a bare list. */
function unionLiterals(body: string): string[] | null {
  const list = body.replace(LEAD_IN_RE, "").trim();
  if (!UNION_BODY_RE.test(list)) return null;
  const literals = (list.match(LITERAL_G) ?? []).map((raw) => raw.slice(1, -1));
  if (literals.some((literal) => literal.length === 0 || literal.length > MAX_LITERAL_LENGTH)) {
    return null;
  }
  return literals;
}

export default createRule<Options, MessageIds>({
  name: "no-union-in-comment",
  documentation: NO_UNION_IN_COMMENT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
    },
    schema: [],
    messages: {
      unionInComment:
        'The annotation for `{{name}}` accepts arbitrary strings. If this list is exhaustive, express it as a string-literal union ("{{first}}" | …); retain separate runtime constraints or examples.',
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (isGeneratedFile(context.filename, sourceCode.text)) {
      return {};
    }

    function annotated(comment: TSESTree.Comment): Target | null {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      let anchor: TSESTree.Node | null;
      if (before !== null && before.loc.end.line === comment.loc.start.line) {
        // The separator a member ends on belongs to the CONTAINER, so resolving
        // `,` or `;` lands on the object and never reaches the member itself.
        let token: TSESTree.Token | null = before;
        while (token !== null && (token.value === "," || token.value === ";")) {
          token = sourceCode.getTokenBefore(token, { includeComments: false });
        }
        anchor = token === null ? null : sourceCode.getNodeByRangeIndex(token.range[0]);
      } else {
        const after = sourceCode.getTokenAfter(comment, { includeComments: false });
        if (after === null || after.loc.start.line !== comment.loc.end.line + 1) return null;
        anchor = sourceCode.getNodeByRangeIndex(after.range[0]);
      }
      for (
        let node: TSESTree.Node | undefined | null = anchor;
        node != null && node.type !== AST_NODE_TYPES.Program;
        node = node.parent
      ) {
        const target = targetOf(node);
        if (target !== null) {
          const follows = target.node.range[1] <= comment.range[0] && target.node.loc.end.line === comment.loc.start.line;
          const precedes = comment.range[1] <= target.node.range[0] && comment.loc.end.line + 1 === target.node.loc.start.line;
          return follows || precedes ? target : null;
        }
      }
      return null;
    }

    return {
      Program(): void {
        for (const comment of sourceCode.getAllComments()) {
          const body = comment.value.replace(/^\*+/, "").replace(/\*+$/, "").trim();
          if (body.length === 0) continue;
          const literals = unionLiterals(body);
          if (literals === null) continue;
          const target = annotated(comment);
          if (target === null) continue;
          context.report({
            node: comment,
            messageId: "unionInComment",
            data: { name: target.name, first: literals[0] ?? "" },
          });
        }
      },
    };
  },
});
