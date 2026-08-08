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
    };
  },
});
