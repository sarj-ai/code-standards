/**
 * @fileoverview require-zod-form-validation — `formData.get(k)` hands back an attacker-controlled `FormDataEntryValue | null`.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-zod-form-validation.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { ZOD_SCHEMA_NAME_RE } from "./_zod.js";

type MessageIds = "missingZodValidation";
type Options = readonly [];

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/** Match `parse` and `safeParse` only on Zod-shaped receivers. */
const isZodParseCall = (node: TSESTree.Node): boolean => {
  if (node.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = node.callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  if (callee.computed) return false;
  if (callee.property.type !== AST_NODE_TYPES.Identifier) return false;
  const method = callee.property.name;
  if (
    method !== "parse" &&
    method !== "safeParse" &&
    method !== "parseAsync" &&
    method !== "safeParseAsync"
  ) {
    return false;
  }
  return looksLikeZodSchema(callee.object);
};

/** Recognize the supported Zod receiver naming conventions. */
const looksLikeZodSchema = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;
  while (true) {
    if (current.type === AST_NODE_TYPES.Identifier) {
      return current.name === "z" || ZOD_SCHEMA_NAME_RE.test(current.name);
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      current = current.object;
      continue;
    }
    return false;
  }
};

/** Match an optionally awaited `<x>.formData()` call. */
const isFormDataMethodCall = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;
  if (current.type === AST_NODE_TYPES.AwaitExpression) {
    current = current.argument;
  }
  if (current.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = current.callee;
  return (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    callee.property.name === "formData"
  );
};

export default createRule<Options, MessageIds>({
  name: "require-zod-form-validation",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
    },
    schema: [],
    messages: {
      missingZodValidation:
        "FormData parsing must use Zod schema validation (e.g., Schema.parse() / Schema.safeParse())",
    },
  },
  defaultOptions: [],
  create(context: Ctx) {
    if (isTestFile(context.filename)) {
      return {};
    }

    // Recognize conventional names and bindings initialized by `.formData()`.
    const isFormSourceIdentifier = (node: TSESTree.Node): boolean => {
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      if (/formdata/i.test(node.name)) return true;

      let scope: Scope.Scope | null = context.sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.set.get(node.name);
        if (variable !== undefined && variable.defs.length === 1) {
          const def = variable.defs[0];
          if (
            def !== undefined &&
            def.type === "Variable" &&
            def.node.type === AST_NODE_TYPES.VariableDeclarator &&
            def.node.init !== null
          ) {
            return isFormDataMethodCall(def.node.init);
          }
          return false;
        }
        scope = scope.upper;
      }
      return false;
    };

    const isFormDataGetCall = (node: TSESTree.CallExpression): boolean => {
      const callee = node.callee;
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      if (
        callee.property.type !== AST_NODE_TYPES.Identifier ||
        callee.property.name !== "get"
      ) {
        return false;
      }
      return isFormSourceIdentifier(callee.object);
    };

    const hasZodParseAncestor = (node: TSESTree.Node): boolean => {
      let parent: TSESTree.Node | null | undefined = node.parent;
      while (parent !== null && parent !== undefined) {
        if (isZodParseCall(parent)) return true;
        parent = parent.parent;
      }
      return false;
    };

    const isInstanceofNarrowing = (node: TSESTree.Node): boolean => {
      const parent: TSESTree.Node | null | undefined = node.parent;
      return (
        parent !== null &&
        parent !== undefined &&
        parent.type === AST_NODE_TYPES.BinaryExpression &&
        parent.operator === "instanceof" &&
        parent.left === node &&
        parent.right.type === AST_NODE_TYPES.Identifier &&
        (parent.right.name === "File" || parent.right.name === "Blob")
      );
    };

    /** The identifier this `.get(...)` call is bound to, or null. */
    const boundDeclarator = (
      node: TSESTree.CallExpression,
    ): TSESTree.VariableDeclarator | null => {
      let current: TSESTree.Node = node;
      let parent = current.parent;
      while (
        (parent.type === AST_NODE_TYPES.TSAsExpression ||
          parent.type === AST_NODE_TYPES.TSSatisfiesExpression ||
          parent.type === AST_NODE_TYPES.TSNonNullExpression ||
          parent.type === AST_NODE_TYPES.ChainExpression) &&
        parent.expression === current
      ) {
        current = parent;
        parent = current.parent;
      }
      if (
        parent.type === AST_NODE_TYPES.VariableDeclarator &&
        parent.init === current &&
        parent.id.type === AST_NODE_TYPES.Identifier
      ) {
        return parent;
      }
      return null;
    };

    /** Is any read of this binding validated (Zod parse, or `instanceof File`)? */
    const bindingIsValidated = (
      declarator: TSESTree.VariableDeclarator,
    ): boolean => {
      const variable = context.sourceCode.getDeclaredVariables(declarator)[0];
      if (variable === undefined) return false;
      return variable.references.some(
        (ref) =>
          hasZodParseAncestor(ref.identifier) ||
          isInstanceofNarrowing(ref.identifier),
      );
    };

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isFormDataGetCall(node)) return;

        if (hasZodParseAncestor(node) || isInstanceofNarrowing(node)) return;

        const declarator = boundDeclarator(node);
        if (declarator !== null && bindingIsValidated(declarator)) return;

        context.report({
          node,
          messageId: "missingZodValidation",
        });
      },
    };
  },
});
