/**
 * @fileoverview prefer-await-in-async-return — prefer explicit async control flow for proven built-in Promise calls.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-await-in-async-return.test.ts
 */

import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";
import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import {
  resolveVariable,
  isGlobalReference,
  unwrapExpression,
} from "./_scope.js";
import {
  createTypeAliasEnvironment,
  hasVisibleTypeBinding,
  resolvedTypeMatches,
} from "./_type-alias-resolution.js";

type MessageIds = "preferAwait" | "preferAwaitCall";
type Options = readonly [
  { readonly scope: "async-return" | "all-promise-calls" },
];

export const PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION = {
  summary:
    "Prefer explicit `await` for proven Promise `.then` calls; the default scope checks direct async returns.",
  rationale:
    "Promise callback chains mix explicit async control flow with nested callbacks, making sequencing and failure handling harder to read.",
  remediation:
    "Consider awaiting the Promise and returning the transformed value with ordinary async statements. Preserve catch boundaries, callback behavior, and observable scheduling when rewriting manually.",
  category: "maintainability",
  since: "15.6.3",
  limitations: [
    "The default async-return scope checks one directly returned `.then` call with an inline callback. The all-promise-calls scope checks direct calls to built-in Promise/PromiseLike.then, including optional and literal-computed calls, without automatic rewrites.",
    "The receiver must be proven by genuine same-file syntax: an unshadowed built-in Promise factory, an explicit Promise/PromiseLike annotation, a local async function, or a known Promise chain. Imported and inferred external return types remain unresolved. The default async-return scope excludes rejection handlers and named callbacks. This is not the upstream return-await policy and no scheduling equivalence is promised.",
    "The default async-return scope excludes direct loader callbacks passed to resolved `React.lazy` and `next/dynamic` imports because returning the module Promise is their framework contract.",
    "All-promise-calls requires that same Promise evidence and excludes unproven/custom thenables, dynamic property names, property reads, destructuring, and extracted method aliases. Catch and finally remain available. Framework callback exclusions apply only to the default async-return scope.",
  ],
  examples: [
    {
      id: "explicit-async-transform",
      title: "Use explicit async control flow",
      outcome: "no-match",
      files: [
        {
          path: "src/load.ts",
          source:
            "async function load() { const value = await Promise.resolve(1); return value + 1; }",
        },
      ],
      focusPath: "src/load.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "returned-then-transform",
      title: "Do not directly return a Promise callback chain from async code",
      outcome: "match",
      files: [
        {
          path: "src/load.ts",
          source:
            "async function load() { return Promise.resolve(1).then((value) => value + 1); }",
        },
      ],
      focusPath: "src/load.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type RuntimeFunction = ESTree.ArrowFunctionExpression | ESTree.Function;

/** A direct return owned by an ordinary async function, never an async generator. */
function directAsyncReturnOwner(
  node: ESTree.CallExpression,
): RuntimeFunction | null {
  const parent = node.parent;
  if (parent.type === "ArrowFunctionExpression" && parent.body === node) {
    return parent.async && !parent.generator ? parent : null;
  }
  if (parent.type !== "ReturnStatement" || parent.argument !== node) {
    return null;
  }

  let owner: ESTree.Node | null = parent.parent;
  while (owner !== null && !isRuntimeFunction(owner)) {
    owner = owner.parent;
  }
  return owner !== null && owner.async && !owner.generator ? owner : null;
}

function isRuntimeFunction(node: ESTree.Node): node is RuntimeFunction {
  return (
    node.type === "ArrowFunctionExpression" ||
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression"
  );
}

/** A single `.then` transform whose rewrite does not need catch/finally logic. */
function promiseThenReceiver(
  node: ESTree.CallExpression,
): ESTree.Expression | null {
  const callee = node.callee;
  if (
    callee.type !== "MemberExpression" ||
    callee.computed ||
    callee.optional ||
    callee.property.type !== "Identifier" ||
    callee.property.name !== "then" ||
    node.optional ||
    node.arguments.length !== 1
  ) {
    return null;
  }
  const callback = node.arguments[0];
  if (
    callback === undefined ||
    (callback.type !== "ArrowFunctionExpression" &&
      callback.type !== "FunctionExpression")
  ) {
    return null;
  }
  return callee.object;
}

function directThenReceiver(
  node: ESTree.CallExpression,
): ESTree.Expression | null {
  const callee = node.callee;
  if (callee.type !== "MemberExpression") return null;
  return staticMemberName(callee) === "then" ? callee.object : null;
}

const PROMISE_FACTORIES: readonly string[] = [
  "resolve",
  "reject",
  "all",
  "allSettled",
  "race",
  "any",
];
const PROMISE_CHAIN_METHODS: readonly string[] = ["then", "catch", "finally"];

function staticMemberName(member: ESTree.MemberExpression): string | null {
  const property = member.property;
  if (!member.computed)
    return property.type === "Identifier" ? property.name : null;
  if (property.type === "Literal" && typeof property.value === "string")
    return property.value;
  if (property.type === "TemplateLiteral" && property.expressions.length === 0)
    return property.quasis[0]?.value.cooked ?? null;
  return null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-await-in-async-return",
  documentation: PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer explicit `await` for proven Promise `.then` calls; the default scope checks direct async returns.",
    },
    schema: [
      {
        type: "object",
        properties: {
          scope: {
            type: "string",
            enum: ["async-return", "all-promise-calls"],
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      preferAwait:
        "This async function directly returns a Promise `.then` transform. Await the Promise, then return the transformed value with explicit async control flow.",
      preferAwaitCall:
        "This call uses built-in Promise.then(). Use async/await, preserving rejection handling and observable scheduling when rewriting.",
    },
  },
  defaultOptions: [{ scope: "async-return" }],
  create(context, [options]) {
    const origin = sourceOrigin(context);
    if (isGeneratedFile(origin.filename, origin.text)) return {};
    const source = context.sourceCode;
    const types = createTypeAliasEnvironment(source.ast, source.visitorKeys);
    const isPromiseReceiver = (
      expression: ESTree.Node,
      seen = new Set<ESTree.Node>(),
    ): boolean => {
      const node = unwrapExpression(expression);
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "ImportExpression") return true;
      if (node.type === "NewExpression")
        return isGlobalReference(source, node.callee, "Promise");
      if (node.type === "CallExpression") return isPromiseCall(node, seen);
      return node.type === "Identifier" && isPromiseVariable(node, seen);
    };
    const isPromiseCall = (
      node: ESTree.CallExpression,
      seen: Set<ESTree.Node>,
    ): boolean => {
      const callee = unwrapExpression(node.callee);
      if (callee.type === "MemberExpression") {
        const name = staticMemberName(callee);
        if (name === null) return false;
        if (
          PROMISE_FACTORIES.includes(name) &&
          isGlobalReference(source, callee.object, "Promise")
        )
          return true;
        return (
          PROMISE_CHAIN_METHODS.includes(name) &&
          isPromiseReceiver(callee.object, seen)
        );
      }
      if (isGlobalReference(source, callee, "fetch")) return true;
      if (callee.type !== "Identifier") return false;
      const callable = localCallable(source, callee);
      if (callable === null) return false;
      if ("async" in callable && callable.async && !callable.generator)
        return true;
      return (
        callable.returnType != null &&
        hasPromiseType(callable.returnType.typeAnnotation)
      );
    };
    const isPromiseVariable = (
      node: Extract<ESTree.Node, { type: "Identifier" }>,
      seen: Set<ESTree.Node>,
    ): boolean => {
      const variable = resolveVariable(source, node);
      if (variable === null || variable.defs.length !== 1) return false;
      const definition = variable.defs[0]?.node;
      const annotation =
        definition?.type === "VariableDeclarator" &&
        definition.id.type === "Identifier"
          ? definition.id.typeAnnotation?.typeAnnotation
          : variable.defs[0]?.name.type === "Identifier"
            ? variable.defs[0].name.typeAnnotation?.typeAnnotation
            : undefined;
      if (annotation != null) return hasPromiseType(annotation);
      if (
        variable.references.some(
          (reference) => reference.isWrite() && !reference.init,
        )
      )
        return false;
      return (
        definition?.type === "VariableDeclarator" &&
        definition.init !== null &&
        isPromiseReceiver(definition.init, seen)
      );
    };
    const hasPromiseType = (
      type: ESTree.TSType,
      seen = new Set<ESTree.Node>(),
    ): boolean =>
      resolvedTypeMatches(type, types, (current, matches) => {
        if (current.type === "TSUnionType") {
          const members = current.types.filter(
            (member) =>
              member.type !== "TSNullKeyword" &&
              member.type !== "TSUndefinedKeyword",
          );
          return members.length > 0 && members.every(matches);
        }
        if (
          current.type !== "TSTypeReference" ||
          current.typeName.type !== "Identifier"
        )
          return false;
        const identifier = current.typeName;
        if (
          (identifier.name === "Promise" ||
            identifier.name === "PromiseLike") &&
          !hasVisibleTypeBinding(identifier.name, identifier, types)
        )
          return true;
        const declaration = resolveVariable(source, identifier)?.defs[0]?.node;
        if (
          declaration?.type !== "ClassDeclaration" ||
          seen.has(declaration) ||
          declaration.superClass === null ||
          declaration.body.body.some(
            (member) =>
              "key" in member &&
              !member.static &&
              ((member.key.type === "Identifier" &&
                member.key.name === "then") ||
                (member.key.type === "Literal" && member.key.value === "then")),
          )
        )
          return false;
        seen.add(declaration);
        return isGlobalReference(source, declaration.superClass, "Promise");
      });
    const frameworkLoaders = new Set<Variable>();
    const rememberFrameworkLoader = (
      identifier: Extract<ESTree.Node, { type: "Identifier" }>,
    ): void => {
      const variable = resolveVariable(context.sourceCode, identifier);
      if (variable !== null) frameworkLoaders.add(variable);
    };
    const isFrameworkLoaderCallback = (owner: RuntimeFunction): boolean => {
      const parent = owner.parent;
      if (
        parent.type !== "CallExpression" ||
        parent.arguments[0] !== owner ||
        parent.callee.type !== "Identifier"
      )
        return false;
      const variable = resolveVariable(context.sourceCode, parent.callee);
      return variable !== null && frameworkLoaders.has(variable);
    };

    return {
      ImportDeclaration(node): void {
        if (node.source.value === "react") {
          for (const specifier of node.specifiers) {
            if (
              specifier.type === "ImportSpecifier" &&
              (specifier.imported.type === "Identifier"
                ? specifier.imported.name
                : specifier.imported.value) === "lazy"
            )
              rememberFrameworkLoader(specifier.local);
          }
        }
        if (node.source.value === "next/dynamic") {
          for (const specifier of node.specifiers) {
            if (specifier.type === "ImportDefaultSpecifier")
              rememberFrameworkLoader(specifier.local);
          }
        }
      },
      CallExpression(node): void {
        if (options.scope === "all-promise-calls") {
          const receiver = directThenReceiver(node);
          if (receiver !== null && isPromiseReceiver(receiver)) {
            context.report({ node, messageId: "preferAwaitCall" });
          }
          return;
        }
        const owner = directAsyncReturnOwner(node);
        if (owner === null || isFrameworkLoaderCallback(owner)) return;
        const receiver = promiseThenReceiver(node);
        if (receiver === null || !isPromiseReceiver(receiver)) {
          return;
        }
        context.report({ node, messageId: "preferAwait" });
      },
    };
  },
});

function localCallable(
  source: SourceCode,
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
): RuntimeFunction | null {
  const variable = resolveVariable(source, identifier);
  if (
    variable === null ||
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return null;
  const declaration =
    variable.defs.length === 1 ? variable.defs[0]?.node : null;
  if (
    declaration?.type === "FunctionDeclaration" ||
    declaration?.type === "TSDeclareFunction"
  )
    return declaration;
  if (declaration?.type !== "VariableDeclarator") return null;
  const initializer = declaration.init;
  return initializer?.type === "ArrowFunctionExpression" ||
    initializer?.type === "FunctionExpression"
    ? initializer
    : null;
}
