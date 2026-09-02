/**
 * @fileoverview prefer-server-actions — an internal `/api/*` mutation hand-rolls the transport, types and error path a Server Action gets from the framework.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-server-actions.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferServerAction";

export const PREFER_SERVER_ACTIONS_DOCUMENTATION = {
  summary: "Prefer Next.js Server Actions over same-origin API mutations.",
  rationale: "Server Actions preserve typed application calls and avoid an internal JSON request-response boundary.",
  remediation: "Move the mutation into a Server Action and invoke that action from the React client.",
  category: "architecture",
  limitations: ["Only statically recognizable /api/ mutations, including explicitly configured literal deployment base paths, in modules with positive Next.js evidence are reported."],
  examples: [
    { id: "server-action-call", title: "Call a Server Action", outcome: "no-match", files: [{ path: "app/tasks/page.tsx", source: "import { createTask } from './actions'; await createTask(input);" }], focusPath: "app/tasks/page.tsx", expectedCount: 0, public: true },
    { id: "api-mutation", title: "Do not mutate through an API route", outcome: "match", files: [{ path: "app/tasks/page.tsx", source: "'use client'; await fetch('/api/tasks', { method: 'POST', body });" }], focusPath: "app/tasks/page.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
export interface RuleOptions {
  readonly basePaths?: readonly string[];
}
type Options = readonly [RuleOptions?];

const MUTATION_METHODS: ReadonlySet<string> = new Set(["POST", "PUT", "DELETE", "PATCH"]);
const AXIOS_MUTATION_METHODS: ReadonlySet<string> = new Set(["post", "put", "delete", "patch"]);

const SKIP_FILE_REGEX =
  /(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|-(?:test|spec)\.[jt]sx?$|\/tests?\/|\/__tests__\/|\/__testfixtures__\/|\/scripts?\/|\/app\/api\/.*\/route\.[jt]sx?$|\/pages\/api\/)/;

const NON_REACT_FRAMEWORK_RE =
  /^(?:@angular\/|@nestjs\/|vue$|vue\/|svelte$|svelte\/|solid-js$|solid-js\/|@ember\/|rxjs$|rxjs\/)/;

const NEXT_MODULE_PATH_RE = /(?:^|[/\\])(?:app|pages)[/\\]/u;
const BASE_PATH_RE = /^\/(?!$)(?!.*[?#])(?:[^/]+\/)*[^/]+$/u;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

function getScope(
  context: Ctx,
  node: TSESTree.Node,
): Scope.Scope {
  return context.sourceCode.getScope(node);
}

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
  apiPrefixes: readonly string[],
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return apiPrefixes.some((prefix) => resolved.value.startsWith(prefix));
  }
  if (resolved.type === "TemplateLiteral") {
    const firstQuasi = resolved.quasis[0];
    const cooked = firstQuasi?.value.cooked;
    return typeof cooked === "string" && apiPrefixes.some((prefix) => cooked.startsWith(prefix));
  }
  if (resolved.type === "BinaryExpression" && resolved.operator === "+") {
    return isApiUrl(resolved.left, context, apiPrefixes);
  }
  return false;
}

function isValidBasePath(basePath: string): boolean {
  return (
    BASE_PATH_RE.test(basePath) &&
    !basePath.split("/").some((segment) => segment === "." || segment === "..")
  );
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

function isFunctionArgument(
  node: TSESTree.CallExpressionArgument,
  context: Ctx,
): boolean {
  const resolved = resolveNode(node, context);
  if (
    resolved?.type === "ArrowFunctionExpression" ||
    resolved?.type === "FunctionExpression"
  ) {
    return true;
  }
  if (node.type !== "Identifier") return false;

  let scope: Scope.Scope | null = getScope(context, node);
  while (scope) {
    const variable = scope.set.get(node.name);
    if (
      variable?.defs.some((definition) => definition.type === "FunctionName")
    ) {
      return true;
    }
    scope = scope.upper;
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

export default createRule<Options, MessageIds>({
  name: "prefer-server-actions",
  documentation: PREFER_SERVER_ACTIONS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer Next.js Server Actions over same-origin API mutations.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          basePaths: {
            type: "array",
            uniqueItems: true,
            items: {
              type: "string",
              pattern: "^/(?!$)(?!.*[?#])(?:[^/]+/)*[^/]+$",
            },
          },
        },
      },
    ],
    messages: {
      preferServerAction:
        "Mutation against a same-origin API route — prefer a Next.js Server Action for type-safety and to avoid the JSON round-trip.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const filename = context.filename;
    if (SKIP_FILE_REGEX.test(filename)) {
      return {};
    }

    const isNonReactFramework = context.sourceCode.ast.body.some(
      (node) =>
        node.type === "ImportDeclaration" &&
        typeof node.source.value === "string" &&
        NON_REACT_FRAMEWORK_RE.test(node.source.value),
    );
    const hasUseClientDirective = context.sourceCode.ast.body.some(
      (node) =>
        node.type === "ExpressionStatement" &&
        node.expression.type === "Literal" &&
        node.expression.value === "use client",
    );
    const hasNextImport = context.sourceCode.ast.body.some(
        (node) =>
          node.type === "ImportDeclaration" &&
          typeof node.source.value === "string" &&
          (node.source.value === "next" || node.source.value.startsWith("next/")),
      );
    const hasNextEvidence =
      hasNextImport ||
      (hasUseClientDirective && NEXT_MODULE_PATH_RE.test(filename));

    if (!hasNextEvidence) {
      return {};
    }

    const apiPrefixes = [
      "/api/",
      ...new Set(
        (options?.basePaths ?? [])
          .filter(isValidBasePath)
          .map((basePath) => `${basePath}/api/`),
      ),
    ];

    return {
      CallExpression(node) {
        if (isNonReactFramework) return;
        let isMutation = false;

        // 1. Standard fetch('/api/orders', { method: 'POST' })
        if (
          node.callee.type === "Identifier" &&
          node.callee.name === "fetch"
        ) {
          const urlArg = node.arguments[0];
          if (urlArg && urlArg.type !== "SpreadElement" && isApiUrl(urlArg, context, apiPrefixes)) {
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
            const hasHandlerArg = node.arguments.some(
              (arg) =>
                arg.type !== "SpreadElement" &&
                isFunctionArgument(arg, context),
            );
            if (
              urlArg &&
              urlArg.type !== "SpreadElement" &&
              !hasHandlerArg &&
              isApiUrl(urlArg, context, apiPrefixes)
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
                isApiUrl(urlNode, context, apiPrefixes) &&
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
