/**
 * @fileoverview no-union-in-comment — a comment listing a field's allowed strings has written a union type the compiler never gets to enforce.
 *
 * Port of the 18.x `no-union-in-comment` rule. The comment scan is
 * unchanged. The original compared a missing `typeParameters` to
 * `undefined`, which Oxlint's `null` never matches; the port checks `null`,
 * which restores the ESLint fix.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-union-in-comment.test.ts
 */

import type { Comment, FixFn, Token } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { forEachOwnAstChild, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

// A literal long enough to be a sentence is an example, a message or a format string — not an enum member.
const MAX_LITERAL_LENGTH = 28;

const LITERAL = String.raw`(?:'[^'\n]*'|"[^"\n]*"|\`[^\`\n]*\`)`;
const LEAD_IN_RE =
  /^(?:one of|either|values?|allowed(?: values)?|options?|possible(?: values)?)\s*[:=-]?\s*/i;
const UNION_BODY_RE = new RegExp(String.raw`^${LITERAL}(?:\s*[|,/]\s*${LITERAL})+\.?$`);
const LITERAL_G = new RegExp(LITERAL, "g");

/** True when a type annotation is an unconstrained `string` after all. */
function isBareString(node: ESTree.TSType | null | undefined): boolean {
  if (node === undefined || node === null) return false;
  switch (node.type) {
    case "TSStringKeyword":
      return true;
    // `string[]` holds members of the same closed set, one element at a time.
    case "TSArrayType":
      return isBareString(node.elementType);
    // `string | null` is still an unconstrained string, and so is `string | "a"`.
    case "TSUnionType":
      return node.types.some((member) => isBareString(member));
    default:
      return false;
  }
}

/** A declaration this rule can judge: a named one that holds a bare string. */
interface Target {
  readonly node: Node;
  readonly name: string;
}

function targetOf(node: Node): Target | null {
  switch (node.type) {
    case "TSPropertySignature":
    case "PropertyDefinition": {
      const name = node.computed ? null : nameOf(node.key);
      if (name === null || !isBareString(node.typeAnnotation?.typeAnnotation)) return null;
      return { node, name };
    }
    case "VariableDeclarator": {
      if (node.id.type !== "Identifier") return null;
      if (!isBareString(node.id.typeAnnotation?.typeAnnotation)) return null;
      return { node, name: node.id.name };
    }
    default:
      return null;
  }
}

function nameOf(key: Node): string | null {
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") return key.value;
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

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
      url: docsUrl("no-union-in-comment"),
    },
    schema: [],
    messages: {
      unionInComment:
        'The annotation for `{{name}}` accepts arbitrary strings. If this list is exhaustive, express it as a string-literal union ("{{first}}" | …); retain separate runtime constraints or examples.',
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;

    function annotated(comment: Comment): Target | null {
      const anchor = commentAnchor(comment);
      for (
        let node: Node | null = anchor;
        node !== null && node.type !== "Program";
        node = parentOf(node)
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

    function commentAnchor(comment: Comment): Node | null {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      if (before !== null && before.loc.end.line === comment.loc.start.line) {
        // The separator a member ends on belongs to the CONTAINER, so step back over `,` and `;`.
        let token: Token | null = before;
        while (token !== null && (token.value === "," || token.value === ";")) {
          token = sourceCode.getTokenBefore(token, { includeComments: false });
        }
        return token === null ? null : sourceCode.getNodeByRangeIndex(token.range[0]);
      }
      const after = sourceCode.getTokenAfter(comment, { includeComments: false });
      if (after === null || after.loc.start.line !== comment.loc.end.line + 1) return null;
      return sourceCode.getNodeByRangeIndex(after.range[0]);
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        return undefined;
      },
      Program(): void {
        for (const comment of sourceCode.getAllComments()) {
          const literals = unionLiterals(comment.value.replace(/^\*+/, "").replace(/\*+$/, "").trim());
          if (literals === null) continue;
          const target = annotated(comment);
          if (target === null) continue;
          const fix = existingLiteralUnionFix(sourceCode, target, literals, context.filename);
          context.report({
            node: comment,
            messageId: "unionInComment",
            data: { name: target.name, first: literals[0] ?? "" },
            ...(fix !== null && { fix }),
          });
        }
      },
    };
  },
});

function existingLiteralUnionFix(
  sourceCode: SourceCode,
  target: Target,
  literals: readonly string[],
  filename: string,
): FixFn | null {
  if (target.node.type !== "TSPropertySignature" || target.node.computed) return null;
  const owner = closedOwner(target.node);
  if (owner === null || owner.typeParameters !== null || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename) ||
      dependentOwner(owner)) return null;
  const annotation = target.node.typeAnnotation?.typeAnnotation;
  if (annotation?.type !== "TSUnionType" || sourceCode.getCommentsInside(annotation).length > 0) return null;
  const members = authoredLiteralMembers(sourceCode, annotation);
  if (members === null) return null;
  const { authored, retained } = members;
  const described = new Set(literals);
  if (authored.size < 2 || authored.size !== described.size || [...authored].some((literal) => !described.has(literal))) return null;
  const replacement = retained.map((member) => sourceCode.getText(member)).join(" | ") +
    sourceCode.getText(annotation).replace(/[^\r\n]/gu, "");
  return (fixer) => fixer.replaceText(annotation, replacement);
}

/** The non-extending interface, or the alias whose whole type is the literal, that directly holds `member`. */
function closedOwner(member: ESTree.TSPropertySignature): ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration | null {
  const container = parentOf(member);
  const owner = container === null ? null : parentOf(container);
  if (container?.type === "TSInterfaceBody" && owner?.type === "TSInterfaceDeclaration" && owner.extends.length === 0) return owner;
  if (container?.type === "TSTypeLiteral" && owner?.type === "TSTypeAliasDeclaration" && owner.typeAnnotation === container) return owner;
  return null;
}

function authoredLiteralMembers(
  sourceCode: SourceCode,
  annotation: ESTree.TSUnionType,
): { readonly authored: ReadonlySet<string>; readonly retained: readonly ESTree.TSType[] } | null {
  const authored = new Set<string>();
  const retained: ESTree.TSType[] = [];
  for (const member of annotation.types) {
    if (member.type === "TSStringKeyword") continue;
    if (member.type === "TSLiteralType" && member.literal.type === "Literal" && typeof member.literal.value === "string") {
      if (sourceCode.getText(member).includes("\\")) return null;
      authored.add(member.literal.value);
    } else if (member.type !== "TSNullKeyword" && member.type !== "TSUndefinedKeyword") return null;
    retained.push(member);
  }
  return { authored, retained };
}

function dependentOwner(owner: ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration): boolean {
  const members: readonly Node[] = owner.type === "TSInterfaceDeclaration" ? owner.body.body :
    owner.typeAnnotation.type === "TSTypeLiteral" ? owner.typeAnnotation.members : [];
  if (members.some((member) => member.type !== "TSPropertySignature" || member.computed)) return true;
  const pending: Node[] = [owner];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    if (node.type === "TSThisType") return true;
    forEachOwnAstChild(node, (child) => { pending.push(child); });
  }
  return false;
}
