/**
 * @fileoverview prefer-non-nullable-collection — review nullish arrays with empty defaults or shared null-or-empty guards.
 *
 * Port of the 18.x `prefer-non-nullable-collection` rule. The rule is untyped, so the port
 * covers all of it.
 *
 * Under Oxlint the original never offers its fix: it requires `owner.typeParameters === undefined`,
 * and Oxlint passes `null` for an absent field. The port accepts both, so the fix matches ESLint.
 */

import type { FixFn as ReportFix } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type Scope, type SourceCode, type TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { forEachAstChild, parentOf, type VisitorKeys } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { typeBinding } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "prefer-non-nullable-collection";

const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);
const NULL_GUARD_OPERATORS: ReadonlySet<string> = new Set(["==", "==="]);
const EMPTY_GUARD_OPERATORS: ReadonlySet<string> = new Set(["==", "===", "<="]);

type FunctionNode =
  | ESTree.ArrowFunctionExpression
  | ESTree.Function;

type LocalTypeDeclaration = ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration;
type SignatureNode = ESTree.ArrowFunctionExpression | ESTree.Function;

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

interface ExportedOwnership {
  readonly declarations: ReadonlySet<Node>;
  readonly callables: ReadonlySet<FunctionNode>;
}

interface CallableTarget {
  readonly callable: FunctionNode | null;
  readonly signatures: readonly SignatureNode[];
}

interface CallableResolution extends CallableTarget {
  readonly annotations: readonly Node[];
}

interface CallableStep {
  readonly target: FunctionNode | ESTree.IdentifierReference | null;
  readonly annotation: ESTree.TSTypeAnnotation | null | undefined;
}

type IdentifierNode = Node & { readonly type: "Identifier"; readonly name: string };

interface ExportSeeds {
  readonly identifiers: IdentifierNode[];
  readonly values: IdentifierNode[];
  readonly roots: LocalTypeDeclaration[];
  readonly callables: Set<FunctionNode>;
  readonly signatures: Set<SignatureNode>;
}

type OwnershipWork =
  | { readonly kind: "type" | "value"; readonly identifier: IdentifierNode }
  | { readonly kind: "syntax"; readonly node: Node };

interface OwnershipGraph {
  readonly pending: OwnershipWork[];
  readonly declarations: Set<Node>;
  readonly callables: Set<FunctionNode>;
  readonly signatures: Set<SignatureNode>;
  readonly types: Set<TsVariable>;
  readonly values: Set<TsVariable>;
  readonly syntax: Set<Node>;
  readonly cache: Map<TsVariable, CallableTarget | null>;
}

type Access = { readonly kind: "identifier"; readonly name: string } |
  { readonly kind: "member"; readonly object: string; readonly property: string };

function propertyName(node: ESTree.TSPropertySignature): string | null {
  const key = node.key;
  if (node.computed) return null;
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") return key.value;
  return null;
}

function isArrayType(node: ESTree.TSType, source: SourceCode): boolean {
  if (node.type === "TSArrayType") return true;
  return (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    ARRAY_TYPE_NAMES.has(node.typeName.name) &&
    node.typeArguments?.params.length === 1 &&
    (typeBinding(source, node.typeName)?.defs.length ?? 0) === 0
  );
}

function nullableProperty(node: ESTree.TSPropertySignature, source: SourceCode): NullableProperty | null {
  if (node.optional) return null;
  const name = propertyName(node);
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (name === null || annotation?.type !== "TSUnionType") return null;
  const concrete = annotation.types.filter(
    (member) => member.type !== "TSNullKeyword" && member.type !== "TSUndefinedKeyword",
  );
  if (concrete.length === 0 || !concrete.every(member => isArrayType(member, source))) return null;
  const acceptsNull = annotation.types.some((member) => member.type === "TSNullKeyword");
  const acceptsUndefined = annotation.types.some((member) => member.type === "TSUndefinedKeyword");
  if (!acceptsNull && !acceptsUndefined) return null;
  return { name, node, acceptsNull, acceptsUndefined };
}

function shapeProperties(members: readonly ESTree.TSSignature[], source: SourceCode): readonly NullableProperty[] {
  return members.flatMap((member) => {
    if (member.type !== "TSPropertySignature") return [];
    const property = nullableProperty(member, source);
    return property === null ? [] : [property];
  });
}

function typeIndex(
  program: ESTree.Program,
  source: SourceCode,
  exportedDeclarations: ReadonlySet<Node>,
): ReadonlyMap<Node, TypeShape> {
  const index = new Map<Node, TypeShape>();
  for (const statement of program.body) {
    const exported = statement.type === "ExportNamedDeclaration";
    const declaration: Node | null = exported ? statement.declaration : statement;
    if (declaration?.type === "TSInterfaceDeclaration") {
      index.set(declaration, {
        exported: exported || exportedDeclarations.has(declaration),
        properties: shapeProperties(declaration.body.body, source),
      });
    } else if (declaration?.type === "TSTypeAliasDeclaration" && declaration.typeAnnotation.type === "TSTypeLiteral") {
      index.set(declaration, {
        exported: exported || exportedDeclarations.has(declaration),
        properties: shapeProperties(declaration.typeAnnotation.members, source),
      });
    }
  }
  return index;
}

function exportedOwnership(program: ESTree.Program, source: SourceCode): ExportedOwnership {
  const seeds: ExportSeeds = { identifiers: [], values: [], roots: [], callables: new Set(), signatures: new Set() };
  for (const statement of program.body) collectExportSeeds(statement, seeds);
  const graph: OwnershipGraph = {
    pending: [], declarations: new Set(), callables: seeds.callables, signatures: new Set(),
    types: new Set(), values: new Set(), syntax: new Set(), cache: new Map(),
  };
  for (const identifier of seeds.identifiers) graph.pending.push({ kind: "type", identifier });
  for (const identifier of seeds.values) graph.pending.push({ kind: "value", identifier });
  for (const declaration of seeds.roots) addTypeDeclaration(declaration, graph);
  for (const callable of seeds.callables) addSignature(callable, graph);
  for (const signature of seeds.signatures) addSignature(signature, graph);
  for (let work = graph.pending.pop(); work !== undefined; work = graph.pending.pop()) {
    processOwnershipWork(work, source, graph);
  }
  return { declarations: graph.declarations, callables: graph.callables };
}

function processOwnershipWork(work: OwnershipWork, source: SourceCode, graph: OwnershipGraph): void {
  if (work.kind === "syntax") processOwnershipSyntax(work.node, source, graph);
  else if (work.kind === "type") processOwnershipType(work.identifier, source, graph);
  else processOwnershipValue(work.identifier, source, graph);
}

function processOwnershipSyntax(node: Node, source: SourceCode, graph: OwnershipGraph): void {
  if (graph.syntax.has(node)) return;
  graph.syntax.add(node);
  if (node.type === "TSTypeReference" && node.typeName.type === "Identifier") {
    graph.pending.push({ kind: "type", identifier: node.typeName });
  } else if (node.type === "TSInterfaceHeritage" && node.expression.type === "Identifier") {
    graph.pending.push({ kind: "type", identifier: node.expression });
  } else if (node.type === "TSTypeQuery" && node.exprName.type === "Identifier") {
    graph.pending.push({ kind: "value", identifier: node.exprName });
  }
  forEachAstChild(node, source.visitorKeys, child => { graph.pending.push({ kind: "syntax", node: child }); });
}

function processOwnershipType(identifier: IdentifierNode, source: SourceCode, graph: OwnershipGraph): void {
  const binding = typeBinding(source, identifier);
  if (binding === null || graph.types.has(binding)) return;
  graph.types.add(binding);
  for (const definition of binding.defs) {
    const declaration = definition.node;
    if (definition.isTypeDefinition && (declaration.type === "TSTypeAliasDeclaration" ||
      declaration.type === "TSInterfaceDeclaration")) addTypeDeclaration(declaration, graph);
  }
}

function processOwnershipValue(identifier: IdentifierNode, source: SourceCode, graph: OwnershipGraph): void {
  const binding = valueBinding(source, identifier);
  if (binding === null || graph.values.has(binding)) return;
  graph.values.add(binding);
  const annotation = exportedValueAnnotation(source, identifier);
  if (isPresent(annotation)) graph.pending.push({ kind: "syntax", node: annotation });
  const resolved = exportedCallable(source, identifier, graph.cache);
  if (resolved === null) return;
  if (resolved.callable !== null) graph.callables.add(resolved.callable);
  for (const signature of resolved.signatures) addSignature(signature, graph);
  for (const node of resolved.annotations) graph.pending.push({ kind: "syntax", node });
}

function addTypeDeclaration(declaration: LocalTypeDeclaration, graph: OwnershipGraph): void {
  if (graph.declarations.has(declaration)) return;
  graph.declarations.add(declaration);
  graph.pending.push({ kind: "syntax", node: declaration });
}

function addSignature(signature: SignatureNode, graph: OwnershipGraph): void {
  if (graph.signatures.has(signature)) return;
  graph.signatures.add(signature);
  for (const node of callableAnnotations(signature)) graph.pending.push({ kind: "syntax", node });
}

function collectExportSeeds(statement: ESTree.Program["body"][number], seeds: ExportSeeds): void {
  if (statement.type === "ExportNamedDeclaration" && statement.source === null) {
    collectNamedExport(statement, seeds);
  } else if (statement.type === "TSExportAssignment") {
    collectExportValue(statement.expression, seeds);
  } else if (statement.type === "ExportDefaultDeclaration") {
    if (statement.declaration.type === "TSInterfaceDeclaration") seeds.roots.push(statement.declaration);
    else collectExportValue(statement.declaration, seeds);
  }
}

function collectNamedExport(statement: ESTree.ExportNamedDeclaration, seeds: ExportSeeds): void {
  const declaration: Node | null = statement.declaration;
  if (declaration?.type === "TSTypeAliasDeclaration" || declaration?.type === "TSInterfaceDeclaration") {
    seeds.roots.push(declaration);
  }
  if (isFunctionNode(declaration)) seeds.callables.add(declaration);
  if (isSignatureNode(declaration)) seeds.signatures.add(declaration);
  if (declaration?.type === "VariableDeclaration") {
    for (const binding of declaration.declarations) {
      if (binding.id.type === "Identifier") seeds.values.push(binding.id);
    }
  }
  for (const specifier of statement.specifiers) {
    const local = specifier.local as Node;
    if (local.type !== "Identifier") continue;
    seeds.identifiers.push(local);
    seeds.values.push(local);
  }
}

function collectExportValue(node: Node, seeds: ExportSeeds): void {
  if (node.type === "Identifier") {
    seeds.identifiers.push(node);
    seeds.values.push(node);
  } else if (isSignatureNode(node)) {
    seeds.signatures.add(node);
    if (isFunctionNode(node)) seeds.callables.add(node);
  }
}

function exportedValueAnnotation(source: SourceCode, identifier: IdentifierNode): ESTree.TSTypeAnnotation | null | undefined {
  const definitions = valueBinding(source, identifier)?.defs.filter(definition => definition.isVariableDefinition) ?? [];
  if (definitions.length !== 1) return undefined;
  const declaration = definitions[0]?.node;
  return declaration?.type === "VariableDeclarator" && declaration.id.type === "Identifier"
    ? declaration.id.typeAnnotation : undefined;
}

/** FunctionDeclaration, FunctionExpression or ArrowFunctionExpression (not TSDeclareFunction). */
// eslint-disable-next-line @sarj/no-explicit-type-predicate -- Oxlint's ESTree `Function` node types FunctionDeclaration, FunctionExpression and TSDeclareFunction as one interface, so TypeScript cannot infer this `type`-discriminator narrowing as it does for TSESTree's split node types.
function isFunctionNode(node: Node | null | undefined): node is FunctionNode {
  return node?.type === "FunctionDeclaration" ||
    node?.type === "FunctionExpression" ||
    node?.type === "ArrowFunctionExpression";
}

// eslint-disable-next-line @sarj/no-explicit-type-predicate -- Oxlint's ESTree `Function` node types FunctionDeclaration, FunctionExpression and TSDeclareFunction as one interface, so TypeScript cannot infer this `type`-discriminator narrowing as it does for TSESTree's split node types.
function isSignatureNode(node: Node | null | undefined): node is SignatureNode {
  const type: string | undefined = node?.type;
  return isFunctionNode(node) || type === "TSDeclareFunction";
}

function exportedCallable(
  source: SourceCode,
  identifier: IdentifierNode,
  cache: Map<TsVariable, CallableTarget | null>,
): CallableResolution | null {
  const visited = new Set<TsVariable>();
  const annotations: Node[] = [];
  let target: CallableTarget | null = null;
  let current: IdentifierNode | undefined = identifier;
  while (current !== undefined) {
    const binding = valueBinding(source, current);
    if (binding === null || visited.has(binding)) break;
    if (cache.has(binding)) {
      target = cache.get(binding) ?? null;
      break;
    }
    visited.add(binding);
    const declared = declaredCallableTarget(binding);
    if (declared !== null) {
      target = declared;
      break;
    }
    const step = constantCallableStep(binding);
    if (step === null) break;
    if (isPresent(step.annotation)) annotations.push(step.annotation);
    if (isFunctionNode(step.target)) {
      target = { callable: step.target, signatures: [step.target] };
      break;
    }
    current = step.target?.type === "Identifier" ? step.target : undefined;
  }
  for (const binding of visited) cache.set(binding, target);
  return target === null ? null : { ...target, annotations };
}

function declaredCallableTarget(binding: TsVariable): CallableTarget | null {
  const definitions = binding.defs.filter(definition => definition.isVariableDefinition);
  const signatures = definitions.flatMap(definition => isSignatureNode(definition.node) ? [definition.node] : []);
  if (signatures.length === 0 || signatures.length !== definitions.length) return null;
  const implementations = signatures.filter(isFunctionNode);
  return implementations.length > 1 ? null : { callable: implementations[0] ?? null, signatures };
}

function constantCallableStep(binding: TsVariable): CallableStep | null {
  const definitions = binding.defs.filter(definition => definition.isVariableDefinition);
  if (definitions.length !== 1) return null;
  const declaration = definitions[0]?.node;
  if (declaration?.type !== "VariableDeclarator") return null;
  const statement = parentOf(declaration);
  if (statement?.type !== "VariableDeclaration" || statement.kind !== "const" ||
    declaration.id.type !== "Identifier") return null;
  const initializer = declaration.init;
  return {
    target: isFunctionNode(initializer) || initializer?.type === "Identifier" ? initializer : null,
    annotation: declaration.id.typeAnnotation,
  };
}

function valueBinding(source: SourceCode, identifier: Node): TsVariable | null {
  const name = (identifier as IdentifierNode).name;
  let scope: Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const found = scope.set.get(name);
    if (found !== undefined) {
      const variable = tsVariable(found);
      if (variable.isValueVariable || variable.defs.some(definition => definition.isVariableDefinition)) return variable;
    }
    scope = scope.upper;
  }
  return null;
}

function callableAnnotations(callable: SignatureNode): readonly Node[] {
  const annotations: Node[] = [];
  if (isPresent(callable.returnType)) annotations.push(callable.returnType);
  if (isPresent(callable.typeParameters)) annotations.push(callable.typeParameters);
  for (const raw of callable.params as readonly Node[]) {
    const parameter = raw.type === "AssignmentPattern" ? raw.left : raw;
    if ((parameter.type === "Identifier" || parameter.type === "ObjectPattern" ||
      parameter.type === "ArrayPattern" || parameter.type === "RestElement")) {
      const annotation = (parameter as { typeAnnotation?: Node | null }).typeAnnotation;
      if (isPresent(annotation)) annotations.push(annotation);
    }
  }
  return annotations;
}

function emptyArray(node: Node): boolean {
  return node.type === "ArrayExpression" && node.elements.length === 0;
}

function sameAccess(node: Node, access: Access): boolean {
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

function memberLengthOf(node: Node, access: Access): boolean {
  const target = node.type === "ChainExpression" ? node.expression : node;
  return (
    target.type === "MemberExpression" &&
    !target.computed &&
    target.property.type === "Identifier" &&
    target.property.name === "length" &&
    sameAccess(target.object, access)
  );
}

function optionalMemberLengthOf(node: Node, access: Access): boolean {
  return (
    node.type === "ChainExpression" &&
    node.expression.type === "MemberExpression" &&
    node.expression.optional &&
    memberLengthOf(node, access)
  );
}

function hasEquivalentLeadingGuard(fn: FunctionNode, access: Access, visitorKeys: VisitorKeys): boolean {
  if (fn.body?.type !== "BlockStatement") return false;
  const first = fn.body.body[0];
  if (first?.type !== "IfStatement") return false;
  if (!exits(first.consequent)) return false;
  if (contains(first.consequent, visitorKeys, (node) => sameAccess(node, access))) return false;
  if (first.test.type === "UnaryExpression" && first.test.operator === "!" &&
    optionalMemberLengthOf(first.test.argument, access)) return true;
  return (
    first.test.type === "LogicalExpression" && first.test.operator === "||" &&
    isNullGuard(first.test.left, access) && isEmptyGuard(first.test.right, access)
  );
}

/** `return …;`, `throw …;`, or a block holding only one of them. */
function exits(statement: Node): boolean {
  const [only] = statement.type === "BlockStatement" && statement.body.length === 1 ? statement.body : [statement];
  return only?.type === "ReturnStatement" || only?.type === "ThrowStatement";
}

function isNullGuard(node: Node, access: Access): boolean {
  if (
    node.type === "UnaryExpression" &&
    node.operator === "!" &&
    (sameAccess(node.argument, access) || optionalMemberLengthOf(node.argument, access))
  ) return true;
  if (node.type !== "BinaryExpression" || !NULL_GUARD_OPERATORS.has(node.operator)) {
    return false;
  }
  return sameAccess(node.left, access) && nullish(node.right) ||
    sameAccess(node.right, access) && nullish(node.left);
}

function isEmptyGuard(node: Node, access: Access): boolean {
  if (
    node.type === "UnaryExpression" &&
    node.operator === "!" &&
    memberLengthOf(node.argument, access)
  ) return true;
  if (node.type !== "BinaryExpression" || !EMPTY_GUARD_OPERATORS.has(node.operator)) {
    return false;
  }
  return memberLengthOf(node.left, access) && zero(node.right) ||
    node.operator !== "<=" && memberLengthOf(node.right, access) && zero(node.left);
}

function nullish(value: Node): boolean {
  return value.type === "Literal" && value.value === null ||
    value.type === "Identifier" && value.name === "undefined";
}

function zero(value: Node): boolean {
  return value.type === "Literal" && value.value === 0;
}

function contains(node: Node, visitorKeys: VisitorKeys, predicate: (current: Node) => boolean): boolean {
  if (predicate(node)) return true;
  return forEachAstChild(node, visitorKeys, child => contains(child, visitorKeys, predicate));
}

function belongsToFunction(node: Node, fn: FunctionNode): boolean {
  let current: Node | null = node;
  while (current !== null && current !== fn) {
    if (
      current !== node &&
      (current.type === "ArrowFunctionExpression" ||
        current.type === "FunctionDeclaration" ||
        current.type === "FunctionExpression")
    ) return false;
    current = parentOf(current);
  }
  return current === fn;
}

function directlyCoalesced(node: Node): boolean {
  const parent = parentOf(node);
  return (
    parent?.type === "LogicalExpression" &&
    parent.left === node &&
    (parent.operator === "??" || parent.operator === "||") &&
    emptyArray(parent.right)
  );
}

function identifierIsOnlyCoalesced(source: SourceCode, binding: IdentifierNode, fn: FunctionNode): boolean {
  const variable = findVariable(source.getScope(binding), binding.name);
  if (variable === null || variable.references.length === 0) return false;
  return variable.references.every(
    (reference) => belongsToFunction(reference.identifier, fn) && directlyCoalesced(reference.identifier),
  );
}

function memberIsOnlyCoalesced(source: SourceCode, object: IdentifierNode, property: string, fn: FunctionNode): boolean {
  const variable = findVariable(source.getScope(object), object.name);
  if (variable === null) return false;
  const accesses = variable.references.flatMap((reference): (Node | null)[] => {
    if (!belongsToFunction(reference.identifier, fn)) return [null];
    const parent = parentOf(reference.identifier);
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

function privateNormalizedCollectionFix(
  sourceCode: SourceCode,
  filename: string,
  owner: FunctionNode,
  parameter: ESTree.ObjectPattern,
  property: ESTree.TSPropertySignature,
): ReportFix | null {
  const type = property.typeAnnotation?.typeAnnotation;
  if (owner.type !== "FunctionDeclaration" || owner.id === null || isPresent(owner.typeParameters) ||
    !isInlineParameterMember(owner, parameter, property) || type?.type !== "TSUnionType" || type.types.length !== 2 ||
    sourceCode.getCommentsInside(owner).length > 0 || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename)) return null;
  const array = type.types.find((member) => member.type !== "TSUndefinedKeyword");
  if (array === undefined || !isArrayType(array, sourceCode)) return null;
  return (fixer) => fixer.replaceText(type, `${sourceCode.getText(array)}${sourceCode.getText(type).replace(/[^\r\n]/gu, "")}`);
}

/** A required member of the inline type literal annotating `owner`'s own `parameter`. */
function isInlineParameterMember(owner: FunctionNode, parameter: ESTree.ObjectPattern, property: ESTree.TSPropertySignature): boolean {
  const parameterType = parameter.typeAnnotation?.typeAnnotation;
  return parentOf(parameter) === owner && parameterType?.type === "TSTypeLiteral" && parentOf(property) === parameterType && !property.optional;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Suggest reviewing nullish arrays that use local empty-array defaults or a shared null-or-empty guard.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferNonNullableCollection:
        "`{{name}}` uses an empty-array default or shared null-or-empty guard; consider a non-null array after checking that the nullish state carries no separate meaning.",
    },
  },
  createOnce(context) {
    let shapes: ReadonlyMap<Node, TypeShape> = new Map();
    let publicCallables: ReadonlySet<FunctionNode> = new Set();
    const evidence = new Map<ESTree.TSPropertySignature, boolean[]>();
    const fixes = new Map<ESTree.TSPropertySignature, ReportFix | null>();

    function propertiesFor(annotation: ESTree.TSType | null | undefined): readonly NullableProperty[] {
      const source = context.sourceCode;
      if (annotation?.type === "TSTypeLiteral") return shapeProperties(annotation.members, source);
      if (annotation?.type === "TSTypeReference" && annotation.typeName.type === "Identifier") {
        const definitions = typeBinding(source, annotation.typeName)?.defs.filter(definition => definition.isTypeDefinition) ?? [];
        if (definitions.length !== 1) return [];
        const declaration = definitions[0]?.node;
        const shape = declaration === undefined ? undefined : shapes.get(declaration);
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
      if (publicCallables.has(fn)) return;
      const source = context.sourceCode;
      const visitorKeys = source.visitorKeys;

      function checkParameter(rawParameter: Node): void {
        const parameter = rawParameter.type === "AssignmentPattern" ? rawParameter.left : rawParameter;
        if (parameter.type === "ObjectPattern") {
          const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
          checkDestructuredProperties(parameter as ESTree.ObjectPattern, properties);
          return;
        }
        if (parameter.type !== "Identifier") return;
        const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
        for (const property of properties) {
          const access = { kind: "member" as const, object: parameter.name, property: property.name };
          record(
            property,
            hasEquivalentLeadingGuard(fn, access, visitorKeys) ||
            memberIsOnlyCoalesced(source, parameter, property.name, fn),
          );
        }
      }

      function checkDestructuredProperties(parameter: ESTree.ObjectPattern, properties: readonly NullableProperty[]): void {
        for (const property of properties) {
          const bindingProperty = parameter.properties.find(
            (entry) => entry.type === "Property" && !entry.computed && getPropertyName(entry) === property.name,
          );
          if (bindingProperty?.type !== "Property") continue;
          const value: Node = bindingProperty.value;
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
            fixes.set(property.node, privateNormalizedCollectionFix(source, context.filename, fn, parameter, property.node));
            continue;
          }
          const access = { kind: "identifier" as const, name: binding.name };
          record(
            property,
            hasEquivalentLeadingGuard(fn, access, visitorKeys) ||
            identifierIsOnlyCoalesced(source, binding, fn),
          );
        }
      }

      for (const rawParameter of fn.params as readonly Node[]) { checkParameter(rawParameter); }
    }

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        shapes = new Map();
        publicCallables = new Set();
        evidence.clear();
        fixes.clear();
        return undefined;
      },
      Program(node: ESTree.Program): void {
        const ownership = exportedOwnership(node, context.sourceCode);
        publicCallables = ownership.callables;
        shapes = typeIndex(node, context.sourceCode, ownership.declarations);
      },
      ArrowFunctionExpression: checkFunction,
      FunctionDeclaration: checkFunction,
      FunctionExpression: checkFunction,
      "Program:exit"(): void {
        for (const [node, values] of evidence) {
          if (values.length === 0 || !values.every(Boolean)) continue;
          const fix = fixes.get(node) ?? null;
          const data = { name: propertyName(node) ?? "collection" };
          context.report(fix === null
            ? { node, messageId: "preferNonNullableCollection", data }
            : { node, messageId: "preferNonNullableCollection", fix, data });
        }
        evidence.clear();
        fixes.clear();
      },
    };
  },
});
