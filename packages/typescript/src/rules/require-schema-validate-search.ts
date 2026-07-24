/**
 * @fileoverview Flag TanStack Router `validateSearch` implementations that
 * hand-roll "validation" with `as` casts. A cast asserts a shape without
 * checking it, so malformed query params flow into the app typed as clean
 * data. Use a schema validator (e.g. `zodValidator(searchSchema)` from
 * `@tanstack/zod-adapter`, or `searchSchema.parse`) so the search params are
 * actually validated at runtime.
 *
 * Deliberately narrow: only fires on a property literally named
 * `validateSearch` whose value is a function containing at least one cast —
 * `as` form or angle-bracket `<T>x` form (`as const` exempt: it narrows
 * rather than lies). Two exemptions:
 *   - Casts that feed a validator are fine: an argument (transitively) of a
 *     call whose callee property is `parse` / `safeParse` / `decode` — e.g.
 *     the rule's own recommended remedy
 *     `validateSearch: (s) => schema.parse(s as Record<string, unknown>)` —
 *     is validated at runtime regardless of the cast.
 *   - Test files, where route stubs are fixtures rather than real routes.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "castInValidateSearch";
type Options = readonly [];

/** Callee property names whose calls validate their input at runtime. */
const VALIDATOR_METHODS: ReadonlySet<string> = new Set([
  "parse",
  "safeParse",
  "decode",
]);

function isConstTypeAnnotation(typeAnnotation: TSESTree.TypeNode): boolean {
  return (
    typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
    typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
    typeAnnotation.typeName.name === "const"
  );
}

/** True for a call whose callee property is a runtime validator (`schema.parse(...)`). */
function isValidatorCall(node: TSESTree.CallExpression): boolean {
  return (
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    VALIDATOR_METHODS.has(node.callee.property.name)
  );
}

/**
 * Depth-first search for the first offending cast under `node`: a non-`const`
 * TSAsExpression or TSTypeAssertion that is not (transitively) an argument of
 * a validator call. `insideValidatorArg` is threaded through the descent so a
 * cast feeding `schema.parse(...)` is exempt however deeply it nests.
 */
function findCastExpression(
  node: TSESTree.Node,
  insideValidatorArg: boolean,
): TSESTree.TSAsExpression | TSESTree.TSTypeAssertion | null {
  if (
    (node.type === AST_NODE_TYPES.TSAsExpression ||
      node.type === AST_NODE_TYPES.TSTypeAssertion) &&
    !isConstTypeAnnotation(node.typeAnnotation) &&
    !insideValidatorArg
  ) {
    return node;
  }

  if (
    node.type === AST_NODE_TYPES.CallExpression &&
    isValidatorCall(node)
  ) {
    // The callee itself is still in scope; only the arguments are validated.
    const inCallee = findCastExpression(node.callee, insideValidatorArg);
    if (inCallee !== null) {
      return inCallee;
    }
    for (const arg of node.arguments) {
      const found = findCastExpression(arg, true);
      if (found !== null) {
        return found;
      }
    }
    return null;
  }

  for (const key of Object.keys(node)) {
    if (key === "parent") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    const children = Array.isArray(value) ? value : [value];
    for (const child of children) {
      if (
        child !== null &&
        typeof child === "object" &&
        "type" in child &&
        typeof (child as { type: unknown }).type === "string"
      ) {
        const found = findCastExpression(
          child as TSESTree.Node,
          insideValidatorArg,
        );
        if (found !== null) {
          return found;
        }
      }
    }
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-schema-validate-search",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `as` casts inside hand-rolled `validateSearch` functions; use a schema validator (e.g. zodValidator) so search params are validated at runtime.",
    },
    schema: [],
    messages: {
      castInValidateSearch:
        "This `validateSearch` asserts the search-param shape with `as` instead of validating it — malformed query params flow through typed as clean data. Use a schema validator (e.g. `zodValidator(searchSchema)` or `searchSchema.parse`) instead of casting.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }

    return {
      Property(node: TSESTree.Property): void {
        const isValidateSearchKey =
          (!node.computed &&
            node.key.type === AST_NODE_TYPES.Identifier &&
            node.key.name === "validateSearch") ||
          (node.key.type === AST_NODE_TYPES.Literal &&
            node.key.value === "validateSearch");
        if (!isValidateSearchKey) {
          return;
        }

        if (
          node.value.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
          node.value.type !== AST_NODE_TYPES.FunctionExpression
        ) {
          return;
        }

        const cast = findCastExpression(node.value.body, false);
        if (cast !== null) {
          context.report({ node: cast, messageId: "castInValidateSearch" });
        }
      },
    };
  },
});
