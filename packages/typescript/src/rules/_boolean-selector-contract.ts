/** @fileoverview _boolean-selector-contract — distinguish owned operation flags from boolean input contracts. */
import { AST_NODE_TYPES, ASTUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression;

interface Authority {
  readonly checker: ts.TypeChecker;
  readonly index: number;
  readonly implementation: ts.Node;
}

const MEMBER_REFERENCES = new WeakMap<TSESLint.SourceCode, ReadonlyMap<ts.Declaration, readonly ts.PropertyAccessExpression[]>>();

/** Only an unchanged, broad boolean owned by this implementation can select its operations. */
export function isEligibleBooleanSelector(identifier: TSESTree.Identifier, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  const owner = enclosingFunction(identifier);
  if (owner === undefined) return false;
  const expression = outerExpression(owner);
  const parent = expression.parent;
  if (parent?.type === AST_NODE_TYPES.CallExpression && parent.arguments.some(argument => argument === expression) ||
    parent?.type === AST_NODE_TYPES.JSXExpressionContainer) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  const definition = binding?.defs[0];
  if (binding?.defs.length !== 1 || definition?.type !== "Parameter" || definition.node !== owner ||
    definition.name.type !== AST_NODE_TYPES.Identifier || binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  const checker = services.program.getTypeChecker();
  if ((checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(definition.name)).flags & ts.TypeFlags.Boolean) === 0) return false;
  const parameter = definition.name.parent.type === AST_NODE_TYPES.AssignmentPattern ? definition.name.parent : definition.name;
  const index = owner.params.indexOf(parameter);
  if (index < 0 || isPureMapping(owner, sourceCode, services)) return false;
  const implementation = services.esTreeNodeToTSNodeMap.get(owner);
  if (ts.isSetAccessorDeclaration(implementation)) return false;
  const authority = { checker, index, implementation };
  if (hasDeclaredContract(authority) || hasMemberCallbackReference(authority, sourceCode, services)) return false;
  const callable = callableBinding(owner, sourceCode);
  return callable === null || !hasCallbackReference(callable, authority, sourceCode, services, new Set());
}

function enclosingFunction(node: TSESTree.Node): FunctionNode | undefined {
  for (let current: TSESTree.Node | undefined = node.parent; current !== undefined; current = current.parent) {
    if (current.type === AST_NODE_TYPES.ArrowFunctionExpression || current.type === AST_NODE_TYPES.FunctionDeclaration || current.type === AST_NODE_TYPES.FunctionExpression) return current;
  }
  return undefined;
}

function booleanContract(authority: Authority, type: ts.Type | undefined, independentlyAnnotated = false): boolean {
  return (type === undefined ? [] : authority.checker.getNonNullableType(type).getCallSignatures()).some(signature => {
    const declaration = signature.declaration;
    const parameter = declaration?.parameters[authority.index];
    if (declaration === undefined || declaration === authority.implementation || parameter === undefined || !ts.isParameter(parameter) || parameter.type === undefined) return false;
    // Contextual inference alone must not take ownership from our implementation.
    if ((authority.checker.getTypeFromTypeNode(parameter.type).flags & ts.TypeFlags.BooleanLike) !== 0) return true;
    const instantiated = signature.getParameters()[authority.index];
    return independentlyAnnotated && instantiated !== undefined &&
      (authority.checker.getTypeOfSymbolAtLocation(instantiated, declaration).flags & ts.TypeFlags.BooleanLike) !== 0;
  });
}

function callbackContract(authority: Authority, expression: ts.Expression): boolean {
  const checker = authority.checker;
  if (booleanContract(authority, checker.getContextualType(expression))) return true;
  const value = outerTypedExpression(expression);
  const parent = value.parent;
  if (ts.isCallExpression(parent)) {
    const index = parent.arguments.indexOf(value);
    const parameter = index < 0 ? undefined : checker.getResolvedSignature(parent)?.declaration?.parameters[index];
    return parameter !== undefined && ts.isParameter(parameter) && parameter.type !== undefined &&
      booleanContract(authority, checker.getTypeFromTypeNode(parameter.type), true);
  }
  if (!ts.isJsxExpression(parent) || !ts.isJsxAttribute(parent.parent)) return false;
  const attribute = parent.parent;
  if (checker.getSymbolAtLocation(attribute.name)?.declarations?.some(declaration =>
    (ts.isPropertyDeclaration(declaration) || ts.isPropertySignature(declaration)) && declaration.type !== undefined &&
    booleanContract(authority, checker.getTypeFromTypeNode(declaration.type), true)) === true) return true;
  if (!ts.isIdentifier(attribute.name)) return false;
  const opening = attribute.parent.parent;
  const propContract = (type: ts.Type): boolean => {
    const property = checker.getPropertyOfType(type, attribute.name.getText());
    return property !== undefined && booleanContract(authority, checker.getTypeOfSymbolAtLocation(property, attribute), true);
  };
  // Resolve original annotations; instantiated JSX inference may originate in our callback.
  const props = checker.getResolvedSignature(opening)?.declaration?.parameters[0];
  if (props !== undefined && ts.isParameter(props) && props.type !== undefined && propContract(checker.getTypeFromTypeNode(props.type))) return true;
  // Generic callable containers can fix their props independently of this JSX invocation.
  return checker.getTypeAtLocation(opening.tagName).getCallSignatures().some(signature => {
    const parameter = signature.getParameters()[0];
    return parameter !== undefined && propContract(checker.getTypeOfSymbolAtLocation(parameter, opening.tagName));
  });
}

function outerTypedExpression(node: ts.Expression): ts.Expression {
  let current = node;
  while ((ts.isParenthesizedExpression(current.parent) || ts.isAsExpression(current.parent) || ts.isTypeAssertionExpression(current.parent) ||
    ts.isNonNullExpression(current.parent) || ts.isSatisfiesExpression(current.parent)) && current.parent.expression === current) current = current.parent;
  return current;
}

function hasDeclaredContract(authority: Authority): boolean {
  const node = authority.implementation;
  const checker = authority.checker;
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
    if (callbackContract(authority, node)) return true;
    const binding = outerTypedExpression(node).parent;
    if ((ts.isVariableDeclaration(binding) || ts.isPropertyDeclaration(binding)) && binding.type !== undefined &&
      booleanContract(authority, checker.getTypeFromTypeNode(binding.type), true)) return true;
    return ts.isPropertyDeclaration(binding) && memberContract(authority, binding);
  }
  if (ts.isMethodDeclaration(node)) return memberContract(authority, node);
  if (!ts.isFunctionDeclaration(node) || node.name === undefined) return false;
  return checker.getSymbolAtLocation(node.name)?.declarations?.some(declaration =>
    declaration !== node && ts.isFunctionDeclaration(declaration) && declaration.parameters[authority.index]?.type !== undefined) === true;
}

function memberContract(authority: Authority, member: ts.MethodDeclaration | ts.PropertyDeclaration): boolean {
  const owner = member.parent;
  const checker = authority.checker;
  const symbol = checker.getSymbolAtLocation(member.name);
  if (symbol === undefined || ts.isPrivateIdentifier(member.name)) return false;
  const matches = (type: ts.Type, independentlyAnnotated = false): boolean => {
    const property = type.getProperties().find(candidate => candidate.escapedName === symbol.escapedName);
    return property !== undefined && booleanContract(authority, checker.getTypeOfSymbolAtLocation(property, member), independentlyAnnotated);
  };
  if (ts.isObjectLiteralExpression(owner)) {
    const contextual = checker.getContextualType(owner);
    const binding = outerTypedExpression(owner).parent;
    if (ts.isVariableDeclaration(binding) && binding.type !== undefined && matches(checker.getTypeFromTypeNode(binding.type), true)) return true;
    return contextual !== undefined && matches(contextual);
  }
  if (!ts.isClassDeclaration(owner) && !ts.isClassExpression(owner)) return false;
  const modifiers = ts.getCombinedModifierFlags(member);
  if ((modifiers & ts.ModifierFlags.Private) !== 0) return false;
  return owner.heritageClauses?.some(clause => clause.types.some(heritage =>
    matches(checker.getTypeAtLocation((modifiers & ts.ModifierFlags.Static) !== 0 ? heritage.expression : heritage), true))) === true;
}

function callableBinding(owner: FunctionNode, sourceCode: TSESLint.SourceCode): TSESLint.Scope.Variable | null {
  if (owner.type === AST_NODE_TYPES.FunctionDeclaration && owner.id !== null) return ASTUtils.findVariable(sourceCode.getScope(owner), owner.id.name);
  const binding = outerExpression(owner).parent;
  return binding?.type === AST_NODE_TYPES.VariableDeclarator && binding.id.type === AST_NODE_TYPES.Identifier
    ? ASTUtils.findVariable(sourceCode.getScope(binding.id), binding.id.name) : null;
}

function hasCallbackReference(binding: TSESLint.Scope.Variable, authority: Authority, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation, seen: Set<TSESLint.Scope.Variable>): boolean {
  if (seen.has(binding)) return false;
  // Very large alias graphs abstain rather than infer ownership beyond the bounded analysis.
  if (seen.size >= 32) return true;
  seen.add(binding);
  if (binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  return binding.references.some(reference => {
    if (!reference.isRead()) return false;
    const value = outerExpression(reference.identifier);
    const parent = value.parent;
    const callArgument = parent?.type === AST_NODE_TYPES.CallExpression && parent.arguments.some(argument => argument === value);
    const jsxAttribute = parent?.type === AST_NODE_TYPES.JSXExpressionContainer && parent.parent.type === AST_NODE_TYPES.JSXAttribute;
    if (callArgument || jsxAttribute) {
      const expression = services.esTreeNodeToTSNodeMap.get(value);
      if (ts.isExpression(expression) && callbackContract(authority, expression)) return true;
    }
    if (parent?.type === AST_NODE_TYPES.CallExpression && parent.callee === value && forwardedCallbackParameter(parent, authority, sourceCode, services)) return true;
    let selected = value;
    let branches = 0;
    while (selected.parent?.type === AST_NODE_TYPES.ConditionalExpression &&
      (selected.parent.consequent === selected || selected.parent.alternate === selected)) {
      if (branches >= 32) return true;
      branches += 1;
      selected = outerExpression(selected.parent);
    }
    const declaration = selected.parent;
    if (declaration?.type !== AST_NODE_TYPES.VariableDeclarator || declaration.init !== selected || declaration.id.type !== AST_NODE_TYPES.Identifier ||
      declaration.parent.kind !== "const") return false;
    const alias = ASTUtils.findVariable(sourceCode.getScope(declaration.id), declaration.id.name);
    return alias !== null && hasCallbackReference(alias, authority, sourceCode, services, seen);
  });
}

function forwardedCallbackParameter(call: TSESTree.CallExpression, authority: Authority, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  if (call.optional || call.arguments.some(argument => argument.type === AST_NODE_TYPES.SpreadElement)) return false;
  const argument = call.arguments[authority.index];
  if (argument?.type !== AST_NODE_TYPES.Identifier) return false;
  const wrapper = enclosingFunction(call);
  if (wrapper === undefined) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(argument), argument.name);
  const definition = binding?.defs[0];
  if (binding?.defs.length !== 1 || definition?.type !== "Parameter" || definition.node !== wrapper || definition.name.type !== AST_NODE_TYPES.Identifier ||
    binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  if ((authority.checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(definition.name)).flags & ts.TypeFlags.Boolean) === 0) return false;
  const parameter = definition.name.parent.type === AST_NODE_TYPES.AssignmentPattern ? definition.name.parent : definition.name;
  const index = wrapper.params.indexOf(parameter);
  const implementation = services.esTreeNodeToTSNodeMap.get(wrapper);
  return index >= 0 && (ts.isArrowFunction(implementation) || ts.isFunctionExpression(implementation)) &&
    callbackContract({ checker: authority.checker, index, implementation }, implementation);
}

function hasMemberCallbackReference(authority: Authority, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  const node = authority.implementation;
  const member = ts.isMethodDeclaration(node) ? node : ts.isArrowFunction(node) || ts.isFunctionExpression(node) ? outerTypedExpression(node).parent : undefined;
  if (member === undefined || (!ts.isMethodDeclaration(member) && !ts.isPropertyDeclaration(member) && !ts.isPropertyAssignment(member))) return false;
  let references = MEMBER_REFERENCES.get(sourceCode);
  if (references === undefined) {
    const collected = new Map<ts.Declaration, ts.PropertyAccessExpression[]>();
    function visit(current: ts.Node): void {
      if (ts.isPropertyAccessExpression(current)) {
        const target = authority.checker.getSymbolAtLocation(current.name);
        for (const declaration of target?.declarations ?? []) {
          const values = collected.get(declaration) ?? [];
          values.push(current);
          collected.set(declaration, values);
        }
      }
      ts.forEachChild(current, visit);
    }
    visit(services.esTreeNodeToTSNodeMap.get(sourceCode.ast));
    references = collected;
    MEMBER_REFERENCES.set(sourceCode, references);
  }
  return references.get(member)?.some(reference => {
    let value = outerTypedExpression(reference);
    const bind = value.parent;
    if (ts.isPropertyAccessExpression(bind) && bind.expression === value && bind.name.text === "bind" && ts.isCallExpression(bind.parent) &&
      bind.parent.expression === bind && bind.parent.arguments.length === 1) {
      const declaration = authority.checker.getResolvedSignature(bind.parent)?.declaration;
      if (declaration === undefined || !services.program.isSourceFileDefaultLibrary(declaration.getSourceFile())) return false;
      value = outerTypedExpression(bind.parent);
    }
    const parent = value.parent;
    const callback = ts.isCallExpression(parent) && parent.arguments.some(argument => argument === value);
    const jsx = ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent);
    return (callback || jsx) && callbackContract(authority, value);
  }) === true;
}

function isPureMapping(owner: FunctionNode, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  if (owner.body?.type !== AST_NODE_TYPES.BlockStatement || owner.body.body.length !== 1) return false;
  const statement = owner.body.body[0];
  if (statement?.type !== AST_NODE_TYPES.IfStatement || statement.alternate === null) return false;
  const consequent = returnedExpression(statement.consequent);
  const alternate = returnedExpression(statement.alternate);
  return consequent !== null && alternate !== null && consequent.kind === alternate.kind &&
    isBooleanDataSelection(consequent.value, alternate.value, sourceCode, services);
}

function returnedExpression(statement: TSESTree.Statement): { readonly value: TSESTree.Expression; readonly kind: "return" | "expression" } | null {
  if (statement.type === AST_NODE_TYPES.BlockStatement) {
    const first = statement.body[0];
    return statement.body.length === 1 && first !== undefined ? returnedExpression(first) : null;
  }
  if (statement.type === AST_NODE_TYPES.ExpressionStatement) return { value: statement.expression, kind: "expression" };
  return statement.type === AST_NODE_TYPES.ReturnStatement && statement.argument !== null ? { value: statement.argument, kind: "return" } : null;
}

/** Selecting syntactic argument/value data for one stable operation does not prove different operations. */
export function isBooleanDataSelection(consequent: TSESTree.Expression, alternate: TSESTree.Expression, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  const left = unwrapExpression(consequent);
  const right = unwrapExpression(alternate);
  if (pureValue(left, sourceCode, services) && pureValue(right, sourceCode, services)) return true;
  if (left.type === AST_NODE_TYPES.CallExpression && right.type === AST_NODE_TYPES.CallExpression && !left.optional && !right.optional &&
    sameTarget(left.callee, right.callee, sourceCode, services, true)) {
    return [...left.arguments, ...right.arguments].every(argument => argument.type !== AST_NODE_TYPES.SpreadElement && pureValue(argument, sourceCode, services));
  }
  return left.type === AST_NODE_TYPES.AssignmentExpression && right.type === AST_NODE_TYPES.AssignmentExpression &&
    left.operator === "=" && right.operator === "=" && sameTarget(left.left, right.left, sourceCode, services, false) &&
    pureValue(left.right, sourceCode, services) && pureValue(right.right, sourceCode, services);
}

function sameTarget(left: TSESTree.Node, right: TSESTree.Node, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation, operation: boolean): boolean {
  const stable = (identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null => {
    const binding = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
    return binding !== null && (!operation || !binding.references.some(reference => reference.isWrite() && reference.init !== true)) ? binding : null;
  };
  if (left.type === AST_NODE_TYPES.Identifier && right.type === AST_NODE_TYPES.Identifier) {
    const binding = stable(left);
    return binding !== null && binding === stable(right);
  }
  if (left.type !== AST_NODE_TYPES.MemberExpression || right.type !== AST_NODE_TYPES.MemberExpression || left.computed || right.computed ||
    left.optional || right.optional || left.property.type !== AST_NODE_TYPES.Identifier || right.property.type !== AST_NODE_TYPES.Identifier ||
    left.property.name !== right.property.name) return false;
  const receiver = left.object.type === AST_NODE_TYPES.ThisExpression && right.object.type === AST_NODE_TYPES.ThisExpression ||
    left.object.type === AST_NODE_TYPES.Identifier && right.object.type === AST_NODE_TYPES.Identifier &&
    stable(left.object) !== null && stable(left.object) === stable(right.object);
  if (!receiver) return false;
  if (!operation) return true;
  const checker = services.program.getTypeChecker();
  const property = checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(left.property));
  return property !== undefined && property === checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(right.property)) &&
    property.declarations?.every(declaration => ts.isMethodDeclaration(declaration)) === true;
}

function pureValue(node: TSESTree.Expression, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): boolean {
  const value = unwrapExpression(node);
  // A property read is data syntax; whether a getter performs work is deliberately not inferred.
  if (value.type === AST_NODE_TYPES.MemberExpression && !value.computed) return value.object.type === AST_NODE_TYPES.Super || pureValue(value.object, sourceCode, services);
  if (value.type === AST_NODE_TYPES.ChainExpression) return pureValue(value.expression, sourceCode, services);
  if (value.type === AST_NODE_TYPES.UnaryExpression && (value.operator === "!" || value.operator === "typeof" || value.operator === "void")) return pureValue(value.argument, sourceCode, services);
  if (value.type === AST_NODE_TYPES.UnaryExpression && (value.operator === "+" || value.operator === "-" || value.operator === "~")) return primitiveValue(value.argument, services) && pureValue(value.argument, sourceCode, services);
  if (!ASTUtils.hasSideEffect(value, sourceCode, { considerGetters: true, considerImplicitTypeConversion: true })) return true;
  if (value.type !== AST_NODE_TYPES.BinaryExpression || value.left.type === AST_NODE_TYPES.PrivateIdentifier) return false;
  return primitiveValue(value.left, services) && primitiveValue(value.right, services) && pureValue(value.left, sourceCode, services) && pureValue(value.right, sourceCode, services);
}

function primitiveValue(operand: TSESTree.Expression, services: ParserServicesWithTypeInformation): boolean {
  const type = services.program.getTypeChecker().getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(operand));
  return (type.isUnion() ? type.types : [type]).every(member => (member.flags &
    (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.BigIntLike | ts.TypeFlags.Null | ts.TypeFlags.Undefined)) !== 0);
}
