/**
 * @fileoverview Prefer Next.js Server Actions over /api/* mutations.
 *
 * Flags mutations against internal `/api/*` URLs (POST/PUT/DELETE/PATCH) via
 * `fetch`, axios-style helpers, or direct axios/request calls. GET requests
 * and external URLs are ignored. Tests, scripts, and Next.js route handlers
 * are skipped because Server Actions don't apply there.
 *
 * The member branch (`api.post('/api/x')`) intentionally skips calls that pass
 * a function argument (e.g. `router.post('/api/x', handler)`) so Express-style
 * route *definitions* aren't mistaken for client-side mutations.
 *
 * NON-REACT FRAMEWORKS ARE SKIPPED. "Use a Server Action" is not advice an
 * Angular, Vue, Svelte or Solid module can act on — the feature does not exist
 * outside React/Next. Corpus sweep (2220 files across zod / TanStack Query /
 * react-router / swr / zustand, 2026-07): 9 hits, of which 3 were Angular
 * services —
 * `query/examples/angular/auto-refetching/src/app/services/tasks.service.ts:38`
 * (`lastValueFrom(this.#http.post('/api/tasks', task))`, an `HttpClient`
 * injection) — and 4 were jscodeshift input/output fixtures under
 * `__testfixtures__/`, which are text a codemod transforms rather than code that
 * runs. Both are now skipped; the 2 genuine React hits still fire.
 *
 * References:
 *   - https://nextjs.org/docs/app/building-your-application/data-fetching/server-actions-and-mutations
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

type MessageIds = "preferServerAction";
type Options = readonly [];

const MUTATION_METHODS = new Set(["POST", "PUT", "DELETE", "PATCH"]);
const AXIOS_MUTATION_METHODS = new Set(["post", "put", "delete", "patch"]);

const SKIP_FILE_REGEX =
  /(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|-(?:test|spec)\.[jt]sx?$|\/tests?\/|\/__tests__\/|\/__testfixtures__\/|\/scripts?\/|\/app\/api\/.*\/route\.[jt]sx?$|\/pages\/api\/)/;

/**
 * Import sources that prove the module belongs to a framework where Server
 * Actions do not exist. See @fileoverview for the corpus evidence.
 */
const NON_REACT_FRAMEWORK_RE =
  /^(?:@angular\/|@nestjs\/|vue$|vue\/|svelte$|svelte\/|solid-js$|solid-js\/|@ember\/|rxjs$|rxjs\/)/;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

function getScope(
  context: Ctx,
  node: TSESTree.Node,
): Scope.Scope {
  return context.sourceCode.getScope(node);
}

/**
 * Walk up the scope chain looking for a variable declared with a single
 * initializer; if found, return the initializer expression so we can analyze
 * it. Falls back to the original node when resolution is not possible.
 */
function resolveNode(
  node: TSESTree.Node | null | undefined,
  context: Ctx,
): TSESTree.Node | null {
  if (!node) return null;
  if (node.type !== "Identifier") return node;

  let scope: Scope.Scope | null = getScope(context, node);
  while (scope) {
    const variable = scope.set.get(node.name);
    if (variable && variable.defs.length === 1) {
      const def = variable.defs[0];
      if (def && def.type === "Variable") {
        const declarator = def.node;
        if (
          declarator.type === "VariableDeclarator" &&
          declarator.init
        ) {
          return declarator.init;
        }
      }
    }
    scope = scope.upper;
  }
  return node;
}

function isApiUrl(
  node: TSESTree.Node | null | undefined,
  context: Ctx,
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return resolved.value.startsWith("/api/");
  }
  if (resolved.type === "TemplateLiteral") {
    const firstQuasi = resolved.quasis[0];
    const cooked = firstQuasi?.value.cooked;
    return typeof cooked === "string" && cooked.startsWith("/api/");
  }
  if (resolved.type === "BinaryExpression" && resolved.operator === "+") {
    return isApiUrl(resolved.left, context);
  }
  return false;
}

function isMutationMethod(
  node: TSESTree.Node | null | undefined,
  context: Ctx,
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return MUTATION_METHODS.has(resolved.value.toUpperCase());
  }

  if (
    resolved.type === "TemplateLiteral" &&
    resolved.expressions.length === 0
  ) {
    const val = resolved.quasis.map((q) => q.value.cooked).join("");
    return MUTATION_METHODS.has(val.toUpperCase());
  }

  if (resolved.type === "ConditionalExpression") {
    return (
      isMutationMethod(resolved.consequent, context) ||
      isMutationMethod(resolved.alternate, context)
    );
  }

  if (resolved.type === "LogicalExpression" && resolved.operator === "||") {
    return (
      isMutationMethod(resolved.left, context) ||
      isMutationMethod(resolved.right, context)
    );
  }

  return false;
}

function getPropertyNode(
  objNode: TSESTree.Node | null | undefined,
  propName: string,
): TSESTree.Node | null {
  if (!objNode || objNode.type !== "ObjectExpression") return null;
  for (const prop of objNode.properties) {
    if (prop.type !== "Property") continue;
    let keyName: string | null = null;
    if (prop.key.type === "Identifier" && !prop.computed) {
      keyName = prop.key.name;
    } else if (
      prop.key.type === "Literal" &&
      typeof prop.key.value === "string"
    ) {
      keyName = prop.key.value;
    }
    if (keyName === propName) {
      // Skip destructuring patterns — they're not valid as config values.
      if (
        prop.value.type === "AssignmentPattern" ||
        prop.value.type === "ArrayPattern" ||
        prop.value.type === "ObjectPattern"
      ) {
        return null;
      }
      return prop.value;
    }
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "prefer-server-actions",
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer Next.js Server Actions over /api/* mutations.",
    },
    schema: [],
    messages: {
      preferServerAction:
        "Mutation against /api/* — prefer a Next.js Server Action for type-safety and to avoid the JSON round-trip.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename;
    if (SKIP_FILE_REGEX.test(filename)) {
      return {};
    }

    // Set by the ImportDeclaration visitor. Imports are hoisted to the top of a
    // module, so every one is seen before the first CallExpression below.
    let isNonReactFramework = false;

    return {
      ImportDeclaration(node) {
        if (
          typeof node.source.value === "string" &&
          NON_REACT_FRAMEWORK_RE.test(node.source.value)
        ) {
          isNonReactFramework = true;
        }
      },
      CallExpression(node) {
        if (isNonReactFramework) return;
        let isMutation = false;

        // 1. Standard fetch('/api/orders', { method: 'POST' })
        if (
          node.callee.type === "Identifier" &&
          node.callee.name === "fetch"
        ) {
          const urlArg = node.arguments[0];
          if (urlArg && urlArg.type !== "SpreadElement" && isApiUrl(urlArg, context)) {
            const initArg = node.arguments[1];
            if (initArg && initArg.type !== "SpreadElement") {
              const resolvedInit = resolveNode(initArg, context);
              const methodNode = getPropertyNode(resolvedInit, "method");
              if (methodNode && isMutationMethod(methodNode, context)) {
                isMutation = true;
              }
            }
          }
        }
        // 2. Custom wrappers or Axios: api.post('/api/orders') or axios.put('/api/orders')
        else if (
          node.callee.type === "MemberExpression" &&
          node.callee.property.type === "Identifier" &&
          !node.callee.computed
        ) {
          const methodName = node.callee.property.name.toLowerCase();
          if (AXIOS_MUTATION_METHODS.has(methodName)) {
            const urlArg = node.arguments[0];
            // Skip Express-style route definitions like
            // `router.post('/api/x', handler)`: a function argument means this
            // is registering a handler, not issuing a client mutation.
            const hasHandlerArg = node.arguments.some(
              (arg) =>
                arg.type === "ArrowFunctionExpression" ||
                arg.type === "FunctionExpression",
            );
            if (
              urlArg &&
              urlArg.type !== "SpreadElement" &&
              !hasHandlerArg &&
              isApiUrl(urlArg, context)
            ) {
              isMutation = true;
            }
          }
        }
        // 3. Direct axios/request call: axios({ method: 'post', url: '/api/orders' })
        else if (
          node.callee.type === "Identifier" &&
          (node.callee.name === "axios" || node.callee.name === "request")
        ) {
          const firstArg = node.arguments[0];
          if (firstArg && firstArg.type !== "SpreadElement") {
            const configArg = resolveNode(firstArg, context);
            if (configArg && configArg.type === "ObjectExpression") {
              const urlNode = getPropertyNode(configArg, "url");
              const methodNode = getPropertyNode(configArg, "method");
              if (
                urlNode &&
                isApiUrl(urlNode, context) &&
                methodNode &&
                isMutationMethod(methodNode, context)
              ) {
                isMutation = true;
              }
            }
          }
        }

        if (isMutation) {
          context.report({ node, messageId: "preferServerAction" });
        }
      },
    };
  },
});
