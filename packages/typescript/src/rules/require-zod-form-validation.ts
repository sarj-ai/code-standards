/**
 * @fileoverview Require Zod validation on values read out of a `FormData`.
 * `formData.get(k)` returns `FormDataEntryValue | null` — an unvalidated,
 * attacker-controlled value. Pipe it through a schema before use.
 *
 * Validation is recognised two ways:
 *   - INLINE: the `.get(...)` call sits inside a Zod `.parse(...)` /
 *     `.safeParse(...)` — found by walking up the parent chain.
 *   - VIA A BINDING: the value is bound and validated one or more statements
 *     later, which is how a real handler reads. Tracked through the scope
 *     manager (the same approach `prefer-schema-for-api-payload` uses for
 *     `response.json()`), so this is not reported:
 *       const tokenRaw = formData.get("t");
 *       const parsed = ZForm.safeParse({ t: typeof tokenRaw === "string" ? tokenRaw : undefined });
 *
 * A binding narrowed by `instanceof File` / `instanceof Blob` is also exempt: a
 * Zod schema has nothing useful to say about a `File`, and `instanceof` IS the
 * validation for that branch.
 *
 * A Zod receiver is recognised by name — `Schema`-suffixed (`userSchema`), the
 * `Z<Capital>` house form (`ZUser`), or the bare `z` builder — matching
 * `zod-naming-convention`, which accepts both conventions.
 */

import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { ZOD_SCHEMA_NAME_RE } from "./_zod.js";

type MessageIds = "missingZodValidation";
type Options = readonly [];

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/**
 * Walk down a (possibly chained) receiver expression and decide whether it
 * originates from something that looks like a Zod schema — the bare `z` builder
 * (`z.object({...}).parse(...)`), a `Schema`-suffixed identifier
 * (`userSchema.parse(...)`), or a `Z`-prefixed identifier (`ZUser.parse(...)`).
 * Non-Zod receivers like `JSON` / `Date` are intentionally rejected.
 */
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

/**
 * Matches a Zod validation call: `<ZodSchema>.parse(...)` or
 * `<ZodSchema>.safeParse(...)`. Keys off the *receiver* looking like a Zod
 * schema rather than the method name alone, so `JSON.parse(...)` /
 * `Date.parse(...)` are NOT treated as validation.
 */
const isZodParseCall = (node: TSESTree.Node): boolean => {
  if (node.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = node.callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  if (callee.computed) return false;
  if (callee.property.type !== AST_NODE_TYPES.Identifier) return false;
  const method = callee.property.name;
  if (method !== "parse" && method !== "safeParse") return false;
  return looksLikeZodSchema(callee.object);
};

/**
 * Matches an (optionally awaited) `<x>.formData()` call — the canonical way a
 * `FormData` object is obtained from a `Request` / `Response`.
 */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
    // A receiver is a FormData source if its name reads like form data, or if
    // it is a binding initialized from a `.formData()` call.
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

    // Walk up from `node` looking for a surrounding Zod `.parse(...)` /
    // `.safeParse(...)` call. `.parent` is `null` at the Program root, so we
    // must guard for both null and undefined.
    const hasZodParseAncestor = (node: TSESTree.Node): boolean => {
      let parent: TSESTree.Node | null | undefined = node.parent;
      while (parent !== null && parent !== undefined) {
        if (isZodParseCall(parent)) return true;
        parent = parent.parent;
      }
      return false;
    };

    // `x instanceof File` / `x instanceof Blob` — a Zod schema adds nothing over
    // the `instanceof` narrowing for a binary upload.
    const isInstanceofNarrowing = (node: TSESTree.Node): boolean => {
      const parent: TSESTree.Node | null | undefined = node.parent;
      return (
        parent !== null &&
        parent !== undefined &&
        parent.type === AST_NODE_TYPES.BinaryExpression &&
        parent.operator === "instanceof" &&
        parent.left === node
      );
    };

    /** The identifier this `.get(...)` call is bound to, or null. */
    const boundDeclarator = (
      node: TSESTree.CallExpression,
    ): TSESTree.VariableDeclarator | null => {
      const parent = node.parent;
      if (
        parent.type === AST_NODE_TYPES.VariableDeclarator &&
        parent.init === node &&
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
