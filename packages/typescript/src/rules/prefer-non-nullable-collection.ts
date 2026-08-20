/**
 * @fileoverview prefer-non-nullable-collection — report only when local control flow proves a nullish array is just an empty array.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-non-nullable-collection.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferNonNullableCollection";

export const preferNonNullableCollectionDocumentation = {
  summary: "Suggest non-null arrays only when local control flow proves the nullish state is equivalent to an empty collection.",
  rationale: "A redundant nullish collection state spreads defaults and guards through consumers without carrying information.",
  remediation: "Use a non-null collection type and normalize omitted input to an empty collection at the boundary.",
  category: "maintainability",
  limitations: ["The rule requires local evidence that nullish and empty values are treated identically and skips exported wire shapes."],
  examples: [
    { id: "non-null-array", title: "Model an always-present collection", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] } function search({ items }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "defaulted-nullish-array", title: "Do not retain a redundant nullish state", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
type Options = readonly [];

const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);

type FunctionNode =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;

interface NullableProperty {
  readonly name: string;
  readonly node: TSESTree.TSPropertySignature;
  readonly acceptsNull: boolean;
  readonly acceptsUndefined: boolean;
}

interface TypeShape {
  readonly exported: boolean;
  readonly properties: readonly NullableProperty[];
}

function propertyName(node: TSESTree.TSPropertySignature): string | null {
  const key = node.key;
  if (node.computed) return null;
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
}

function isArrayType(node: TSESTree.TypeNode): boolean {
  if (node.type === AST_NODE_TYPES.TSArrayType) return true;
  return (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    ARRAY_TYPE_NAMES.has(node.typeName.name)
  );
}

function nullableProperty(node: TSESTree.TSPropertySignature): NullableProperty | null {
  if (node.optional) return null;
  const name = propertyName(node);
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (name === null || annotation?.type !== AST_NODE_TYPES.TSUnionType) return null;
  const concrete = annotation.types.filter(
    (member) =>
      member.type !== AST_NODE_TYPES.TSNullKeyword &&
      member.type !== AST_NODE_TYPES.TSUndefinedKeyword,
  );
  if (concrete.length === 0 || !concrete.every(isArrayType)) return null;
  const acceptsNull = annotation.types.some((member) => member.type === AST_NODE_TYPES.TSNullKeyword);
  const acceptsUndefined = annotation.types.some(
    (member) => member.type === AST_NODE_TYPES.TSUndefinedKeyword,
  );
  if (!acceptsNull && !acceptsUndefined) return null;
  return { name, node, acceptsNull, acceptsUndefined };
}

function shapeProperties(members: readonly TSESTree.TypeElement[]): readonly NullableProperty[] {
  return members.flatMap((member) => {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) return [];
    const property = nullableProperty(member);
    return property === null ? [] : [property];
  });
}

function typeIndex(program: TSESTree.Program): ReadonlyMap<string, TypeShape> {
  const index = new Map<string, TypeShape>();
  for (const statement of program.body) {
    const exported = statement.type === AST_NODE_TYPES.ExportNamedDeclaration;
    const declaration = exported ? statement.declaration : statement;
    if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
      index.set(declaration.id.name, {
        exported,
        properties: shapeProperties(declaration.body.body),
      });
    } else if (
      declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration &&
      declaration.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral
    ) {
      index.set(declaration.id.name, {
        exported,
        properties: shapeProperties(declaration.typeAnnotation.members),
      });
    }
  }
  return index;
}

function emptyArray(node: TSESTree.Expression): boolean {
  return node.type === AST_NODE_TYPES.ArrayExpression && node.elements.length === 0;
}

function sameAccess(
  node: TSESTree.Node,
  access: { readonly kind: "identifier"; readonly name: string } |
    { readonly kind: "member"; readonly object: string; readonly property: string },
): boolean {
  if (access.kind === "identifier") {
    return node.type === AST_NODE_TYPES.Identifier && node.name === access.name;
  }
  return (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    node.object.type === AST_NODE_TYPES.Identifier &&
    node.object.name === access.object &&
    node.property.type === AST_NODE_TYPES.Identifier &&
    node.property.name === access.property
  );
}

function isNullGuard(node: TSESTree.Node, access: Parameters<typeof sameAccess>[1]): boolean {
  if (
    node.type === AST_NODE_TYPES.UnaryExpression &&
    node.operator === "!" &&
    (sameAccess(node.argument, access) || optionalMemberLengthOf(node.argument, access))
  ) return true;
  if (node.type !== AST_NODE_TYPES.BinaryExpression || !["==", "==="].includes(node.operator)) {
    return false;
  }
  const nullish = (value: TSESTree.Node): boolean =>
    value.type === AST_NODE_TYPES.Literal && value.value === null ||
    value.type === AST_NODE_TYPES.Identifier && value.name === "undefined";
  return sameAccess(node.left, access) && nullish(node.right) ||
    sameAccess(node.right, access) && nullish(node.left);
}

function isEmptyGuard(node: TSESTree.Node, access: Parameters<typeof sameAccess>[1]): boolean {
  if (
    node.type === AST_NODE_TYPES.UnaryExpression &&
    node.operator === "!" &&
    memberLengthOf(node.argument, access)
  ) return true;
  if (node.type !== AST_NODE_TYPES.BinaryExpression || !["==", "===", "<="].includes(node.operator)) {
    return false;
  }
  const zero = (value: TSESTree.Node): boolean =>
    value.type === AST_NODE_TYPES.Literal && value.value === 0;
  return memberLengthOf(node.left, access) && zero(node.right) ||
    memberLengthOf(node.right, access) && zero(node.left);
}

function memberLengthOf(
  node: TSESTree.Node,
  access: Parameters<typeof sameAccess>[1],
): boolean {
  const target = node.type === AST_NODE_TYPES.ChainExpression ? node.expression : node;
  return (
    target.type === AST_NODE_TYPES.MemberExpression &&
    !target.computed &&
    target.property.type === AST_NODE_TYPES.Identifier &&
    target.property.name === "length" &&
    sameAccess(target.object, access)
  );
}

function optionalMemberLengthOf(
  node: TSESTree.Node,
  access: Parameters<typeof sameAccess>[1],
): boolean {
  return (
    node.type === AST_NODE_TYPES.ChainExpression &&
    node.expression.type === AST_NODE_TYPES.MemberExpression &&
    node.expression.optional &&
    memberLengthOf(node, access)
  );
}

function hasEquivalentLeadingGuard(
  fn: FunctionNode,
  access: Parameters<typeof sameAccess>[1],
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
): boolean {
  if (fn.body.type !== AST_NODE_TYPES.BlockStatement) return false;
  const first = fn.body.body[0];
  if (first?.type !== AST_NODE_TYPES.IfStatement) return false;
  const terminating =
    first.consequent.type === AST_NODE_TYPES.ReturnStatement ||
    first.consequent.type === AST_NODE_TYPES.ThrowStatement ||
    first.consequent.type === AST_NODE_TYPES.BlockStatement &&
      first.consequent.body.length === 1 &&
      (first.consequent.body[0]?.type === AST_NODE_TYPES.ReturnStatement ||
        first.consequent.body[0]?.type === AST_NODE_TYPES.ThrowStatement);
  if (!terminating) return false;
  if (contains(first.consequent, visitorKeys, (node) => sameAccess(node, access))) return false;
  return (
    contains(first.test, visitorKeys, (node) => isNullGuard(node, access)) &&
    contains(first.test, visitorKeys, (node) => isEmptyGuard(node, access))
  );
}

function contains(
  node: TSESTree.Node,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
  predicate: (current: TSESTree.Node) => boolean,
): boolean {
  if (predicate(node)) return true;
  for (const key of visitorKeys[node.type] ?? []) {
    const child = (node as unknown as Record<string, unknown>)[key];
    for (const value of (Array.isArray(child) ? child : [child]) as unknown[]) {
      if (
        value !== null &&
        typeof value === "object" &&
        "type" in value &&
        contains(value as TSESTree.Node, visitorKeys, predicate)
      ) return true;
    }
  }
  return false;
}

function belongsToFunction(node: TSESTree.Node, fn: FunctionNode): boolean {
  let current: TSESTree.Node | undefined = node;
  while (current !== undefined && current !== fn) {
    if (
      current !== node &&
      (current.type === AST_NODE_TYPES.ArrowFunctionExpression ||
        current.type === AST_NODE_TYPES.FunctionDeclaration ||
        current.type === AST_NODE_TYPES.FunctionExpression)
    ) return false;
    current = current.parent;
  }
  return current === fn;
}

function directlyCoalesced(node: TSESTree.Node): boolean {
  const parent = node.parent;
  return (
    parent?.type === AST_NODE_TYPES.LogicalExpression &&
    parent.left === node &&
    (parent.operator === "??" || parent.operator === "||") &&
    emptyArray(parent.right)
  );
}

function identifierIsOnlyCoalesced(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  binding: TSESTree.Identifier,
  fn: FunctionNode,
): boolean {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(binding), binding.name);
  if (variable === null || variable.references.length === 0) return false;
  return variable.references.every(
    (reference) =>
      belongsToFunction(reference.identifier, fn) && directlyCoalesced(reference.identifier),
  );
}

function memberIsOnlyCoalesced(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  object: TSESTree.Identifier,
  property: string,
  fn: FunctionNode,
): boolean {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(object), object.name);
  if (variable === null) return false;
  const accesses = variable.references.flatMap((reference) => {
    if (!belongsToFunction(reference.identifier, fn)) return [null];
    const parent = reference.identifier.parent;
    if (
      parent?.type === AST_NODE_TYPES.MemberExpression &&
      !parent.computed &&
      parent.object === reference.identifier &&
      parent.property.type === AST_NODE_TYPES.Identifier &&
      parent.property.name === property
    ) return [parent];
    return [];
  });
  return accesses.length > 0 && accesses.every((access) => access !== null && directlyCoalesced(access));
}

export default createRule<Options, MessageIds>({
  name: "prefer-non-nullable-collection",
  documentation: preferNonNullableCollectionDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Suggest non-null arrays only when local control flow proves the nullish state is equivalent to an empty collection.",
    },
    schema: [],
    messages: {
      preferNonNullableCollection:
        "`{{name}}` is locally treated exactly like `[]`; make it a non-null array and normalize omitted input at the boundary.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    let shapes: ReadonlyMap<string, TypeShape> = new Map();
    const evidence = new Map<TSESTree.TSPropertySignature, boolean[]>();

    function propertiesFor(annotation: TSESTree.TypeNode | undefined): readonly NullableProperty[] {
      if (annotation?.type === AST_NODE_TYPES.TSTypeLiteral) return shapeProperties(annotation.members);
      if (
        annotation?.type === AST_NODE_TYPES.TSTypeReference &&
        annotation.typeName.type === AST_NODE_TYPES.Identifier
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
      for (const rawParameter of fn.params) {
        const parameter = rawParameter.type === AST_NODE_TYPES.AssignmentPattern
          ? rawParameter.left
          : rawParameter;
        if (parameter.type === AST_NODE_TYPES.ObjectPattern) {
          const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
          for (const property of properties) {
            const bindingProperty = parameter.properties.find(
              (entry): entry is TSESTree.Property =>
                entry.type === AST_NODE_TYPES.Property &&
                !entry.computed &&
                entry.key.type === AST_NODE_TYPES.Identifier &&
                entry.key.name === property.name,
            );
            if (bindingProperty === undefined) continue;
            const value = bindingProperty.value;
            const binding = value.type === AST_NODE_TYPES.AssignmentPattern ? value.left : value;
            if (binding.type !== AST_NODE_TYPES.Identifier) {
              record(property, false);
              continue;
            }
            if (
              value.type === AST_NODE_TYPES.AssignmentPattern &&
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
          continue;
        }
        if (parameter.type !== AST_NODE_TYPES.Identifier) continue;
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
