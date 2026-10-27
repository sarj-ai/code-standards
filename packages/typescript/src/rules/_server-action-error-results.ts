/** @fileoverview _server-action-error-results — follow closed caught details into exported Server Action results. */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { escapingActionReturn } from "./_escaping-action-return.js";
import { nativeRuntimeUnchanged } from "./_native-runtime-unchanged.js";
import { staticPropertyName } from "./_static-string.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Variable = TSESLint.Scope.Variable;
type FunctionNode = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
const MAX_ALIAS_HOPS = 8;

export function serverActionErrorResults(sourceCode: TSESLint.SourceCode): readonly TSESTree.ReturnStatement[] {
  const program = sourceCode.ast;
  if (directive(program.body, "use client")) return [];
  const moduleAction = directive(program.body, "use server");
  const actions = exportedFunctions(program, sourceCode).filter((node) => node.async && !node.generator &&
    (moduleAction || (node.body.type === AST_NODE_TYPES.BlockStatement && directive(node.body.body, "use server"))));
  if (actions.length === 0) return [];
  const nodes: TSESTree.Node[] = [];
  walk(program, sourceCode, (node) => { nodes.push(node); });
  if (nodes.some((node) => node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.Identifier && node.callee.name === "eval")) return [];
  const analysis = new ActionResults(sourceCode);
  const actionSet = new Set(actions);
  return nodes.filter((node): node is TSESTree.ReturnStatement => {
    if (node.type !== AST_NODE_TYPES.ReturnStatement || node.argument === null) return false;
    const owner = functionOwner(node);
    return owner !== null && actionSet.has(owner) && escapingActionReturn(node, owner, sourceCode) && analysis.payload(node.argument, owner);
  });
}

function directive(body: readonly TSESTree.Statement[], name: string): boolean {
  for (const statement of body) {
    if (statement.type !== AST_NODE_TYPES.ExpressionStatement || statement.directive === undefined) return false;
    if (statement.directive === name) return true;
  }
  return false;
}

function isFunction(node: TSESTree.Node): node is FunctionNode {
  return node.type === AST_NODE_TYPES.FunctionDeclaration || node.type === AST_NODE_TYPES.FunctionExpression || node.type === AST_NODE_TYPES.ArrowFunctionExpression;
}

function functionOwner(node: TSESTree.Node): FunctionNode | null {
  let parent = node.parent;
  while (parent != null) {
    if (isFunction(parent)) return parent;
    parent = parent.parent;
  }
  return null;
}

function binding(node: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): Variable | null {
  return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
}

function stable(variable: Variable): boolean {
  return variable.references.every((reference) => !reference.isWrite() || reference.init === true);
}

function constInitializer(variable: Variable): TSESTree.Expression | null {
  const definition = variable.defs.length === 1 ? variable.defs[0] : undefined;
  return definition?.type === "Variable" && definition.node.type === AST_NODE_TYPES.VariableDeclarator &&
    definition.node.id.type === AST_NODE_TYPES.Identifier && definition.node.parent.kind === "const" && stable(variable)
    ? definition.node.init : null;
}

function declaredFunction(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): FunctionNode | null {
  const value = unwrapExpression(node);
  if (isFunction(value)) {
    const variable = value.type === AST_NODE_TYPES.FunctionDeclaration && value.id !== null ? binding(value.id, sourceCode) : null;
    return variable !== null && !stable(variable) ? null : value;
  }
  if (value.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = binding(value, sourceCode);
  if (variable === null || !stable(variable) || variable.defs.length !== 1) return null;
  const definition = variable.defs[0];
  if (definition?.type === "FunctionName" && definition.node.type === AST_NODE_TYPES.FunctionDeclaration) return definition.node;
  const initializer = constInitializer(variable);
  const expression = initializer === null ? null : unwrapExpression(initializer);
  return expression !== null && isFunction(expression) ? expression : null;
}

function exportedFunctions(program: TSESTree.Program, sourceCode: TSESLint.SourceCode): FunctionNode[] {
  const functions = new Set<FunctionNode>();
  for (const statement of program.body) {
    for (const value of exportedValues(statement)) {
      const node = declaredFunction(value, sourceCode);
      if (node !== null) functions.add(node);
    }
  }
  return [...functions];
}

function exportedValues(statement: TSESTree.Statement): readonly TSESTree.Node[] {
  if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) return [statement.declaration];
  if (statement.type !== AST_NODE_TYPES.ExportNamedDeclaration || statement.exportKind === "type" || statement.source !== null) return [];
  const declaration = statement.declaration;
  const values: TSESTree.Node[] = declaration === null ? [] : [declaration];
  if (declaration?.type === AST_NODE_TYPES.VariableDeclaration) {
    for (const item of declaration.declarations) {
      if (item.id.type === AST_NODE_TYPES.Identifier && item.init !== null) values.push(item.id);
    }
  }
  for (const specifier of statement.specifiers) {
    if (specifier.exportKind !== "type" && specifier.local.type === AST_NODE_TYPES.Identifier) values.push(specifier.local);
  }
  return values;
}

function walk(node: TSESTree.Node, sourceCode: TSESLint.SourceCode, visit: (node: TSESTree.Node) => void): void {
  visit(node);
  forEachAstChild(node, sourceCode.visitorKeys, (child) => { walk(child, sourceCode, visit); });
}

class ActionResults {
  readonly #sourceCode: TSESLint.SourceCode;
  readonly #closedErrors = new Map<Variable, boolean>();
  readonly #helpers = new Map<Variable, { parameter: TSESTree.Identifier; expression: TSESTree.Expression } | null>();

  constructor(sourceCode: TSESLint.SourceCode) { this.#sourceCode = sourceCode; }

  payload(node: TSESTree.Node, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): boolean {
    const value = unwrapExpression(node);
    switch (value.type) {
      case AST_NODE_TYPES.ChainExpression:
        return this.payload(value.expression, owner, seen);
      case AST_NODE_TYPES.Identifier: {
        const variable = binding(value, this.#sourceCode);
        if (variable === null || seen.has(variable) || seen.size >= MAX_ALIAS_HOPS) return false;
        const initializer = constInitializer(variable);
        return initializer !== null && this.#closedAlias(variable, owner) && this.payload(initializer, owner, new Set([...seen, variable]));
      }
      case AST_NODE_TYPES.MemberExpression: {
        if (!this.#detailField(value)) return false;
        const error = this.#errorRoot(value.object, owner);
        return error !== null && this.#closedError(error, owner);
      }
      case AST_NODE_TYPES.ObjectExpression: {
        const properties = this.#properties(value);
        return properties !== null && [...properties.values()].some((field) => this.payload(field, owner, seen));
      }
      case AST_NODE_TYPES.ArrayExpression:
        return !value.elements.some((element) => element?.type === AST_NODE_TYPES.SpreadElement) &&
          value.elements.some((element) => element !== null && this.payload(element, owner, seen));
      case AST_NODE_TYPES.TemplateLiteral:
        return value.expressions.some((expression) => this.payload(expression, owner, seen));
      case AST_NODE_TYPES.BinaryExpression:
        return value.operator === "+" && (this.payload(value.left, owner, seen) || this.payload(value.right, owner, seen));
      case AST_NODE_TYPES.ConditionalExpression:
      case AST_NODE_TYPES.LogicalExpression:
        return this.#branches(value).some((branch) => this.payload(branch, owner, seen));
      case AST_NODE_TYPES.CallExpression:
        return this.#helperPayload(value, owner);
      default:
        return false;
    }
  }

  #detailField(node: TSESTree.MemberExpression): boolean {
    const name = staticPropertyName(node, this.#sourceCode);
    return name === "message" || name === "stack";
  }

  #properties(node: TSESTree.ObjectExpression): ReadonlyMap<string, TSESTree.Node> | null {
    const fields = new Map<string, TSESTree.Node>();
    for (const property of node.properties) {
      if (property.type !== AST_NODE_TYPES.Property || property.method || property.kind !== "init") return null;
      const name = staticPropertyName(property, this.#sourceCode);
      if (name === null || name === "toJSON" || name === "__proto__") return null;
      fields.set(name, property.value);
    }
    return fields;
  }

  #branches(node: TSESTree.ConditionalExpression | TSESTree.LogicalExpression): readonly TSESTree.Expression[] {
    if (node.type === AST_NODE_TYPES.ConditionalExpression) {
      const condition = ASTUtils.getStaticValue(node.test, this.#sourceCode.getScope(node.test));
      return condition === null ? [node.consequent, node.alternate] : [condition.value ? node.consequent : node.alternate];
    }
    const left = ASTUtils.getStaticValue(node.left, this.#sourceCode.getScope(node.left));
    if (left === null) return node.operator === "&&" ? [node.right] : [node.left, node.right];
    const right = node.operator === "??" ? left.value == null : node.operator === "&&" ? Boolean(left.value) : !left.value;
    return right ? [node.right] : [];
  }

  #errorRoot(node: TSESTree.Node, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): Variable | null {
    const value = unwrapExpression(node);
    if (value.type !== AST_NODE_TYPES.Identifier) return null;
    const variable = binding(value, this.#sourceCode);
    if (variable === null || seen.has(variable) || seen.size >= MAX_ALIAS_HOPS || !stable(variable) || variable.defs.length !== 1) return null;
    const definition = variable.defs[0];
    if (definition?.type === "CatchClause" && definition.node.param?.type === AST_NODE_TYPES.Identifier && functionOwner(definition.node) === owner) return variable;
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
      const parent = value.parent;
      if (parent === undefined) return false;
      if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value && this.#detailField(parent)) {
        return this.#readOnlyDetail(parent);
      }
      if (parent.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "instanceof" && parent.left === value) return this.#nativeError(parent.right);
      if (parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof") return true;
      if (parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === value && parent.id.type === AST_NODE_TYPES.Identifier) {
        const alias = binding(parent.id, this.#sourceCode);
        return alias !== null && constInitializer(alias) !== null && this.#closedError(alias, owner, visited);
      }
      return parent.type === AST_NODE_TYPES.CallExpression && !parent.optional && parent.arguments.length === 1 &&
        parent.arguments[0] === value && this.#helper(parent.callee) !== null;
    });
    this.#closedErrors.set(variable, closed);
    return closed;
  }

  #readOnlyDetail(node: TSESTree.MemberExpression): boolean {
    let value: TSESTree.Node = outerExpression(node);
    while (value.parent?.type === AST_NODE_TYPES.MemberExpression && value.parent.object === value) value = outerExpression(value.parent);
    const parent = value.parent;
    if (parent === undefined) return false;
    return !(parent.type === AST_NODE_TYPES.AssignmentExpression && parent.left === value) &&
      parent.type !== AST_NODE_TYPES.UpdateExpression && !(parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "delete") &&
      !(parent.type === AST_NODE_TYPES.CallExpression && parent.callee === value) &&
      !(parent.type === AST_NODE_TYPES.Property && parent.parent.type === AST_NODE_TYPES.ObjectPattern) && parent.type !== AST_NODE_TYPES.ArrayPattern &&
      parent.type !== AST_NODE_TYPES.ForOfStatement && parent.type !== AST_NODE_TYPES.ForInStatement;
  }

  #nativeError(node: TSESTree.Node): boolean {
    const value = unwrapExpression(node);
    if (value.type !== AST_NODE_TYPES.Identifier || value.name !== "Error") return false;
    const variable = binding(value, this.#sourceCode);
    return (variable === null || (variable.defs.length === 0 && stable(variable))) && nativeRuntimeUnchanged(this.#sourceCode, "Error");
  }

  #closedAlias(variable: Variable, owner: FunctionNode, seen: ReadonlySet<Variable> = new Set()): boolean {
    if (seen.has(variable) || seen.size >= MAX_ALIAS_HOPS || !stable(variable)) return false;
    const visited = new Set([...seen, variable]);
    return variable.references.every((reference) => reference.isWrite() ? reference.init === true :
      reference.isValueReference === false || this.#aliasRead(reference.identifier, owner, visited));
  }

  #aliasRead(node: TSESTree.Node, owner: FunctionNode, seen: ReadonlySet<Variable>): boolean {
    let value = outerExpression(node);
    if (functionOwner(value) !== owner) return false;
    while (true) {
      const parent = value.parent;
      if (parent === undefined) return false;
      if (parent.type === AST_NODE_TYPES.ReturnStatement) return functionOwner(parent) === owner;
      if (parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === value && parent.id.type === AST_NODE_TYPES.Identifier) {
        const variable = binding(parent.id, this.#sourceCode);
        return variable !== null && constInitializer(variable) !== null && this.#closedAlias(variable, owner, seen);
      }
      if (parent.type === AST_NODE_TYPES.Property && parent.value === value && parent.parent.type === AST_NODE_TYPES.ObjectExpression) value = parent.parent;
      else if (parent.type === AST_NODE_TYPES.ArrayExpression || parent.type === AST_NODE_TYPES.TemplateLiteral ||
        parent.type === AST_NODE_TYPES.ConditionalExpression || parent.type === AST_NODE_TYPES.LogicalExpression ||
        (parent.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "+")) value = parent;
      else return false;
      value = outerExpression(value);
    }
  }

  #helper(node: TSESTree.Node): { parameter: TSESTree.Identifier; expression: TSESTree.Expression } | null {
    const value = unwrapExpression(node);
    if (value.type !== AST_NODE_TYPES.Identifier) return null;
    const variable = binding(value, this.#sourceCode);
    if (variable === null) return null;
    const cached = this.#helpers.get(variable);
    if (cached !== undefined) return cached;
    const fn = declaredFunction(value, this.#sourceCode);
    const parameter = fn?.params[0];
    let expression: TSESTree.Expression | null = null;
    if (fn !== null && !fn.async && !fn.generator && fn.typeParameters === undefined &&
      (fn.returnType === undefined || fn.returnType.typeAnnotation.type === AST_NODE_TYPES.TSStringKeyword) &&
      fn.params.length === 1 && parameter?.type === AST_NODE_TYPES.Identifier &&
      (parameter.typeAnnotation === undefined || parameter.typeAnnotation.typeAnnotation.type === AST_NODE_TYPES.TSUnknownKeyword) && functionOwner(fn) === null) {
      if (fn.body.type !== AST_NODE_TYPES.BlockStatement) expression = fn.body;
      else if (fn.body.body.length === 1 && fn.body.body[0]?.type === AST_NODE_TYPES.ReturnStatement) expression = fn.body.body[0].argument;
    }
    const result = expression !== null && parameter?.type === AST_NODE_TYPES.Identifier && this.#pureHelper(expression, parameter)
      ? { parameter, expression } : null;
    this.#helpers.set(variable, result);
    return result;
  }

  #sameParameter(node: TSESTree.Node, parameter: TSESTree.Identifier): boolean {
    const value = unwrapExpression(node);
    return value.type === AST_NODE_TYPES.Identifier && binding(value, this.#sourceCode) === binding(parameter, this.#sourceCode);
  }

  #pureHelper(node: TSESTree.Node, parameter: TSESTree.Identifier): boolean {
    const value = unwrapExpression(node);
    switch (value.type) {
      case AST_NODE_TYPES.Literal:
        return !("regex" in value);
      case AST_NODE_TYPES.Identifier:
        return this.#sameParameter(value, parameter);
      case AST_NODE_TYPES.MemberExpression:
        return this.#detailField(value) && this.#sameParameter(value.object, parameter);
      case AST_NODE_TYPES.BinaryExpression:
        if (value.operator === "instanceof") return this.#sameParameter(value.left, parameter) && this.#nativeError(value.right);
        return ["+", "===", "!==", "==", "!="].includes(value.operator) && this.#pureHelper(value.left, parameter) && this.#pureHelper(value.right, parameter);
      case AST_NODE_TYPES.UnaryExpression:
        return (value.operator === "typeof" || value.operator === "!") && this.#pureHelper(value.argument, parameter);
      case AST_NODE_TYPES.ConditionalExpression:
        return this.#pureHelper(value.test, parameter) && this.#pureHelper(value.consequent, parameter) && this.#pureHelper(value.alternate, parameter);
      case AST_NODE_TYPES.LogicalExpression:
        return this.#pureHelper(value.left, parameter) && this.#pureHelper(value.right, parameter);
      case AST_NODE_TYPES.TemplateLiteral:
        return value.expressions.every((expression) => this.#pureHelper(expression, parameter));
      default:
        return false;
    }
  }

  #helperPayload(call: TSESTree.CallExpression, owner: FunctionNode): boolean {
    if (call.optional || call.arguments.length !== 1 || call.arguments[0] === undefined) return false;
    const helper = this.#helper(call.callee);
    const error = this.#errorRoot(call.arguments[0], owner);
    if (helper === null || error === null || !this.#closedError(error, owner)) return false;
    return this.#helperDetail(helper.expression, helper.parameter);
  }

  #helperDetail(node: TSESTree.Node, parameter: TSESTree.Identifier): boolean {
    const value = unwrapExpression(node);
    if (value.type === AST_NODE_TYPES.MemberExpression) return this.#detailField(value) && this.#sameParameter(value.object, parameter);
    if (value.type === AST_NODE_TYPES.ConditionalExpression || value.type === AST_NODE_TYPES.LogicalExpression) return this.#branches(value).some((branch) => this.#helperDetail(branch, parameter));
    if (value.type === AST_NODE_TYPES.BinaryExpression && value.operator === "+") return this.#helperDetail(value.left, parameter) || this.#helperDetail(value.right, parameter);
    return value.type === AST_NODE_TYPES.TemplateLiteral && value.expressions.some((expression) => this.#helperDetail(expression, parameter));
  }
}
