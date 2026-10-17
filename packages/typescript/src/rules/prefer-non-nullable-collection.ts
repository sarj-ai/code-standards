/**
 * @fileoverview prefer-non-nullable-collection — review nullish arrays with empty defaults or shared null-or-empty guards.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-non-nullable-collection.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { typeBinding } from "./_type-binding.js";

type MessageIds = "preferNonNullableCollection";

export const PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION = {
  summary: "Suggest reviewing nullish arrays that use local empty-array defaults or a shared null-or-empty guard.",
  rationale: "A redundant nullish collection state spreads defaults and guards through consumers without carrying information.",
  remediation: "Use a non-null collection type and normalize omitted input to an empty collection at the boundary.",
  category: "maintainability",
  limitations: [
    "Recognized defaults and guards are manual modeling prompts, not proof of equivalence for every caller or later use. Recognized exported wire shapes and unknown object escapes are excluded; preserve meaningful null states and boundary compatibility.",
    "Only inline object types or single unmerged top-level local declarations are resolved, using the type namespace. Array and ReadonlyArray names must be unshadowed built-ins; custom and imported constructors are not inferred. Local named, default and export-assignment type exports preserve ownership of their local interface and alias dependencies; arbitrary value exports remain opaque.",
    "Explicit exported variable annotations and signatures of local functions or constant callable aliases preserve input ownership, including callable signatures reached by an exported typeof query. Executable bodies, arbitrary value expressions, inferred exported types, class surfaces and ambiguous callable definitions are not resolved.",
  ],
  examples: [
    { id: "non-null-array", title: "Model an always-present collection", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] } function search({ items }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "defaulted-nullish-array", title: "Do not retain a redundant nullish state", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
    { id: "exported-nullish-input", scenarioId: "exported-input", title: "Preserve an exported input contract", outcome: "no-match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } export type WireInput = Input; function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 0, public: true },
    { id: "private-nullish-input", scenarioId: "exported-input", title: "Review a private input with an empty default", outcome: "match", files: [{ path: "src/search.ts", source: "interface Input { items: string[] | undefined } type WireInput = Input; function search({ items = [] }: Input) { return items.length; }" }], focusPath: "src/search.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
type Options = readonly [];

const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);

type FunctionNode =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;

type LocalTypeDeclaration = TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration;
type SignatureNode = FunctionNode | TSESTree.TSDeclareFunction;

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

interface ExportedOwnership {
  readonly declarations: ReadonlySet<TSESTree.Node>;
  readonly callables: ReadonlySet<FunctionNode>;
}

interface CallableTarget {
  readonly callable: FunctionNode | null;
  readonly signatures: readonly SignatureNode[];
}

interface CallableResolution extends CallableTarget {
  readonly annotations: readonly TSESTree.Node[];
}

interface CallableStep {
  readonly target: FunctionNode | TSESTree.Identifier | null;
  readonly annotation: TSESTree.TSTypeAnnotation | undefined;
}

interface ExportSeeds {
  readonly identifiers: TSESTree.Identifier[];
  readonly values: TSESTree.Identifier[];
  readonly roots: LocalTypeDeclaration[];
  readonly callables: Set<FunctionNode>;
  readonly signatures: Set<SignatureNode>;
}

type OwnershipWork =
  | { readonly kind: "type" | "value"; readonly identifier: TSESTree.Identifier }
  | { readonly kind: "syntax"; readonly node: TSESTree.Node };

interface OwnershipGraph {
  readonly pending: OwnershipWork[];
  readonly declarations: Set<TSESTree.Node>;
  readonly callables: Set<FunctionNode>;
  readonly signatures: Set<SignatureNode>;
  readonly types: Set<TSESLint.Scope.Variable>;
  readonly values: Set<TSESLint.Scope.Variable>;
  readonly syntax: Set<TSESTree.Node>;
  readonly cache: Map<TSESLint.Scope.Variable, CallableTarget | null>;
}

function propertyName(node: TSESTree.TSPropertySignature): string | null {
  const key = node.key;
  if (node.computed) return null;
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
}

function isArrayType(node: TSESTree.TypeNode, source: Readonly<TSESLint.SourceCode>): boolean {
  if (node.type === AST_NODE_TYPES.TSArrayType) return true;
  return (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    ARRAY_TYPE_NAMES.has(node.typeName.name) &&
    node.typeArguments?.params.length === 1 &&
    (typeBinding(source, node.typeName)?.defs.length ?? 0) === 0
  );
}

function nullableProperty(node: TSESTree.TSPropertySignature, source: Readonly<TSESLint.SourceCode>): NullableProperty | null {
  if (node.optional) return null;
  const name = propertyName(node);
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (name === null || annotation?.type !== AST_NODE_TYPES.TSUnionType) return null;
  const concrete = annotation.types.filter(
    (member) =>
      member.type !== AST_NODE_TYPES.TSNullKeyword &&
      member.type !== AST_NODE_TYPES.TSUndefinedKeyword,
  );
  if (concrete.length === 0 || !concrete.every(member => isArrayType(member, source))) return null;
  const acceptsNull = annotation.types.some((member) => member.type === AST_NODE_TYPES.TSNullKeyword);
  const acceptsUndefined = annotation.types.some(
    (member) => member.type === AST_NODE_TYPES.TSUndefinedKeyword,
  );
  if (!acceptsNull && !acceptsUndefined) return null;
  return { name, node, acceptsNull, acceptsUndefined };
}

function shapeProperties(members: readonly TSESTree.TypeElement[], source: Readonly<TSESLint.SourceCode>): readonly NullableProperty[] {
  return members.flatMap((member) => {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) return [];
    const property = nullableProperty(member, source);
    return property === null ? [] : [property];
  });
}

function typeIndex(
  program: TSESTree.Program,
  source: Readonly<TSESLint.SourceCode>,
  exportedDeclarations: ReadonlySet<TSESTree.Node>,
): ReadonlyMap<TSESTree.Node, TypeShape> {
  const index = new Map<TSESTree.Node, TypeShape>();
  for (const statement of program.body) {
    const exported = statement.type === AST_NODE_TYPES.ExportNamedDeclaration;
    const declaration = exported ? statement.declaration : statement;
    if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
      index.set(declaration, {
        exported: exported || exportedDeclarations.has(declaration),
        properties: shapeProperties(declaration.body.body, source),
      });
    } else if (
      declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration &&
      declaration.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral
    ) {
      index.set(declaration, {
        exported: exported || exportedDeclarations.has(declaration),
        properties: shapeProperties(declaration.typeAnnotation.members, source),
      });
    }
  }
  return index;
}

function exportedOwnership(program: TSESTree.Program, source: Readonly<TSESLint.SourceCode>): ExportedOwnership {
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

function processOwnershipWork(work: OwnershipWork, source: Readonly<TSESLint.SourceCode>, graph: OwnershipGraph): void {
  if (work.kind === "syntax") processOwnershipSyntax(work.node, source, graph);
  else if (work.kind === "type") processOwnershipType(work.identifier, source, graph);
  else processOwnershipValue(work.identifier, source, graph);
}

function processOwnershipSyntax(node: TSESTree.Node, source: Readonly<TSESLint.SourceCode>, graph: OwnershipGraph): void {
  if (graph.syntax.has(node)) return;
  graph.syntax.add(node);
  if (node.type === AST_NODE_TYPES.TSTypeReference && node.typeName.type === AST_NODE_TYPES.Identifier) {
    graph.pending.push({ kind: "type", identifier: node.typeName });
  } else if (node.type === AST_NODE_TYPES.TSInterfaceHeritage && node.expression.type === AST_NODE_TYPES.Identifier) {
    graph.pending.push({ kind: "type", identifier: node.expression });
  } else if (node.type === AST_NODE_TYPES.TSTypeQuery && node.exprName.type === AST_NODE_TYPES.Identifier) {
    graph.pending.push({ kind: "value", identifier: node.exprName });
  }
  forEachAstChild(node, source.visitorKeys, child => { graph.pending.push({ kind: "syntax", node: child }); });
}

function processOwnershipType(identifier: TSESTree.Identifier, source: Readonly<TSESLint.SourceCode>, graph: OwnershipGraph): void {
  const binding = typeBinding(source, identifier);
  if (binding === null || graph.types.has(binding)) return;
  graph.types.add(binding);
  for (const definition of binding.defs) {
    const declaration = definition.node;
    if (definition.isTypeDefinition && (declaration.type === AST_NODE_TYPES.TSTypeAliasDeclaration ||
      declaration.type === AST_NODE_TYPES.TSInterfaceDeclaration)) addTypeDeclaration(declaration, graph);
  }
}

function processOwnershipValue(identifier: TSESTree.Identifier, source: Readonly<TSESLint.SourceCode>, graph: OwnershipGraph): void {
  const binding = valueBinding(source, identifier);
  if (binding === null || graph.values.has(binding)) return;
  graph.values.add(binding);
  const annotation = exportedValueAnnotation(source, identifier);
  if (annotation !== undefined) graph.pending.push({ kind: "syntax", node: annotation });
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

function collectExportSeeds(statement: TSESTree.Program["body"][number], seeds: ExportSeeds): void {
  if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration && statement.source === null) {
    collectNamedExport(statement, seeds);
  } else if (statement.type === AST_NODE_TYPES.TSExportAssignment) {
    collectExportValue(statement.expression, seeds);
  } else if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) {
    if (statement.declaration.type === AST_NODE_TYPES.TSInterfaceDeclaration) seeds.roots.push(statement.declaration);
    else collectExportValue(statement.declaration, seeds);
  }
}

function collectNamedExport(statement: TSESTree.ExportNamedDeclaration, seeds: ExportSeeds): void {
  const declaration = statement.declaration;
  if (declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration || declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
    seeds.roots.push(declaration);
  }
  if (isFunctionNode(declaration)) seeds.callables.add(declaration);
  if (isSignatureNode(declaration)) seeds.signatures.add(declaration);
  if (declaration?.type === AST_NODE_TYPES.VariableDeclaration) {
    for (const binding of declaration.declarations) {
      if (binding.id.type === AST_NODE_TYPES.Identifier) seeds.values.push(binding.id);
    }
  }
  for (const specifier of statement.specifiers) {
    if (specifier.local.type !== AST_NODE_TYPES.Identifier) continue;
    seeds.identifiers.push(specifier.local);
    seeds.values.push(specifier.local);
  }
}

function collectExportValue(node: TSESTree.Node, seeds: ExportSeeds): void {
  if (node.type === AST_NODE_TYPES.Identifier) {
    seeds.identifiers.push(node);
    seeds.values.push(node);
  } else if (isSignatureNode(node)) {
    seeds.signatures.add(node);
    if (isFunctionNode(node)) seeds.callables.add(node);
  }
}

function exportedValueAnnotation(source: Readonly<TSESLint.SourceCode>, identifier: TSESTree.Identifier): TSESTree.TSTypeAnnotation | undefined {
  const definitions = valueBinding(source, identifier)?.defs.filter(definition => definition.isVariableDefinition) ?? [];
  if (definitions.length !== 1) return undefined;
  const declaration = definitions[0]?.node;
  return declaration?.type === AST_NODE_TYPES.VariableDeclarator && declaration.id.type === AST_NODE_TYPES.Identifier
    ? declaration.id.typeAnnotation : undefined;
}

function isFunctionNode(node: TSESTree.Node | null | undefined): node is FunctionNode {
  return node?.type === AST_NODE_TYPES.FunctionDeclaration ||
    node?.type === AST_NODE_TYPES.FunctionExpression ||
    node?.type === AST_NODE_TYPES.ArrowFunctionExpression;
}

function isSignatureNode(node: TSESTree.Node | null | undefined): node is SignatureNode {
  return isFunctionNode(node) || node?.type === AST_NODE_TYPES.TSDeclareFunction;
}

function exportedCallable(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
  cache: Map<TSESLint.Scope.Variable, CallableTarget | null>,
): CallableResolution | null {
  const visited = new Set<TSESLint.Scope.Variable>();
  const annotations: TSESTree.Node[] = [];
  let target: CallableTarget | null = null;
  let current: TSESTree.Identifier | undefined = identifier;
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
    if (step.annotation !== undefined) annotations.push(step.annotation);
    if (isFunctionNode(step.target)) {
      target = { callable: step.target, signatures: [step.target] };
      break;
    }
    current = step.target?.type === AST_NODE_TYPES.Identifier ? step.target : undefined;
  }
  for (const binding of visited) cache.set(binding, target);
  return target === null ? null : { ...target, annotations };
}

function declaredCallableTarget(binding: TSESLint.Scope.Variable): CallableTarget | null {
  const definitions = binding.defs.filter(definition => definition.isVariableDefinition);
  const signatures = definitions.flatMap(definition => isSignatureNode(definition.node) ? [definition.node] : []);
  if (signatures.length === 0 || signatures.length !== definitions.length) return null;
  const implementations = signatures.filter(isFunctionNode);
  return implementations.length > 1 ? null : { callable: implementations[0] ?? null, signatures };
}

function constantCallableStep(binding: TSESLint.Scope.Variable): CallableStep | null {
  const definitions = binding.defs.filter(definition => definition.isVariableDefinition);
  if (definitions.length !== 1) return null;
  const declaration = definitions[0]?.node;
  if (declaration?.type !== AST_NODE_TYPES.VariableDeclarator ||
    declaration.parent.type !== AST_NODE_TYPES.VariableDeclaration || declaration.parent.kind !== "const" ||
    declaration.id.type !== AST_NODE_TYPES.Identifier) return null;
  const initializer = declaration.init;
  return {
    target: isFunctionNode(initializer) || initializer?.type === AST_NODE_TYPES.Identifier ? initializer : null,
    annotation: declaration.id.typeAnnotation,
  };
}

function valueBinding(source: Readonly<TSESLint.SourceCode>, identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    if (variable !== undefined && (variable.isValueVariable || variable.defs.some(definition => definition.isVariableDefinition))) return variable;
    scope = scope.upper;
  }
  return null;
}

function callableAnnotations(callable: SignatureNode): readonly TSESTree.Node[] {
  const annotations: TSESTree.Node[] = [];
  if (callable.returnType !== undefined) annotations.push(callable.returnType);
  if (callable.typeParameters !== undefined) annotations.push(callable.typeParameters);
  for (const raw of callable.params) {
    const parameter = raw.type === AST_NODE_TYPES.AssignmentPattern ? raw.left : raw;
    if ((parameter.type === AST_NODE_TYPES.Identifier || parameter.type === AST_NODE_TYPES.ObjectPattern ||
      parameter.type === AST_NODE_TYPES.ArrayPattern || parameter.type === AST_NODE_TYPES.RestElement) &&
      parameter.typeAnnotation !== undefined) annotations.push(parameter.typeAnnotation);
  }
  return annotations;
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
  if (first.test.type === AST_NODE_TYPES.UnaryExpression && first.test.operator === "!" &&
    optionalMemberLengthOf(first.test.argument, access)) return true;
  return (
    first.test.type === AST_NODE_TYPES.LogicalExpression && first.test.operator === "||" &&
    isNullGuard(first.test.left, access) && isEmptyGuard(first.test.right, access)
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
    node.operator !== "<=" && memberLengthOf(node.right, access) && zero(node.left);
}

function contains(
  node: TSESTree.Node,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
  predicate: (current: TSESTree.Node) => boolean,
): boolean {
  if (predicate(node)) return true;
  return forEachAstChild(node, visitorKeys, child => contains(child, visitorKeys, predicate));
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
    return parent?.type === AST_NODE_TYPES.MemberExpression && parent.object === reference.identifier ? [] : [null];
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
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    let shapes: ReadonlyMap<TSESTree.Node, TypeShape> = new Map();
    let publicCallables: ReadonlySet<FunctionNode> = new Set();
    const evidence = new Map<TSESTree.TSPropertySignature, boolean[]>();

    function propertiesFor(annotation: TSESTree.TypeNode | undefined): readonly NullableProperty[] {
      if (annotation?.type === AST_NODE_TYPES.TSTypeLiteral) return shapeProperties(annotation.members, context.sourceCode);
      if (
        annotation?.type === AST_NODE_TYPES.TSTypeReference &&
        annotation.typeName.type === AST_NODE_TYPES.Identifier
      ) {
        const definitions = typeBinding(context.sourceCode, annotation.typeName)?.defs.filter(definition => definition.isTypeDefinition) ?? [];
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
      function checkParameter(rawParameter: TSESTree.Parameter): void {
        const parameter = rawParameter.type === AST_NODE_TYPES.AssignmentPattern
          ? rawParameter.left
          : rawParameter;
        if (parameter.type === AST_NODE_TYPES.ObjectPattern) {
          const properties = propertiesFor(parameter.typeAnnotation?.typeAnnotation);
          checkDestructuredProperties(parameter, properties);
          return;
        }
        if (parameter.type !== AST_NODE_TYPES.Identifier) return;
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

      function checkDestructuredProperties(parameter: TSESTree.ObjectPattern, properties: readonly NullableProperty[]): void {
        for (const property of properties) {
          const bindingProperty = parameter.properties.find(
            (entry): entry is TSESTree.Property =>
              entry.type === AST_NODE_TYPES.Property &&
              !entry.computed &&
              ASTUtils.getPropertyName(entry) === property.name,
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
      }

      for (const rawParameter of fn.params) { checkParameter(rawParameter); }
    }

    return {
      Program(node): void {
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
