/**
 * @fileoverview _no-boolean-selector-parameter-contract — distinguish owned operation flags from boolean input contracts.
 *
 * Port of the 18.x `_boolean-selector-contract.ts` helper on tsrs: the same
 * checks over tsrs's checker and AST (`ts.is*` from `tsrs/ast`). Signature and
 * symbol declarations are tsrs node handles, resolved where the original reads
 * a declaration's parameters or type; a same-file handle resolves to the very
 * node of the local source file, so identity checks hold. The original's
 * whole-file member-reference index resolves every property-access name in one
 * batched request, cached per AST.
 */

import type * as TsrsAst from "tsrs/ast";
import type { Signature, Symbol as TsSymbol, Type } from "tsrs/sync";

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { functionNode, type NativeTypes } from "../utils/checked-native-source.js";
import { hasSideEffect } from "../utils/has-side-effect.js";
import { isPresent } from "../utils/is-present.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };
type TsNode = TsrsAst.Node;
type Expression = ESTree.Expression;

interface Authority {
  readonly native: NativeTypes;
  readonly index: number;
  readonly implementation: TsNode;
}

/** Only an unchanged, broad boolean owned by this implementation can select its operations. */
export function isEligibleBooleanSelector(identifier: Identifier, sourceCode: SourceCode, native: NativeTypes): boolean {
  const { ast } = native;
  const owner = enclosingFunction(identifier);
  if (owner === null) return false;
  const expression = outerExpression(owner);
  const parent = parentOf(expression);
  if (parent?.type === "CallExpression" && parent.arguments.some((argument) => argument === expression) ||
    parent?.type === "JSXExpressionContainer") return false;
  const index = booleanParameterIndex(identifier, owner, sourceCode, native);
  if (index < 0 || isPureMapping(owner, sourceCode, native)) return false;
  const implementation = functionNode(native, owner);
  if (implementation === undefined || ast.isSetAccessorDeclaration(implementation)) return false;
  const authority: Authority = { native, index, implementation };
  if (hasDeclaredContract(authority) || hasMemberCallbackReference(authority, sourceCode)) return false;
  const callable = callableBinding(owner, sourceCode);
  return callable === null || !hasCallbackReference(callable, authority, sourceCode, new Set());
}

/** Where `identifier`, a never reassigned boolean parameter of `owner`, sits in its parameter list, or -1. */
function booleanParameterIndex(identifier: Identifier, owner: FunctionNode, sourceCode: SourceCode, native: NativeTypes): number {
  const binding = findVariable(sourceCode.getScope(identifier), identifier.name);
  const definition = binding?.defs[0];
  if (binding?.defs.length !== 1 || definition?.type !== "Parameter" || definition.node !== owner ||
    definition.name.type !== "Identifier" || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return -1;
  const name = native.node(definition.name);
  if (name === undefined || (native.checker.getTypeAtLocation(name).flags & native.sync.TypeFlags.Boolean) === 0) return -1;
  const nameParent = parentOf(definition.name);
  const parameter = nameParent?.type === "AssignmentPattern" ? nameParent : definition.name;
  return (owner.params as readonly Node[]).indexOf(parameter);
}

type ParameterView = TsNode & { readonly type?: TsNode | undefined };
type SignatureDeclarationView = TsNode & { readonly parameters?: readonly ParameterView[] | undefined };

function resolvedDeclaration(signature: Signature | undefined): SignatureDeclarationView | undefined {
  return signature?.declaration?.resolve();
}

function booleanContract(authority: Authority, type: Type | undefined, independentlyAnnotated = false): boolean {
  const { ast, checker, sync } = authority.native;
  return (type === undefined ? [] : checker.getNonNullableType(type).getCallSignatures()).some((signature) => {
    const declaration = resolvedDeclaration(signature);
    const parameter = declaration?.parameters?.[authority.index];
    if (declaration === undefined || declaration === authority.implementation || parameter === undefined ||
      !ast.isParameterDeclaration(parameter) || !isPresent(parameter.type)) return false;
    // Contextual inference alone must not take ownership from our implementation.
    if ((checker.getTypeFromTypeNode(parameter.type).flags & sync.TypeFlags.BooleanLike) !== 0) return true;
    const instantiated = signature.getParameters()[authority.index];
    return independentlyAnnotated && instantiated !== undefined &&
      (checker.getTypeOfSymbolAtLocation(instantiated, declaration).flags & sync.TypeFlags.BooleanLike) !== 0;
  });
}

function callbackContract(authority: Authority, expression: TsNode): boolean {
  const { ast, checker } = authority.native;
  if (booleanContract(authority, checker.getContextualType(expression as TsrsAst.Expression))) return true;
  const value = outerTypedExpression(authority.native, expression);
  const parent = value.parent;
  if (ast.isCallExpression(parent)) {
    const index = parent.arguments.indexOf(value as TsrsAst.Expression);
    const parameter = index < 0 ? undefined : resolvedDeclaration(checker.getResolvedSignature(parent))?.parameters?.[index];
    return parameter !== undefined && ast.isParameterDeclaration(parameter) && isPresent(parameter.type) &&
      booleanContract(authority, checker.getTypeFromTypeNode(parameter.type), true);
  }
  if (!ast.isJsxExpression(parent) || !ast.isJsxAttribute(parent.parent)) return false;
  const attribute = parent.parent;
  const declarations = checker.getSymbolAtLocation(attribute.name)?.declarations ?? [];
  if (declarations.some((handle) => {
    if (handle.kind !== ast.SyntaxKind.PropertyDeclaration && handle.kind !== ast.SyntaxKind.PropertySignature) return false;
    const declaration = handle.resolve() as ParameterView | undefined;
    return declaration !== undefined && isPresent(declaration.type) &&
      booleanContract(authority, checker.getTypeFromTypeNode(declaration.type as TsrsAst.TypeNode), true);
  })) return true;
  if (!ast.isIdentifier(attribute.name)) return false;
  const propertyName = attribute.name.text;
  const opening = attribute.parent.parent;
  const propContract = (type: Type): boolean => {
    const property = checker.getPropertyOfType(type, propertyName);
    return property !== undefined && booleanContract(authority, checker.getTypeOfSymbolAtLocation(property, attribute), true);
  };
  // Resolve original annotations; instantiated JSX inference may originate in our callback.
  const props = resolvedDeclaration(checker.getResolvedSignature(opening))?.parameters?.[0];
  if (props !== undefined && ast.isParameterDeclaration(props) && isPresent(props.type) &&
    propContract(checker.getTypeFromTypeNode(props.type))) return true;
  // Generic callable containers can fix their props independently of this JSX invocation.
  const tagName = (opening as TsrsAst.JsxOpeningLikeElement).tagName;
  return checker.getTypeAtLocation(tagName).getCallSignatures().some((signature) => {
    const parameter = signature.getParameters()[0];
    return parameter !== undefined && propContract(checker.getTypeOfSymbolAtLocation(parameter, tagName));
  });
}

function outerTypedExpression(native: NativeTypes, node: TsNode): TsNode {
  const { ast } = native;
  let current = node;
  while ((ast.isParenthesizedExpression(current.parent) || ast.isAsExpression(current.parent) || ast.isTypeAssertion(current.parent) ||
    ast.isNonNullExpression(current.parent) || ast.isSatisfiesExpression(current.parent)) && current.parent.expression === current) current = current.parent;
  return current;
}

function hasDeclaredContract(authority: Authority): boolean {
  const node = authority.implementation;
  const { ast, checker } = authority.native;
  if (ast.isArrowFunction(node) || ast.isFunctionExpression(node)) {
    if (callbackContract(authority, node)) return true;
    const binding = outerTypedExpression(authority.native, node).parent;
    if ((ast.isVariableDeclaration(binding) || ast.isPropertyDeclaration(binding)) && isPresent(binding.type) &&
      booleanContract(authority, checker.getTypeFromTypeNode(binding.type), true)) return true;
    return ast.isPropertyDeclaration(binding) && memberContract(authority, binding);
  }
  if (ast.isMethodDeclaration(node)) return memberContract(authority, node);
  if (!ast.isFunctionDeclaration(node) || !isPresent(node.name)) return false;
  const declarations = checker.getSymbolAtLocation(node.name)?.declarations ?? [];
  return declarations.some((handle) => {
    if (handle.kind !== ast.SyntaxKind.FunctionDeclaration) return false;
    const declaration = handle.resolve() as SignatureDeclarationView | undefined;
    return declaration !== undefined && declaration !== node && isPresent(declaration.parameters?.[authority.index]?.type);
  });
}

function memberContract(authority: Authority, member: TsrsAst.MethodDeclaration | TsrsAst.PropertyDeclaration): boolean {
  const { ast, checker } = authority.native;
  const owner = member.parent;
  const symbol = checker.getSymbolAtLocation(member.name);
  if (symbol === undefined || ast.isPrivateIdentifier(member.name)) return false;
  const matches = (type: Type, independentlyAnnotated = false): boolean => {
    const property = type.getProperties().find((candidate) => candidate.escapedName === symbol.escapedName);
    return property !== undefined && booleanContract(authority, checker.getTypeOfSymbolAtLocation(property, member), independentlyAnnotated);
  };
  if (ast.isObjectLiteralExpression(owner)) {
    const contextual = checker.getContextualType(owner);
    const binding = outerTypedExpression(authority.native, owner).parent;
    if (ast.isVariableDeclaration(binding) && isPresent(binding.type) && matches(checker.getTypeFromTypeNode(binding.type), true)) return true;
    return contextual !== undefined && matches(contextual);
  }
  if (!ast.isClassDeclaration(owner) && !ast.isClassExpression(owner)) return false;
  const modifiers = ast.getCombinedModifierFlags(member);
  if ((modifiers & ast.ModifierFlags.Private) !== 0) return false;
  return owner.heritageClauses?.some((clause) => clause.types.some((heritage) =>
    matches(checker.getTypeAtLocation((modifiers & ast.ModifierFlags.Static) !== 0 ? (heritage as TsrsAst.ExpressionWithTypeArguments).expression : heritage), true))) === true;
}

function callableBinding(owner: FunctionNode, sourceCode: SourceCode): TsVariable | null {
  if (owner.type === "FunctionDeclaration" && owner.id !== null) return findVariable(sourceCode.getScope(owner), owner.id.name);
  const binding = parentOf(outerExpression(owner));
  return binding?.type === "VariableDeclarator" && binding.id.type === "Identifier"
    ? findVariable(sourceCode.getScope(binding.id), binding.id.name) : null;
}

function hasCallbackReference(binding: TsVariable, authority: Authority, sourceCode: SourceCode, seen: Set<TsVariable>): boolean {
  if (seen.has(binding)) return false;
  // Very large alias graphs abstain rather than infer ownership beyond the bounded analysis.
  if (seen.size >= 32) return true;
  seen.add(binding);
  if (binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  return binding.references.some((reference) => {
    if (!reference.isRead()) return false;
    const value = outerExpression(reference.identifier);
    const parent = parentOf(value);
    if (isContractedCallback(value, authority)) return true;
    if (parent?.type === "CallExpression" && parent.callee === value && forwardedCallbackParameter(parent, authority, sourceCode)) return true;
    let selected = value;
    let branches = 0;
    for (let conditional = parentOf(selected); conditional?.type === "ConditionalExpression" &&
      (conditional.consequent === selected || conditional.alternate === selected); conditional = parentOf(selected)) {
      if (branches >= 32) return true;
      branches += 1;
      selected = outerExpression(conditional);
    }
    const declaration = parentOf(selected);
    if (declaration?.type !== "VariableDeclarator" || declaration.init !== selected || declaration.id.type !== "Identifier" ||
      (parentOf(declaration) as ESTree.VariableDeclaration | null)?.kind !== "const") return false;
    const alias = findVariable(sourceCode.getScope(declaration.id), declaration.id.name);
    return alias !== null && hasCallbackReference(alias, authority, sourceCode, seen);
  });
}

/** `value` is passed as a call argument or JSX attribute whose declared contract takes a boolean there. */
function isContractedCallback(value: Node, authority: Authority): boolean {
  const parent = parentOf(value);
  const callArgument = parent?.type === "CallExpression" && parent.arguments.some((argument) => argument === value);
  const jsxAttribute = parent?.type === "JSXExpressionContainer" && parentOf(parent)?.type === "JSXAttribute";
  if (!callArgument && !jsxAttribute) return false;
  const expression = authority.native.node(value);
  return expression !== undefined && authority.native.ast.isExpression(expression) && callbackContract(authority, expression);
}

function forwardedCallbackParameter(call: ESTree.CallExpression, authority: Authority, sourceCode: SourceCode): boolean {
  const { ast } = authority.native;
  if (call.optional || call.arguments.some((argument) => argument.type === "SpreadElement")) return false;
  const argument = call.arguments[authority.index];
  if (argument?.type !== "Identifier") return false;
  const wrapper = enclosingFunction(call);
  if (wrapper === null) return false;
  const index = booleanParameterIndex(argument, wrapper, sourceCode, authority.native);
  const implementation = functionNode(authority.native, wrapper);
  return index >= 0 && implementation !== undefined && (ast.isArrowFunction(implementation) || ast.isFunctionExpression(implementation)) &&
    callbackContract({ native: authority.native, index, implementation }, implementation);
}

// Property accesses of one file by the declaration each name resolves to (`path#index` of its handle), per AST.
const MEMBER_REFERENCES = new WeakMap<object, ReadonlyMap<string, readonly TsrsAst.PropertyAccessExpression[]>>();

function declarationKey(path: string, index: number): string {
  return `${path}#${String(index)}`;
}

function hasMemberCallbackReference(authority: Authority, sourceCode: SourceCode): boolean {
  const native = authority.native;
  const { ast, checker } = native;
  const node = authority.implementation;
  const member = ast.isMethodDeclaration(node) ? node : ast.isArrowFunction(node) || ast.isFunctionExpression(node) ? outerTypedExpression(native, node).parent : undefined;
  if (member === undefined || (!ast.isMethodDeclaration(member) && !ast.isPropertyDeclaration(member) && !ast.isPropertyAssignment(member))) return false;
  // Local tsrs nodes carry the node index their handles name.
  const index = (member as unknown as { readonly index: number }).index;
  return memberReferences(native, sourceCode).get(declarationKey(native.source.path, index))?.some((reference) => {
    let value = outerTypedExpression(native, reference);
    const bind = value.parent;
    if (ast.isPropertyAccessExpression(bind) && bind.expression === value && ast.isIdentifier(bind.name) && bind.name.text === "bind" &&
      ast.isCallExpression(bind.parent) && bind.parent.expression === bind && bind.parent.arguments.length === 1) {
      const declaration = checker.getResolvedSignature(bind.parent).declaration;
      if (declaration === undefined || native.program.getSourceFileMetadataByPath(declaration.path)?.isDefaultLibrary !== true) return false;
      value = outerTypedExpression(native, bind.parent);
    }
    const parent = value.parent;
    const callback = ast.isCallExpression(parent) && parent.arguments.some((argument) => argument === value);
    const jsx = ast.isJsxExpression(parent) && ast.isJsxAttribute(parent.parent);
    return (callback || jsx) && callbackContract(authority, value);
  }) === true;
}

function memberReferences(native: NativeTypes, sourceCode: SourceCode): ReadonlyMap<string, readonly TsrsAst.PropertyAccessExpression[]> {
  const cached = MEMBER_REFERENCES.get(sourceCode.ast);
  if (cached !== undefined) return cached;
  const accesses: TsrsAst.PropertyAccessExpression[] = [];
  const visit = (current: TsNode): undefined => {
    if (native.ast.isPropertyAccessExpression(current)) accesses.push(current);
    current.forEachChild(visit);
    return undefined;
  };
  visit(native.source);
  // One request for every name, where the original asks per access.
  const symbols: (TsSymbol | undefined)[] = accesses.length === 0 ? [] : native.checker.getSymbolAtLocation(accesses.map((access) => access.name));
  const collected = new Map<string, TsrsAst.PropertyAccessExpression[]>();
  accesses.forEach((access, i) => {
    for (const declaration of symbols[i]?.declarations ?? []) {
      const key = declarationKey(declaration.path, declaration.index);
      const values = collected.get(key) ?? [];
      values.push(access);
      collected.set(key, values);
    }
  });
  MEMBER_REFERENCES.set(sourceCode.ast, collected);
  return collected;
}

function isPureMapping(owner: FunctionNode, sourceCode: SourceCode, native: NativeTypes): boolean {
  if (owner.body?.type !== "BlockStatement" || owner.body.body.length !== 1) return false;
  const statement = owner.body.body[0];
  if (statement?.type !== "IfStatement" || !isPresent(statement.alternate)) return false;
  const consequent = returnedExpression(statement.consequent);
  const alternate = returnedExpression(statement.alternate);
  return consequent !== null && alternate !== null && consequent.kind === alternate.kind &&
    isBooleanDataSelection(consequent.value, alternate.value, sourceCode, native);
}

function returnedExpression(statement: ESTree.Statement): { readonly value: Expression; readonly kind: "return" | "expression" } | null {
  if (statement.type === "BlockStatement") {
    const first = statement.body[0];
    return statement.body.length === 1 && first !== undefined ? returnedExpression(first) : null;
  }
  if (statement.type === "ExpressionStatement") return { value: statement.expression, kind: "expression" };
  return statement.type === "ReturnStatement" && statement.argument !== null ? { value: statement.argument, kind: "return" } : null;
}

/** Selecting syntactic argument/value data for one stable operation does not prove different operations. */
export function isBooleanDataSelection(consequent: Node, alternate: Node, sourceCode: SourceCode, native: NativeTypes): boolean {
  const left = unwrapExpression(consequent);
  const right = unwrapExpression(alternate);
  if (pureValue(left, sourceCode, native) && pureValue(right, sourceCode, native)) return true;
  if (left.type === "CallExpression" && right.type === "CallExpression" && !left.optional && !right.optional &&
    sameTarget(left.callee, right.callee, sourceCode, native, true)) {
    return [...left.arguments, ...right.arguments].every((argument) => argument.type !== "SpreadElement" && pureValue(argument, sourceCode, native));
  }
  return left.type === "AssignmentExpression" && right.type === "AssignmentExpression" &&
    left.operator === "=" && right.operator === "=" && sameTarget(left.left, right.left, sourceCode, native, false) &&
    pureValue(left.right, sourceCode, native) && pureValue(right.right, sourceCode, native);
}

function sameTarget(left: Node, right: Node, sourceCode: SourceCode, native: NativeTypes, operation: boolean): boolean {
  const stable = (identifier: Identifier): TsVariable | null => {
    const binding = findVariable(sourceCode.getScope(identifier), identifier.name);
    return binding !== null && (!operation || !binding.references.some((reference) => reference.isWrite() && reference.init !== true)) ? binding : null;
  };
  if (left.type === "Identifier" && right.type === "Identifier") {
    const binding = stable(left);
    return binding !== null && binding === stable(right);
  }
  if (left.type !== "MemberExpression" || right.type !== "MemberExpression" || left.computed || right.computed ||
    left.optional || right.optional || left.property.type !== "Identifier" || right.property.type !== "Identifier" ||
    left.property.name !== right.property.name) return false;
  const receiver = left.object.type === "ThisExpression" && right.object.type === "ThisExpression" ||
    left.object.type === "Identifier" && right.object.type === "Identifier" &&
    stable(left.object) !== null && stable(left.object) === stable(right.object);
  if (!receiver) return false;
  if (!operation) return true;
  const leftProperty = native.node(left.property);
  const rightProperty = native.node(right.property);
  if (leftProperty === undefined || rightProperty === undefined) return false;
  const [property, other] = native.checker.getSymbolAtLocation([leftProperty, rightProperty]);
  return property !== undefined && property === other &&
    property.declarations.every((declaration) => declaration.kind === native.ast.SyntaxKind.MethodDeclaration);
}

function pureValue(node: Node, sourceCode: SourceCode, native: NativeTypes): boolean {
  const value = unwrapExpression(node);
  // A property read is data syntax; whether a getter performs work is deliberately not inferred.
  if (value.type === "MemberExpression" && !value.computed) return value.object.type === "Super" || pureValue(value.object, sourceCode, native);
  if (value.type === "ChainExpression") return pureValue(value.expression, sourceCode, native);
  if (value.type === "UnaryExpression" && (value.operator === "!" || value.operator === "typeof" || value.operator === "void")) return pureValue(value.argument, sourceCode, native);
  if (value.type === "UnaryExpression" && (value.operator === "+" || value.operator === "-" || value.operator === "~")) return primitiveValue(value.argument, native) && pureValue(value.argument, sourceCode, native);
  if (!hasSideEffect(value, sourceCode, { considerGetters: true, considerImplicitTypeConversion: true })) return true;
  if (value.type !== "BinaryExpression" || (value.left as Node).type === "PrivateIdentifier") return false;
  return primitiveValue(value.left, native) && primitiveValue(value.right, native) && pureValue(value.left, sourceCode, native) && pureValue(value.right, sourceCode, native);
}

function primitiveValue(operand: Node, native: NativeTypes): boolean {
  const location = native.node(operand);
  if (location === undefined) return false;
  const flags = native.sync.TypeFlags;
  const type = native.checker.getTypeAtLocation(location);
  return (type.isUnionType() ? type.getTypes() : [type]).every((member) => (member.flags &
    (flags.StringLike | flags.NumberLike | flags.BooleanLike | flags.BigIntLike | flags.Null | flags.Undefined)) !== 0);
}
