/**
 * @fileoverview stepdown — a private helper with one direct same-scope caller belongs below that caller.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/stepdown.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { nodeAncestors } from "./_scope.js";
import type { ESTree, Context, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "helperAboveOnlyCaller";
type Options = [];

export const STEPDOWN_DOCUMENTATION = {
  summary: "Place a private helper below its sole direct same-scope caller.",
  rationale:
    "Caller-first ordering lets a reader follow the main flow before descending into implementation details.",
  remediation:
    "Consider moving the private helper below its sole caller after reviewing initialization and reflection dependencies.",
  category: "maintainability",
  limitations: [
    "Generated and test files, cycles, dynamic or escaped references, overload targets, and helpers with multiple callers are excluded; immutable local callable aliases are followed only when every use stays in the caller. Function bodies include nested sibling helpers.",
    "Class helpers and their sole callers must belong to the private accessibility band; member-ordering owns cross-accessibility ordering.",
    "Runtime class-field, static-block, computed-member, and decorator barriers are never crossed; non-hoisted module helpers also cannot cross eager execution or unrelated initialization.",
    "This rule is report-only: reordering methods can change reflective property order, and moving module declarations can change initialization behavior or introduce temporal-dead-zone failures. Review module cycles and eager callers manually.",
  ],
  examples: [
    {
      id: "caller-before-helper",
      title: "Place the caller first",
      outcome: "no-match",
      files: [
        {
          path: "src/run.ts",
          source:
            "function run() { return load(); }\nfunction load() { return 1; }",
        },
      ],
      focusPath: "src/run.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "helper-before-caller",
      title: "Do not lead with a sole-caller helper",
      outcome: "match",
      files: [
        {
          path: "src/run.ts",
          source:
            "function load() { return 1; }\nfunction run() { return load(); }",
        },
      ],
      focusPath: "src/run.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

interface Definition {
  readonly key: string;
  readonly name: string;
  readonly node: ESTree.Node;
  readonly functionNode?: FunctionNode;
  readonly bindingNode?: ESTree.Function | ESTree.VariableDeclarator;
}

function isFunction(node: ESTree.Node): node is FunctionNode {
  return (
    node.type === "ArrowFunctionExpression" ||
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression"
  );
}

function reportMisordered(
  context: Readonly<Context>,
  candidates: readonly Definition[],
  scopeDefinitions: readonly Definition[],
  calls: ReadonlyMap<string, ReadonlySet<string>>,
  pinned: ReadonlySet<string>,
  canMove: (helper: Definition, caller: Definition) => boolean = () => true,
): void {
  const byName = new Map(
    scopeDefinitions.map((definition) => [definition.key, definition]),
  );
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
      (cycles.has(helper.key) &&
        cycles.get(helper.key) === cycles.get(callerName))
    )
      continue;
    const caller = byName.get(callerName);
    if (
      caller === undefined ||
      helper.node.range[0] >= caller.node.range[0] ||
      !canMove(helper, caller)
    )
      continue;
    context.report({
      node: helper.node,
      messageId: "helperAboveOnlyCaller",
      data: { helper: helper.name, caller: caller.name },
    });
  }
}

/** Iterative Kosaraju SCC index; self recursion is not an ordering cycle. */
function cycleComponents(
  graph: ReadonlyMap<string, ReadonlySet<string>>,
): ReadonlyMap<string, number> {
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
    const pending: Array<{ readonly name: string; readonly exiting: boolean }> =
      [{ name: root, exiting: false }];
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

  for (const root of nodes) {
    finishTraversal(root);
  }
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
      for (const cyclicName of members)
        components.set(cyclicName, nextComponent);
      nextComponent += 1;
    }
  }

  for (let index = finishOrder.length - 1; index >= 0; index -= 1) {
    assignComponent(index);
  }
  return components;
}

type ErasedExpression =
  | ESTree.TSAsExpression
  | ESTree.TSTypeAssertion
  | ESTree.TSSatisfiesExpression
  | ESTree.TSNonNullExpression
  | ESTree.TSInstantiationExpression;

type Variable = NonNullable<ReturnType<typeof findVariable>>;

function isErasedExpression(node: ESTree.Node): node is ErasedExpression {
  return (
    node.type === "TSAsExpression" ||
    node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression" ||
    node.type === "TSInstantiationExpression"
  );
}

function unwrapExpression(node: ESTree.Node): ESTree.Node {
  let current = node;
  while (isErasedExpression(current)) current = current.expression;
  return current;
}

function wrappedExpression(node: ESTree.Node): ESTree.Node {
  let current = node;
  while (
    current.parent !== null &&
    isErasedExpression(current.parent) &&
    current.parent.expression === current
  )
    current = current.parent;
  return current;
}

function enclosingFunction(node: ESTree.Node): FunctionNode | undefined {
  return nodeAncestors(node).toReversed().find(isFunction);
}

/** A value is callable here only when every alias use remains a direct local call. */
function localCallCount(
  context: Readonly<Context>,
  node: ESTree.Node,
  owner: FunctionNode,
): number | null {
  const seen = new Set<Variable>();
  const pending = [node];
  let count = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined || enclosingFunction(current) !== owner)
      return null;
    const expression = wrappedExpression(current);
    const parent = expression.parent;
    if (parent?.type === "CallExpression" && parent.callee === expression) {
      count += 1;
      continue;
    }
    if (
      parent?.type !== "VariableDeclarator" ||
      parent.init !== expression ||
      parent.id.type !== "Identifier" ||
      parent.parent.type !== "VariableDeclaration" ||
      parent.parent.kind !== "const"
    )
      return null;
    const variable = context.sourceCode.getDeclaredVariables(parent)[0];
    if (
      variable === undefined ||
      seen.has(variable) ||
      !stableVariable(variable)
    )
      return null;
    seen.add(variable);
    pending.push(
      ...variable.references
        .filter((reference) => reference.isRead())
        .map((reference) => reference.identifier),
    );
  }
  return count;
}

type DeclarationScope = ESTree.Program | ESTree.BlockStatement;

function declarationScope(
  context: Readonly<Context>,
  program: DeclarationScope,
): void {
  const declarations = moduleDefinitions(program);
  if (declarations.length < 2) return;
  const counts = new Map<string, number>();
  for (const node of declarations)
    counts.set(node.name, (counts.get(node.name) ?? 0) + 1);
  const overloadNames = new Set(
    program.body.flatMap((statement) => {
      const node =
        statement.type === "ExportNamedDeclaration"
          ? statement.declaration
          : statement;
      return node?.type === "TSDeclareFunction" && node.id !== null
        ? [node.id.name]
        : [];
    }),
  );
  const exported =
    program.type === "Program" ? exportedNames(program) : new Set<string>();
  const scopeDefinitions = declarations.filter(
    (node) => counts.get(node.name) === 1,
  );
  const definitions = scopeDefinitions.filter(
    (definition) =>
      !exported.has(definition.name) && !overloadNames.has(definition.name),
  );
  const { calls, pinned } = moduleCallGraph(context, scopeDefinitions);
  const statementIndexes = new Map<ESTree.Node, number>(
    program.body.map((statement, index) => [statement, index]),
  );
  const runtimeBarrierPrefix = [0];
  for (const statement of program.body) {
    runtimeBarrierPrefix.push(
      (runtimeBarrierPrefix.at(-1) ?? 0) +
        (isDeferredModuleStatement(statement) ? 0 : 1),
    );
  }
  const canMove = (helper: Definition, caller: Definition): boolean => {
    if (helper.node.type === "FunctionDeclaration") return true;
    const helperIndex = statementIndex(helper);
    const callerIndex = statementIndex(caller);
    return (
      helperIndex !== undefined &&
      callerIndex !== undefined &&
      runtimeBarrierPrefix[callerIndex + 1] ===
        runtimeBarrierPrefix[helperIndex + 1]
    );
  };
  const statementIndex = (definition: Definition): number | undefined => {
    let current = definition.node;
    while (current.parent !== null && current.parent !== program)
      current = current.parent;
    return statementIndexes.get(current);
  };
  reportMisordered(
    context,
    definitions,
    scopeDefinitions,
    calls,
    pinned,
    canMove,
  );
}

interface ModuleCallGraph {
  readonly calls: Map<string, Set<string>>;
  readonly pinned: Set<string>;
}

function moduleCallGraph(
  context: Readonly<Context>,
  scopeDefinitions: readonly Definition[],
): ModuleCallGraph {
  const byFunction = new Map(
    scopeDefinitions.map((definition) => [definition.functionNode, definition]),
  );
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();

  for (const definition of scopeDefinitions) {
    const variable = context.sourceCode.getDeclaredVariables(
      definition.bindingNode!,
    )[0];
    for (const reference of variable?.references ?? []) {
      if (reference.isWrite() && reference.init !== true) {
        pinned.add(definition.key);
        continue;
      }
      if (!reference.isRead()) continue;
      const callerDefinition = byFunction.get(
        enclosingFunction(reference.identifier),
      );
      if (callerDefinition?.functionNode === undefined) {
        pinned.add(definition.key);
        continue;
      }
      const count = localCallCount(
        context,
        reference.identifier,
        callerDefinition.functionNode,
      );
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

function isDeferredModuleStatement(statement: ESTree.Statement): boolean {
  const node =
    statement.type === "ExportNamedDeclaration" ||
    statement.type === "ExportDefaultDeclaration"
      ? statement.declaration
      : statement;
  if (
    node === null ||
    node.type === "FunctionDeclaration" ||
    node.type === "TSDeclareFunction" ||
    node.type === "TSInterfaceDeclaration" ||
    node.type === "TSTypeAliasDeclaration" ||
    node.type === "ImportDeclaration" ||
    node.type === "ExportAllDeclaration" ||
    node.type === "EmptyStatement"
  )
    return true;
  return (
    node.type === "VariableDeclaration" &&
    node.declarations.every(
      (declaration) =>
        declaration.id.type === "Identifier" &&
        declaration.init !== null &&
        isFunction(unwrapExpression(declaration.init)),
    )
  );
}

function exportedNames(program: ESTree.Program): Set<string> {
  const names = new Set<string>();
  function collectNamedExports(statement: ESTree.Statement): void {
    if (
      statement.type !== "ExportNamedDeclaration" ||
      statement.exportKind === "type" ||
      statement.source !== null
    )
      return;
    if (
      statement.declaration?.type === "FunctionDeclaration" &&
      statement.declaration.id !== null
    ) {
      names.add(statement.declaration.id.name);
    }
    if (statement.declaration?.type === "VariableDeclaration") {
      for (const declarator of statement.declaration.declarations) {
        if (declarator.id.type === "Identifier") names.add(declarator.id.name);
      }
    }
    for (const specifier of statement.specifiers) {
      if (
        specifier.exportKind !== "type" &&
        specifier.local.type === "Identifier"
      ) {
        names.add(specifier.local.name);
      }
    }
  }

  for (const statement of program.body) {
    collectNamedExports(statement);
  }
  for (const statement of program.body) {
    if (
      statement.type === "ExportDefaultDeclaration" &&
      statement.declaration.type === "Identifier"
    )
      names.add(statement.declaration.name);
    if (
      statement.type === "ExportDefaultDeclaration" &&
      statement.declaration.type === "FunctionDeclaration" &&
      statement.declaration.id !== null
    )
      names.add(statement.declaration.id.name);
  }
  return names;
}

function moduleDefinitions(program: DeclarationScope): Definition[] {
  const definitions: Definition[] = [];
  for (const statement of program.body) {
    const node =
      statement.type === "ExportNamedDeclaration" ||
      statement.type === "ExportDefaultDeclaration"
        ? statement.declaration
        : statement;
    if (
      node?.type === "FunctionDeclaration" &&
      node.id !== null &&
      node.body !== null
    ) {
      definitions.push({
        key: node.id.name,
        name: node.id.name,
        node,
        functionNode: node,
        bindingNode: node,
      });
      continue;
    }
    if (
      node?.type !== "VariableDeclaration" ||
      node.kind !== "const" ||
      node.declarations.length !== 1
    )
      continue;
    for (const declarator of node.declarations) {
      const initializer =
        declarator.init === null ? null : unwrapExpression(declarator.init);
      if (
        declarator.id.type === "Identifier" &&
        initializer !== null &&
        isFunction(initializer)
      ) {
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

function methodName(node: ESTree.MethodDefinition): string | null {
  if (node.key.type === "PrivateIdentifier") return `#${node.key.name}`;
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  return node.key.type === "Literal" && typeof node.key.value === "string"
    ? node.key.value
    : null;
}

function methodKey(name: string, isStatic: boolean): string {
  return `${isStatic ? "static" : "instance"}:${name}`;
}

function receiverDomain(
  context: Readonly<Context>,
  object: ESTree.Node,
  receivers: ReadonlyMap<Variable, boolean>,
  thisIsStatic: boolean,
): boolean | "unrelated" | null {
  const unwrapped = unwrapExpression(object);
  if (unwrapped.type === "ThisExpression") return thisIsStatic;
  return externalReceiverDomain(context, unwrapped, receivers);
}

/** Resolve receiver identity through immutable bindings without guessing from property names. */
function externalReceiverDomain(
  context: Readonly<Context>,
  object: ESTree.Node,
  receivers: ReadonlyMap<Variable, boolean>,
): boolean | "unrelated" | null {
  const origin = receiverOrigin(context, object, receivers);
  if (origin === null || typeof origin === "boolean") return origin;
  if (origin.type === "NewExpression") {
    return receiverOrigin(context, origin.callee, receivers) === true
      ? false
      : null;
  }
  if (
    origin.type === "ObjectExpression" ||
    origin.type === "ArrayExpression" ||
    origin.type === "Literal" ||
    origin.type === "ArrowFunctionExpression" ||
    origin.type === "FunctionExpression"
  )
    return "unrelated";
  return null;
}

/** Follow immutable alias chains to a known class receiver or a concrete initializer. */
function receiverOrigin(
  context: Readonly<Context>,
  object: ESTree.Node,
  receivers: ReadonlyMap<Variable, boolean>,
): ESTree.Node | boolean | null {
  let current = object;
  const seen = new Set<Variable>();
  while (true) {
    const unwrapped = unwrapExpression(current);
    if (unwrapped.type !== "Identifier") return unwrapped;
    const variable = findVariable(
      context.sourceCode.getScope(unwrapped),
      unwrapped.name,
    );
    if (variable === null) return null;
    const known = receivers.get(variable);
    if (known !== undefined) return known;
    const initializer = immutableInitializer(variable, seen);
    if (initializer === null) return null;
    current = initializer;
  }
}

function immutableInitializer(
  variable: Variable,
  seen: Set<Variable>,
): ESTree.Node | null {
  if (
    seen.has(variable) ||
    !stableVariable(variable) ||
    variable.defs.length !== 1
  )
    return null;
  seen.add(variable);
  const definition = variable.defs[0];
  if (
    definition?.node.type !== "VariableDeclarator" ||
    definition.node.parent.type !== "VariableDeclaration" ||
    definition.node.parent.kind !== "const"
  )
    return null;
  return definition.node.init;
}

function stableVariable(variable: Variable): boolean {
  return !variable.references.some(
    (reference) => reference.isWrite() && reference.init !== true,
  );
}

function referencedPropertyName(node: ESTree.MemberExpression): string | null {
  if (node.property.type === "PrivateIdentifier")
    return `#${node.property.name}`;
  if (!node.computed && node.property.type === "Identifier")
    return node.property.name;
  return node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
    ? node.property.value
    : null;
}

function walk(
  node: ESTree.Node,
  visitorKeys: Readonly<SourceCode["visitorKeys"]>,
  visit: (node: ESTree.Node, nestedFunction: boolean) => void,
  nestedFunction = false,
): void {
  visit(node, nestedFunction);
  const nested =
    nestedFunction ||
    isFunction(node) ||
    node.type === "ClassDeclaration" ||
    node.type === "ClassExpression";
  forEachAstChild(node, visitorKeys, (child) =>
    walk(child, visitorKeys, visit, nested),
  );
}

function classScope(
  context: Readonly<Context>,
  node: ESTree.Class,
  computedReferences: readonly ESTree.MemberExpression[],
): void {
  const methods = node.body.body.filter(
    (member): member is ESTree.MethodDefinition =>
      member.type === "MethodDefinition",
  );
  const counts = classMethodCounts(node.body, methods);
  const implementations = methods.filter((method) => isFunction(method.value));
  const implementationCounts = classMethodCounts(node.body, implementations);
  const scopeDefinitions = implementations.flatMap((method) => {
    const name = methodName(method);
    const key = name === null ? null : methodKey(name, method.static);
    return name !== null && key !== null && implementationCounts.get(key) === 1
      ? [{ key, name, node: method }]
      : [];
  });
  const definitions = scopeDefinitions.filter(
    ({ key, node: method }) =>
      (method.accessibility === "private" ||
        method.key.type === "PrivateIdentifier") &&
      counts.get(key) === 1 &&
      method.decorators.length === 0 &&
      !method.computed &&
      method.kind === "method",
  );
  if (definitions.length === 0) return;
  const methodKeys = new Set(
    scopeDefinitions.map((definition) => definition.key),
  );
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();
  const classReceivers = classReceiverBindings(context, node);
  const pinNames = (
    name: string | null,
    domain: boolean | null = null,
  ): void => {
    for (const definition of definitions) {
      if (
        (name === null || definition.name === name) &&
        (domain === null || definition.node.static === domain)
      ) {
        pinned.add(definition.key);
      }
    }
  };
  function pinDestructuredMembers(
    binding: ESTree.ObjectPattern | ESTree.ObjectAssignmentTarget,
    domain: boolean | null,
  ): void {
    for (const property of binding.properties) {
      if (property.type === "RestElement" || property.computed) {
        pinNames(null, domain);
      } else if (property.key.type === "Identifier") {
        pinNames(property.key.name, domain);
      } else if (
        property.key.type === "Literal" &&
        typeof property.key.value === "string"
      ) {
        pinNames(property.key.value, domain);
      }
    }
  }
  function collectMethodCalls(method: ESTree.MethodDefinition): void {
    const name = methodName(method);
    if (name === null) {
      pinNames(null);
      return;
    }
    if (!isFunction(method.value)) return;
    const methodFunction = method.value;
    const body = methodFunction.body;
    if (body === null) return;
    const caller = methodKey(name, method.static);
    const receivers = new Map(classReceivers);
    const parameterDecoratorNodes = new Set<ESTree.Node>();
    for (const parameter of method.value.params) {
      for (const decorator of parameter.decorators ?? []) {
        walk(decorator, context.sourceCode.visitorKeys, (current) =>
          parameterDecoratorNodes.add(current),
        );
      }
    }
    const collectAlias = (
      current: ESTree.Node,
      nestedFunction: boolean,
    ): void => {
      if (
        nestedFunction ||
        current.type !== "VariableDeclarator" ||
        current.init === null
      )
        return;
      const domain = receiverDomain(
        context,
        current.init,
        receivers,
        method.static,
      );
      if (domain === null || domain === "unrelated") return;
      if (current.id.type === "ObjectPattern") {
        pinDestructuredMembers(current.id, domain);
        return;
      }
      if (current.id.type !== "Identifier") return;
      if (
        current.parent.type !== "VariableDeclaration" ||
        current.parent.kind !== "const"
      ) {
        pinNames(null, domain);
        return;
      }
      const variable = context.sourceCode.getDeclaredVariables(current)[0];
      if (variable === undefined || !stableVariable(variable)) return;
      const local = variable.references.every((reference) => {
        if (!reference.isRead()) return true;
        const expression = wrappedExpression(reference.identifier);
        return (
          enclosingFunction(reference.identifier) === methodFunction &&
          expression.parent?.type === "MemberExpression" &&
          expression.parent.object === expression
        );
      });
      if (local) receivers.set(variable, domain);
      else pinNames(null, domain);
    };
    for (const statement of body.body)
      walk(statement, context.sourceCode.visitorKeys, collectAlias);

    const visitCall = (current: ESTree.Node, nestedFunction: boolean): void => {
      const destructuring = receiverDestructuring(current);
      if (destructuring !== null) {
        const domain = receiverDomain(
          context,
          destructuring.value,
          receivers,
          method.static,
        );
        if (domain !== "unrelated")
          pinDestructuredMembers(destructuring.binding, domain);
      }
      if (current.type !== "MemberExpression") return;
      const domain = receiverDomain(
        context,
        current.object,
        receivers,
        method.static,
      );
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
      if (
        current.computed ||
        nestedFunction ||
        parameterDecoratorNodes.has(current)
      ) {
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
    for (const decorator of method.decorators)
      walk(decorator, context.sourceCode.visitorKeys, visitCall, true);
    if (method.computed)
      walk(method.key, context.sourceCode.visitorKeys, visitCall, true);
    for (const parameter of method.value.params)
      walk(parameter, context.sourceCode.visitorKeys, visitCall);
    for (const statement of body.body)
      walk(statement, context.sourceCode.visitorKeys, visitCall);
  }
  for (const method of methods) collectMethodCalls(method);
  for (const member of node.body.body) {
    if (
      member.type === "MethodDefinition" ||
      member.type === "TSAbstractMethodDefinition"
    )
      continue;
    walk(member, context.sourceCode.visitorKeys, (current) => {
      if (current.type !== "MemberExpression") return;
      if (
        externalReceiverDomain(context, current.object, classReceivers) ===
        "unrelated"
      )
        return;
      pinNames(referencedPropertyName(current));
    });
  }
  const externalReceivers = new Map(classReceivers);
  for (const variable of context.sourceCode.getDeclaredVariables(node)) {
    if (stableVariable(variable)) externalReceivers.set(variable, true);
  }
  for (const reference of computedReferences) {
    if (nodeAncestors(reference).includes(node)) continue;
    const domain = externalReceiverDomain(
      context,
      reference.object,
      externalReceivers,
    );
    if (domain === "unrelated") continue;
    const name = referencedPropertyName(reference);
    if (name !== null || domain !== null) pinNames(name, domain);
  }

  const memberIndexes = new Map<ESTree.Node, number>(
    node.body.body.map((member, index) => [member, index]),
  );
  const runtimeBarrierPrefix = [0];
  for (const member of node.body.body) {
    runtimeBarrierPrefix.push(
      (runtimeBarrierPrefix.at(-1) ?? 0) +
        (isClassRuntimeBarrier(member) ? 1 : 0),
    );
  }
  const canMove = (helper: Definition, caller: Definition): boolean => {
    if (
      caller.node.type !== "MethodDefinition" ||
      (caller.node.accessibility !== "private" &&
        caller.node.key.type !== "PrivateIdentifier")
    )
      return false;
    const helperIndex = memberIndexes.get(helper.node);
    const callerIndex = memberIndexes.get(caller.node);
    if (helperIndex === undefined || callerIndex === undefined) return false;
    return (
      runtimeBarrierPrefix[callerIndex + 1] ===
      runtimeBarrierPrefix[helperIndex + 1]
    );
  };

  reportMisordered(
    context,
    definitions,
    scopeDefinitions,
    calls,
    pinned,
    canMove,
  );
}

function classReceiverBindings(
  context: Readonly<Context>,
  node: ESTree.Class,
): Map<Variable, boolean> {
  const classReceivers = new Map<Variable, boolean>();
  if (node.id !== null) {
    const internal = findVariable(
      context.sourceCode.getScope(node),
      node.id.name,
    );
    if (internal !== null && stableVariable(internal))
      classReceivers.set(internal, true);
  }
  if (
    node.type === "ClassExpression" &&
    node.parent.type === "VariableDeclarator" &&
    node.parent.id.type === "Identifier" &&
    node.parent.parent.type === "VariableDeclaration" &&
    node.parent.parent.kind === "const"
  ) {
    const outer = findVariable(
      context.sourceCode.getScope(node.parent),
      node.parent.id.name,
    );
    if (outer !== null && stableVariable(outer))
      classReceivers.set(outer, true);
  }
  return classReceivers;
}

function receiverDestructuring(node: ESTree.Node): {
  binding: ESTree.ObjectPattern | ESTree.ObjectAssignmentTarget;
  value: ESTree.Node;
} | null {
  if (
    node.type === "VariableDeclarator" &&
    node.id.type === "ObjectPattern" &&
    node.init !== null
  ) {
    return { binding: node.id, value: node.init };
  }
  if (
    (node.type === "AssignmentPattern" ||
      node.type === "AssignmentExpression") &&
    node.left.type === "ObjectPattern"
  ) {
    return { binding: node.left, value: node.right };
  }
  return null;
}

function isClassRuntimeBarrier(member: ESTree.ClassElement): boolean {
  switch (member.type) {
    case "StaticBlock":
      return true;
    case "PropertyDefinition":
    case "AccessorProperty":
      return (
        member.static ||
        member.computed ||
        member.decorators.length > 0 ||
        member.value !== null
      );
    case "MethodDefinition":
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
    docs: {
      description:
        "Place a private helper below its sole direct same-scope caller.",
    },
    schema: [],
    messages: {
      helperAboveOnlyCaller:
        "Private helper `{{helper}}` is defined above its only caller `{{caller}}`; move it below the caller.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(
        sourceOrigin(context).filename,
        sourceOrigin(context).text,
      )
    )
      return {};
    const classes: Array<ESTree.Class> = [];
    const functionBodies: ESTree.BlockStatement[] = [];
    return {
      ClassDeclaration: (node): void => {
        classes.push(node);
      },
      ClassExpression: (node): void => {
        classes.push(node);
      },
      "FunctionDeclaration, FunctionExpression, ArrowFunctionExpression": (
        node: ESTree.Node,
      ): void => {
        if (isFunction(node) && node.body?.type === "BlockStatement")
          functionBodies.push(node.body);
      },
      "Program:exit": (program): void => {
        declarationScope(context, program);
        for (const body of functionBodies) declarationScope(context, body);
        const computedReferences: ESTree.MemberExpression[] = [];
        walk(program, context.sourceCode.visitorKeys, (node) => {
          if (node.type === "MemberExpression" && node.computed)
            computedReferences.push(node);
        });
        for (const node of classes)
          classScope(context, node, computedReferences);
      },
    };
  },
});

function classMethodCounts(
  body: ESTree.ClassBody,
  methods: readonly ESTree.MethodDefinition[],
): Map<string, number> {
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
    const name =
      !member.computed && member.key.type === "Identifier"
        ? member.key.name
        : null;
    if (name !== null) {
      const key = methodKey(name, member.static);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}
