/**
 * @fileoverview prefer-discriminated-union — represent correlated tags and payloads as explicit variants.
 *
 * Port of the 18.x `prefer-discriminated-union` rule. The rule is
 * untyped, so the port covers all of it. Optional AST fields are `null` under
 * Oxlint, so the `undefined` checks accept both.
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

/**
 * Boolean-typed member names that read as a success/error status discriminant.
 */
const STATUS_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "success",
  "ok",
]);
const FAILURE_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "error",
  "errors",
  "reason",
  "cause",
]);
const SUCCESS_PAYLOAD_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "data",
  "events",
  "payload",
  "response",
  "result",
  "value",
]);

const REQUIRED_STATUS_MEMBER_COUNT = 1;

const FUNCTION_RETURN_OWNER_TYPES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression",
  "FunctionDeclaration",
  "FunctionExpression",
  "TSDeclareFunction",
  "TSEmptyBodyFunctionExpression",
  "TSFunctionType",
  "TSMethodSignature",
]);

/**
 * Returns true for the canonical flat result shape: one required positive
 * boolean status plus optional success and failure payloads.
 */
function looksLikeMutuallyExclusiveState(
  typeLiteral: Pick<ESTree.TSTypeLiteral, "members">,
): boolean {
  let statusMemberCount = 0;
  let hasFailurePayload = false;
  let hasSuccessPayload = false;
  let hasUnrecognizedMember = false;

  for (const member of typeLiteral.members) {
    if (member.type !== "TSPropertySignature") {
      hasUnrecognizedMember = true;
      continue;
    }

    const name = getMemberName(member);
    if (
      name !== null &&
      STATUS_MEMBER_NAMES.has(name) &&
      isBooleanTyped(member) &&
      !member.optional
    ) {
      statusMemberCount += 1;
      continue;
    }

    if (!member.optional || isBooleanTyped(member) || name === null) {
      hasUnrecognizedMember = true;
      continue;
    }
    if (FAILURE_MEMBER_NAMES.has(name)) {
      hasFailurePayload = true;
    } else if (SUCCESS_PAYLOAD_MEMBER_NAMES.has(name)) {
      hasSuccessPayload = true;
    } else {
      hasUnrecognizedMember = true;
    }
  }

  return (
    statusMemberCount === REQUIRED_STATUS_MEMBER_COUNT &&
    hasFailurePayload &&
    (hasSuccessPayload || !hasUnrecognizedMember)
  );
}

/**
 * Returns the property key name for a member if it is a plain identifier or
 * string-literal property signature, otherwise `null`.
 */
function getMemberName(member: ESTree.TSSignature): string | null {
  if (member.type !== "TSPropertySignature" || member.computed) {
    return null;
  }
  const { key } = member;
  if (key.type === "Identifier") {
    return key.name;
  }
  if (key.type === "Literal" && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

/**
 * Whether a property signature is annotated with `boolean`.
 */
function isBooleanTyped(member: ESTree.TSPropertySignature): boolean {
  return (
    member.typeAnnotation?.typeAnnotation.type ===
    "TSBooleanKeyword"
  );
}

/** The whole inline object returned by a function, directly or through `Promise`. */
function inlineReturnTypeLiteral(
  node: ESTree.TSTypeLiteral,
): ESTree.TSTypeAnnotation | null {
  let annotation: ESTree.TSTypeAnnotation | null = null;
  if (node.parent.type === "TSTypeAnnotation") {
    annotation = node.parent;
  } else if (
    node.parent.type === "TSTypeParameterInstantiation" &&
    node.parent.params.length === 1 &&
    node.parent.params[0] === node &&
    node.parent.parent.type === "TSTypeReference" &&
    node.parent.parent.typeName.type === "Identifier" &&
    node.parent.parent.typeName.name === "Promise" &&
    node.parent.parent.parent.type === "TSTypeAnnotation"
  ) {
    annotation = node.parent.parent.parent;
  }
  if (annotation === null) return null;
  const owner = annotation.parent;
  return FUNCTION_RETURN_OWNER_TYPES.has(owner.type) &&
    "returnType" in owner &&
    owner.returnType === annotation
    ? annotation
    : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Prefer discriminated unions for result contracts and locally proven tag-specific return payloads.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferProducedVariants:
        "This producer returns tag-specific payloads for `{{tag}}`, but its flat return contract makes them optional. If these variants define the domain, use a discriminated union with each variant's required payload, or give this producer a precise return type separate from the broader contract.",
      preferDiscriminatedUnion:
        "This object type combines a boolean status with optional payloads. If success and failure are mutually exclusive, consider a discriminated union such as `{ ok: true; data: T } | { ok: false; error: E }`.",
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
      context.report({ node: result.reportNode, messageId: "preferProducedVariants",
        ...(fix !== null && { fix }), data: { tag: result.tag } });
    }

    function checkTypeLiteral(
      typeLiteral: Pick<ESTree.TSTypeLiteral, "members">,
      reportNode: Node,
    ): void {
      if (looksLikeMutuallyExclusiveState(typeLiteral) && !reportedContracts.has(reportNode)) {
        reportedContracts.add(reportNode);
        const fix = inlineProducerFix(reportNode);
        context.report({
          node: reportNode,
          messageId: "preferDiscriminatedUnion",
          ...(fix !== null && { fix }),
        });
      }
    }

    function inlineProducerFix(reportNode: Node): ReportFix | null {
      if (reportNode.type !== "TSTypeAnnotation" || reportNode.parent.type !== "FunctionDeclaration") return null;
      const owner = reportNode.parent;
      const result = discriminatedUnionReturns(owner, context.sourceCode);
      return result === undefined ? null : privateVariantReturn(context.sourceCode, context.filename, owner, result);
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
        // Alias declarations can follow their producers. Always give the legacy
        // contract diagnostic precedence independent of declaration order.
        for (const producer of producers) checkProducer(producer);
      },
      TSInterfaceDeclaration(node): void {
        if (node.extends.length > 0) {
          return;
        }
        // An interface body is structurally an object type literal; reuse the
        // same membership analysis by treating its `body.body` as members.
        checkTypeLiteral({ members: node.body.body }, node);
      },
      TSTypeLiteral(node): void {
        // "TSTypeAliasDeclaration > TSTypeLiteral" in the original.
        if (node.parent.type === "TSTypeAliasDeclaration") checkTypeLiteral(node, node.parent);
        const annotation = inlineReturnTypeLiteral(node);
        if (annotation !== null) checkTypeLiteral(node, annotation);
      },
    };
  },
});


function privateVariantReturn(sourceCode: SourceCode, filename: string, owner: Producer, result: DiscriminatedReturn): ReportFix | null {
  const annotation = owner.returnType?.typeAnnotation;
  if (owner.type !== "FunctionDeclaration" || owner.id === null || !returnsOnlyConditionalObject(owner) || annotation?.type !== "TSTypeLiteral" || result.reportNode !== owner.returnType || result.returned.length !== 2 ||
    sourceCode.getCommentsInside(owner).length > 0 || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename) ||
    !retainsNamedTypeUses(sourceCode, annotation)) return null;
  const variants = result.returned.map((properties) => privateVariantType(properties, result, sourceCode));
  if (variants.some((variant) => variant === null)) return null;
  const text = `${variants.join(" | ")}${sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")}`;
  return (fixer) => fixer.replaceText(annotation, text);
}

/** `function f() { return test ? { … } : { … }; }`, sync and non-generic. */
function returnsOnlyConditionalObject(fn: ESTree.Function): boolean {
  if (fn.async || fn.generator || isPresent(fn.typeParameters)) return false;
  const statements = fn.body?.body ?? [];
  const [returned] = statements;
  return statements.length === 1 && returned?.type === "ReturnStatement" &&
    returned.argument?.type === "ConditionalExpression" &&
    returned.argument.consequent.type === "ObjectExpression" && returned.argument.alternate.type === "ObjectExpression";
}

function privateVariantType(properties: ReadonlyMap<string, Node>, result: DiscriminatedReturn, sourceCode: SourceCode): string | null {
  if ([...properties.values()].some((value) => value.type !== "Literal" ||
    (typeof value.value === "object" && value.value !== null) || (typeof value.value === "number" && !Number.isFinite(value.value)))) return null;
  const fields: string[] = [];
  for (const [name, member] of result.members) {
    const value = properties.get(name);
    if (value === undefined) continue;
    const annotation = member.typeAnnotation?.typeAnnotation;
    if (annotation === undefined) return null;
    const type = name === result.tag ? sourceCode.getText(value) : sourceCode.getText(annotation);
    fields.push(`${member.readonly ? "readonly " : ""}${sourceCode.getText(member.key)}: ${type}`);
  }
  return `{ ${fields.join("; ")} }`;
}
