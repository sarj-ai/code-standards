/**
 * @fileoverview no-broad-return-type — Report explicit broad return annotations that erase a known return value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-broad-return-type.test.ts
 */


import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import {
  isGlobalReference,
  resolveVariable,
  unwrapExpression,
} from "./_scope.js";

export const NO_BROAD_RETURN_TYPE_DOCUMENTATION = {
  summary:
    "Report explicit broad return annotations that erase a known return value.",
  rationale:
    "An unknown, object, or unknown-valued dictionary return hides fields that the implementation already knows.",
  remediation:
    "Return the existing domain type or retain the inferred return contract. Keep unknown at unparsed input boundaries.",
  category: "maintainability",
  limitations: [
    "Checks explicit unknown/object/unknown-valued dictionary return syntax, same-file aliases, and unshadowed Promise envelopes. Returned values must have a local explicit annotation or a nonempty literal shape.",
    "Imported contracts, inferred calls and member expressions, generics, opaque return branches, empty objects, and declaration-only signatures are excluded. No cross-module assignability or contextual inference is attempted. No autofix.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Record<string, unknown> { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Invoice { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;
interface ReturnFrame {
  readonly annotation: ESTree.TSTypeAnnotation | null;
  known: boolean;
  opaque: boolean;
}

/** Classify only explicit annotation syntax; imports and inference are unknown. */
function annotationKind(
  type: ESTree.TSType,
  source: SourceCode,
  seen = new Set<ESTree.Node>(),
): "broad" | "known" | "opaque" {
  if (seen.has(type)) return "opaque";
  seen.add(type);
  if (type.type === "TSUnknownKeyword" || type.type === "TSObjectKeyword")
    return "broad";
  if (
    type.type === "TSAnyKeyword" ||
    type.type === "TSNeverKeyword" ||
    type.type === "TSVoidKeyword" ||
    type.type === "TSUndefinedKeyword" ||
    type.type === "TSNullKeyword"
  )
    return "opaque";
  if (type.type === "TSUnionType") {
    const kinds = type.types.map((part) =>
      annotationKind(part, source, new Set(seen)),
    );
    return kinds.every((kind) => kind === "known") ? "known" : "opaque";
  }
  if (type.type === "TSTypeReference" && type.typeName.type === "Identifier")
    return referenceAnnotationKind(type, type.typeName, source, seen);
  if (type.type === "TSTypeLiteral") {
    if (type.members.length === 0) return "opaque";
    if (
      type.members.every(
        (member) =>
          member.type === "TSIndexSignature" &&
          member.typeAnnotation.typeAnnotation.type === "TSUnknownKeyword",
      )
    )
      return "broad";
    return type.members.some(
      (member) =>
        member.type === "TSPropertySignature" ||
        member.type === "TSMethodSignature",
    )
      ? "known"
      : "opaque";
  }
  return [
    "TSStringKeyword",
    "TSNumberKeyword",
    "TSBooleanKeyword",
    "TSBigIntKeyword",
    "TSSymbolKeyword",
    "TSLiteralType",
    "TSArrayType",
    "TSTupleType",
  ].includes(type.type)
    ? "known"
    : "opaque";
}

function referenceAnnotationKind(
  type: ESTree.TSTypeReference,
  name: ESTree.IdentifierReference,
  source: SourceCode,
  seen: Set<ESTree.Node>,
): "broad" | "known" | "opaque" {
    const args = type.typeArguments?.params ?? [];
    if (
      name.name === "Promise" &&
      isGlobalReference(source, name, "Promise") &&
      args.length === 1
    ) {
      return annotationKind(args[0]!, source, seen);
    }
    if (
      name.name === "Record" &&
      isGlobalReference(source, name, "Record") &&
      args.length === 2 &&
      (args[0]?.type === "TSStringKeyword" ||
        args[0]?.type === "TSNumberKeyword") &&
      args[1]?.type === "TSUnknownKeyword"
    )
      return "broad";
    const definitions = resolveVariable(source, name)?.defs;
    if (definitions?.length !== 1) return "opaque";
    const declaration = definitions[0]?.node;
    if (
      declaration?.type === "TSTypeAliasDeclaration" &&
      !declaration.typeParameters
    )
      return annotationKind(declaration.typeAnnotation, source, seen);
    if (
      declaration?.type === "TSInterfaceDeclaration" &&
      !declaration.typeParameters &&
      declaration.body.body.length > 0 &&
      declaration.extends.length === 0
    )
      return "known";
    return "opaque";
}

function valueKind(
  value: ESTree.Expression,
  source: SourceCode,
  seen = new Set<ESTree.Node>(),
): "known" | "opaque" | "nullish" {
  if (
    value.type === "TSAsExpression" ||
    value.type === "TSTypeAssertion" ||
    value.type === "TSSatisfiesExpression"
  )
    return "opaque";
  const node = unwrapExpression(value);
  if (seen.has(node)) return "opaque";
  seen.add(node);
  if (node.type === "AwaitExpression")
    return valueKind(node.argument, source, seen);
  if (node.type === "Literal") return node.value === null ? "nullish" : "known";
  if (node.type === "ObjectExpression")
    return node.properties.length > 0 &&
      node.properties.every(
        (property) => property.type === "Property" && !property.computed,
      )
      ? "known"
      : "nullish";
  if (node.type === "ArrayExpression")
    return node.elements.length > 0 &&
      node.elements.every(
        (element) =>
          element !== null &&
          element.type !== "SpreadElement" &&
          valueKind(element, source, new Set(seen)) === "known",
      )
      ? "known"
      : "opaque";
  if (node.type !== "Identifier") return "opaque";
  return identifierValueKind(node, source, seen);
}

function identifierValueKind(
  node: Extract<ESTree.Node, { type: "Identifier" }>,
  source: SourceCode,
  seen: Set<ESTree.Node>,
): "known" | "opaque" | "nullish" {
  if (node.name === "undefined" && isGlobalReference(source, node, "undefined"))
    return "nullish";
  const variable = resolveVariable(source, node);
  if (variable?.defs.length !== 1) return "opaque";
  const definition = variable.defs[0];
  if (definition === undefined) return "opaque";
  const annotation = definition.name.typeAnnotation;
  if (annotation)
    return annotationKind(annotation.typeAnnotation, source) === "known"
      ? "known"
      : "opaque";
  if (
    definition.node.type === "VariableDeclarator" &&
    definition.node.parent.type === "VariableDeclaration" &&
    definition.node.parent.kind === "const" &&
    definition.node.init &&
    !variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  ) {
    return valueKind(definition.node.init, source, seen);
  }
  return "opaque";
}

export default createRule<[], "avoid">({
  name: "no-broad-return-type",
  documentation: NO_BROAD_RETURN_TYPE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_BROAD_RETURN_TYPE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "This explicit broad return annotation hides a value with a local annotation or literal shape. Return the local contract or retain inference.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    const frames: ReturnFrame[] = [];
    const inspect = (value: ESTree.Expression): void => {
      const frame = frames.at(-1);
      if (!frame?.annotation) return;
      const kind = valueKind(value, context.sourceCode);
      frame.known ||= kind === "known";
      frame.opaque ||= kind === "opaque";
    };
    const enter = (node: FunctionNode): void => {
      const annotation = node.returnType;
      frames.push({
        annotation:
          !node.typeParameters &&
          annotation &&
          annotationKind(annotation.typeAnnotation, context.sourceCode) ===
            "broad"
            ? annotation
            : null,
        known: false,
        opaque: false,
      });
      if (node.body && node.body.type !== "BlockStatement") inspect(node.body);
    };
    const leave = (): void => {
      const frame = frames.pop();
      if (frame?.annotation && frame.known && !frame.opaque)
        context.report({ node: frame.annotation, messageId: "avoid" });
    };
    return {
      FunctionDeclaration: enter,
      FunctionExpression: enter,
      ArrowFunctionExpression: enter,
      "FunctionDeclaration:exit": leave,
      "FunctionExpression:exit": leave,
      "ArrowFunctionExpression:exit": leave,
      ReturnStatement(node): void {
        if (node.argument) inspect(node.argument);
      },
    };
  },
});
