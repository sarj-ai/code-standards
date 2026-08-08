/**
 * @fileoverview stepdown — a private helper with one direct same-scope caller belongs below that caller.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/stepdown.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "helperAboveOnlyCaller";
type Options = [];

export const stepdownDocumentation = {
  summary: "Place a private helper below its sole direct same-scope caller.",
  rationale: "Caller-first ordering lets a reader follow the main flow before descending into implementation details.",
  remediation: "Move the private helper immediately below its sole caller.",
  category: "maintainability",
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
): void {
  const byName = new Map(scopeDefinitions.map((definition) => [definition.name, definition]));
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
    const helperCallers = [...(callers.get(helper.name) ?? [])];
    if (pinned.has(helper.name) || helperCallers.length !== 1) continue;
    const callerName = helperCallers[0];
    if (
      callerName === undefined ||
      (cycles.has(helper.name) && cycles.get(helper.name) === cycles.get(callerName))
    ) continue;
    const caller = byName.get(callerName);
    if (caller === undefined || helper.node.range[0] >= caller.node.range[0]) continue;
    context.report({
      node: helper.node,
      messageId: "helperAboveOnlyCaller",
      data: { helper: helper.name, caller: callerName },
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
  for (const root of nodes) {
    if (seen.has(root)) continue;
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
  const components = new Map<string, number>();
  let nextComponent = 0;
  const assigned = new Set<string>();
  for (let index = finishOrder.length - 1; index >= 0; index -= 1) {
    const root = finishOrder[index];
    if (root === undefined || assigned.has(root)) continue;
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
  return components;
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
  const scopeDefinitions = declarations
    .filter((node) => counts.get(node.name) === 1 && !overloadNames.has(node.name));
  const definitions = scopeDefinitions.filter((definition) => !exported.has(definition.name));
  const byFunction = new Map(scopeDefinitions.map((definition) => [definition.functionNode, definition]));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();

  for (const definition of scopeDefinitions) {
    const variable = context.sourceCode.getDeclaredVariables(definition.bindingNode!)[0];
    for (const reference of variable?.references ?? []) {
      if (reference.isWrite() && reference.init !== true) {
        pinned.add(definition.name);
        continue;
      }
      if (!reference.isRead()) continue;
      const identifier = reference.identifier;
      const ancestors = context.sourceCode.getAncestors(identifier);
      const nearestFunction = [...ancestors].reverse().find(isFunction);
      const parent = identifier.parent;
      const callerDefinition = nearestFunction === undefined ? undefined : byFunction.get(nearestFunction);
      if (callerDefinition === undefined || parent.type !== AST_NODE_TYPES.CallExpression || parent.callee !== identifier) {
        pinned.add(definition.name);
        continue;
      }
      const caller = callerDefinition.name;
      const callees = calls.get(caller) ?? new Set<string>();
      callees.add(definition.name);
      calls.set(caller, callees);
    }
  }
  reportMisordered(context, definitions, scopeDefinitions, calls, pinned);
}

function exportedNames(program: TSESTree.Program): Set<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.exportKind === "type" ||
      statement.source !== null
    ) continue;
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
      definitions.push({ name: node.id.name, node, functionNode: node, bindingNode: node });
      continue;
    }
    if (node?.type !== AST_NODE_TYPES.VariableDeclaration || node.kind !== "const") continue;
    for (const declarator of node.declarations) {
      if (
        declarator.id.type === AST_NODE_TYPES.Identifier &&
        declarator.init !== null &&
        isFunction(declarator.init)
      ) {
        definitions.push({
          name: declarator.id.name,
          node: declarator,
          functionNode: declarator.init,
          bindingNode: declarator,
        });
      }
    }
  }
  return definitions;
}

function methodName(node: TSESTree.MethodDefinition): string | null {
  if (node.key.type === AST_NODE_TYPES.PrivateIdentifier) return `#${node.key.name}`;
  return !node.computed && node.key.type === AST_NODE_TYPES.Identifier ? node.key.name : null;
}

function referencedMethod(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.MemberExpression,
  classVariables: ReadonlySet<NonNullable<ReturnType<typeof ASTUtils.findVariable>>>,
): string | null {
  const objectVariable = node.object.type === AST_NODE_TYPES.Identifier
    ? ASTUtils.findVariable(context.sourceCode.getScope(node.object), node.object.name)
    : null;
  const isClassReference =
    objectVariable !== null && classVariables.has(objectVariable);
  if (node.object.type !== AST_NODE_TYPES.ThisExpression && !isClassReference) return null;
  if (node.property.type === AST_NODE_TYPES.PrivateIdentifier) return `#${node.property.name}`;
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  return node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
    ? node.property.value
    : null;
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
  const nested = nestedFunction || isFunction(node);
  for (const key of visitorKeys[node.type] ?? []) {
    const child = (node as unknown as Record<string, unknown>)[key];
    if (Array.isArray(child)) {
      for (const item of child) if (typeof item === "object" && item !== null && "type" in item) walk(item as TSESTree.Node, visitorKeys, visit, nested);
    } else if (typeof child === "object" && child !== null && "type" in child) {
      walk(child as TSESTree.Node, visitorKeys, visit, nested);
    }
  }
}

function classScope(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  node: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
  computedReferenceNames: ReadonlySet<string>,
): void {
  const methods = node.body.body.filter(
    (member): member is TSESTree.MethodDefinition => member.type === AST_NODE_TYPES.MethodDefinition,
  );
  const counts = new Map<string, number>();
  for (const method of methods) {
    const name = methodName(method);
    if (name !== null) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  for (const member of node.body.body) {
    if (member.type !== AST_NODE_TYPES.TSAbstractMethodDefinition) continue;
    const name = !member.computed && member.key.type === AST_NODE_TYPES.Identifier ? member.key.name : null;
    if (name !== null) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const scopeDefinitions = methods.flatMap((method) => {
    const name = methodName(method);
    return name !== null && counts.get(name) === 1 ? [{ name, node: method }] : [];
  });
  const definitions = methods.flatMap((method) => {
    const name = methodName(method);
    const isPrivate = method.accessibility === "private" || method.key.type === AST_NODE_TYPES.PrivateIdentifier;
    return name !== null && isPrivate && counts.get(name) === 1 && method.decorators.length === 0
      ? [{ name, node: method }]
      : [];
  });
  if (definitions.length === 0) return;
  const privateNames = new Set(definitions.map((definition) => definition.name));
  const calls = new Map<string, Set<string>>();
  const pinned = new Set<string>();
  const classVariables = new Set<NonNullable<ReturnType<typeof ASTUtils.findVariable>>>();
  if (node.id !== null) {
    const internal = ASTUtils.findVariable(context.sourceCode.getScope(node), node.id.name);
    if (internal !== null) classVariables.add(internal);
  }
  if (
    node.type === AST_NODE_TYPES.ClassExpression &&
    node.parent.type === AST_NODE_TYPES.VariableDeclarator &&
    node.parent.id.type === AST_NODE_TYPES.Identifier
  ) {
    const outer = ASTUtils.findVariable(context.sourceCode.getScope(node.parent), node.parent.id.name);
    if (outer !== null) classVariables.add(outer);
  }

  for (const method of methods) {
    const caller = methodName(method);
    if (caller === null || method.value.body === null) continue;
    const methodClassVariables = new Set(classVariables);
    const methodAliases = new Set<NonNullable<ReturnType<typeof ASTUtils.findVariable>>>();
    const parameterDecoratorNodes = new Set<TSESTree.Node>();
    for (const parameter of method.value.params) {
      for (const decorator of parameter.decorators) {
        walk(decorator, context.sourceCode.visitorKeys, (current) => parameterDecoratorNodes.add(current));
      }
    }
    const thisValue = (value: TSESTree.Expression | null | undefined): boolean => {
      let current = value;
      while (
        current?.type === AST_NODE_TYPES.TSAsExpression ||
        current?.type === AST_NODE_TYPES.TSSatisfiesExpression ||
        current?.type === AST_NODE_TYPES.TSNonNullExpression
      ) current = current.expression;
      return current?.type === AST_NODE_TYPES.ThisExpression;
    };
    const collectAlias = (current: TSESTree.Node, nestedFunction: boolean): void => {
      if (
        nestedFunction ||
        (current.type !== AST_NODE_TYPES.VariableDeclarator &&
          current.type !== AST_NODE_TYPES.AssignmentPattern)
      ) return;
      if (
        current.type === AST_NODE_TYPES.VariableDeclarator &&
        (current.parent.type !== AST_NODE_TYPES.VariableDeclaration || current.parent.kind !== "const")
      ) return;
      const binding = current.type === AST_NODE_TYPES.VariableDeclarator ? current.id : current.left;
      const value = current.type === AST_NODE_TYPES.VariableDeclarator ? current.init : current.right;
      if (!thisValue(value)) return;
      if (binding.type === AST_NODE_TYPES.ObjectPattern) {
        for (const property of binding.properties) {
          if (property.type === AST_NODE_TYPES.RestElement) {
            for (const name of privateNames) pinned.add(name);
          } else if (property.key.type === AST_NODE_TYPES.Identifier && privateNames.has(property.key.name)) {
            pinned.add(property.key.name);
          }
        }
        return;
      }
      if (binding.type !== AST_NODE_TYPES.Identifier) return;
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(binding), binding.name);
      if (variable !== null) {
        methodClassVariables.add(variable);
        methodAliases.add(variable);
      }
    };
    for (const parameter of method.value.params) {
      walk(parameter, context.sourceCode.visitorKeys, collectAlias);
    }
    for (const statement of method.value.body.body) {
      walk(statement, context.sourceCode.visitorKeys, collectAlias);
    }
    const visitCall = (current: TSESTree.Node, nestedFunction: boolean): void => {
      if (
        current.type === AST_NODE_TYPES.VariableDeclarator &&
        current.id.type === AST_NODE_TYPES.ObjectPattern &&
        thisValue(current.init)
      ) {
        for (const property of current.id.properties) {
          if (property.type === AST_NODE_TYPES.RestElement) {
            for (const name of privateNames) pinned.add(name);
            continue;
          }
          if (
            property.type === AST_NODE_TYPES.Property &&
            property.key.type === AST_NODE_TYPES.Identifier &&
            privateNames.has(property.key.name)
          ) pinned.add(property.key.name);
        }
      }
      if (current.type !== AST_NODE_TYPES.MemberExpression) return;
      const target = referencedMethod(context, current, methodClassVariables);
      if (target === null) {
        const possibleTarget = referencedPropertyName(current);
        if (possibleTarget !== null && privateNames.has(possibleTarget)) pinned.add(possibleTarget);
        return;
      }
      if (!privateNames.has(target)) return;
      const objectVariable = current.object.type === AST_NODE_TYPES.Identifier
        ? ASTUtils.findVariable(context.sourceCode.getScope(current.object), current.object.name)
        : null;
      if (objectVariable !== null && methodAliases.has(objectVariable)) {
        pinned.add(target);
        return;
      }
      if (
        current.computed ||
        nestedFunction ||
        parameterDecoratorNodes.has(current) ||
        current.parent.type !== AST_NODE_TYPES.CallExpression ||
        current.parent.callee !== current
      ) {
        pinned.add(target);
        return;
      }
      const callees = calls.get(caller) ?? new Set<string>();
      callees.add(target);
      calls.set(caller, callees);
    };
    for (const decorator of method.decorators) {
      walk(decorator, context.sourceCode.visitorKeys, visitCall, true);
    }
    if (method.computed) walk(method.key, context.sourceCode.visitorKeys, visitCall, true);
    for (const parameter of method.value.params) {
      walk(parameter, context.sourceCode.visitorKeys, visitCall);
    }
    for (const statement of method.value.body.body) {
      walk(statement, context.sourceCode.visitorKeys, visitCall);
    }
  }
  for (const member of node.body.body) {
    if (member.type === AST_NODE_TYPES.MethodDefinition || member.type === AST_NODE_TYPES.TSAbstractMethodDefinition) continue;
    walk(member, context.sourceCode.visitorKeys, (current) => {
      if (current.type !== AST_NODE_TYPES.MemberExpression) return;
      const target = referencedMethod(context, current, classVariables);
      const possibleTarget = target ?? referencedPropertyName(current);
      if (possibleTarget !== null && privateNames.has(possibleTarget)) pinned.add(possibleTarget);
    });
  }
  for (const name of privateNames) if (computedReferenceNames.has(name)) pinned.add(name);

  const accessibility = new Map(
    scopeDefinitions.map((definition) => {
      const method = definition.node;
      const accessibility = method.key.type === AST_NODE_TYPES.PrivateIdentifier
        ? "private"
        : method.accessibility ?? "public";
      return [definition.name, accessibility] as const;
    }),
  );
  for (const [caller, callees] of calls) {
    if (accessibility.get(caller) === "private") continue;
    for (const callee of callees) pinned.add(callee);
  }
  reportMisordered(context, definitions, scopeDefinitions, calls, pinned);
}

export default createRule<Options, MessageIds>({
  name: "stepdown",
  documentation: stepdownDocumentation,
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
