/** @fileoverview prefer-named-literal-union — name repeated inline string literal unions in a module. */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingTypeAliasFix } from "../utils/existing-type-alias-fix.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { ownsCallbackDomain } from "./prefer-named-callback-domain.js";

const NAME = "prefer-named-literal-union";
const SUMMARY = "Name repeated inline string literal unions in a module.";
const KEY_SET_UTILITIES: ReadonlySet<string> = new Set([
  "Pick", "Omit", "Exclude", "Extract", "Record", "Partial", "Required", "Readonly",
]);

interface UnionGroup {
  readonly minimumOccurrences: number;
  readonly inline: ESTree.TSUnionType[];
  readonly aliases: ESTree.TSTypeAliasDeclaration[];
}

function utilityTypeArgument(parent: Node | null): boolean {
  if (parent?.type !== "TSTypeParameterInstantiation") return false;
  const reference = parentOf(parent);
  return reference?.type === "TSTypeReference" && reference.typeName.type === "Identifier" &&
    KEY_SET_UTILITIES.has(reference.typeName.name);
}

function stringUnion(node: ESTree.TSUnionType) {
  const values = new Set<string>();
  let nullable = false;
  let undefinable = false;
  for (const member of node.types) {
    if (member.type === "TSNullKeyword") nullable = true;
    else if (member.type === "TSUndefinedKeyword") undefinable = true;
    else if (member.type === "TSLiteralType" && member.literal.type === "Literal" &&
      typeof member.literal.value === "string") values.add(member.literal.value);
    else return null;
  }
  if (values.size < 2) return null;
  return { key: JSON.stringify([[...values].sort(), nullable, undefinable]), size: values.size };
}

function moduleAlias(node: ESTree.TSTypeAliasDeclaration): boolean {
  const parent = parentOf(node);
  return parent?.type === "Program" ||
    (parent?.type === "ExportNamedDeclaration" && parentOf(parent)?.type === "Program");
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: SUMMARY, url: docsUrl(NAME) },
    schema: [],
    messages: {
      useExistingAlias: "Reuse a named type alias for this string literal union.",
      nameRepeatedUnion: "Extract this repeated string literal union to a named type alias.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const groups = new Map<string, UnionGroup>();
    return {
      before() {
        groups.clear();
        sourceCode = context.sourceCode;
        return !(isTestFile(context) || isGeneratedFile(context, sourceCode.text));
      },
      TSUnionType(node) {
        const parent = parentOf(node);
        if (utilityTypeArgument(parent)) return;
        const union = stringUnion(node);
        if (union === null) return;
        const group = groups.get(union.key) ?? {
          minimumOccurrences: union.size >= 3 ? 2 : 3,
          inline: [],
          aliases: [],
        };
        groups.set(union.key, group);
        if (parent?.type === "TSTypeAliasDeclaration" && parent.typeAnnotation === node) {
          if (moduleAlias(parent)) group.aliases.push(parent);
        } else {
          group.inline.push(node);
        }
      },
      "Program:exit"() {
        for (const { aliases, inline, minimumOccurrences } of groups.values()) {
          const hasAlias = aliases.length > 0;
          if (!hasAlias && inline.length < minimumOccurrences) continue;
          const messageId = hasAlias ? "useExistingAlias" : "nameRepeatedUnion";
          const occurrences = hasAlias ? inline : inline.slice(1);
          for (const node of occurrences) {
            if (ownsCallbackDomain(node)) continue;
            const name = hasAlias ? existingTypeAliasFix(sourceCode, node, aliases) : null;
            if (name === null) {
              context.report({ node, messageId });
              continue;
            }
            context.report({
              node,
              messageId,
              fix: (fixer) => fixer.replaceText(node, name + sourceCode.getText(node).replace(/[^\r\n]/gu, "")),
            });
          }
        }
      },
    };
  },
});
