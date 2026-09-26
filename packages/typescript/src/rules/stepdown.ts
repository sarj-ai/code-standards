/**
 * @fileoverview stepdown — a private helper with one direct same-scope caller belongs below that caller.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/stepdown.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "helperAboveOnlyCaller";
type Options = [];

export const STEPDOWN_DOCUMENTATION = {
  summary: "Place a private helper below its sole direct same-scope caller.",
  rationale: "Caller-first ordering lets a reader follow the main flow before descending into implementation details.",
  remediation: "Consider moving the private helper below its sole caller after reviewing initialization and reflection dependencies.",
  category: "maintainability",
  limitations: [
    "Generated and test files, cycles, dynamic or escaped references, overload targets, and helpers with multiple callers are excluded; immutable local callable aliases are followed only when every use stays in the caller.",
    "Class helpers must be private; their sole caller may be public, protected, or private.",
    "Runtime class-field, static-block, computed-member, and decorator barriers are never crossed; non-hoisted module helpers also cannot cross eager execution or unrelated initialization.",
    "This rule is report-only: reordering methods can change reflective property order, and moving module declarations can change initialization behavior or introduce temporal-dead-zone failures. Review module cycles and eager callers manually.",
  ],
  examples: [
    { id: "caller-before-helper", title: "Place the caller first", outcome: "no-match", files: [{ path: "src/run.ts", source: "function run() { return load(); }\nfunction load() { return 1; }" }], focusPath: "src/run.ts", expectedCount: 0, public: true },
    { id: "helper-before-caller", title: "Do not lead with a sole-caller helper", outcome: "match", files: [{ path: "src/run.ts", source: "function load() { return 1; }\nfunction run() { return load(); }" }], focusPath: "src/run.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type FunctionNode =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;

interface Definition {
  readonly key: string;
  readonly name: string;
  readonly node: TSESTree.Node;
  readonly functionNode?: FunctionNode;
  readonly bindingNode?: TSESTree.FunctionDeclaration | TSESTree.VariableDeclarator;
}

function isFunction(node: TSESTree.Node): node is FunctionNode {
  return (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.FunctionExpression
  );
}

function reportMisordered(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  candidates: readonly Definition[],
  scopeDefinitions: readonly Definition[],
  calls: ReadonlyMap<string, ReadonlySet<string>>,
  pinned: ReadonlySet<string>,
  canMove: (helper: Definition, caller: Definition) => boolean = () => true,
): void {
  const byName = new Map(scopeDefinitions.map((definition) => [definition.key, definition]));
  const cycles = cycleComponents(calls);
  const callers = new Map<string, Set<string>>();
  for (const [caller, callees] of calls) {
    for (const callee of callees) {
      if (caller === callee) continue;
      const names = callers.get(callee) ?? new Set<string>();
      names.add(caller);
      callers.set(callee, names);
    }
  }
  for (const helper of candidates) {
    const helperCallers = [...(callers.get(helper.key) ?? [])];
    if (pinned.has(helper.key) || helperCallers.length !== 1) continue;
    const callerName = helperCallers[0];
    if (
      callerName === undefined ||
      (cycles.has(helper.key) && cycles.get(helper.key) === cycles.get(callerName))
    ) continue;
    const caller = byName.get(callerName);
    if (caller === undefined || helper.node.range[0] >= caller.node.range[0] || !canMove(helper, caller)) continue;
    context.report({
      node: helper.node,
      messageId: "helperAboveOnlyCaller",
      data: { helper: helper.name, caller: caller.name },
    });
  }
}

/** Iterative Kosaraju SCC index; self recursion is not an ordering cycle. */
function cycleComponents(graph: ReadonlyMap<string, ReadonlySet<string>>): ReadonlyMap<string, number> {
  const nodes = new Set<string>();
  const reverse = new Map<string, Set<string>>();
  for (const [caller, callees] of graph) {
    nodes.add(caller);
    for (const callee of callees) {
      nodes.add(callee);
      const incoming = reverse.get(callee) ?? new Set<string>();
      incoming.add(caller);
      reverse.set(callee, incoming);
    }
  }
  const seen = new Set<string>();
  const finishOrder: string[] = [];
  function finishTraversal(root: string): void {
    if (seen.has(root)) return;
    const pending: Array<{ readonly name: string; readonly exiting: boolean }> = [
      { name: root, exiting: false },
    ];
    while (pending.length > 0) {
      const current = pending.pop();
      if (current === undefined) break;
      if (current.exiting) {
        finishOrder.push(current.name);
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

  for (const root of nodes) { finishTraversal(root); }
  const components = new Map<string, number>();
  let nextComponent = 0;
  const assigned = new Set<string>();
  function assignComponent(index: number): void {
    const root = finishOrder[index];
    if (root === undefined || assigned.has(root)) return;
    const members: string[] = [];
    const pending = [root];
    assigned.add(root);
    while (pending.length > 0) {
      const member = pending.pop();
      if (member === undefined) break;
      members.push(member);
      for (const caller of reverse.get(member) ?? []) {
        if (!assigned.has(caller)) {
          assigned.add(caller);
          pending.push(caller);
        }
      }
    }
    if (members.length > 1) {
      for (const cyclicName of members) components.set(cyclicName, nextComponent);
      nextComponent += 1;
    }
  }

  for (let index = finishOrder.length - 1;index >= 0;index -= 1) { assignComponent(index); }
  return components;
}

type ErasedExpression =
  | TSESTree.TSAsExpression
  | TSESTree.TSTypeAssertion
  | TSESTree.TSSatisfiesExpression
  | TSESTree.TSNonNullExpression
  | TSESTree.TSInstantiationExpression;

type Variable = NonNullable<ReturnType<typeof ASTUtils.findVariable>>;

function isErasedExpression(node: TSESTree.Node): node is ErasedExpression {
  return node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSInstantiationExpression;
}

function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  let current = node;
  while (isErasedExpression(current)) current = current.expression;
  return current;
}

function wrappedExpression(node: TSESTree.Node): TSESTree.Node {
  let current = node;
  while (current.parent !== undefined && isErasedExpression(current.parent) && current.parent.expression === current) current = current.parent;
  return current;
}

function enclosingFunction(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.Node,
): FunctionNode | undefined {
  return [...context.sourceCode.getAncestors(node)].reverse().find(isFunction);
}

/** A value is callable here only when every alias use remains a direct local call. */
function localCallCount(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.Node,
  owner: FunctionNode,
): number | null {
  const seen = new Set<Variable>();
  const pending = [node];
  let count = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined || enclosingFunction(context, current) !== owner) return null;
    const expression = wrappedExpression(current);
    const parent = expression.parent;
    if (parent?.type === AST_NODE_TYPES.CallExpression && parent.callee === expression) {
      count += 1;
      continue;
    }
    if (
      parent?.type !== AST_NODE_TYPES.VariableDeclarator || parent.init !== expression ||
      parent.id.type !== AST_NODE_TYPES.Identifier ||
      parent.parent.type !== AST_NODE_TYPES.VariableDeclaration || parent.parent.kind !== "const"
    ) return null;
    const variable = context.sourceCode.getDeclaredVariables(parent)[0];
    if (variable === undefined || seen.has(variable) || !stableVariable(variable)) return null;
    seen.add(variable);
    pending.push(...variable.references.filter((reference) => reference.isRead()).map((reference) => reference.identifier));
  }
  return count;
}

function moduleScope(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  program: TSESTree.Program,
): void {
  const declarations = moduleDefinitions(program);
  const counts = new Map<string, number>();
  for (const node of declarations) counts.set(node.name, (counts.get(node.name) ?? 0) + 1);
  const overloadNames = new Set(
    program.body.flatMap((statement) => {
      const node = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
      return node?.type === AST_NODE_TYPES.TSDeclareFunction && node.id !== null ? [node.id.name] : [];
    }),
  );
  const exported = exportedNames(program);
  const scopeDefinitions = declarations.filter((node) => counts.get(node.name) === 1);
  const definitions = scopeDefinitions.filter(
    (definition) => !exported.has(definition.name) && !overloadNames.has(definition.name),
  );
  const { calls, pinned } = moduleCallGraph(context, scopeDefinitions);
  const statementIndexes = new Map(program.body.map((statement, index) => [statement, index]));
  const runtimeBarrierPrefix = [0];
  for (const statement of program.body) {
    runtimeBarrierPrefix.push((runtimeBarrierPrefix.at(-1) ?? 0) + (isDeferredModuleStatement(statement) ? 0 : 1));
  }
  const statementIndex = (definition: Definition): number | undefined => {
    let current = definition.node;
    while (current.parent !== undefined && current.parent.type !== AST_NODE_TYPES.Program) current = current.parent;
    return statementIndexes.get(current as TSESTree.ProgramStatement);
  };
  const canMove = (helper: Definition, caller: Definition): boolean => {
    if (helper.node.type === AST_NODE_TYPES.FunctionDeclaration) return true;
    const helperIndex = statementIndex(helper);
    const callerIndex = statementIndex(caller);
    return helperIndex !== undefined && callerIndex !== undefined &&
      runtimeBarrierPrefix[callerIndex + 1] === runtimeBarrierPrefix[helperIndex + 1];
  };
  reportMisordered(context, definitions, scopeDefinitions, calls, pinned, canMove);
}

function moduleCallGraph(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  scopeDefinitions: readonly Definition[],
): { calls: Map<string, Set<string>>; pinned: Set<string> } {
  const byFunction = new Map(scopeDefinitions.map((definition) => [definition.functionNode, definition]));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();

  for (const definition of scopeDefinitions) {
    const variable = context.sourceCode.getDeclaredVariables(definition.bindingNode!)[0];
    for (const reference of variable?.references ?? []) {
      if (reference.isWrite() && reference.init !== true) {
        pinned.add(definition.key);
        continue;
      }
      if (!reference.isRead()) continue;
      const callerDefinition = byFunction.get(enclosingFunction(context, reference.identifier));
      if (callerDefinition?.functionNode === undefined) {
        pinned.add(definition.key);
        continue;
      }
      const count = localCallCount(context, reference.identifier, callerDefinition.functionNode);
      if (count === null) {
        pinned.add(definition.key);
      } else if (count > 0) {
        const callees = calls.get(callerDefinition.key) ?? new Set<string>();
        callees.add(definition.key);
        calls.set(callerDefinition.key, callees);
      }
    }
  }
  return { calls, pinned };
}

function isDeferredModuleStatement(statement: TSESTree.ProgramStatement): boolean {
  const node = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    statement.type === AST_NODE_TYPES.ExportDefaultDeclaration ? statement.declaration : statement;
  if (node === null || node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.TSDeclareFunction || node.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
    node.type === AST_NODE_TYPES.TSTypeAliasDeclaration || node.type === AST_NODE_TYPES.ImportDeclaration ||
    node.type === AST_NODE_TYPES.ExportAllDeclaration || node.type === AST_NODE_TYPES.EmptyStatement) return true;
  return node.type === AST_NODE_TYPES.VariableDeclaration && node.declarations.every((declaration) =>
    declaration.id.type === AST_NODE_TYPES.Identifier && declaration.init !== null &&
    isFunction(unwrapExpression(declaration.init)),
  );
}

function exportedNames(program: TSESTree.Program): Set<string> {
  const names = new Set<string>();
  function collectNamedExports(statement: TSESTree.ProgramStatement): void {
    if (
      statement.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.exportKind === "type" ||
      statement.source !== null
    ) return;
    if (statement.declaration?.type === AST_NODE_TYPES.FunctionDeclaration && statement.declaration.id !== null) {
      names.add(statement.declaration.id.name);
    }
    if (statement.declaration?.type === AST_NODE_TYPES.VariableDeclaration) {
      for (const declarator of statement.declaration.declarations) {
        if (declarator.id.type === AST_NODE_TYPES.Identifier) names.add(declarator.id.name);
      }
    }
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind !== "type" && specifier.local.type === AST_NODE_TYPES.Identifier) {
        names.add(specifier.local.name);
      }
    }
  }

  for (const statement of program.body) { collectNamedExports(statement); }
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      statement.declaration.type === AST_NODE_TYPES.Identifier
    ) names.add(statement.declaration.name);
    if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      statement.declaration.type === AST_NODE_TYPES.FunctionDeclaration &&
      statement.declaration.id !== null
    ) names.add(statement.declaration.id.name);
  }
  return names;
}

function moduleDefinitions(program: TSESTree.Program): Definition[] {
  const definitions: Definition[] = [];
  for (const statement of program.body) {
    const node = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration
      ? statement.declaration
      : statement;
    if (node?.type === AST_NODE_TYPES.FunctionDeclaration && node.id !== null && node.body !== null) {
      definitions.push({ key: node.id.name, name: node.id.name, node, functionNode: node, bindingNode: node });
      continue;
    }
    if (node?.type !== AST_NODE_TYPES.VariableDeclaration || node.kind !== "const" || node.declarations.length !== 1) continue;
    for (const declarator of node.declarations) {
      const initializer = declarator.init === null ? null : unwrapExpression(declarator.init);
      if (declarator.id.type === AST_NODE_TYPES.Identifier && initializer !== null && isFunction(initializer)) {
        definitions.push({
          key: declarator.id.name,
          name: declarator.id.name,
          node: declarator,
          functionNode: initializer,
          bindingNode: declarator,
        });
      }
    }
  }
  return definitions;
}

function methodName(node: TSESTree.MethodDefinition): string | null {
  if (node.key.type === AST_NODE_TYPES.PrivateIdentifier) return `#${node.key.name}`;
  if (!node.computed && node.key.type === AST_NODE_TYPES.Identifier) return node.key.name;
  return node.key.type === AST_NODE_TYPES.Literal && typeof node.key.value === "string" ? node.key.value : null;
}

function methodKey(name: string, isStatic: boolean): string {
  return `${isStatic ? "static" : "instance"}:${name}`;
}

function receiverDomain(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  object: TSESTree.Node,
  receivers: ReadonlyMap<Variable, boolean>,
  thisIsStatic: boolean,
): boolean | null {
  const unwrapped = unwrapExpression(object);
  if (unwrapped.type === AST_NODE_TYPES.ThisExpression) return thisIsStatic;
  if (unwrapped.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(unwrapped), unwrapped.name);
  return variable === null ? null : receivers.get(variable) ?? null;
}

function stableVariable(variable: Variable): boolean {
  return !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
}

function referencedPropertyName(node: TSESTree.MemberExpression): string | null {
  if (node.property.type === AST_NODE_TYPES.PrivateIdentifier) return `#${node.property.name}`;
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  return node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
    ? node.property.value
    : null;
}

function walk(
  node: TSESTree.Node,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
  visit: (node: TSESTree.Node, nestedFunction: boolean) => void,
  nestedFunction = false,
): void {
  visit(node, nestedFunction);
  const nested = nestedFunction || isFunction(node) ||
    node.type === AST_NODE_TYPES.ClassDeclaration || node.type === AST_NODE_TYPES.ClassExpression;
  forEachAstChild(node, visitorKeys, child => walk(child, visitorKeys, visit, nested));
}

function classScope(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
  computedReferenceNames: ReadonlySet<string>,
): void {
  const methods = node.body.body.filter(
    (member): member is TSESTree.MethodDefinition => member.type === AST_NODE_TYPES.MethodDefinition,
  );
  const counts = classMethodCounts(node.body, methods);
  const implementations = methods.filter((method) => isFunction(method.value));
  const implementationCounts = classMethodCounts(node.body, implementations);
  const scopeDefinitions = implementations.flatMap((method) => {
    const name = methodName(method);
    const key = name === null ? null : methodKey(name, method.static);
    return name !== null && key !== null && implementationCounts.get(key) === 1 ? [{ key, name, node: method }] : [];
  });
  const definitions = scopeDefinitions.filter(({ key, node: method }) =>
    (method.accessibility === "private" || method.key.type === AST_NODE_TYPES.PrivateIdentifier) &&
    counts.get(key) === 1 && method.decorators.length === 0 && !method.computed && method.kind === "method",
  );
  if (definitions.length === 0) return;
  const methodKeys = new Set(scopeDefinitions.map((definition) => definition.key));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();
  const classReceivers = classReceiverBindings(context, node);
  const pinNames = (name: string | null, domain: boolean | null = null): void => {
    for (const definition of definitions) {
      if ((name === null || definition.name === name) && (domain === null || definition.node.static === domain)) {
        pinned.add(definition.key);
      }
    }
  };
  function pinDestructuredMembers(binding: TSESTree.ObjectPattern, domain: boolean | null): void {
    for (const property of binding.properties) {
      if (property.type === AST_NODE_TYPES.RestElement || property.computed) {
        pinNames(null, domain);
      } else if (property.key.type === AST_NODE_TYPES.Identifier) {
        pinNames(property.key.name, domain);
      } else if (property.key.type === AST_NODE_TYPES.Literal && typeof property.key.value === "string") {
        pinNames(property.key.value, domain);
      }
    }
  }
  function collectMethodCalls(method: TSESTree.MethodDefinition): void {
    const name = methodName(method);
    if (name === null) {
      pinNames(null);
      return;
    }
    if (!isFunction(method.value)) return;
    const methodFunction = method.value;
    const caller = methodKey(name, method.static);
    const receivers = new Map(classReceivers);
    const parameterDecoratorNodes = new Set<TSESTree.Node>();
    for (const parameter of method.value.params) {
      for (const decorator of parameter.decorators) {
        walk(decorator, context.sourceCode.visitorKeys, (current) => parameterDecoratorNodes.add(current));
      }
    }
    const collectAlias = (current: TSESTree.Node, nestedFunction: boolean): void => {
      if (nestedFunction || current.type !== AST_NODE_TYPES.VariableDeclarator || current.init === null) return;
      const domain = receiverDomain(context, current.init, receivers, method.static);
      if (domain === null) return;
      if (current.id.type === AST_NODE_TYPES.ObjectPattern) {
        pinDestructuredMembers(current.id, domain);
        return;
      }
      if (current.id.type !== AST_NODE_TYPES.Identifier) return;
      if (current.parent.type !== AST_NODE_TYPES.VariableDeclaration || current.parent.kind !== "const") {
        pinNames(null, domain);
        return;
      }
      const variable = context.sourceCode.getDeclaredVariables(current)[0];
      if (variable === undefined || !stableVariable(variable)) return;
      const local = variable.references.every((reference) => {
        if (!reference.isRead()) return true;
        const expression = wrappedExpression(reference.identifier);
        return enclosingFunction(context, reference.identifier) === methodFunction &&
          expression.parent?.type === AST_NODE_TYPES.MemberExpression && expression.parent.object === expression;
      });
      if (local) receivers.set(variable, domain);
      else pinNames(null, domain);
    };
    for (const statement of method.value.body.body) walk(statement, context.sourceCode.visitorKeys, collectAlias);

    const visitCall = (current: TSESTree.Node, nestedFunction: boolean): void => {
      const destructuring = receiverDestructuring(current);
      if (destructuring !== null) {
        const domain = receiverDomain(context, destructuring.value, receivers, method.static);
        pinDestructuredMembers(destructuring.binding, domain);
      }
      if (current.type !== AST_NODE_TYPES.MemberExpression) return;
      const domain = receiverDomain(context, current.object, receivers, method.static);
      const targetName = referencedPropertyName(current);
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
      const count = localCallCount(context, current, methodFunction);
      if (count === null) {
        pinned.add(target);
      } else if (count > 0) {
        const callees = calls.get(caller) ?? new Set<string>();
        callees.add(target);
        calls.set(caller, callees);
      }
    };
    for (const decorator of method.decorators) walk(decorator, context.sourceCode.visitorKeys, visitCall, true);
    if (method.computed) walk(method.key, context.sourceCode.visitorKeys, visitCall, true);
    for (const parameter of method.value.params) walk(parameter, context.sourceCode.visitorKeys, visitCall);
    for (const statement of method.value.body.body) walk(statement, context.sourceCode.visitorKeys, visitCall);
  }
  for (const method of methods) collectMethodCalls(method);
  for (const member of node.body.body) {
    if (member.type === AST_NODE_TYPES.MethodDefinition || member.type === AST_NODE_TYPES.TSAbstractMethodDefinition) continue;
    walk(member, context.sourceCode.visitorKeys, (current) => {
      if (current.type !== AST_NODE_TYPES.MemberExpression) return;
      pinNames(referencedPropertyName(current));
    });
  }
  for (const definition of definitions) {
    if (computedReferenceNames.has(definition.name)) pinned.add(definition.key);
  }

  const memberIndexes = new Map(node.body.body.map((member, index) => [member, index]));
  const runtimeBarrierPrefix = [0];
  for (const member of node.body.body) {
    runtimeBarrierPrefix.push((runtimeBarrierPrefix.at(-1) ?? 0) + (isClassRuntimeBarrier(member) ? 1 : 0));
  }
  const canMove = (helper: Definition, caller: Definition): boolean => {
    const helperIndex = memberIndexes.get(helper.node as TSESTree.ClassElement);
    const callerIndex = memberIndexes.get(caller.node as TSESTree.ClassElement);
    if (helperIndex === undefined || callerIndex === undefined) return false;
    return runtimeBarrierPrefix[callerIndex + 1] === runtimeBarrierPrefix[helperIndex + 1];
  };

  reportMisordered(context, definitions, scopeDefinitions, calls, pinned, canMove);
}

function classReceiverBindings(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): Map<Variable, boolean> {
  const classReceivers = new Map<Variable, boolean>();
  if (node.id !== null) {
    const internal = ASTUtils.findVariable(context.sourceCode.getScope(node), node.id.name);
    if (internal !== null && stableVariable(internal)) classReceivers.set(internal, true);
  }
  if (
    node.type === AST_NODE_TYPES.ClassExpression &&
    node.parent.type === AST_NODE_TYPES.VariableDeclarator &&
    node.parent.id.type === AST_NODE_TYPES.Identifier &&
    node.parent.parent.type === AST_NODE_TYPES.VariableDeclaration && node.parent.parent.kind === "const"
  ) {
    const outer = ASTUtils.findVariable(context.sourceCode.getScope(node.parent), node.parent.id.name);
    if (outer !== null && stableVariable(outer)) classReceivers.set(outer, true);
  }
  return classReceivers;
}

function receiverDestructuring(node: TSESTree.Node): { binding: TSESTree.ObjectPattern; value: TSESTree.Node } | null {
  if (node.type === AST_NODE_TYPES.VariableDeclarator && node.id.type === AST_NODE_TYPES.ObjectPattern && node.init !== null) {
    return { binding: node.id, value: node.init };
  }
  if ((node.type === AST_NODE_TYPES.AssignmentPattern || node.type === AST_NODE_TYPES.AssignmentExpression) &&
    node.left.type === AST_NODE_TYPES.ObjectPattern) {
    return { binding: node.left, value: node.right };
  }
  return null;
}

function isClassRuntimeBarrier(member: TSESTree.ClassElement): boolean {
  switch (member.type) {
    case AST_NODE_TYPES.StaticBlock:
      return true;
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.AccessorProperty:
      return member.static || member.computed || member.decorators.length > 0 || member.value !== null;
    case AST_NODE_TYPES.MethodDefinition:
      return member.computed || member.decorators.length > 0;
    default:
      return false;
  }
}

export default createRule<Options, MessageIds>({
  name: "stepdown",
  documentation: STEPDOWN_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Place a private helper below its sole direct same-scope caller." },
    schema: [],
    messages: {
      helperAboveOnlyCaller:
        "Private helper `{{helper}}` is defined above its only caller `{{caller}}`; move it below the caller.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const classes: Array<TSESTree.ClassDeclaration | TSESTree.ClassExpression> = [];
    return {
      ClassDeclaration: (node): void => { classes.push(node); },
      ClassExpression: (node): void => { classes.push(node); },
      "Program:exit": (program): void => {
        moduleScope(context, program);
        const computedReferenceNames = new Set<string>();
        walk(program, context.sourceCode.visitorKeys, (node) => {
          if (
            node.type === AST_NODE_TYPES.MemberExpression &&
            node.computed &&
            node.property.type === AST_NODE_TYPES.Literal &&
            typeof node.property.value === "string"
          ) computedReferenceNames.add(node.property.value);
        });
        for (const node of classes) classScope(context, node, computedReferenceNames);
      },
    };
  },
});

function classMethodCounts(body: TSESTree.ClassBody, methods: readonly TSESTree.MethodDefinition[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const method of methods) {
    const name = methodName(method);
    if (name !== null) {
      const key = methodKey(name, method.static);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  for (const member of body.body) {
    if (member.type !== AST_NODE_TYPES.TSAbstractMethodDefinition) continue;
    const name = !member.computed && member.key.type === AST_NODE_TYPES.Identifier ? member.key.name : null;
    if (name !== null) {
      const key = methodKey(name, member.static);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}
