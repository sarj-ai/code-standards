/**
 * @fileoverview prefer-discriminated-union — represent correlated tags and payloads as explicit variants.
 *
 * Require producer evidence before suggesting a more precise state contract.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";
import { discriminatedUnionReturns, type DiscriminatedReturn } from "./_discriminated-union-returns.js";

const NAME = "prefer-discriminated-union";

type Producer = ESTree.ArrowFunctionExpression | ESTree.Function;
type ReportFix = (fixer: Fixer) => Fix;

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Preserve producer-proven tag/payload and Boolean state relationships in return types.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferProducedVariants:
        "This producer returns tag-specific payloads for `{{tag}}`, but its flat return contract makes them optional. If these variants define the domain, use a discriminated union with each variant's required payload, or give this producer a precise return type separate from the broader contract.",
      preferProducedState:
        "This producer returns a restricted set of literal combinations for `{{fields}}`, while its Boolean fields permit all four. Review a union preserving every returned combination, or a typed disposition if these are domain phases. Other writers and readers of a shared contract require review.",
    },
  },
  createOnce(context) {
    const reportedContracts = new Set<Node>();
    const producers: Producer[] = [];

    function rememberProducer(node: Producer): void {
      producers.push(node);
    }

    function checkProducer(node: Producer): void {
      const result = discriminatedUnionReturns(node, context.sourceCode);
      if (result === undefined || reportedContracts.has(result.reportNode)) return;
      reportedContracts.add(result.reportNode);
      const fix = privateVariantReturn(context.sourceCode, context.filename, node, result);
      const relationship = result.relationship;
      context.report({ node: result.reportNode,
        ...(fix !== null && { fix }),
        ...(relationship.kind === "presence"
          ? { messageId: "preferProducedVariants", data: { tag: relationship.tag } }
          : { messageId: "preferProducedState", data: { fields: [relationship.fields.left, relationship.fields.right].join("`, `") } }),
      });
    }

    return {
      before() {
        reportedContracts.clear();
        producers.length = 0;
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      ArrowFunctionExpression: rememberProducer,
      FunctionDeclaration: rememberProducer,
      FunctionExpression: rememberProducer,
      "Program:exit"(): void {
        for (const producer of producers) checkProducer(producer);
      },
    };
  },
});


function privateVariantReturn(sourceCode: SourceCode, filename: string, owner: Producer, result: DiscriminatedReturn): ReportFix | null {
  const annotation = owner.returnType?.typeAnnotation;
  if (owner.type !== "FunctionDeclaration" || owner.id === null || !returnsOnlyConditionalObject(owner) || annotation?.type !== "TSTypeLiteral" || result.reportNode !== owner.returnType || result.returned.length > 4 ||
    sourceCode.getCommentsInside(owner).length > 0 || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename) ||
    !retainsNamedTypeUses(sourceCode, annotation)) return null;
  const variants = result.returned.map((properties) => privateVariantType(properties, result, sourceCode));
  if (variants.some((variant) => variant === null)) return null;
  const text = `${variants.join(" | ")}${sourceCode.getText(annotation).replace(/[^\r\n\u2028\u2029]/gu, "")}`;
  return (fixer) => fixer.replaceText(annotation, text);
}

/** `function f() { return test ? { … } : { … }; }`, sync and non-generic. */
function returnsOnlyConditionalObject(fn: ESTree.Function): boolean {
  if (fn.async || fn.generator || isPresent(fn.typeParameters)) return false;
  const statements = fn.body?.body ?? [];
  const [returned] = statements;
  return statements.length === 1 && returned?.type === "ReturnStatement" &&
    returned.argument?.type === "ConditionalExpression" && bareConditionalObjects(returned.argument);
}

/** Assertions and local aliases can widen expression types; detecting them does not justify narrowing a function annotation. */
function bareConditionalObjects(expression: ESTree.Expression): boolean {
  return expression.type === "ObjectExpression" || (expression.type === "ConditionalExpression" &&
    bareConditionalObjects(expression.consequent) && bareConditionalObjects(expression.alternate));
}

function privateVariantType(properties: ReadonlyMap<string, Node>, result: DiscriminatedReturn, sourceCode: SourceCode): string | null {
  if ([...properties.values()].some((value) => value.type !== "Literal" ||
    (typeof value.value === "object" && value.value !== null) || (typeof value.value === "number" && !Number.isFinite(value.value)))) return null;
  const fields: string[] = [];
  for (const [name, member] of result.members) {
    const value = properties.get(name);
    if (value === undefined && result.relationship.kind === "presence") continue;
    const annotation = member.typeAnnotation?.typeAnnotation;
    if (annotation === undefined) return null;
    const narrow = result.relationship.kind === "presence"
      ? name === result.relationship.tag
      : name === result.relationship.fields.left || name === result.relationship.fields.right;
    let type = sourceCode.getText(annotation);
    if (narrow) {
      if (value === undefined) return null;
      type = sourceCode.getText(value);
    }
    const optional = result.relationship.kind === "boolean-pair" && !narrow && member.optional;
    fields.push(`${member.readonly ? "readonly " : ""}${sourceCode.getText(member.key)}${optional ? "?" : ""}: ${type}`);
  }
  return `{ ${fields.join("; ")} }`;
}
