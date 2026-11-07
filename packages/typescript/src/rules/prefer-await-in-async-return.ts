/**
 * @fileoverview prefer-await-in-async-return — replace a directly returned Promise `.then` transform with explicit async control flow.
 *
 * Port of the 18.x `prefer-await-in-async-return` rule. Typed: without
 * tsrs types it reports nothing, as the original returns no visitors without
 * type services. The walk collects `.then` calls that pass the syntactic
 * checks; `Program:exit` proves their receivers are built-in Promises.
 */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { directArgumentCall, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { type NativeTypes, nativeTypes, type TsNode } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-await-in-async-return";

type RuntimeFunction = ESTree.ArrowFunctionExpression | ESTree.Function;
type MessageId = "preferAwait" | "preferAwaitCall";

/** A direct return owned by an ordinary async function, never an async generator. */
function directAsyncReturnOwner(node: ESTree.CallExpression): RuntimeFunction | null {
  const parent = parentOf(node);
  if (parent?.type === "ArrowFunctionExpression" && parent.body === node) {
    return parent.async && !parent.generator ? parent : null;
  }
  if (parent?.type !== "ReturnStatement" || parent.argument !== node) return null;
  for (let owner = parentOf(parent); owner !== null; owner = parentOf(owner)) {
    if (owner.type === "ArrowFunctionExpression" || owner.type === "FunctionDeclaration" || owner.type === "FunctionExpression") {
      return owner.async && !owner.generator ? owner : null;
    }
  }
  return null;
}

/** A single `.then` transform whose rewrite does not need catch/finally logic. */
function promiseThenReceiver(node: ESTree.CallExpression): Node | null {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression" || callee.optional || getPropertyName(callee) !== "then" ||
    node.optional || node.arguments.length !== 1) return null;
  const argument = node.arguments[0];
  const callback = argument === undefined ? undefined : unwrapExpression(argument);
  if (callback === undefined || (callback.type !== "ArrowFunctionExpression" && callback.type !== "FunctionExpression")) return null;
  return callee.object;
}

function directThenReceiver(node: ESTree.CallExpression): Node | null {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return null;
  const property = callee.property;
  const isThen = callee.computed
    ? (property.type === "Literal" && property.value === "then") ||
      (property.type === "TemplateLiteral" && property.expressions.length === 0 && property.quasis[0]?.value.cooked === "then")
    : property.type === "Identifier" && property.name === "then";
  return isThen ? callee.object : null;
}

function isProvenPromiseLike(native: NativeTypes, node: Node): boolean {
  const tsNode = native.node(node);
  if (tsNode === undefined) return false;
  const receiverType = native.checker.getNonNullableType(native.checker.getTypeAtLocation(tsNode));
  const members = receiverType.isUnionType() ? receiverType.getTypes() : [receiverType];
  return members.every((member) => isBuiltInPromiseType(native, member));
}

function isBuiltInPromiseType(native: NativeTypes, type: Type): boolean {
  const flags = native.sync.TypeFlags;
  if ((type.flags & (flags.Any | flags.Unknown | flags.Never)) !== 0) return false;
  const declarations = native.checker.getPropertyOfType(type, "then")?.declarations;
  if (declarations === undefined || declarations.length === 0) return false;
  return declarations.every((handle) => {
    // Default-library metadata is cheap; only then fetch the declaration to find its interface.
    if (native.program.getSourceFileMetadataByPath(handle.path)?.isDefaultLibrary !== true) return false;
    const declaration = handle.resolve(native.program.getProject()) as TsNode | undefined;
    let owner: TsNode | undefined = declaration?.parent;
    while (owner !== undefined && !native.ast.isInterfaceDeclaration(owner)) owner = owner.parent;
    return owner !== undefined && (owner.name.text === "Promise" || owner.name.text === "PromiseLike") &&
      native.program.isSourceFileDefaultLibrary(owner.getSourceFile());
  });
}

export default defineRule({
  meta: {
    defaultOptions: [{ scope: "async-return" }],
    type: "suggestion",
    docs: {
      description:
        "Prefer explicit `await` for proven Promise `.then` calls; the default scope checks direct async returns.",
      url: docsUrl(NAME),
    },
    schema: [{
      type: "object",
      properties: { scope: { description: "Check async return statements or every promise-valued call.", type: "string", enum: ["async-return", "all-promise-calls"] } },
      additionalProperties: false,
    }],
    messages: {
      preferAwait:
        "This async function directly returns a Promise `.then` transform. Await the Promise, then return the transformed value with explicit async control flow.",
      preferAwaitCall:
        "This call uses built-in Promise.then(). Use async/await, preserving rejection handling and observable scheduling when rewriting.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let allPromiseCalls = false;
    let frameworkLoaders = new Set<TsVariable>();
    let candidates: { readonly node: ESTree.CallExpression; readonly receiver: Node; readonly messageId: MessageId }[] = [];

    const rememberFrameworkLoader = (identifier: ESTree.BindingIdentifier): void => {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable !== null) frameworkLoaders.add(variable);
    };
    const isFrameworkLoaderCallback = (owner: RuntimeFunction): boolean => {
      const parent = directArgumentCall(owner);
      if (parent === null || parent.arguments[0] !== outerExpression(owner)) return false;
      const callee = unwrapExpression(parent.callee);
      if (callee.type !== "Identifier") return false;
      const variable = findVariable(context.sourceCode.getScope(callee), callee.name);
      return variable !== null && frameworkLoaders.has(variable);
    };

    return {
      before() {
        frameworkLoaders = new Set();
        candidates = [];
        const options = context.options[0] as { readonly scope?: string } | undefined;
        allPromiseCalls = options?.scope === "all-promise-calls";
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      ImportDeclaration(node) {
        if (node.source.value === "react") {
          for (const specifier of node.specifiers) {
            if (specifier.type === "ImportSpecifier" &&
              (specifier.imported.type === "Identifier" ? specifier.imported.name : specifier.imported.value) === "lazy") {
              rememberFrameworkLoader(specifier.local);
            }
          }
        }
        if (node.source.value === "next/dynamic") {
          for (const specifier of node.specifiers) {
            if (specifier.type === "ImportDefaultSpecifier") rememberFrameworkLoader(specifier.local);
          }
        }
      },
      CallExpression(node) {
        if (allPromiseCalls) {
          const receiver = directThenReceiver(node);
          if (receiver !== null) candidates.push({ node, receiver, messageId: "preferAwaitCall" });
          return;
        }
        const owner = directAsyncReturnOwner(node);
        if (owner === null || isFrameworkLoaderCallback(owner)) return;
        const receiver = promiseThenReceiver(node);
        if (receiver !== null) candidates.push({ node, receiver, messageId: "preferAwait" });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const proven = tsrs.run((file) => {
          const native = nativeTypes(file);
          return candidates.map((candidate) => isProvenPromiseLike(native, candidate.receiver));
        });
        if (proven === null) return;
        candidates.forEach(({ node, messageId }, i) => {
          if (proven[i] === true) context.report({ node, messageId });
        });
      },
    };
  },
});
