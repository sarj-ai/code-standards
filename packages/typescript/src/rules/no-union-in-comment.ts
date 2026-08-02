/**
 * @fileoverview no-union-in-comment — a comment listing a field's allowed strings has written a union type the compiler never gets to enforce.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-union-in-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "unionInComment";
type Options = readonly [];

// A literal long enough to be a sentence is an example, a message or a format
// string — not an enum member.
const MAX_LITERAL_LENGTH = 28;

const LITERAL = String.raw`(?:'[^'\n]*'|"[^"\n]*"|\`[^\`\n]*\`)`;

// Anchored at BOTH ends on purpose: a literal list inside a sentence is prose
// that happens to quote values, and the sentence is what carries the meaning.
// Only a body that is nothing but the list is a type someone wrote down.
const LEAD_IN_RE =
  /^(?:one of|either|values?|allowed(?: values)?|options?|possible(?: values)?)\s*[:=-]?\s*/i;
const UNION_BODY_RE = new RegExp(String.raw`^${LITERAL}(?:\s*[|,/]\s*${LITERAL})+\.?$`);
const LITERAL_G = new RegExp(LITERAL, "g");

/**
 * Column builders whose call spells the stored type where TypeScript has no
 * annotation to read. A schema row is where a closed set is most often left as
 * `text` with the set in a comment beside it.
 */
const STRING_BUILDERS: ReadonlySet<string> = new Set([
  "char", "citext", "longtext", "mediumtext", "string", "text", "tinytext", "varchar",
]);

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

/** The identifier a call chain hangs off: `text("k").notNull()` -> `text`. */
function rootCallee(node: TSESTree.Node | null | undefined): string | null {
  let current: TSESTree.Node | null | undefined = node;
  for (let hops = 0; current != null && hops < 12; hops += 1) {
    switch (current.type) {
      case AST_NODE_TYPES.CallExpression:
        current = current.callee;
        break;
      case AST_NODE_TYPES.MemberExpression:
        current = current.object;
        break;
      case AST_NODE_TYPES.Identifier:
        return current.name;
      default:
        return null;
    }
  }
  return null;
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

function targetOf(node: TSESTree.Node): Target | null {
  switch (node.type) {
    case AST_NODE_TYPES.TSPropertySignature:
    case AST_NODE_TYPES.PropertyDefinition: {
      const name = node.computed ? null : nameOf(node.key);
      if (name === null || !isBareString(node.typeAnnotation?.typeAnnotation)) return null;
      return { node, name };
    }
    case AST_NODE_TYPES.Property: {
      const name = node.computed || node.shorthand ? null : nameOf(node.key);
      const callee = rootCallee(node.value);
      if (name === null || callee === null || !STRING_BUILDERS.has(callee)) return null;
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
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
    },
    schema: [],
    messages: {
      unionInComment:
        'This comment is a type — `{{name}}` still accepts every string, so the set it lists is enforced by nobody. Make it a string-literal union ("{{first}}" | …) and delete the comment.',
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (isGeneratedFile(context.filename, sourceCode.text)) {
      return {};
    }

    /**
     * The declaration a comment annotates: the one it trails on its own line, or
     * the one starting on the line below when the comment has that line to
     * itself. Anything else annotates nothing this rule can read.
     */
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
        if (target !== null) return target;
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
          // A declaration that already spells every value HAS the type; the
          // comment beside it is a restatement, which is a different defect.
          const declaration = sourceCode.getText(target.node);
          if (literals.every((literal) => declaration.includes(literal))) continue;
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
