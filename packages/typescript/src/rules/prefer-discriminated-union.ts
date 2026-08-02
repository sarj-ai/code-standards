/**
 * @fileoverview prefer-discriminated-union — a boolean status flag beside many optionals makes illegal states representable.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-discriminated-union.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "preferDiscriminatedUnion";
type Options = readonly [];

/**
 * Boolean-typed member names that read as a success/error status discriminant.
 */
const STATUS_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "success",
  "ok",
  "error",
  "failed",
  "isError",
]);

const MIN_OPTIONAL_MEMBERS = 2;

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

/**
 * Returns true when the object type literal has BOTH a boolean-typed status
 * member AND at least `MIN_OPTIONAL_MEMBERS` optional members.
 */
function looksLikeMutuallyExclusiveState(
  typeLiteral: TSESTree.TSTypeLiteral,
): boolean {
  let hasStatusBoolean = false;
  let optionalCount = 0;
  let optionalPayloadCount = 0;

  for (const member of typeLiteral.members) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) {
      continue;
    }

    if (member.optional) {
      optionalCount += 1;
      // A non-boolean optional can land in the wrong branch. All-boolean
      // records are independent flag sets, not state machines.
      if (!isBooleanTyped(member)) {
        optionalPayloadCount += 1;
      }
    }

    const name = getMemberName(member);
    if (
      name !== null &&
      STATUS_MEMBER_NAMES.has(name) &&
      isBooleanTyped(member)
    ) {
      hasStatusBoolean = true;
    }
  }

  return (
    hasStatusBoolean &&
    optionalCount >= MIN_OPTIONAL_MEMBERS &&
    optionalPayloadCount >= 1
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-discriminated-union",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag object types with a boolean status member and at least two optional members, including a non-boolean payload.",
    },
    schema: [],
    messages: {
      preferDiscriminatedUnion:
        "This object type uses a boolean status flag alongside several optional fields, which lets illegal states be representable. Model it as a `z.discriminatedUnion` / discriminated union (e.g. `{ ok: true; data: T } | { ok: false; error: E }`) to make illegal states unrepresentable.",
    },
  },
  defaultOptions: [],
  create(context) {
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
        // An interface body is structurally an object type literal; reuse the
        // same membership analysis by treating its `body.body` as members.
        const synthetic: TSESTree.TSTypeLiteral = {
          ...node.body,
          type: AST_NODE_TYPES.TSTypeLiteral,
          members: node.body.body,
        } as TSESTree.TSTypeLiteral;
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
