/**
 * @fileoverview prefer-schema-for-http-headers — Validate HTTP header scalars through a named Zod schema.
 */

import { defineRule, type Context, type ESTree, type Node, type TsVariable } from "../types.js";
import { isErasedExpression, outerExpression, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { nativeRuntimeUnchanged } from "../utils/native-runtime-unchanged.js";
import {
  stableValueBinding,
  typeOnlyReference,
  writtenMember,
} from "../utils/stable-value-binding.js";
import { isResponseSource, isUnshadowedGlobal, unwrap } from "./prefer-schema-for-api-payload.js";

const NAME = "prefer-schema-for-http-headers";

const HEADER_SCALARS: ReadonlySet<string> = new Set([
  "Number",
  "Boolean",
  "parseInt",
  "parseFloat",
]);

const isHeaderScalar = (node: ESTree.CallExpression, context: Context): boolean =>
  node.callee.type === "Identifier" &&
  HEADER_SCALARS.has(node.callee.name) &&
  (node.arguments.length === 1 ||
    (node.callee.name === "parseInt" && node.arguments.length === 2)) &&
  node.arguments.every((argument) => argument.type !== "SpreadElement") &&
  isUnshadowedGlobal(node.callee, context);

const HEADER_METHODS: ReadonlySet<string> = new Set(["get", "has", "set", "append", "delete"]);

const closedCarrier = (input: Node, context: Context, seen = new Set<TsVariable>()): boolean => {
  const node = unwrap(input);
  if (node?.type !== "Identifier") return node !== null;
  const binding = findVariable(context.sourceCode.getScope(node), node.name);
  if (
    binding === null ||
    binding.defs.length !== 1 ||
    binding.references.length > 32 ||
    seen.size >= 8 ||
    seen.has(binding)
  )
    return false;
  const next = new Set(seen).add(binding);
  return stableValueBinding(binding, (reference) => {
    if (typeOnlyReference(reference)) return true;
    let current = outerExpression(reference.identifier);
    let parent = parentOf(current);
    const properties: string[] = [];
    for (
      let depth = 0;
      parent?.type === "MemberExpression" && parent.object === current;
      depth += 1
    ) {
      if (
        depth >= 8 ||
        parent.optional ||
        getPropertyName(parent) === null ||
        writtenMember(parent)
      )
        return false;
      properties.push(getPropertyName(parent)!);
      current = outerExpression(parent);
      parent = parentOf(current);
    }
    if (
      parent?.type === "CallExpression" &&
      parent.callee === current &&
      !parent.optional &&
      current.type === "MemberExpression" &&
      HEADER_METHODS.has(getPropertyName(current) ?? "") &&
      (properties.length === 1 || (properties.length === 2 && properties[0] === "headers"))
    )
      return parent.arguments.every((argument) => argument.type === "Literal");
    if (
      parent?.type !== "VariableDeclarator" ||
      parent.init !== current ||
      parent.id.type !== "Identifier"
    )
      return false;
    if (properties.length > 0 && (properties.length !== 1 || properties[0] !== "headers"))
      return false;
    const declaration = parentOf(parent);
    if (declaration?.type !== "VariableDeclaration" || declaration.kind !== "const") return false;
    return closedCarrier(parent.id, context, next);
  });
};

const hasHeaderRead = (input: Node | undefined, context: Context, depth = 0): boolean => {
  const node = unwrap(input);
  if (node === null || depth >= 16) return false;
  if (node.type === "LogicalExpression")
    return (
      hasHeaderRead(node.left, context, depth + 1) || hasHeaderRead(node.right, context, depth + 1)
    );
  if (node.type !== "CallExpression") return false;
  if (isHeaderScalar(node, context)) return hasHeaderRead(node.arguments[0], context, depth + 1);
  const callee = unwrap(node.callee);
  const [key] = node.arguments;
  return (
    callee?.type === "MemberExpression" &&
    !node.optional &&
    !callee.optional &&
    getPropertyName(callee) === "get" &&
    node.arguments.length === 1 &&
    key?.type === "Literal" &&
    typeof key.value === "string" &&
    isNativeHeaders(callee.object, context)
  );
};

const isNativeHeaders = (input: Node, context: Context, seen = new Set<Node>()): boolean => {
  const node = unwrap(input);
  if (node === null || seen.size >= 32 || seen.has(node)) return false;
  seen.add(node);
  if (node.type === "MemberExpression")
    return (
      !node.optional &&
      getPropertyName(node) === "headers" &&
      isResponseSource(node.object, context) &&
      closedCarrier(node.object, context)
    );
  if (node.type === "NewExpression")
    return (
      node.callee.type === "Identifier" &&
      node.callee.name === "Headers" &&
      isUnshadowedGlobal(node.callee, context)
    );
  if (node.type !== "Identifier") return false;
  const binding = findVariable(context.sourceCode.getScope(node), node.name);
  if (binding?.defs.length !== 1 || !closedCarrier(node, context)) return false;
  const definition = binding.defs[0]!;
  const annotation =
    definition.name.type === "Identifier"
      ? definition.name.typeAnnotation?.typeAnnotation
      : undefined;
  if (
    annotation?.type === "TSTypeReference" &&
    annotation.typeName.type === "Identifier" &&
    annotation.typeName.name === "Headers" &&
    isUnshadowedGlobal(annotation.typeName, context)
  )
    return true;
  return (
    definition.type === "Variable" &&
    (definition.parent as ESTree.VariableDeclaration | null)?.kind === "const" &&
    definition.node.type === "VariableDeclarator" &&
    definition.node.init !== null &&
    isNativeHeaders(definition.node.init, context, seen)
  );
};

const insideHeaderScalar = (node: Node, context: Context): boolean => {
  let current = node;
  let parent = parentOf(current);
  for (let depth = 0; parent !== null && depth < 16; depth += 1) {
    while (
      parent !== null &&
      (isErasedExpression(parent) || parent.type === "ChainExpression") &&
      parent.expression === current
    ) {
      current = parent;
      parent = parentOf(current);
    }
    if (parent?.type === "CallExpression")
      return (
        parent.arguments[0] === current &&
        isHeaderScalar(parent, context) &&
        hasHeaderRead(current, context) &&
        parent.callee.type === "Identifier" &&
        nativeRuntimeUnchanged(
          context.sourceCode,
          parent.callee.name as "Number" | "Boolean" | "parseInt" | "parseFloat",
        )
      );
    if (parent?.type !== "LogicalExpression") return false;
    current = parent;
    parent = parentOf(current);
  }
  return false;
};

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer named Zod contracts for scalar parsing of native HTTP headers.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      unparsedHeaderContract:
        "Parse these HTTP header fields through a named Zod schema; preserve scalar grammar, fallback precedence, defaults and failure handling. Text, signatures and custom parsers retain their own contracts.",
    },
  },
  createOnce(context) {
    return {
      before() {
        const source = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        return (
          source.text.includes("get") &&
          [...HEADER_SCALARS].some((name) => source.text.includes(name)) &&
          !isTestFile(file) &&
          !isScriptFile(file) &&
          !isGeneratedFile(file, source.text)
        );
      },
      CallExpression(node) {
        if (
          isHeaderScalar(node, context) &&
          hasHeaderRead(node.arguments[0], context) &&
          !insideHeaderScalar(node, context) &&
          nativeRuntimeUnchanged(context.sourceCode, "Headers") &&
          nativeRuntimeUnchanged(context.sourceCode, "Request") &&
          nativeRuntimeUnchanged(context.sourceCode, "Response") &&
          node.callee.type === "Identifier" &&
          HEADER_SCALARS.has(node.callee.name) &&
          nativeRuntimeUnchanged(
            context.sourceCode,
            node.callee.name as "Number" | "Boolean" | "parseInt" | "parseFloat",
          )
        ) {
          context.report({ node, messageId: "unparsedHeaderContract" });
        }
      },
    };
  },
});
