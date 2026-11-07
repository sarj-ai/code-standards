/**
 * @fileoverview stepdown — a private helper with one direct same-scope caller belongs below that caller.
 *
 * Port of the 18.x `stepdown` rule. The rule is untyped, so the port
 * covers all of it.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type Context, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { forEachAstChild, parentOf, type VisitorKeys } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type ReportFix = (fixer: Fixer) => Fix;
type ClassNode = ESTree.Class;
type MethodNode = ESTree.MethodDefinition;
type DeclarationScope = ESTree.Program | ESTree.FunctionBody;
type ScopeStatement = DeclarationScope["body"][number];
type CallGraph = ReadonlyMap<string, ReadonlySet<string>>;

interface Definition {
  readonly key: string;
  readonly name: string;
  readonly node: Node;
  readonly functionNode?: FunctionNode;
  readonly bindingNode?: ESTree.Function | ESTree.VariableDeclarator;
}

interface FunctionStatement {
  readonly name: string;
  readonly statement: ScopeStatement;
  readonly node: ESTree.Function;
  readonly exported: boolean;
}

/** Per-file state the visitors and helpers share. */
interface FileState {
  context: Context;
  sourceCode: SourceCode;
  /** Receiver alias chains by starting node; cleared for every file. */
  readonly aliasChains: Map<Node, AliasChain>;
}

/**
 * The immutable alias bindings `receiverOrigin` passes through from one node,
 * and where the walk ends when none of them is a known receiver.
 */
interface AliasChain {
  readonly variables: readonly TsVariable[];
  readonly end: Node | null;
}

// eslint-disable-next-line @sarj/no-explicit-type-predicate -- Oxlint's ESTree `Function` node types FunctionDeclaration, FunctionExpression and TSDeclareFunction as one interface, so TypeScript cannot infer this `type`-discriminator narrowing as it does for TSESTree's split node types.
function isFunction(node: Node): node is FunctionNode {
  return node.type === "ArrowFunctionExpression" || node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression";
}

// The original also erases instantiation expressions, unlike the shared helper.
function isErasedExpression(node: Node) {
  return node.type === "TSAsExpression" || node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" || node.type === "TSNonNullExpression" ||
    node.type === "TSInstantiationExpression";
}

function unwrapExpression(node: Node): Node {
  let current = node;
  while (isErasedExpression(current)) current = current.expression;
  return current;
}

function wrappedExpression(node: Node): Node {
  let current = node;
  let parent = parentOf(current);
  while (parent !== null && isErasedExpression(parent) && parent.expression === current) {
    current = parent;
    parent = parentOf(current);
  }
  return current;
}

/** Nearest function ancestor, as `getAncestors(node).reverse().find(isFunction)`. */
function enclosingFunction(node: Node): FunctionNode | undefined {
  let current = parentOf(node);
  while (current !== null) {
    if (isFunction(current)) return current;
    current = parentOf(current);
  }
  return undefined;
}

// Scope variables do not change while a file is linted; `before()` clears this for each file.
const STABLE_VARIABLES = new Map<TsVariable, boolean>();

function stableVariable(variable: TsVariable): boolean {
  let stable = STABLE_VARIABLES.get(variable);
  if (stable === undefined) {
    stable = !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
    STABLE_VARIABLES.set(variable, stable);
  }
  return stable;
}

function declaredVariable(state: FileState, node: Node): TsVariable | undefined {
  const variable = state.sourceCode.getDeclaredVariables(node)[0];
  return variable === undefined ? undefined : tsVariable(variable);
}

function reportMisordered(
  state: FileState,
  candidates: readonly Definition[],
  scopeDefinitions: readonly Definition[],
  calls: CallGraph,
  pinned: ReadonlySet<string>,
  canMove: (helper: Definition, caller: Definition) => boolean = () => true,
): void {
  const byName = new Map(scopeDefinitions.map((definition) => [definition.key, definition]));
  const cycles = cycleComponents(calls);
  const callers = callersByCallee(calls);
  // The original builds the fix before the loop; building it on the first report gives the same fix.
  let fix: ReportFix | null | undefined;
  for (const helper of candidates) {
    const helperCallers = callers.get(helper.key);
    if (pinned.has(helper.key) || helperCallers?.size !== 1) continue;
    const callerName = helperCallers.values().next().value as string;
    if (cycles.has(helper.key) && cycles.get(helper.key) === cycles.get(callerName)) continue;
    const caller = byName.get(callerName);
    if (caller === undefined || helper.node.range[0] >= caller.node.range[0] || !canMove(helper, caller)) continue;
    if (fix === undefined) fix = declarationOrderFix(state.sourceCode, scopeDefinitions, calls, pinned);
    state.context.report({
      node: helper.node,
      messageId: "helperAboveOnlyCaller",
      data: { helper: helper.name, caller: caller.name },
      ...(fix !== null && { fix }),
    });
  }
}

/** Invert the call graph, leaving out self recursion. */
function callersByCallee(calls: CallGraph): Map<string, Set<string>> {
  const callers = new Map<string, Set<string>>();
  for (const [caller, callees] of calls) {
    for (const callee of callees) {
      if (caller !== callee) addEdge(callers, callee, caller);
    }
  }
  return callers;
}

function addEdge(graph: Map<string, Set<string>>, from: string, to: string): void {
  const targets = graph.get(from);
  if (targets === undefined) graph.set(from, new Set([to]));
  else targets.add(to);
}

function declarationOrderFix(
  sourceCode: SourceCode,
  definitions: readonly Definition[],
  calls: CallGraph,
  pinned: ReadonlySet<string>,
): ReportFix | null {
  if (pinned.size > 0 || sourceCode.getAllComments().length > 0 || hasIdentifierNamed(sourceCode, "eval")) {
    return null;
  }
  const statements = ordinaryFunctionStatements(sourceCode.ast);
  if (statements === null || definitions.length !== statements.length) return null;
  const nodes = new Set<Node>(statements.map((entry) => entry.node));
  if (definitions.some((definition) => !nodes.has(definition.node))) return null;
  const entries = statements.filter((entry) => entry.exported);
  if (entries.length !== 1 || entries[0] === undefined) return null;
  const ordered = callerFirstStatements(statements, calls, entries[0].name);
  if (ordered === null) return null;
  const first = sourceCode.ast.body[0];
  const last = sourceCode.ast.body.at(-1);
  if (first === undefined || last === undefined) return null;
  const newline = sourceCode.text.includes("\r\n") ? "\r\n" : "\n";
  const replacement = ordered.map((statement) => sourceCode.getText(statement)).join(newline);
  return (fixer) => fixer.replaceTextRange([first.range[0], last.range[1]], replacement);
}

function ordinaryFunctionStatements(program: ESTree.Program): FunctionStatement[] | null {
  const definitions: FunctionStatement[] = [];
  for (const statement of program.body) {
    const exported = statement.type === "ExportNamedDeclaration";
    const node = exported ? statement.declaration : statement;
    // TS-ESTree leaves `typeParameters` undefined when absent; Oxlint sets it to null.
    if (node?.type !== "FunctionDeclaration" || node.id === null || node.declare === true || node.async ||
      node.generator || (node.typeParameters !== undefined && node.typeParameters !== null)) return null;
    definitions.push({ name: node.id.name, statement, node, exported });
  }
  return new Set(definitions.map((definition) => definition.name)).size === definitions.length ? definitions : null;
}

function callerFirstStatements(
  definitions: readonly FunctionStatement[],
  calls: CallGraph,
  entry: string,
): ScopeStatement[] | null {
  const byName = new Map(definitions.map((definition) => [definition.name, definition]));
  const ordered: ScopeStatement[] = [];
  const seen = new Set<string>();
  const pending = [entry];
  while (pending.length > 0) {
    const name = pending.pop();
    if (name === undefined || seen.has(name)) return null;
    const definition = byName.get(name);
    if (definition === undefined) return null;
    seen.add(name);
    ordered.push(definition.statement);
    const children = [...(calls.get(name) ?? [])].sort((first, second) =>
      (byName.get(first)?.node.range[0] ?? 0) - (byName.get(second)?.node.range[0] ?? 0));
    pending.push(...children.reverse());
  }
  return ordered.length === definitions.length ? ordered : null;
}

/** Iterative Kosaraju SCC index; self recursion is not an ordering cycle. */
function cycleComponents(graph: CallGraph): ReadonlyMap<string, number> {
  const nodes = new Set<string>();
  const reverse = new Map<string, Set<string>>();
  for (const [caller, callees] of graph) {
    nodes.add(caller);
    for (const callee of callees) {
      nodes.add(callee);
      addEdge(reverse, callee, caller);
    }
  }
  const components = new Map<string, number>();
  let nextComponent = 0;
  const assigned = new Set<string>();
  const order = finishOrder(graph, nodes);
  for (let index = order.length - 1; index >= 0; index -= 1) {
    const root = order[index] as string;
    if (assigned.has(root)) continue;
    const members = reachable(root, reverse, assigned);
    if (members.length > 1) {
      for (const cyclicName of members) components.set(cyclicName, nextComponent);
      nextComponent += 1;
    }
  }
  return components;
}

/** Depth-first finish order over the whole graph, without recursion. */
function finishOrder(graph: CallGraph, nodes: ReadonlySet<string>): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const root of nodes) {
    if (seen.has(root)) continue;
    const pending: Array<{ readonly name: string; readonly exiting: boolean }> = [{ name: root, exiting: false }];
    for (let current = pending.pop(); current !== undefined; current = pending.pop()) {
      if (current.exiting) {
        order.push(current.name);
        continue;
      }
      if (seen.has(current.name)) continue;
      seen.add(current.name);
      pending.push({ name: current.name, exiting: true });
      for (const callee of graph.get(current.name) ?? []) {
        if (!seen.has(callee)) pending.push({ name: callee, exiting: false });
      }
    }
  }
  return order;
}

/** Nodes reachable from `root` that are not yet `assigned`; marks them assigned. */
function reachable(root: string, graph: CallGraph, assigned: Set<string>): string[] {
  const members: string[] = [];
  const pending = [root];
  assigned.add(root);
  for (let member = pending.pop(); member !== undefined; member = pending.pop()) {
    members.push(member);
    for (const next of graph.get(member) ?? []) {
      if (assigned.has(next)) continue;
      assigned.add(next);
      pending.push(next);
    }
  }
  return members;
}

/** A value is callable here only when every alias use remains a direct local call. */
function localCallCount(state: FileState, node: Node, owner: FunctionNode): number | null {
  const seen = new Set<TsVariable>();
  const pending = [node];
  let count = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined || enclosingFunction(current) !== owner) return null;
    const expression = wrappedExpression(current);
    const parent = parentOf(expression);
    if (parent?.type === "CallExpression" && parent.callee === expression) {
      count += 1;
      continue;
    }
    const variable = parent?.type === "VariableDeclarator" && parent.init === expression ? constAlias(state, parent) : null;
    if (variable === null || seen.has(variable)) return null;
    seen.add(variable);
    for (const reference of variable.references) {
      if (reference.isRead()) pending.push(reference.identifier);
    }
  }
  return count;
}

/** The stable binding of `const alias = value`. */
function constAlias(state: FileState, declarator: ESTree.VariableDeclarator): TsVariable | null {
  if (declarator.id.type !== "Identifier" || declarator.parent.type !== "VariableDeclaration" ||
    declarator.parent.kind !== "const") return null;
  const variable = declaredVariable(state, declarator);
  return variable !== undefined && stableVariable(variable) ? variable : null;
}

/** Running counts of barriers before each item; two items share a run when their counts match. */
function barrierRuns<T>(items: readonly T[], isBarrier: (item: T) => boolean): readonly number[] {
  const runs = [0];
  for (const item of items) runs.push((runs.at(-1) ?? 0) + (isBarrier(item) ? 1 : 0));
  return runs;
}

function declarationScope(state: FileState, program: DeclarationScope): void {
  const declarations = moduleDefinitions(program);
  if (declarations.length < 2) return;
  const counts = new Map<string, number>();
  for (const node of declarations) counts.set(node.name, (counts.get(node.name) ?? 0) + 1);
  const overloadNames = new Set<string>();
  for (const statement of program.body) {
    const node = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
    if (node?.type === "TSDeclareFunction" && node.id !== null) overloadNames.add(node.id.name);
  }
  const exported = program.type === "Program" ? exportedNames(program) : new Set<string>();
  const scopeDefinitions = declarations.filter((node) => counts.get(node.name) === 1);
  const definitions = scopeDefinitions.filter((definition) =>
    !exported.has(definition.name) && !overloadNames.has(definition.name));
  const { calls, pinned } = moduleCallGraph(state, scopeDefinitions);
  const statementIndexes = new Map<Node, number>(program.body.map((statement, index) => [statement, index]));
  const runtimeBarrierPrefix = barrierRuns(program.body, (statement) => !isDeferredModuleStatement(statement));
  const canMove = (helper: Definition, caller: Definition): boolean => {
    if (helper.node.type === "FunctionDeclaration") return true;
    const helperIndex = statementIndex(helper);
    const callerIndex = statementIndex(caller);
    return helperIndex !== undefined && callerIndex !== undefined &&
      runtimeBarrierPrefix[callerIndex + 1] === runtimeBarrierPrefix[helperIndex + 1];
  };

  const statementIndex = (definition: Definition): number | undefined => {
    let current = definition.node;
    let parent = parentOf(current);
    while (parent !== null && parent !== program) {
      current = parent;
      parent = parentOf(current);
    }
    return statementIndexes.get(current);
  };
  reportMisordered(state, definitions, scopeDefinitions, calls, pinned, canMove);
}

function moduleCallGraph(
  state: FileState,
  scopeDefinitions: readonly Definition[],
): { calls: Map<string, Set<string>>; pinned: Set<string> } {
  const byFunction = new Map<FunctionNode | undefined, Definition>(
    scopeDefinitions.map((definition) => [definition.functionNode, definition]));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();
  for (const definition of scopeDefinitions) {
    if (definition.bindingNode === undefined) continue;
    const variable = declaredVariable(state, definition.bindingNode);
    for (const reference of variable?.references ?? []) {
      if (reference.isWrite() && reference.init !== true) {
        pinned.add(definition.key);
        continue;
      }
      if (!reference.isRead()) continue;
      const callerDefinition = byFunction.get(enclosingFunction(reference.identifier));
      if (callerDefinition?.functionNode === undefined) {
        pinned.add(definition.key);
        continue;
      }
      const count = localCallCount(state, reference.identifier, callerDefinition.functionNode);
      if (count === null) {
        pinned.add(definition.key);
      } else if (count > 0) {
        addEdge(calls, callerDefinition.key, definition.key);
      }
    }
  }
  return { calls, pinned };
}

function isDeferredModuleStatement(statement: ScopeStatement): boolean {
  const node = statement.type === "ExportNamedDeclaration" || statement.type === "ExportDefaultDeclaration"
    ? statement.declaration : statement;
  if (node === null || node.type === "FunctionDeclaration" || node.type === "TSDeclareFunction" ||
    node.type === "TSInterfaceDeclaration" || node.type === "TSTypeAliasDeclaration" ||
    node.type === "ImportDeclaration" || node.type === "ExportAllDeclaration" || node.type === "EmptyStatement") {
    return true;
  }
  return node.type === "VariableDeclaration" && node.declarations.every((declaration) =>
    declaration.id.type === "Identifier" && declaration.init !== null &&
    isFunction(unwrapExpression(declaration.init)));
}

function exportedNames(program: ESTree.Program): Set<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (statement.type === "ExportNamedDeclaration") addNamedExports(statement, names);
    else if (statement.type === "ExportDefaultDeclaration") addDefaultExport(statement.declaration, names);
  }
  return names;
}

function addNamedExports(statement: ESTree.ExportNamedDeclaration, names: Set<string>): void {
  if (statement.exportKind === "type" || statement.source !== null) return;
  const declaration = statement.declaration;
  if (declaration?.type === "FunctionDeclaration" && declaration.id !== null) names.add(declaration.id.name);
  if (declaration?.type === "VariableDeclaration") {
    for (const declarator of declaration.declarations) {
      if (declarator.id.type === "Identifier") names.add(declarator.id.name);
    }
  }
  for (const specifier of statement.specifiers) {
    if (specifier.exportKind !== "type" && specifier.local.type === "Identifier") names.add(specifier.local.name);
  }
}

function addDefaultExport(declaration: ESTree.ExportDefaultDeclaration["declaration"], names: Set<string>): void {
  if (declaration.type === "Identifier") names.add(declaration.name);
  if (declaration.type === "FunctionDeclaration" && declaration.id !== null) names.add(declaration.id.name);
}

function moduleDefinitions(program: DeclarationScope): Definition[] {
  const definitions: Definition[] = [];
  for (const statement of program.body) {
    const node = statement.type === "ExportNamedDeclaration" || statement.type === "ExportDefaultDeclaration"
      ? statement.declaration : statement;
    if (node?.type === "FunctionDeclaration" && node.id !== null && node.body !== null) {
      definitions.push({ key: node.id.name, name: node.id.name, node, functionNode: node, bindingNode: node });
    } else if (node?.type === "VariableDeclaration" && node.kind === "const" && node.declarations.length === 1) {
      definitions.push(...node.declarations.flatMap(constFunctionDefinition));
    }
  }
  return definitions;
}

/** `const helper = () => …` (through erased type wrappers). */
function constFunctionDefinition(declarator: ESTree.VariableDeclarator): Definition[] {
  const initializer = declarator.init === null ? null : unwrapExpression(declarator.init);
  if (declarator.id.type !== "Identifier" || initializer === null || !isFunction(initializer)) return [];
  const { name } = declarator.id;
  return [{ key: name, name, node: declarator, functionNode: initializer, bindingNode: declarator }];
}

function methodName(node: MethodNode): string | null {
  if (node.key.type === "PrivateIdentifier") return `#${node.key.name}`;
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  return node.key.type === "Literal" && typeof node.key.value === "string" ? node.key.value : null;
}

function methodKey(name: string, isStatic: boolean): string {
  return `${isStatic ? "static" : "instance"}:${name}`;
}

type Domain = boolean | "unrelated" | null;
type Receivers = ReadonlyMap<TsVariable, boolean>;

function receiverDomain(state: FileState, object: Node, receivers: Receivers, thisIsStatic: boolean): Domain {
  const unwrapped = unwrapExpression(object);
  if (unwrapped.type === "ThisExpression") return thisIsStatic;
  return externalReceiverDomain(state, unwrapped, receivers);
}

/** Resolve receiver identity through immutable bindings without guessing from property names. */
function externalReceiverDomain(state: FileState, object: Node, receivers: Receivers): Domain {
  const origin = receiverOrigin(state, object, receivers);
  if (origin === null || typeof origin === "boolean") return origin;
  if (origin.type === "NewExpression") {
    return receiverOrigin(state, origin.callee, receivers) === true ? false : null;
  }
  if (origin.type === "ObjectExpression" || origin.type === "ArrayExpression" || origin.type === "Literal" ||
    origin.type === "ArrowFunctionExpression" || origin.type === "FunctionExpression") return "unrelated";
  return null;
}

/** Follow immutable alias chains to a known class receiver or a concrete initializer. */
function receiverOrigin(state: FileState, object: Node, receivers: Receivers): Node | boolean | null {
  const chain = aliasChain(state, object);
  for (const variable of chain.variables) {
    const known = receivers.get(variable);
    if (known !== undefined) return known;
  }
  return chain.end;
}

/**
 * The original walks the chain again for every class and every receiver map.
 * The chain does not depend on the receivers, which only stop the walk early,
 * so it is computed once per node and replayed against each receiver map.
 */
function aliasChain(state: FileState, object: Node): AliasChain {
  const cached = state.aliasChains.get(object);
  if (cached !== undefined) return cached;
  const variables: TsVariable[] = [];
  const seen = new Set<TsVariable>();
  let current = object;
  let end: Node | null;
  while (true) {
    const unwrapped = unwrapExpression(current);
    if (unwrapped.type !== "Identifier") {
      end = unwrapped;
      break;
    }
    const variable = findVariable(state.sourceCode.getScope(unwrapped), unwrapped.name);
    if (variable === null) {
      end = null;
      break;
    }
    variables.push(variable);
    const initializer = immutableInitializer(variable, seen);
    if (initializer === null) {
      end = null;
      break;
    }
    current = initializer;
  }
  const chain = { variables, end };
  state.aliasChains.set(object, chain);
  return chain;
}

function immutableInitializer(variable: TsVariable, seen: Set<TsVariable>): Node | null {
  if (seen.has(variable) || !stableVariable(variable) || variable.defs.length !== 1) return null;
  seen.add(variable);
  const definition = variable.defs[0];
  const node = definition?.node;
  if (node?.type !== "VariableDeclarator" || node.parent.type !== "VariableDeclaration" ||
    node.parent.kind !== "const") return null;
  return node.init;
}

function referencedPropertyName(node: ESTree.MemberExpression): string | null {
  if (node.property.type === "PrivateIdentifier") return `#${node.property.name}`;
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  return node.computed && node.property.type === "Literal" && typeof node.property.value === "string"
    ? node.property.value : null;
}

function walk(
  node: Node,
  visitorKeys: VisitorKeys,
  visit: (node: Node, nestedFunction: boolean) => void,
  nestedFunction = false,
): void {
  visit(node, nestedFunction);
  const nested = nestedFunction || isFunction(node) || node.type === "ClassDeclaration" ||
    node.type === "ClassExpression";
  forEachAstChild(node, visitorKeys, (child) => {
    walk(child, visitorKeys, visit, nested);
  });
}

function isPrivateMethod(node: Node): boolean {
  return node.type === "MethodDefinition" && (node.accessibility === "private" || node.key.type === "PrivateIdentifier");
}

function receiverDestructuring(node: Node): { binding: ESTree.ObjectPattern; value: Node } | null {
  if (node.type === "VariableDeclarator" && node.id.type === "ObjectPattern" && node.init !== null) {
    return { binding: node.id, value: node.init };
  }
  if ((node.type === "AssignmentPattern" || node.type === "AssignmentExpression") &&
    node.left.type === "ObjectPattern") {
    // Oxlint types an assignment's pattern as ObjectAssignmentTarget; its runtime shape is an ObjectPattern.
    return { binding: node.left as ESTree.ObjectPattern, value: node.right };
  }
  return null;
}

function classScope(
  state: FileState,
  node: ClassNode,
  computedReferences: readonly ESTree.MemberExpression[],
  privateBandOnly: boolean,
): void {
  const visitorKeys = state.sourceCode.visitorKeys;
  const methods = node.body.body.flatMap((member) => member.type === "MethodDefinition" ? [member] : []);
  const counts = classMethodCounts(node.body, methods);
  const implementations = methods.filter((method) => isFunction(method.value));
  const implementationCounts = classMethodCounts(node.body, implementations);
  const scopeDefinitions = implementations.flatMap((method) => {
    const name = methodName(method);
    const key = name === null ? null : methodKey(name, method.static);
    return name !== null && key !== null && implementationCounts.get(key) === 1
      ? [{ key, name, node: method }] : [];
  });
  const definitions = scopeDefinitions.filter(({ key, node: method }) =>
    isPrivateMethod(method) && counts.get(key) === 1 && method.decorators.length === 0 && !method.computed &&
    method.kind === "method");
  if (definitions.length === 0) return;
  const methodKeys = new Set(scopeDefinitions.map((definition) => definition.key));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();
  const classReceivers = classReceiverBindings(state, node);
  const pinNames = (name: string | null, domain: boolean | null = null): void => {
    for (const definition of definitions) {
      if ((name === null || definition.name === name) && (domain === null || definition.node.static === domain)) {
        pinned.add(definition.key);
      }
    }
  };
  const pinDestructuredMembers = (binding: ESTree.ObjectPattern, domain: boolean | null): void => {
    for (const property of binding.properties) {
      if (property.type === "RestElement" || property.computed) {
        pinNames(null, domain);
      } else if (property.key.type === "Identifier") {
        pinNames(property.key.name, domain);
      } else if (property.key.type === "Literal" && typeof property.key.value === "string") {
        pinNames(property.key.value, domain);
      }
    }
  };
  const collectMethodCalls = (method: MethodNode): void => {
    const name = methodName(method);
    if (name === null) {
      pinNames(null);
      return;
    }
    const methodFunction = method.value;
    if (!isFunction(methodFunction) || methodFunction.body === null) return;
    const body = methodFunction.body;
    const caller = methodKey(name, method.static);
    const receivers = new Map(classReceivers);
    const parameterDecoratorNodes = new Set<Node>();
    for (const parameter of methodFunction.params) {
      for (const decorator of (parameter as { decorators?: readonly Node[] }).decorators ?? []) {
        walk(decorator, visitorKeys, (current) => parameterDecoratorNodes.add(current));
      }
    }
    const collectAlias = (current: Node, nestedFunction: boolean): void => {
      if (nestedFunction || current.type !== "VariableDeclarator" || current.init === null) return;
      const domain = receiverDomain(state, current.init, receivers, method.static);
      if (domain === null || domain === "unrelated") return;
      if (current.id.type === "ObjectPattern") {
        pinDestructuredMembers(current.id, domain);
        return;
      }
      if (current.id.type !== "Identifier") return;
      if (current.parent.type !== "VariableDeclaration" || current.parent.kind !== "const") {
        pinNames(null, domain);
        return;
      }
      const variable = declaredVariable(state, current);
      if (variable === undefined || !stableVariable(variable)) return;
      const local = variable.references.every((reference) => {
        if (!reference.isRead()) return true;
        const expression = wrappedExpression(reference.identifier);
        const parent = parentOf(expression);
        return enclosingFunction(reference.identifier) === methodFunction &&
          parent?.type === "MemberExpression" && parent.object === expression;
      });
      if (local) receivers.set(variable, domain);
      else pinNames(null, domain);
    };
    for (const statement of body.body) walk(statement, visitorKeys, collectAlias);

    const visitCall = (current: Node, nestedFunction: boolean): void => {
      const destructuring = receiverDestructuring(current);
      if (destructuring !== null) {
        const domain = receiverDomain(state, destructuring.value, receivers, method.static);
        if (domain !== "unrelated") pinDestructuredMembers(destructuring.binding, domain);
      }
      if (current.type !== "MemberExpression") return;
      const domain = receiverDomain(state, current.object, receivers, method.static);
      const targetName = referencedPropertyName(current);
      if (domain === "unrelated") return;
      if (domain === null) {
        pinNames(targetName);
        return;
      }
      if (targetName === null) {
        if (current.computed) pinNames(null, domain);
        return;
      }
      const target = methodKey(targetName, domain);
      if (!methodKeys.has(target)) return;
      if (current.computed || nestedFunction || parameterDecoratorNodes.has(current)) {
        pinned.add(target);
        return;
      }
      const count = localCallCount(state, current, methodFunction);
      if (count === null) {
        pinned.add(target);
      } else if (count > 0) {
        addEdge(calls, caller, target);
      }
    };
    for (const decorator of method.decorators) walk(decorator, visitorKeys, visitCall, true);
    if (method.computed) walk(method.key, visitorKeys, visitCall, true);
    for (const parameter of methodFunction.params) walk(parameter, visitorKeys, visitCall);
    for (const statement of body.body) walk(statement, visitorKeys, visitCall);
  };
  for (const method of methods) collectMethodCalls(method);
  for (const member of node.body.body) {
    if (member.type === "MethodDefinition" || member.type === "TSAbstractMethodDefinition") continue;
    walk(member, visitorKeys, (current) => {
      if (current.type !== "MemberExpression") return;
      if (externalReceiverDomain(state, current.object, classReceivers) === "unrelated") return;
      pinNames(referencedPropertyName(current));
    });
  }
  const externalReceivers = new Map(classReceivers);
  for (const variable of state.sourceCode.getDeclaredVariables(node)) {
    const binding = tsVariable(variable);
    if (stableVariable(binding)) externalReceivers.set(binding, true);
  }
  for (const reference of computedReferences) {
    if (hasAncestor(reference, node)) continue;
    const domain = externalReceiverDomain(state, reference.object, externalReceivers);
    if (domain === "unrelated") continue;
    const name = referencedPropertyName(reference);
    if (name !== null || domain !== null) pinNames(name, domain);
  }

  reportMisordered(state, definitions, scopeDefinitions, calls, pinned, classMemberMove(node.body, privateBandOnly));
}

/** A helper method may move below its caller only within one run of members between runtime barriers. */
function classMemberMove(body: ESTree.ClassBody, privateBandOnly: boolean): (helper: Definition, caller: Definition) => boolean {
  const memberIndexes = new Map<Node, number>(body.body.map((member, index) => [member, index]));
  const runtimeBarrierPrefix = barrierRuns(body.body, isClassRuntimeBarrier);
  return (helper, caller) => {
    if (privateBandOnly && !isPrivateMethod(caller.node)) return false;
    const helperIndex = memberIndexes.get(helper.node);
    const callerIndex = memberIndexes.get(caller.node);
    if (helperIndex === undefined || callerIndex === undefined) return false;
    return runtimeBarrierPrefix[callerIndex + 1] === runtimeBarrierPrefix[helperIndex + 1];
  };
}

function isClassRuntimeBarrier(member: ESTree.ClassElement): boolean {
  switch (member.type) {
    case "StaticBlock":
      return true;
    case "PropertyDefinition":
    case "AccessorProperty":
      return member.static || member.computed || member.decorators.length > 0 || member.value !== null;
    case "MethodDefinition":
      return member.computed || member.decorators.length > 0;
    default:
      return false;
  }
}

function classReceiverBindings(state: FileState, node: ClassNode): Map<TsVariable, boolean> {
  const classReceivers = new Map<TsVariable, boolean>();
  if (node.id !== null) {
    const internal = findVariable(state.sourceCode.getScope(node), node.id.name);
    if (internal !== null && stableVariable(internal)) classReceivers.set(internal, true);
  }
  const parent = node.parent;
  if (node.type === "ClassExpression" && parent.type === "VariableDeclarator" && parent.id.type === "Identifier" &&
    parent.parent.type === "VariableDeclaration" && parent.parent.kind === "const") {
    const outer = findVariable(state.sourceCode.getScope(parent), parent.id.name);
    if (outer !== null && stableVariable(outer)) classReceivers.set(outer, true);
  }
  return classReceivers;
}

function classMethodCounts(body: ESTree.ClassBody, methods: readonly MethodNode[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const method of methods) {
    const name = methodName(method);
    if (name !== null) {
      const key = methodKey(name, method.static);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  for (const member of body.body) {
    if (member.type !== "TSAbstractMethodDefinition") continue;
    const name = !member.computed && member.key.type === "Identifier" ? member.key.name : null;
    if (name !== null) {
      const key = methodKey(name, member.static);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

function hasAncestor(node: Node, ancestor: Node): boolean {
  let current = parentOf(node);
  while (current !== null) {
    if (current === ancestor) return true;
    current = parentOf(current);
  }
  return false;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Place a private helper below its sole direct same-scope caller.",
      url: docsUrl("stepdown"),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          privateBandOnly: {
            type: "boolean",
            description:
              "Restrict class reports to private callers when another rule owns accessibility-band ordering.",
          },
        },
      },
    ],
    messages: {
      helperAboveOnlyCaller:
        "Private helper `{{helper}}` is defined above its only caller `{{caller}}`; move it below the caller.",
    },
  },
  createOnce(context) {
    const state = { context, aliasChains: new Map() } as unknown as FileState;
    let privateBandOnly = false;
    let classes: ClassNode[] = [];
    let functionBodies: ESTree.FunctionBody[] = [];
    let computedReferences: ESTree.MemberExpression[] = [];
    const collectBody = (node: FunctionNode): void => {
      if (node.body?.type === "BlockStatement") functionBodies.push(node.body);
    };
    const collectClass = (node: ClassNode): void => {
      classes.push(node);
    };
    return {
      before() {
        const sourceCode = context.sourceCode;
        if (isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        state.sourceCode = sourceCode;
        state.aliasChains.clear();
        STABLE_VARIABLES.clear();
        const options = context.options[0] as { readonly privateBandOnly?: boolean } | undefined;
        privateBandOnly = options?.privateBandOnly === true;
        classes = [];
        functionBodies = [];
        computedReferences = [];
        return undefined;
      },
      ClassDeclaration: collectClass,
      ClassExpression: collectClass,
      FunctionDeclaration: collectBody,
      FunctionExpression: collectBody,
      ArrowFunctionExpression: collectBody,
      // The original walks the whole program for these once it has seen a class.
      MemberExpression(node) {
        if (node.computed) computedReferences.push(node);
      },
      "Program:exit"(program) {
        declarationScope(state, program);
        for (const body of functionBodies) declarationScope(state, body);
        for (const node of classes) classScope(state, node, computedReferences, privateBandOnly);
      },
    };
  },
});
