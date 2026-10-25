/**
 * @fileoverview no-union-in-comment — a comment listing a field's allowed strings has written a union type the compiler never gets to enforce.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-union-in-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { isGeneratedFile } from "./_paths.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";

type MessageIds = "unionInComment";
type Options = readonly [];

export const NO_UNION_IN_COMMENT_DOCUMENTATION = {
  summary: "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
  rationale: "A broad string annotation does not express a closed set documented beside it.",
  remediation: "If the list is exhaustive, express it as a string-literal union; keep examples and runtime constraints documented separately.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Only bare quoted-value lists directly attached to explicitly annotated string declarations are inspected. Unknown schema builders and runtime validation are not inferred.",
    "Automatic fixes remove only the broad string member from an unused private unmerged interface/object alias whose existing quoted literal branches exactly match the adjacent comment's set. Authored literal branches, nullability and the comment are retained. Bare string declarations, observed/public types, heritage, generics, dependent this, computed/indexed members, escapes and comments inside the changed union remain manual."],
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
    {
      id: "safe-autofix",
      title: "Keep the literal contract already authored beside its exact comment",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; interface Choice { kind: string | 'aa' | 'bb'; // 'aa' | 'bb'\n}" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; interface Choice { kind: 'aa' | 'bb'; // 'aa' | 'bb'\n}" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
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
    fixable: "code",
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
    if (isGeneratedFile(context, sourceCode.text)) {
      return {};
    }

    function annotated(comment: TSESTree.Comment): Target | null {
      const anchor = commentAnchor(comment);
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

    function commentAnchor(comment: TSESTree.Comment): TSESTree.Node | null {
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
      return anchor;
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
            fix: existingLiteralUnionFix(sourceCode, target, literals, context.filename),
          });
        }
      },
    };
  },
});

function existingLiteralUnionFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  target: Target,
  literals: readonly string[],
  filename: string,
): TSESLint.ReportFixFunction | null {
  if (target.node.type !== AST_NODE_TYPES.TSPropertySignature || target.node.computed) return null;
  const container = target.node.parent;
  const owner = container.parent;
  if ((container.type !== AST_NODE_TYPES.TSInterfaceBody || owner.type !== AST_NODE_TYPES.TSInterfaceDeclaration || owner.extends.length > 0) &&
    (container.type !== AST_NODE_TYPES.TSTypeLiteral || owner.type !== AST_NODE_TYPES.TSTypeAliasDeclaration || owner.typeAnnotation !== container)) return null;
  if ((owner.type !== AST_NODE_TYPES.TSInterfaceDeclaration && owner.type !== AST_NODE_TYPES.TSTypeAliasDeclaration) ||
    owner.typeParameters !== undefined || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename) || dependentOwner(owner)) return null;
  const annotation = target.node.typeAnnotation?.typeAnnotation;
  if (annotation?.type !== AST_NODE_TYPES.TSUnionType || sourceCode.getCommentsInside(annotation).length > 0) return null;
  const members = authoredLiteralMembers(sourceCode, annotation);
  if (members === null) return null;
  const { authored, retained } = members;
  const described = new Set(literals);
  if (authored.size < 2 || authored.size !== described.size || [...authored].some((literal) => !described.has(literal))) return null;
  const replacement = retained.map((member) => sourceCode.getText(member)).join(" | ") +
    sourceCode.getText(annotation).replace(/[^\r\n]/gu, "");
  return (fixer) => fixer.replaceText(annotation, replacement);
}

function authoredLiteralMembers(
  sourceCode: Readonly<TSESLint.SourceCode>,
  annotation: TSESTree.TSUnionType,
): { readonly authored: ReadonlySet<string>; readonly retained: readonly TSESTree.TypeNode[] } | null {
  const authored = new Set<string>();
  const retained: TSESTree.TypeNode[] = [];
  for (const member of annotation.types) {
    if (member.type === AST_NODE_TYPES.TSStringKeyword) continue;
    if (member.type === AST_NODE_TYPES.TSLiteralType && member.literal.type === AST_NODE_TYPES.Literal && typeof member.literal.value === "string") {
      if (sourceCode.getText(member).includes("\\")) return null;
      authored.add(member.literal.value);
    } else if (member.type !== AST_NODE_TYPES.TSNullKeyword && member.type !== AST_NODE_TYPES.TSUndefinedKeyword) return null;
    retained.push(member);
  }
  return { authored, retained };
}

function dependentOwner(owner: TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration): boolean {
  const members = owner.type === AST_NODE_TYPES.TSInterfaceDeclaration ? owner.body.body :
    owner.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral ? owner.typeAnnotation.members : [];
  if (members.some((member) => member.type !== AST_NODE_TYPES.TSPropertySignature || member.computed)) return true;
  const pending: TSESTree.Node[] = [owner];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    if (node.type === AST_NODE_TYPES.TSThisType) return true;
    forEachOwnAstChild(node, (child) => { pending.push(child); });
  }
  return false;
}
