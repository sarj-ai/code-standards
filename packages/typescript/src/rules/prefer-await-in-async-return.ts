/**
 * @fileoverview prefer-await-in-async-return — replace a directly returned Promise `.then` transform with explicit async control flow.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-await-in-async-return.test.ts
 */

import {
  ASTUtils,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferAwait";
type Options = readonly [];

export const preferAwaitInAsyncReturnDocumentation = {
  summary:
    "Prefer explicit `await` when an async function directly returns one typed Promise `.then` transform.",
  rationale:
    "Mixing a directly returned Promise callback into otherwise async control flow makes sequencing and failures harder to read.",
  remediation:
    "Await the Promise, then return the transformed value with ordinary async statements.",
  category: "maintainability",
  since: "15.6.3",
  limitations: [
    "Only a single directly returned `.then` call with an inline callback is checked.",
    "The receiver must be proven Promise-like by TypeScript; untyped files and larger chains are intentionally ignored.",
    "Direct loader callbacks passed to resolved `React.lazy` and `next/dynamic` imports are excluded because returning the module Promise is their framework contract.",
  ],
  examples: [
    {
      id: "explicit-async-transform",
      title: "Use explicit async control flow",
      outcome: "no-match",
      files: [{
        path: "src/load.ts",
        source:
          "async function load() { const value = await Promise.resolve(1); return value + 1; }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "returned-then-transform",
      title: "Do not directly return a Promise callback chain from async code",
      outcome: "match",
      files: [{
        path: "src/load.ts",
        source:
          "async function load() { return Promise.resolve(1).then((value) => value + 1); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type RuntimeFunction =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;

/** A direct return owned by an ordinary async function, never an async generator. */
function directAsyncReturnOwner(node: TSESTree.CallExpression): RuntimeFunction | null {
  const parent = node.parent;
  if (
    parent.type === AST_NODE_TYPES.ArrowFunctionExpression &&
    parent.body === node
  ) {
    return parent.async && !parent.generator ? parent : null;
  }
  if (
    parent.type !== AST_NODE_TYPES.ReturnStatement ||
    parent.argument !== node
  ) {
    return null;
  }

  let owner: TSESTree.Node | undefined = parent.parent;
  while (owner !== undefined && !isRuntimeFunction(owner)) {
    owner = owner.parent;
  }
  return owner !== undefined && owner.async && !owner.generator ? owner : null;
}

function isRuntimeFunction(node: TSESTree.Node): node is RuntimeFunction {
  return (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.FunctionExpression
  );
}

/** A single `.then` transform whose rewrite does not need catch/finally logic. */
function promiseThenReceiver(
  node: TSESTree.CallExpression,
): TSESTree.Expression | null {
  const callee = node.callee;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.optional ||
    callee.property.type !== AST_NODE_TYPES.Identifier ||
    callee.property.name !== "then" ||
    node.optional ||
    node.arguments.length !== 1
  ) {
    return null;
  }
  const callback = node.arguments[0];
  if (
    callback === undefined ||
    (callback.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      callback.type !== AST_NODE_TYPES.FunctionExpression)
  ) {
    return null;
  }
  return callee.object;
}

function isProvenPromiseLike(
  node: TSESTree.Expression,
  services: ParserServicesWithTypeInformation,
): boolean {
  const checker = services.program.getTypeChecker();
  const tsNode = services.esTreeNodeToTSNodeMap.get(node);
  const receiverType = checker.getTypeAtLocation(tsNode);
  if (
    (receiverType.flags &
      (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never)) !==
    0
  ) {
    return false;
  }
  const thenSymbol = checker.getPropertyOfType(receiverType, "then");
  const hasBuiltInPromiseDeclaration = thenSymbol?.declarations?.some(
    (declaration) => {
      let owner: ts.Node | undefined = declaration.parent;
      while (owner !== undefined && !ts.isInterfaceDeclaration(owner)) {
        owner = owner.parent;
      }
      return (
        owner !== undefined &&
        (owner.name.text === "Promise" || owner.name.text === "PromiseLike") &&
        services.program.isSourceFileDefaultLibrary(owner.getSourceFile())
      );
    },
  ) ?? false;
  return hasBuiltInPromiseDeclaration;
}

export default createRule<Options, MessageIds>({
  name: "prefer-await-in-async-return",
  documentation: preferAwaitInAsyncReturnDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer explicit `await` when an async function directly returns one typed Promise `.then` transform.",
    },
    schema: [],
    messages: {
      preferAwait:
        "This async function directly returns a Promise `.then` transform. Await the Promise, then return the transformed value with explicit async control flow.",
    },
  },
  defaultOptions: [],
  create(context) {
    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }
    if (services === null) return {};
    type ScopeVariable = NonNullable<ReturnType<typeof ASTUtils.findVariable>>;
    const frameworkLoaders = new Set<ScopeVariable>();
    const rememberFrameworkLoader = (identifier: TSESTree.Identifier): void => {
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable !== null) frameworkLoaders.add(variable);
    };
    const isFrameworkLoaderCallback = (owner: RuntimeFunction): boolean => {
      const parent = owner.parent;
      if (
        parent.type !== AST_NODE_TYPES.CallExpression ||
        parent.arguments[0] !== owner ||
        parent.callee.type !== AST_NODE_TYPES.Identifier
      ) return false;
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(parent.callee), parent.callee.name);
      return variable !== null && frameworkLoaders.has(variable);
    };

    return {
      ImportDeclaration(node): void {
        if (node.source.value === "react") {
          for (const specifier of node.specifiers) {
            if (
              specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              (specifier.imported.type === AST_NODE_TYPES.Identifier
                ? specifier.imported.name
                : specifier.imported.value) === "lazy"
            ) rememberFrameworkLoader(specifier.local);
          }
        }
        if (node.source.value === "next/dynamic") {
          for (const specifier of node.specifiers) {
            if (specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier) rememberFrameworkLoader(specifier.local);
          }
        }
      },
      CallExpression(node): void {
        const owner = directAsyncReturnOwner(node);
        if (owner === null || isFrameworkLoaderCallback(owner)) return;
        const receiver = promiseThenReceiver(node);
        if (receiver === null || !isProvenPromiseLike(receiver, services)) {
          return;
        }
        context.report({ node, messageId: "preferAwait" });
      },
    };
  },
});
