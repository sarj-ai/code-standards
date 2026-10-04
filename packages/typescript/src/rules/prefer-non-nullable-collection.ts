/**
 * @fileoverview prefer-non-nullable-collection — review nullish arrays with empty defaults or shared null-or-empty guards.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-non-nullable-collection.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { forEachAstChild } from "./_for-each-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferNonNullableCollection";

export const PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION = {
  summary: "Suggest reviewing nullish arrays that use local empty-array defaults or a shared null-or-empty guard.",
  rationale: "A redundant nullish collection state spreads defaults and guards through consumers without carrying information.",
  remediation: "Use a non-null collection type and normalize omitted input to an empty collection at the boundary.",
  category: "maintainability",
  limitations: ["Recognized defaults and guards are manual modeling prompts, not proof of equivalence for every caller or later use. Exported wire shapes and unknown object escapes are excluded; preserve meaningful null states and boundary compatibility."],
  examples: [
    { id: "non-null-array", title: "Model an always-present collection", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] } function search({ items }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "defaulted-nullish-array", title: "Do not retain a redundant nullish state", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
type Options = readonly [];

const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);

type FunctionNode =
  | ESTree.ArrowFunctionExpression | ESTree.Function;

interface NullableProperty {
  readonly name: string;
  readonly node: ESTree.TSPropertySignature;
  readonly acceptsNull: boolean;
  readonly acceptsUndefined: boolean;
}

interface TypeShape {
  readonly exported: boolean;
  readonly properties: readonly NullableProperty[];
}

function propertyName(node: ESTree.TSPropertySignature): string | null {
  const key = node.key;
  if (node.computed) return null;
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") return key.value;
  return null;
}

function isArrayType(node: ESTree.TSType): boolean {
  if (node.type === "TSArrayType") return true;
  return (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    ARRAY_TYPE_NAMES.has(node.typeName.name)
  );
}

function nullableProperty(node: ESTree.TSPropertySignature): NullableProperty | null {
  if (node.optional) return null;
  const name = propertyName(node);
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (name === null || annotation?.type !== "TSUnionType") return null;
  const concrete = annotation.types.filter(
    (member) =>
      member.type !== "TSNullKeyword" &&
      member.type !== "TSUndefinedKeyword",
  );
  if (concrete.length === 0 || !concrete.every(isArrayType)) return null;
  const acceptsNull = annotation.types.some((member) => member.type === "TSNullKeyword");
  const acceptsUndefined = annotation.types.some(
    (member) => member.type === "TSUndefinedKeyword",
  );
  if (!acceptsNull && !acceptsUndefined) return null;
  return { name, node, acceptsNull, acceptsUndefined };
}

function shapeProperties(members: readonly ESTree.TSSignature[]): readonly NullableProperty[] {
  return members.flatMap((member) => {
    if (member.type !== "TSPropertySignature") return [];
    const property = nullableProperty(member);
    return property === null ? [] : [property];
  });
}

function typeIndex(program: ESTree.Program): ReadonlyMap<string, TypeShape> {
  const index = new Map<string, TypeShape>();
  for (const statement of program.body) {
    const exported = statement.type === "ExportNamedDeclaration";
    const declaration = exported ? statement.declaration : statement;
    if (declaration?.type === "TSInterfaceDeclaration") {
      index.set(declaration.id.name, {
        exported,
        properties: shapeProperties(declaration.body.body),
      });
    } else if (
      declaration?.type === "TSTypeAliasDeclaration" &&
      declaration.typeAnnotation.type === "TSTypeLiteral"
    ) {
      index.set(declaration.id.name, {
        exported,
        properties: shapeProperties(declaration.typeAnnotation.members),
      });
    }
  }
  return index;
}

function emptyArray(node: ESTree.Expression): boolean {
  return node.type === "ArrayExpression" && node.elements.length === 0;
}

function sameAccess(
  node: ESTree.Node,
  access: { readonly kind: "identifier"; readonly name: string } |
  { readonly kind: "member"; readonly object: string; readonly property: string },
): boolean {
  if (access.kind === "identifier") {
    return node.type === "Identifier" && node.name === access.name;
  }
  return (
    node.type === "MemberExpression" &&
    !node.computed &&
    node.object.type === "Identifier" &&
    node.object.name === access.object &&
    node.property.type === "Identifier" &&
    node.property.name === access.property
  );
}

function memberLengthOf(
  node: ESTree.Node,
  access: Parameters<typeof sameAccess>[1],
): boolean {
  const target = node.type === "ChainExpression" ? node.expression : node;
  return (
    target.type === "MemberExpression" &&
    !target.computed &&
    target.property.type === "Identifier" &&
    target.property.name === "length" &&
    sameAccess(target.object, access)
  );
}

function optionalMemberLengthOf(
  node: ESTree.Node,
  access: Parameters<typeof sameAccess>[1],
): boolean {
  return (
    node.type === "ChainExpression" &&
    node.expression.type === "MemberExpression" &&
    node.expression.optional &&
    memberLengthOf(node, access)
  );
}

function hasEquivalentLeadingGuard(
  fn: FunctionNode,
  access: Parameters<typeof sameAccess>[1],
  visitorKeys: Readonly<SourceCode["visitorKeys"]>,
): boolean {
  if (fn.body === null) return false;
  if (fn.body.type !== "BlockStatement") return false;
  const first = fn.body.body[0];
  if (first?.type !== "IfStatement") return false;
  const terminating =
    first.consequent.type === "ReturnStatement" ||
    first.consequent.type === "ThrowStatement" ||
    first.consequent.type === "BlockStatement" &&
    first.consequent.body.length === 1 &&
    (first.consequent.body[0]?.type === "ReturnStatement" ||
      first.consequent.body[0]?.type === "ThrowStatement");
  if (!terminating) return false;
  if (contains(first.consequent, visitorKeys, (node) => sameAccess(node, access))) return false;
  if (first.test.type === "UnaryExpression" && first.test.operator === "!" &&
    optionalMemberLengthOf(first.test.argument, access)) return true;
  return (
    first.test.type === "LogicalExpression" && first.test.operator === "||" &&
    isNullGuard(first.test.left, access) && isEmptyGuard(first.test.right, access)
  );
}

function isNullGuard(node: ESTree.Node, access: Parameters<typeof sameAccess>[1]): boolean {
  if (
    node.type === "UnaryExpression" &&
    node.operator === "!" &&
    (sameAccess(node.argument, access) || optionalMemberLengthOf(node.argument, access))
  ) return true;
  if (node.type !== "BinaryExpression" || !["==", "==="].includes(node.operator)) {
    return false;
  }
  const nullish = (value: ESTree.Node): boolean =>
    value.type === "Literal" && value.value === null ||
    value.type === "Identifier" && value.name === "undefined";
  return sameAccess(node.left, access) && nullish(node.right) ||
    sameAccess(node.right, access) && nullish(node.left);
}

function isEmptyGuard(node: ESTree.Node, access: Parameters<typeof sameAccess>[1]): boolean {
  if (
    node.type === "UnaryExpression" &&
    node.operator === "!" &&
    memberLengthOf(node.argument, access)
  ) return true;
  if (node.type !== "BinaryExpression" || !["==", "===", "<="].includes(node.operator)) {
    return false;
  }
  const zero = (value: ESTree.Node): boolean =>
    value.type === "Literal" && value.value === 0;
  return memberLengthOf(node.left, access) && zero(node.right) ||
    node.operator !== "<=" && memberLengthOf(node.right, access) && zero(node.left);
}

function contains(
  node: ESTree.Node,
  visitorKeys: Readonly<SourceCode["visitorKeys"]>,
  predicate: (current: ESTree.Node) => boolean,
): boolean {
  if (predicate(node)) return true;
  return forEachAstChild(node, visitorKeys, child => contains(child, visitorKeys, predicate));
}

function belongsToFunction(node: ESTree.Node, fn: FunctionNode): boolean {
  let current: ESTree.Node | null | undefined = node;
  while (current != null && current !== fn) {
    if (
      current !== node &&
      (current.type === "ArrowFunctionExpression" ||
        current.type === "FunctionDeclaration" ||
        current.type === "FunctionExpression")
    ) return false;
    current = current.parent;
  }
  return current === fn;
}

function directlyCoalesced(node: ESTree.Node): boolean {
  const parent = node.parent;
  return (
    parent?.type === "LogicalExpression" &&
    parent.left === node &&
    (parent.operator === "??" || parent.operator === "||") &&
    emptyArray(parent.right)
  );
}

function identifierIsOnlyCoalesced(
  context: Readonly<Context>,
  binding: ESTree.BindingIdentifier,
  fn: FunctionNode,
): boolean {
  const variable = findVariable(context.sourceCode.getScope(binding), binding.name);
  if (variable === null || variable.references.length === 0) return false;
  return variable.references.every(
    (reference) =>
      belongsToFunction(reference.identifier, fn) && directlyCoalesced(reference.identifier),
  );
}

function memberIsOnlyCoalesced(
  context: Readonly<Context>,
  object: ESTree.BindingIdentifier,
  property: string,
  fn: FunctionNode,
): boolean {
  const variable = findVariable(context.sourceCode.getScope(object), object.name);
  if (variable === null) return false;
  const accesses = variable.references.flatMap((reference) => {
    if (!belongsToFunction(reference.identifier, fn)) return [null];
    const parent = reference.identifier.parent;
    if (
      parent?.type === "MemberExpression" &&
      !parent.computed &&
      parent.object === reference.identifier &&
      parent.property.type === "Identifier" &&
      parent.property.name === property
    ) return [parent];
    return parent?.type === "MemberExpression" && parent.object === reference.identifier ? [] : [null];
  });
  return accesses.length > 0 && accesses.every((access) => access !== null && directlyCoalesced(access));
}

export default createRule<Options, MessageIds>({
  name: "prefer-non-nullable-collection",
  documentation: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Suggest reviewing nullish arrays that use local empty-array defaults or a shared null-or-empty guard.",
    },
    schema: [],
    messages: {
      preferNonNullableCollection:
        "`{{name}}` uses an empty-array default or shared null-or-empty guard; consider a non-null array after checking that the nullish state carries no separate meaning.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }

    let shapes: ReadonlyMap<string, TypeShape> = new Map();
    const evidence = new Map<ESTree.TSPropertySignature, boolean[]>();

    function propertiesFor(annotation: ESTree.TSType | undefined): readonly NullableProperty[] {
      if (annotation?.type === "TSTypeLiteral") return shapeProperties(annotation.members);
      if (
        annotation?.type === "TSTypeReference" &&
        annotation.typeName.type === "Identifier"
      ) {
        const shape = shapes.get(annotation.typeName.name);
        return shape?.exported === false ? shape.properties : [];
      }
      return [];
    }

    function record(property: NullableProperty, proven: boolean): void {
      const values = evidence.get(property.node) ?? [];
      values.push(proven);
      evidence.set(property.node, values);
    }

    function checkFunction(fn: FunctionNode): void {
      function checkParameter(rawParameter: ESTree.ParamPattern): void {
        const parameter = rawParameter.type === "AssignmentPattern"
          ? rawParameter.left
          : rawParameter;
        if (parameter.type === "ObjectPattern") {
          const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
          checkDestructuredProperties(parameter, properties);
          return;
        }
        if (parameter.type !== "Identifier") return;
        const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
        for (const property of properties) {
          const access = {
            kind: "member" as const,
            object: parameter.name,
            property: property.name,
          };
          record(
            property,
            hasEquivalentLeadingGuard(fn, access, context.sourceCode.visitorKeys) ||
            memberIsOnlyCoalesced(context, parameter, property.name, fn),
          );
        }
      }

      function checkDestructuredProperties(parameter: ESTree.ObjectPattern, properties: readonly NullableProperty[]): void {
        for (const property of properties) {
          const bindingProperty = parameter.properties.find(
            (entry): entry is ESTree.BindingProperty =>
              entry.type === "Property" &&
              !entry.computed &&
              entry.key.type === "Identifier" &&
              entry.key.name === property.name,
          );
          if (bindingProperty === undefined) continue;
          const value = bindingProperty.value;
          const binding = value.type === "AssignmentPattern" ? value.left : value;
          if (binding.type !== "Identifier") {
            record(property, false);
            continue;
          }
          if (
            value.type === "AssignmentPattern" &&
            emptyArray(value.right) &&
            property.acceptsUndefined &&
            !property.acceptsNull
          ) {
            record(property, true);
            continue;
          }
          const access = { kind: "identifier" as const, name: binding.name };
          record(
            property,
            hasEquivalentLeadingGuard(fn, access, context.sourceCode.visitorKeys) ||
            identifierIsOnlyCoalesced(context, binding, fn),
          );
        }
      }

      for (const rawParameter of fn.params) { checkParameter(rawParameter); }
    }

    return {
      Program(node): void {
        shapes = typeIndex(node);
      },
      ArrowFunctionExpression: checkFunction,
      FunctionDeclaration: checkFunction,
      FunctionExpression: checkFunction,
      "Program:exit"(): void {
        for (const [node, values] of evidence) {
          if (values.length === 0 || !values.every(Boolean)) continue;
          context.report({
            node,
            messageId: "preferNonNullableCollection",
            data: { name: propertyName(node) ?? "collection" },
          });
        }
      },
    };
  },
});
