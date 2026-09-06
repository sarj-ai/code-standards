/**
 * @fileoverview prefer-server-actions — an internal `/api/*` mutation hand-rolls the transport, types and error path a Server Action gets from the framework.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-server-actions.test.ts
 */

import { ASTUtils, type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferServerAction";

export const PREFER_SERVER_ACTIONS_DOCUMENTATION = {
  summary: "Prefer Next.js Server Actions over same-origin API mutations.",
  rationale: "Server Actions can remove a hand-written internal API wrapper while retaining typed application calls. Client invocations still cross a network and serialization boundary.",
  remediation: "Consider a Server Action for application-owned mutations; preserve authorization, input validation and any public API consumers.",
  category: "architecture",
  limitations: ["Only statically recognizable /api/ mutations through global fetch or proven Axios imports/instances in use-client modules are reported. Custom wrapper provenance, mutated configuration and unknown option overrides are not inferred; server boundaries and route handlers are excluded."],
  examples: [
    { id: "server-action-call", title: "Call a Server Action", outcome: "no-match", files: [{ path: "app/tasks/page.tsx", source: "import { createTask } from './actions'; await createTask(input);" }], focusPath: "app/tasks/page.tsx", expectedCount: 0, public: true },
    { id: "api-mutation", title: "Do not mutate through an API route", outcome: "match", files: [{ path: "app/tasks/page.tsx", source: "'use client'; await fetch('/api/tasks', { method: 'POST', body });" }], focusPath: "app/tasks/page.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
export interface RuleOptions {
  readonly basePath?: string;
}
type Options = readonly [RuleOptions?];

const MUTATION_METHODS: ReadonlySet<string> = new Set(["POST", "PUT", "DELETE", "PATCH"]);
const AXIOS_MUTATION_METHODS: ReadonlySet<string> = new Set(["post", "put", "delete", "patch"]);

const SKIP_FILE_REGEX =
  /(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|-(?:test|spec)\.[jt]sx?$|\/tests?\/|\/__tests__\/|\/__testfixtures__\/|\/scripts?\/|(?:^|\/)app(?:\/.*)?\/route\.[jt]sx?$|(?:^|\/)middleware\.[jt]sx?$|\/pages\/api\/)/;

const NON_REACT_FRAMEWORK_RE =
  /^(?:@angular\/|@nestjs\/|vue$|vue\/|svelte$|svelte\/|solid-js$|solid-js\/|@ember\/|rxjs$|rxjs\/)/;

const BASE_PATH_RE = /^\/(?!$)(?!.*[?#])(?:[^/]+\/)*[^/]+$/u;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

function getScope(
  context: Ctx,
  node: TSESTree.Node,
): Scope.Scope {
  return context.sourceCode.getScope(node);
}

function resolvesToGlobalFetch(
  context: Ctx,
  identifier: TSESTree.Identifier,
): boolean {
  let scope: Scope.Scope | null = getScope(context, identifier);
  while (scope) {
    const variable = scope.set.get(identifier.name);
    if (variable !== undefined) return variable.defs.length === 0;
    scope = scope.upper;
  }
  return true;
}

function resolveNode(
  node: TSESTree.Node | null | undefined,
  context: Ctx,
): TSESTree.Node | null {
  if (!node) return null;
  if (node.type !== "Identifier") return node;

  const variable = ASTUtils.findVariable(getScope(context, node), node.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
  if (definition?.type !== "Variable" || definition.parent.kind !== "const" || definition.node.init === null || variable?.references.some((reference) => reference.isWrite() && reference.init !== true)) return node;
  if (definition.node.init.type === "ObjectExpression" && variable?.references.some((reference) => reference.identifier !== node && reference.init !== true)) return node;
  return definition.node.init;
}

function isAxiosClient(node: TSESTree.Node, context: Ctx, seen = new Set<TSESTree.Node>()): boolean {
  if (node.type !== "Identifier" || seen.has(node)) return false;
  seen.add(node);
  const variable = ASTUtils.findVariable(getScope(context, node), node.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
  if (definition === undefined || variable?.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  if (variable?.references.some((reference) => {
    if (reference.init === true) return false;
    const identifier = reference.identifier;
    const parent = identifier.parent;
    if (parent.type === "CallExpression" && parent.callee === identifier) return false;
    return parent.type !== "MemberExpression" || parent.object !== identifier || parent.computed ||
      parent.parent.type !== "CallExpression" || parent.parent.callee !== parent;
  })) return false;
  if (definition.type === "ImportBinding") {
    const declaration = definition.parent;
    return declaration.type === "ImportDeclaration" && declaration.source.value === "axios" && declaration.importKind !== "type" &&
      (definition.node.type === "ImportDefaultSpecifier" || (definition.node.type === "ImportSpecifier" && definition.node.importKind !== "type" && (definition.node.imported.type === "Identifier" ? definition.node.imported.name : definition.node.imported.value) === "default"));
  }
  if (definition.type !== "Variable" || definition.parent.kind !== "const") return false;
  const init = definition.node.init;
  return init?.type === "CallExpression" && init.arguments.length <= 1 && hasLocalAxiosOptions(init.arguments[0], context) && init.callee.type === "MemberExpression" && !init.callee.computed &&
    init.callee.property.type === "Identifier" && init.callee.property.name === "create" && isAxiosClient(init.callee.object, context, seen);
}

function hasLocalAxiosOptions(node: TSESTree.Node | undefined, context: Ctx): boolean {
  if (node === undefined) return true;
  const options = resolveNode(node, context);
  return options?.type === "ObjectExpression" && options.properties.every((property) =>
    property.type === "Property" && !property.computed && property.kind === "init" &&
    !["baseURL", "adapter"].includes(property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? String(property.key.value) : "baseURL"),
  );
}

function isApiUrl(
  node: TSESTree.Node | null | undefined,
  context: Ctx,
  apiPrefixes: readonly string[],
): boolean {
  const resolved = resolveNode(node, context);
  if (!resolved) return false;

  if (resolved.type === "Literal" && typeof resolved.value === "string") {
    return apiPrefixes.some(
      (prefix) => resolved.value === prefix.slice(0, -1) || resolved.value.startsWith(prefix),
    );
  }
  if (resolved.type === "TemplateLiteral") {
    const firstQuasi = resolved.quasis[0];
    const cooked = firstQuasi?.value.cooked;
    return typeof cooked === "string" && apiPrefixes.some(
      (prefix) => cooked === prefix.slice(0, -1) || cooked.startsWith(prefix),
    );
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
  if (objNode.properties.some((property) => property.type === "SpreadElement" || property.computed)) return null;
  for (const prop of [...objNode.properties].reverse()) {
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
          basePath: {
            type: "string",
            pattern: "^/(?!$)(?!.*[?#])(?!(?:.*/)?\\.\\.?(?:/|$))(?:[^/]+/)*[^/]+$",
          },
        },
      },
    ],
    messages: {
      preferServerAction:
        "This client mutation targets a same-origin API route. Consider a Server Action to remove the hand-written API wrapper; retain authorization and validation, since the call still crosses a network boundary.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const filename = context.filename.replaceAll("\\", "/");
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
        node.directive === "use client",
    );
    const hasUseServerDirective = context.sourceCode.ast.body.some(
        (node) =>
          node.type === "ExpressionStatement" &&
          node.directive === "use server",
      );
    const importsServerOnly = context.sourceCode.ast.body.some(
      (node) =>
        node.type === "ImportDeclaration" &&
        typeof node.source.value === "string" &&
        (node.source.value === "server-only" || node.source.value === "next/server"),
    );

    if (!hasUseClientDirective || hasUseServerDirective || importsServerOnly) {
      return {};
    }

    const apiPrefixes = ["/api/"];
    if (options?.basePath !== undefined && isValidBasePath(options.basePath)) {
      apiPrefixes.push(`${options.basePath}/api/`);
    }

    return {
      CallExpression(node) {
        if (isNonReactFramework) return;
        let isMutation = false;

        // 1. Standard fetch('/api/orders', { method: 'POST' })
        if (
          node.callee.type === "Identifier" &&
          node.callee.name === "fetch" &&
          resolvesToGlobalFetch(context, node.callee)
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
        // Axios method calls require import or instance provenance.
        else if (
          node.callee.type === "MemberExpression" &&
          node.callee.property.type === "Identifier" &&
          !node.callee.computed && isAxiosClient(node.callee.object, context)
        ) {
          const methodName = node.callee.property.name.toLowerCase();
          if (AXIOS_MUTATION_METHODS.has(methodName)) {
            const config = node.arguments[methodName === "delete" ? 1 : 2];
            if (!hasLocalAxiosOptions(config, context)) return;
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
          isAxiosClient(node.callee, context)
        ) {
          const firstArg = node.arguments[0];
          if (firstArg && firstArg.type !== "SpreadElement") {
            const configArg = resolveNode(firstArg, context);
            if (configArg && configArg.type === "ObjectExpression") {
              if (!hasLocalAxiosOptions(firstArg, context)) return;
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
