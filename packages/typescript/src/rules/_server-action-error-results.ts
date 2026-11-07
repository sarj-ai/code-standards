/**
 * @fileoverview _server-action-error-results — follow closed caught details into exported Server Action results.
 *
 * Merges the 18.x `_server-action-error-results.ts` and `_escaping-action-return.ts` helpers,
 * which only no-exception-text-in-5xx-response uses.
 */

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { forEachAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { isPresent } from "../utils/is-present.js";
import { nativeRuntimeUnchanged } from "../utils/native-runtime-unchanged.js";
import { findVariable, staticPropertyName } from "../utils/static-string.js";
import { getStaticValue } from "./_get-static-value.js";

type Variable = TsVariable;
type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };
const MAX_ALIAS_HOPS = 8;
const PURE_HELPER_OPERATORS: ReadonlySet<string> = new Set(["+", "===", "!==", "==", "!="]);

export function serverActionErrorResults(sourceCode: SourceCode): readonly ESTree.ReturnStatement[] {
  const program = sourceCode.ast;
  if (directive(program.body, "use client")) return [];
  const moduleAction = directive(program.body, "use server");
  const actions = exportedFunctions(program, sourceCode).filter((node) => node.async && !node.generator &&
    (moduleAction || (node.body?.type === "BlockStatement" && directive(node.body.body, "use server"))));
  if (actions.length === 0) return [];
  const nodes: Node[] = [];
  walk(program, sourceCode, (node) => { nodes.push(node); });
  if (nodes.some((node) => node.type === "CallExpression" &&
    node.callee.type === "Identifier" && node.callee.name === "eval")) return [];
  const analysis = new ActionResults(sourceCode);
  const actionSet = new Set(actions);
  return nodes.filter((node) => node.type === "ReturnStatement").filter((node) => {
    if (node.argument === null) return false;
    const owner = functionOwner(node);
    return owner !== null && actionSet.has(owner) && escapingActionReturn(node, owner, sourceCode) && analysis.payload(node.argument, owner);
  });
}

function directive(body: readonly Node[], name: string): boolean {
  for (const statement of body) {
    // Oxlint gives non-directive expression statements `directive: null`, TS-ESTree leaves it undefined.
    if (statement.type !== "ExpressionStatement" || statement.directive == null) return false;
    if (statement.directive === name) return true;
  }
  return false;
}

function asFunction(node: Node | null | undefined): FunctionNode | null {
  return node?.type === "FunctionDeclaration" || node?.type === "FunctionExpression" || node?.type === "ArrowFunctionExpression"
    ? node : null;
}

function functionOwner(node: Node): FunctionNode | null {
  let parent = parentOf(node);
  while (parent != null) {
    const owner = asFunction(parent);
    if (owner !== null) return owner;
    parent = parentOf(parent);
  }
  return null;
}

function binding(node: Identifier, sourceCode: SourceCode): Variable | null {
  return findVariable(sourceCode.getScope(node), node.name);
}

function stable(variable: Variable): boolean {
  return variable.references.every((reference) => !reference.isWrite() || reference.init === true);
}

function constInitializer(variable: Variable): Node | null {
  const definition = variable.defs.length === 1 ? variable.defs[0] : undefined;
  if (definition?.type !== "Variable") return null;
  const declarator = definition.node;
  if (declarator.type !== "VariableDeclarator" || declarator.id.type !== "Identifier") return null;
  const statement = parentOf(declarator);
  return statement?.type === "VariableDeclaration" && statement.kind === "const" && stable(variable)
    ? declarator.init : null;
}

function declaredFunction(node: Node, sourceCode: SourceCode): FunctionNode | null {
  const value = unwrapExpression(node);
  const declared = asFunction(value);
  if (declared !== null) {
    const variable = declared.type === "FunctionDeclaration" && declared.id !== null ? binding(declared.id, sourceCode) : null;
    return variable !== null && !stable(variable) ? null : declared;
  }
  if (value.type !== "Identifier") return null;
  const variable = binding(value, sourceCode);
  if (variable === null || !stable(variable) || variable.defs.length !== 1) return null;
  const definition = variable.defs[0];
  const definitionNode = definition?.node;
  if (definition?.type === "FunctionName" && definitionNode?.type === "FunctionDeclaration") return definitionNode;
  const initializer = constInitializer(variable);
  const expression = initializer === null ? null : unwrapExpression(initializer);
  return asFunction(expression);
}

function exportedFunctions(program: ESTree.Program, sourceCode: SourceCode): FunctionNode[] {
  const functions = new Set<FunctionNode>();
  for (const statement of program.body) {
    for (const value of exportedValues(statement)) {
      const node = declaredFunction(value, sourceCode);
      if (node !== null) functions.add(node);
    }
  }
  return [...functions];
}

function exportedValues(statement: Node): readonly Node[] {
  if (statement.type === "ExportDefaultDeclaration") return [statement.declaration];
  if (statement.type !== "ExportNamedDeclaration" || statement.exportKind === "type" || statement.source !== null) return [];
  const declaration: Node | null = statement.declaration;
  const values: Node[] = declaration === null ? [] : [declaration];
  if (declaration?.type === "VariableDeclaration") {
    for (const item of declaration.declarations) {
      if (item.id.type === "Identifier" && item.init !== null) values.push(item.id);
    }
  }
  for (const specifier of statement.specifiers) {
    const local = specifier.local as Node;
    if (specifier.exportKind !== "type" && local.type === "Identifier") values.push(local);
  }
  return values;
}

function walk(node: Node, sourceCode: SourceCode, visit: (node: Node) => void): void {
  visit(node);
  forEachAstChild(node, sourceCode.visitorKeys, (child) => { walk(child, sourceCode, visit); });
}

interface Helper {
  readonly parameter: Identifier;
  readonly expression: Node;
}

/** The object, array, template, conditional, logical or `+` expression that carries `value` into its result, or null. */
function composedValue(parent: Node, value: Node): Node | null {
  if (parent.type === "Property") {
    const object = parentOf(parent);
    return parent.value === value && object?.type === "ObjectExpression" ? object : null;
  }
  return parent.type === "ArrayExpression" || parent.type === "TemplateLiteral" ||
    parent.type === "ConditionalExpression" || parent.type === "LogicalExpression" ||
    (parent.type === "BinaryExpression" && parent.operator === "+") ? parent : null;
}

/** The parameter and result of a synchronous module-level `(detail: unknown): string` helper. */
function helperShape(fn: FunctionNode | null): Helper | null {
  const parameter = fn?.params[0] as Node | undefined;
  if (fn === null || fn.async || fn.generator || isPresent(fn.typeParameters) ||
    (isPresent(fn.returnType) && fn.returnType.typeAnnotation.type !== "TSStringKeyword") ||
    fn.params.length !== 1 || parameter?.type !== "Identifier" ||
    (isPresent(parameter.typeAnnotation) && parameter.typeAnnotation.typeAnnotation.type !== "TSUnknownKeyword") ||
    functionOwner(fn) !== null) return null;
  const body = fn.body as Node | null;
  if (body?.type !== "BlockStatement") return body === null ? null : { parameter, expression: body };
  const [statement] = body.body;
  return body.body.length === 1 && statement?.type === "ReturnStatement" && statement.argument !== null
    ? { parameter, expression: statement.argument }
    : null;
}

class ActionResults {
  readonly #sourceCode: SourceCode;
  readonly #closedErrors = new Map<Variable, boolean>();
  readonly #helpers = new Map<Variable, Helper | null>();

  constructor(sourceCode: SourceCode) { this.#sourceCode = sourceCode; }

  payload(node: Node, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): boolean {
    const value = unwrapExpression(node);
    switch (value.type) {
      case "ChainExpression":
        return this.payload(value.expression, owner, seen);
      case "Identifier": {
        const variable = binding(value, this.#sourceCode);
        if (variable === null || seen.has(variable) || seen.size >= MAX_ALIAS_HOPS) return false;
        const initializer = constInitializer(variable);
        return initializer !== null && this.#closedAlias(variable, owner) && this.payload(initializer, owner, new Set([...seen, variable]));
      }
      case "MemberExpression": {
        if (!this.#detailField(value)) return false;
        const error = this.#errorRoot(value.object, owner);
        return error !== null && this.#closedError(error, owner);
      }
      case "ObjectExpression": {
        const properties = this.#properties(value);
        return properties !== null && [...properties.values()].some((field) => this.payload(field, owner, seen));
      }
      case "ArrayExpression":
        return !value.elements.some((element) => element?.type === "SpreadElement") &&
          value.elements.some((element) => element !== null && this.payload(element, owner, seen));
      case "TemplateLiteral":
        return value.expressions.some((expression) => this.payload(expression, owner, seen));
      case "BinaryExpression":
        return value.operator === "+" && (this.payload(value.left, owner, seen) || this.payload(value.right, owner, seen));
      case "ConditionalExpression":
      case "LogicalExpression":
        return this.#branches(value).some((branch) => this.payload(branch, owner, seen));
      case "CallExpression":
        return this.#helperPayload(value, owner);
      default:
        return false;
    }
  }

  #detailField(node: ESTree.MemberExpression): boolean {
    const name = staticPropertyName(node, this.#sourceCode);
    return name === "message" || name === "stack";
  }

  #properties(node: ESTree.ObjectExpression): ReadonlyMap<string, Node> | null {
    const fields = new Map<string, Node>();
    for (const property of node.properties) {
      if (property.type !== "Property" || property.method || property.kind !== "init") return null;
      const name = staticPropertyName(property, this.#sourceCode);
      if (name === null || name === "toJSON" || name === "__proto__") return null;
      fields.set(name, property.value);
    }
    return fields;
  }

  #branches(node: ESTree.ConditionalExpression | ESTree.LogicalExpression): readonly Node[] {
    if (node.type === "ConditionalExpression") {
      const condition = getStaticValue(node.test, this.#sourceCode.getScope(node.test));
      return condition === null ? [node.consequent, node.alternate] : [condition.value ? node.consequent : node.alternate];
    }
    const left = getStaticValue(node.left, this.#sourceCode.getScope(node.left));
    if (left === null) return node.operator === "&&" ? [node.right] : [node.left, node.right];
    const right = node.operator === "??" ? left.value == null : node.operator === "&&" ? Boolean(left.value) : !left.value;
    return right ? [node.right] : [];
  }

  #errorRoot(node: Node, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): Variable | null {
    const value = unwrapExpression(node);
    if (value.type !== "Identifier") return null;
    const variable = binding(value, this.#sourceCode);
    if (variable === null || seen.has(variable) || seen.size >= MAX_ALIAS_HOPS || !stable(variable) || variable.defs.length !== 1) return null;
    const definition = variable.defs[0];
    const clause = definition?.node;
    if (definition?.type === "CatchClause" && clause?.type === "CatchClause" && clause.param?.type === "Identifier" &&
      functionOwner(clause) === owner) return variable;
    const initializer = constInitializer(variable);
    return initializer === null ? null : this.#errorRoot(initializer, owner, new Set([...seen, variable]));
  }

  #closedError(variable: Variable, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): boolean {
    const cached = this.#closedErrors.get(variable);
    if (cached !== undefined) return cached;
    if (seen.has(variable) || seen.size >= MAX_ALIAS_HOPS || !stable(variable)) return false;
    const visited = new Set([...seen, variable]);
    const closed = variable.references.every((reference) => {
      if (reference.isWrite()) return reference.init === true;
      if (reference.isValueReference === false) return true;
      const value = outerExpression(reference.identifier);
      if (functionOwner(value) !== owner) return false;
      const parent = parentOf(value);
      if (parent === null) return false;
      if (parent.type === "MemberExpression" && parent.object === value && this.#detailField(parent)) {
        return this.#readOnlyDetail(parent);
      }
      if (parent.type === "BinaryExpression" && parent.operator === "instanceof" && parent.left === value) return this.#nativeError(parent.right);
      if (parent.type === "UnaryExpression" && parent.operator === "typeof") return true;
      if (parent.type === "VariableDeclarator" && parent.init === value && parent.id.type === "Identifier") {
        const alias = binding(parent.id, this.#sourceCode);
        return alias !== null && constInitializer(alias) !== null && this.#closedError(alias, owner, visited);
      }
      return parent.type === "CallExpression" && !parent.optional && parent.arguments.length === 1 &&
        parent.arguments[0] === value && this.#helper(parent.callee) !== null;
    });
    this.#closedErrors.set(variable, closed);
    return closed;
  }

  #readOnlyDetail(node: ESTree.MemberExpression): boolean {
    let value: Node = outerExpression(node);
    for (let up = parentOf(value); up?.type === "MemberExpression" && up.object === value; up = parentOf(value)) {
      value = outerExpression(up);
    }
    const parent = parentOf(value);
    if (parent === null) return false;
    return !(parent.type === "AssignmentExpression" && parent.left === value) &&
      parent.type !== "UpdateExpression" && !(parent.type === "UnaryExpression" && parent.operator === "delete") &&
      !(parent.type === "CallExpression" && parent.callee === value) &&
      !(parent.type === "Property" && parentOf(parent)?.type === "ObjectPattern") && parent.type !== "ArrayPattern" &&
      parent.type !== "ForOfStatement" && parent.type !== "ForInStatement";
  }

  #nativeError(node: Node): boolean {
    const value = unwrapExpression(node);
    if (value.type !== "Identifier" || value.name !== "Error") return false;
    const variable = binding(value, this.#sourceCode);
    return (variable === null || (variable.defs.length === 0 && stable(variable))) && nativeRuntimeUnchanged(this.#sourceCode, "Error");
  }

  #closedAlias(variable: Variable, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): boolean {
    if (seen.has(variable) || seen.size >= MAX_ALIAS_HOPS || !stable(variable)) return false;
    const visited = new Set([...seen, variable]);
    return variable.references.every((reference) => reference.isWrite() ? reference.init === true :
      reference.isValueReference === false || this.#aliasRead(reference.identifier, owner, visited));
  }

  #aliasRead(node: Node, owner: FunctionNode, seen: ReadonlySet<Variable>): boolean {
    let value = outerExpression(node);
    if (functionOwner(value) !== owner) return false;
    for (let parent = parentOf(value); parent !== null; parent = parentOf(value)) {
      if (parent.type === "ReturnStatement") return functionOwner(parent) === owner;
      if (parent.type === "VariableDeclarator" && parent.init === value && parent.id.type === "Identifier") {
        const variable = binding(parent.id, this.#sourceCode);
        return variable !== null && constInitializer(variable) !== null && this.#closedAlias(variable, owner, seen);
      }
      const container = composedValue(parent, value);
      if (container === null) return false;
      value = outerExpression(container);
    }
    return false;
  }

  #helper(node: Node): Helper | null {
    const value = unwrapExpression(node);
    if (value.type !== "Identifier") return null;
    const variable = binding(value, this.#sourceCode);
    if (variable === null) return null;
    const cached = this.#helpers.get(variable);
    if (cached !== undefined) return cached;
    const shape = helperShape(declaredFunction(value, this.#sourceCode));
    const result = shape !== null && this.#pureHelper(shape.expression, shape.parameter) ? shape : null;
    this.#helpers.set(variable, result);
    return result;
  }

  #sameParameter(node: Node, parameter: Identifier): boolean {
    const value = unwrapExpression(node);
    return value.type === "Identifier" && binding(value, this.#sourceCode) === binding(parameter, this.#sourceCode);
  }

  #pureHelper(node: Node, parameter: Identifier): boolean {
    const value = unwrapExpression(node);
    switch (value.type) {
      case "Literal":
        return !("regex" in value) || (value as { regex?: unknown }).regex == null;
      case "Identifier":
        return this.#sameParameter(value, parameter);
      case "MemberExpression":
        return this.#detailField(value) && this.#sameParameter(value.object, parameter);
      case "BinaryExpression":
        if (value.operator === "instanceof") return this.#sameParameter(value.left, parameter) && this.#nativeError(value.right);
        return PURE_HELPER_OPERATORS.has(value.operator) && this.#pureHelper(value.left, parameter) && this.#pureHelper(value.right, parameter);
      case "UnaryExpression":
        return (value.operator === "typeof" || value.operator === "!") && this.#pureHelper(value.argument, parameter);
      case "ConditionalExpression":
        return this.#pureHelper(value.test, parameter) && this.#pureHelper(value.consequent, parameter) && this.#pureHelper(value.alternate, parameter);
      case "LogicalExpression":
        return this.#pureHelper(value.left, parameter) && this.#pureHelper(value.right, parameter);
      case "TemplateLiteral":
        return value.expressions.every((expression) => this.#pureHelper(expression, parameter));
      default:
        return false;
    }
  }

  #helperPayload(call: ESTree.CallExpression, owner: FunctionNode): boolean {
    const argument = call.arguments[0];
    if (call.optional || call.arguments.length !== 1 || argument === undefined) return false;
    const helper = this.#helper(call.callee);
    const error = this.#errorRoot(argument, owner);
    if (helper === null || error === null || !this.#closedError(error, owner)) return false;
    return this.#helperDetail(helper.expression, helper.parameter);
  }

  #helperDetail(node: Node, parameter: Identifier): boolean {
    const value = unwrapExpression(node);
    if (value.type === "MemberExpression") return this.#detailField(value) && this.#sameParameter(value.object, parameter);
    if (value.type === "ConditionalExpression" || value.type === "LogicalExpression") return this.#branches(value).some((branch) => this.#helperDetail(branch, parameter));
    if (value.type === "BinaryExpression" && value.operator === "+") return this.#helperDetail(value.left, parameter) || this.#helperDetail(value.right, parameter);
    return value.type === "TemplateLiteral" && value.expressions.some((expression) => this.#helperDetail(expression, parameter));
  }
}

// --- escaping-action-return: exclude visibly dead or finalizer-overridden action results. ---

function escapingActionReturn(node: ESTree.ReturnStatement, owner: Node, sourceCode: SourceCode): boolean {
  let child: Node = node;
  for (let parent = parentOf(child); parent !== null && parent !== owner; parent = parentOf(child)) {
    if (!reachableAncestor(child, parent, sourceCode)) return false;
    child = parent;
  }
  return true;
}

function reachableAncestor(child: Node, parent: Node, sourceCode: SourceCode): boolean {
  switch (parent.type) {
    case "IfStatement": {
      const truth = condition(parent.test, sourceCode);
      if (truth === null) return true;
      return parent.consequent === child ? truth : !truth;
    }
    case "WhileStatement":
    case "ForStatement":
      return parent.test === null || condition(parent.test, sourceCode) !== false;
    case "ForInStatement":
    case "ForOfStatement":
    case "SwitchStatement":
      return false;
    case "TryStatement":
      return parent.finalizer === null || parent.finalizer === child || !transfers(parent.finalizer, sourceCode);
    case "BlockStatement":
      return reachableBlockChild(parent.body, child, sourceCode);
    default:
      return true;
  }
}

function condition(node: Node, sourceCode: SourceCode): boolean | null {
  const value = getStaticValue(node, sourceCode.getScope(node));
  return value === null ? null : Boolean(value.value);
}

function reachableBlockChild(statements: readonly Node[], child: Node, sourceCode: SourceCode): boolean {
  for (const statement of statements) {
    if (statement === child) return true;
    if (opaquePrefix(statement) || exits(statement, sourceCode)) return false;
  }
  return true;
}

function exits(node: Node, sourceCode: SourceCode): boolean {
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement" ||
    node.type === "BreakStatement" || node.type === "ContinueStatement") return true;
  if (node.type === "BlockStatement") return node.body.some((statement) => exits(statement, sourceCode));
  if (node.type !== "IfStatement") return false;
  const truth = condition(node.test, sourceCode);
  if (truth === true) return exits(node.consequent, sourceCode);
  if (truth === false) return node.alternate !== null && exits(node.alternate, sourceCode);
  return node.alternate !== null && exits(node.consequent, sourceCode) && exits(node.alternate, sourceCode);
}

function opaquePrefix(node: Node): boolean {
  if (node.type === "BlockStatement") return node.body.some(opaquePrefix);
  if (node.type === "IfStatement") return opaquePrefix(node.consequent) || (node.alternate !== null && opaquePrefix(node.alternate));
  return node.type === "TryStatement" || node.type === "SwitchStatement" ||
    node.type === "LabeledStatement" || node.type === "WithStatement" ||
    node.type === "ForStatement" || node.type === "ForInStatement" ||
    node.type === "ForOfStatement" || node.type === "WhileStatement" || node.type === "DoWhileStatement";
}

function transfers(node: Node, sourceCode: SourceCode): boolean {
  if (node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression") return false;
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement" ||
    node.type === "BreakStatement" || node.type === "ContinueStatement") return true;
  return forEachAstChild(node, sourceCode.visitorKeys, (child) => transfers(child, sourceCode));
}
