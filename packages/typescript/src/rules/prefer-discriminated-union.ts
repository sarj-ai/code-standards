/**
 * @fileoverview prefer-discriminated-union — a boolean status flag beside many optionals makes illegal states representable.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-discriminated-union.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "preferDiscriminatedUnion";
type Options = readonly [];

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

const FUNCTION_RETURN_OWNER_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.TSDeclareFunction,
  AST_NODE_TYPES.TSEmptyBodyFunctionExpression,
  AST_NODE_TYPES.TSFunctionType,
  AST_NODE_TYPES.TSMethodSignature,
]);

/**
 * Returns true for the canonical flat result shape: one required positive
 * boolean status plus optional success and failure payloads.
 */
function looksLikeMutuallyExclusiveState(
  typeLiteral: TSESTree.TSTypeLiteral,
): boolean {
  let statusMemberCount = 0;
  let hasFailurePayload = false;
  let hasSuccessPayload = false;

  for (const member of typeLiteral.members) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) {
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
      continue;
    }
    if (FAILURE_MEMBER_NAMES.has(name)) {
      hasFailurePayload = true;
    } else if (SUCCESS_PAYLOAD_MEMBER_NAMES.has(name)) {
      hasSuccessPayload = true;
    }
  }

  return (
    statusMemberCount === REQUIRED_STATUS_MEMBER_COUNT &&
    hasFailurePayload &&
    hasSuccessPayload
  );
}

/**
 * Returns the property key name for a member if it is a plain identifier or
 * string-literal property signature, otherwise `null`.
 */
function getMemberName(member: TSESTree.TypeElement): string | null {
  if (member.type !== AST_NODE_TYPES.TSPropertySignature) {
    return null;
  }
  const { key } = member;
  if (key.type === AST_NODE_TYPES.Identifier) {
    return key.name;
  }
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

/**
 * Whether a property signature is annotated with `boolean`.
 */
function isBooleanTyped(member: TSESTree.TSPropertySignature): boolean {
  return (
    member.typeAnnotation?.typeAnnotation.type ===
    AST_NODE_TYPES.TSBooleanKeyword
  );
}

/** The whole inline object returned by a function, directly or through `Promise`. */
function inlineReturnTypeLiteral(
  node: TSESTree.TSTypeLiteral,
): TSESTree.TSTypeAnnotation | null {
  let annotation: TSESTree.TSTypeAnnotation | null = null;
  if (node.parent.type === AST_NODE_TYPES.TSTypeAnnotation) {
    annotation = node.parent;
  } else if (
    node.parent.type === AST_NODE_TYPES.TSTypeParameterInstantiation &&
    node.parent.params.length === 1 &&
    node.parent.params[0] === node &&
    node.parent.parent.type === AST_NODE_TYPES.TSTypeReference &&
    node.parent.parent.typeName.type === AST_NODE_TYPES.Identifier &&
    node.parent.parent.typeName.name === "Promise" &&
    node.parent.parent.parent.type === AST_NODE_TYPES.TSTypeAnnotation
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
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag flat result objects with a required positive boolean status and optional success/failure payloads.",
    },
    schema: [],
    messages: {
      preferDiscriminatedUnion:
        "This object type uses a boolean status flag alongside several optional fields, which lets illegal states be representable. Model it as a `z.discriminatedUnion` / discriminated union (e.g. `{ ok: true; data: T } | { ok: false; error: E }`) to make illegal states unrepresentable.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
      return {};
    }

    function checkTypeLiteral(
      typeLiteral: TSESTree.TSTypeLiteral,
      reportNode: TSESTree.Node,
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
        node: TSESTree.TSInterfaceDeclaration,
      ): void {
        if (node.extends.length > 0) {
          return;
        }
        // An interface body is structurally an object type literal; reuse the
        // same membership analysis by treating its `body.body` as members.
        const synthetic: TSESTree.TSTypeLiteral = {
          ...node.body,
          type: AST_NODE_TYPES.TSTypeLiteral,
          members: node.body.body,
        };
        checkTypeLiteral(synthetic, node);
      },
      "TSTypeAliasDeclaration > TSTypeLiteral"(
        node: TSESTree.TSTypeLiteral,
      ): void {
        checkTypeLiteral(node, node.parent);
      },
      TSTypeLiteral(node: TSESTree.TSTypeLiteral): void {
        const annotation = inlineReturnTypeLiteral(node);
        if (annotation !== null) checkTypeLiteral(node, annotation);
      },
    };
  },
});
