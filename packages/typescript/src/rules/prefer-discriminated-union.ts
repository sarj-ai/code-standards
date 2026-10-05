/**
 * @fileoverview prefer-discriminated-union — a boolean status flag beside many optionals makes illegal states representable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-discriminated-union.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import type { ESTree } from "@oxlint/plugins";


type MessageIds = "preferDiscriminatedUnion";
type Options = readonly [];

export const PREFER_DISCRIMINATED_UNION_DOCUMENTATION = {
  summary: "Flag flat result objects with a required positive boolean status and optional success/failure payloads.",
  rationale: "When success and failure are mutually exclusive outcomes, a boolean plus optional branch data permits contradictory and incomplete states.",
  remediation: "If the outcomes are mutually exclusive, represent each branch as a discriminated union member with its required payload.",
  category: "correctness",
  limitations: ["Only local object shapes with recognized non-computed status and payload names are inspected. Names do not prove that partial-success outcomes are forbidden; review the domain before changing its representation."],
  examples: [
    { id: "explicit-result-branches", title: "Use explicit result branches", outcome: "no-match", files: [{ path: "src/result.ts", source: "type Result = { ok: true; data: string } | { ok: false; error: string };" }], focusPath: "src/result.ts", expectedCount: 0, public: true },
    { id: "optional-result-payloads", title: "Do not make both result payloads optional", outcome: "match", files: [{ path: "src/result.ts", source: "type Result = { ok: boolean; data?: string; error?: string };" }], focusPath: "src/result.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

const FUNCTION_RETURN_OWNER_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set([
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
  typeLiteral: ESTree.TSTypeLiteral,
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
  if (node.parent?.type === "TSTypeAnnotation") {
    annotation = node.parent;
  } else if (
    node.parent?.type === "TSTypeParameterInstantiation" &&
    node.parent.params.length === 1 &&
    node.parent.params[0] === node &&
    node.parent.parent?.type === "TSTypeReference" &&
    node.parent.parent?.typeName.type === "Identifier" &&
    node.parent.parent?.typeName.name === "Promise" &&
    node.parent.parent.parent?.type === "TSTypeAnnotation"
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

export default createRule<Options, MessageIds>({
  name: "prefer-discriminated-union",
  documentation: PREFER_DISCRIMINATED_UNION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag flat result objects with a required positive boolean status and optional success/failure payloads.",
    },
    schema: [],
    messages: {
      preferDiscriminatedUnion:
        "This object type combines a boolean status with optional payloads. If success and failure are mutually exclusive, consider a discriminated union such as `{ ok: true; data: T } | { ok: false; error: E }`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    ) {
      return {};
    }

    function checkTypeLiteral(
      typeLiteral: ESTree.TSTypeLiteral,
      reportNode: ESTree.Node,
    ): void {
      if (looksLikeMutuallyExclusiveState(typeLiteral)) {
        context.report({
          node: reportNode,
          messageId: "preferDiscriminatedUnion",
        });
      }
    }

    return {
      TSInterfaceDeclaration(
        node: ESTree.TSInterfaceDeclaration,
      ): void {
        if (node.extends.length > 0) {
          return;
        }
        // An interface body is structurally an object type literal; reuse the
        // same membership analysis by treating its `body.body` as members.
        const synthetic: ESTree.TSTypeLiteral = {
          ...node.body,
          type: "TSTypeLiteral",
          members: node.body.body,
        };
        checkTypeLiteral(synthetic, node);
      },
      "TSTypeAliasDeclaration > TSTypeLiteral"(
        node: ESTree.TSTypeLiteral,
      ): void {
        checkTypeLiteral(node, node.parent);
      },
      TSTypeLiteral(node: ESTree.TSTypeLiteral): void {
        const annotation = inlineReturnTypeLiteral(node);
        if (annotation !== null) checkTypeLiteral(node, annotation);
      },
    };
  },
});
