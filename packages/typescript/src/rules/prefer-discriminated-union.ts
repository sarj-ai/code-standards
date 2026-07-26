/**
 * @fileoverview Flag object types that model mutually-exclusive states with a
 * boolean status flag plus many optional members. A shape like
 * `{ success: boolean; data?: T; error?: E; code?: number }` encodes "success
 * vs. error" implicitly and lets illegal states (e.g. `success: true` with an
 * `error`) be representable.
 *
 * Such shapes should be modelled as a discriminated union, e.g.
 * `{ ok: true; data: T } | { ok: false; error: E }`, so the compiler enforces
 * that exactly one branch's fields are present.
 *
 * This is the TypeScript mirror of the Python rule SARJ005.
 *
 * A PAYLOAD IS REQUIRED. The defect is that a payload can be present in the
 * wrong branch (`success: true` carrying an `error`), so the shape must have at
 * least one optional member that is NOT itself a boolean. An all-boolean record
 * is a FLAG SET, not a state machine: every combination of its members is legal,
 * so there is no illegal state to make unrepresentable and a discriminated union
 * would be strictly worse.
 *
 * Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
 * zustand, 2026-07): the rule fired exactly once, and it was this false
 * positive — `swr/src/_internal/types.ts:1191`,
 * `interface StateDependencies { data?: boolean; error?: boolean;
 * isValidating?: boolean; isLoading?: boolean }`. That is SWR's dependency
 * TRACKER: each flag records "did the render read this field?", and all sixteen
 * combinations are meaningful.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
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
      // A non-boolean optional is a PAYLOAD — the thing that can end up in the
      // wrong branch. An all-boolean record is a flag set; see @fileoverview.
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "prefer-discriminated-union",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag object types with a boolean status flag and many optionals; model them as a discriminated union instead.",
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
