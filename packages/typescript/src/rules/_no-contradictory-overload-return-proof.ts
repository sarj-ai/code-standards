/**
 * @fileoverview _no-contradictory-overload-return-proof — the original's TypeScript-AST proof, on tsrs remote nodes.
 *
 * The original reads the TypeScript AST of the implementation and its
 * overloads. tsrs serves the same TypeScript 7 nodes (same property names,
 * TypeScript 7 `SyntaxKind` numbering), so this is the original's logic with
 * `ts.is*` taken from `tsrs/ast` and two identity checks made positional:
 * tsrs builds a new remote node object per lookup (a resolved declaration
 * handle is not `===` the node found by walking the file), so nodes compare by
 * kind and range and symbols by id.
 */

import { nullTolerantAst, type TsrsFile, type TsrsNode, type TsrsNodeHandle, type TsrsSymbol, type TsrsType } from "../utils/tsrs-services.js";

/** A tsrs remote node: TypeScript's node shape, every child optional. */
export interface RemoteNode extends TsrsNode {
  readonly parent?: RemoteNode | undefined;
  readonly [field: string]: unknown;
}
type Field = RemoteNode | undefined;
type List = readonly RemoteNode[] | undefined;
interface Handle extends TsrsNodeHandle {
  readonly kind: number;
  resolve(): RemoteNode | undefined;
}
interface Symbol extends TsrsSymbol {
  readonly id: number;
  readonly declarations: readonly Handle[];
}
interface Signature {
  readonly declaration?: Handle | undefined;
}
interface Type extends Omit<TsrsType, "getTypes"> {
  getTypes(): readonly Type[];
}
interface Checker {
  getSymbolAtLocation(node: TsrsNode): Symbol | undefined;
  getSignatureFromDeclaration(node: TsrsNode): Signature | undefined;
  getReturnTypeOfSignature(signature: Signature): Type;
  getTypeAtLocation(node: TsrsNode): Type;
  isTypeAssignableTo(source: Type, target: Type): boolean;
  getPropertyOfType(type: Type, name: string): Symbol | undefined;
  getTypeOfSymbolAtLocation(symbol: Symbol, location: TsrsNode): Type;
  typeToString(type: Type): string;
}

type Is = (node: RemoteNode | undefined) => boolean;
interface Ast {
  readonly SyntaxKind: Readonly<Record<string, number>>;
  readonly isSourceFile: Is;
  readonly isReturnStatement: Is;
  readonly isConditionalExpression: Is;
  readonly isParenthesizedExpression: Is;
  readonly isBinaryExpression: Is;
  readonly isIdentifier: Is;
  readonly isStringLiteral: Is;
  readonly isNumericLiteral: Is;
  readonly isPrefixUnaryExpression: Is;
  readonly isObjectLiteralExpression: Is;
  readonly isPropertyAssignment: Is;
  readonly isFunctionDeclaration: Is;
  readonly isLiteralTypeNode: Is;
  readonly isParenthesizedTypeNode: Is;
  readonly isUnionTypeNode: Is;
  readonly isTypeLiteralNode: Is;
  readonly isPropertySignatureDeclaration: Is;
}

type Primitive = string | number | boolean | null;
export interface LiteralValue { readonly node: RemoteNode; readonly value: Primitive; }
export interface LiteralCase { readonly input: LiteralValue; readonly output: Type; readonly declaration: RemoteNode; }
export type Branch =
  | { readonly kind: "literal"; readonly node: RemoteNode; readonly value: LiteralValue }
  | { readonly kind: "record"; readonly node: RemoteNode; readonly values: ReadonlyMap<string, LiteralValue> };
export interface Proof {
  readonly condition: LiteralValue;
  readonly equal: boolean;
  readonly yes: Branch;
  readonly no: Branch;
  readonly cases: readonly LiteralCase[];
  /** Whether every declaration of the function is in one file (the original's `getSourceFile()` comparison). */
  readonly oneFile: boolean;
}
const LIMIT = 32;

export function sameNode(left: TsrsNode, right: TsrsNode): boolean {
  return left.kind === right.kind && left.pos === right.pos && left.end === right.end;
}

/** The original's free functions, bound to one file's checker and tsrs syntax. */
export function overloadProof(file: TsrsFile) {
  const a = nullTolerantAst<Ast>(file);
  const k = a.SyntaxKind;
  const flags = file.flags;
  const checker = file.checker as unknown as Checker;

  function unparen(expression: RemoteNode): RemoteNode {
    let node = expression;
    while (a.isParenthesizedExpression(node)) node = node["expression"] as RemoteNode;
    return node;
  }

  function primitiveLiteral(expression: RemoteNode): LiteralValue | undefined {
    const node = unparen(expression);
    if (a.isStringLiteral(node)) return { node, value: node["text"] as string };
    if (node.kind === k["TrueKeyword"]) return { node, value: true };
    if (node.kind === k["FalseKeyword"]) return { node, value: false };
    if (node.kind === k["NullKeyword"]) return { node, value: null };
    if (a.isNumericLiteral(node) && Number.isFinite(Number(node["text"]))) return { node, value: Number(node["text"]) };
    const operand = node["operand"] as Field;
    if (a.isPrefixUnaryExpression(node) && (node["operator"] === k["MinusToken"] || node["operator"] === k["PlusToken"]) &&
      a.isNumericLiteral(operand)) {
      const value = Number(operand!["text"]) * (node["operator"] === k["MinusToken"] ? -1 : 1);
      if (Number.isFinite(value)) return { node, value };
    }
    return undefined;
  }

  function propertyKey(name: RemoteNode): string | undefined {
    if (a.isIdentifier(name) || a.isStringLiteral(name)) return name["text"] as string;
    if (a.isNumericLiteral(name) && Number.isFinite(Number(name["text"]))) return String(Number(name["text"]));
    return undefined;
  }

  function directParameter(node: RemoteNode): { readonly name: RemoteNode; readonly type: RemoteNode } | undefined {
    const parameters = node["parameters"] as List ?? [];
    const parameter = parameters[0];
    if (parameters.length !== 1 || parameter === undefined) return undefined;
    const name = parameter["name"] as Field;
    const type = parameter["type"] as Field;
    if (!a.isIdentifier(name) || name!["text"] === "this" || type === undefined || parameter["questionToken"] !== undefined ||
      parameter["dotDotDotToken"] !== undefined || parameter["initializer"] !== undefined) return undefined;
    return { name: name!, type };
  }

  function implementationProof(node: RemoteNode): Proof | undefined {
    const parameter = directParameter(node);
    const statements = (node["body"] as Field)?.["statements"] as List;
    const modifiers = node["modifiers"] as List;
    if (!a.isSourceFile(node.parent) || node["name"] === undefined || statements?.length !== 1 ||
      node["typeParameters"] !== undefined || node["asteriskToken"] !== undefined ||
      modifiers?.some((modifier) => modifier.kind === k["AsyncKeyword"]) || parameter === undefined) return undefined;
    const returned = statements[0];
    const returnedExpression = returned?.["expression"] as Field;
    if (returned === undefined || !a.isReturnStatement(returned) || returnedExpression === undefined) return undefined;
    const expression = unparen(returnedExpression);
    if (!a.isConditionalExpression(expression)) return undefined;
    const condition = equality(expression["condition"] as RemoteNode, checker.getSymbolAtLocation(parameter.name));
    const yes = branchValue(expression["whenTrue"] as RemoteNode);
    const no = branchValue(expression["whenFalse"] as RemoteNode);
    if (condition === undefined || yes === undefined || no === undefined) return undefined;
    const signature = checker.getSignatureFromDeclaration(node);
    if (signature === undefined) return undefined;
    const output = checker.getReturnTypeOfSignature(signature);
    if (!checker.isTypeAssignableTo(checker.getTypeAtLocation(yes.node), output) ||
      !checker.isTypeAssignableTo(checker.getTypeAtLocation(no.node), output)) return undefined;
    const found = overloadCases(node, output);
    return found === undefined ? undefined : { ...condition, yes, no, cases: found.cases, oneFile: found.oneFile };
  }

  function overloadCases(node: RemoteNode, implementationOutput: Type): { cases: readonly LiteralCase[]; oneFile: boolean } | undefined {
    const name = node["name"] as Field;
    const handles = name === undefined ? undefined : checker.getSymbolAtLocation(name)?.declarations;
    if (handles === undefined || handles.length < 3 || handles.length > LIMIT + 1 ||
      handles.some((handle) => handle.kind !== k["FunctionDeclaration"])) return undefined;
    const declarations = handles.map((handle) => handle.resolve());
    if (declarations.some((declaration) => !a.isFunctionDeclaration(declaration))) return undefined;
    const cases: LiteralCase[] = [];
    const seen = new Set<Primitive>();
    const implementationParameter = directParameter(node);
    if (implementationParameter === undefined) return undefined;
    const implementationInput = checker.getTypeAtLocation(implementationParameter.type);
    for (const declaration of declarations) {
      if (declaration === undefined || sameNode(declaration, node)) continue;
      const found = literalCase(declaration, implementationInput, implementationOutput);
      if (found === undefined || seen.has(found.input.value)) return undefined;
      seen.add(found.input.value);
      cases.push(found);
    }
    const oneFile = handles.every((handle) => handle.path === handles[0]!.path);
    return cases.length >= 2 ? { cases, oneFile } : undefined;
  }

  /** A bodiless, non-generic overload of one literal-typed parameter whose input and output fit the implementation's. */
  function literalCase(declaration: RemoteNode, implementationInput: Type, implementationOutput: Type): LiteralCase | undefined {
    const parameter = directParameter(declaration);
    if (declaration["body"] !== undefined || declaration["typeParameters"] !== undefined || parameter === undefined ||
      !a.isLiteralTypeNode(parameter.type)) return undefined;
    const input = primitiveLiteral(parameter.type["literal"] as RemoteNode);
    const signature = checker.getSignatureFromDeclaration(declaration);
    if (input === undefined || signature === undefined ||
      !checker.isTypeAssignableTo(checker.getTypeAtLocation(parameter.type), implementationInput)) return undefined;
    const output = checker.getReturnTypeOfSignature(signature);
    return checker.isTypeAssignableTo(output, implementationOutput) ? { input, output, declaration } : undefined;
  }

  function branchValue(expression: RemoteNode): Branch | undefined {
    const node = unparen(expression);
    const literal = primitiveLiteral(node);
    if (literal !== undefined) return { kind: "literal", node, value: literal };
    const properties = node["properties"] as List ?? [];
    if (!a.isObjectLiteralExpression(node) || properties.length > LIMIT) return undefined;
    const values = new Map<string, LiteralValue>();
    for (const property of properties) {
      if (!a.isPropertyAssignment(property)) return undefined;
      const name = propertyKey(property["name"] as RemoteNode);
      const value = primitiveLiteral(property["initializer"] as RemoteNode);
      if (name === undefined || name === "__proto__" || values.has(name) || value === undefined) return undefined;
      values.set(name, value);
    }
    return { kind: "record", node, values };
  }

  function equality(expression: RemoteNode, parameter: Symbol | undefined) {
    const value = unparen(expression);
    const operator = (value["operatorToken"] as Field)?.kind;
    if (parameter === undefined || !a.isBinaryExpression(value) ||
      (operator !== k["EqualsEqualsEqualsToken"] && operator !== k["ExclamationEqualsEqualsToken"])) return undefined;
    const left = value["left"] as RemoteNode;
    const right = value["right"] as RemoteNode;
    for (const [tested, expected] of [[left, right], [right, left]] as const) {
      const named = unparen(tested);
      const condition = primitiveLiteral(expected);
      if (a.isIdentifier(named) && checker.getSymbolAtLocation(named)?.id === parameter.id && condition !== undefined) {
        return { condition, equal: operator === k["EqualsEqualsEqualsToken"] };
      }
    }
    return undefined;
  }

  function mismatches(branch: Branch, expected: Type): readonly LiteralValue[] {
    if (branch.kind === "literal") {
      const literal = branch.value;
      return plainPrimitive(expected) && !checker.isTypeAssignableTo(checker.getTypeAtLocation(literal.node), expected) ? [literal] : [];
    }
    const result: LiteralValue[] = [];
    for (const [key, literal] of branch.values) {
      const property = checker.getPropertyOfType(expected, key);
      if (property === undefined) continue;
      const target = checker.getTypeOfSymbolAtLocation(property, branch.node);
      if (plainPrimitive(target) && !checker.isTypeAssignableTo(checker.getTypeAtLocation(literal.node), target)) result.push(literal);
    }
    return result;
  }

  function plainPrimitive(type: Type): boolean {
    const members = type.isUnionType() ? type.getTypes() : [type];
    const allowed = flags.String | flags.StringLiteral | flags.Number | flags.NumberLiteral | flags.BooleanLiteral | flags.Null |
      flags.Undefined | flags.Never;
    return members.length <= LIMIT && members.every((member) => (member.flags & allowed) !== 0 &&
      (member.flags & (flags.Enum | flags.EnumLiteral)) === 0);
  }

  function primitiveResultSyntax(node: RemoteNode): boolean {
    if (a.isParenthesizedTypeNode(node)) return primitiveResultSyntax(node["type"] as RemoteNode);
    const types = node["types"] as List ?? [];
    if (a.isUnionTypeNode(node)) return types.length <= LIMIT && types.every(primitiveResultSyntax);
    if (a.isLiteralTypeNode(node)) return primitiveLiteral(node["literal"] as RemoteNode) !== undefined;
    return node.kind === k["StringKeyword"] || node.kind === k["NumberKeyword"] || node.kind === k["BooleanKeyword"] ||
      node.kind === k["UndefinedKeyword"] || node.kind === k["NeverKeyword"];
  }

  function directResultSyntax(node: RemoteNode): boolean {
    if (a.isParenthesizedTypeNode(node)) return directResultSyntax(node["type"] as RemoteNode);
    const types = node["types"] as List ?? [];
    if (a.isUnionTypeNode(node)) return types.length <= LIMIT && types.every(directResultSyntax);
    if (!a.isTypeLiteralNode(node)) return primitiveResultSyntax(node);
    return (node["members"] as List ?? []).every((member) => {
      const type = member["type"] as Field;
      return a.isPropertySignatureDeclaration(member) && propertyKey(member["name"] as RemoteNode) !== undefined &&
        type !== undefined && primitiveResultSyntax(type);
    });
  }

  return {
    implementationProof,
    directParameter,
    mismatches,
    primitiveResultSyntax,
    directResultSyntax,
    typeToString: (type: Type) => checker.typeToString(type),
  };
}

export type OverloadProof = NonNullable<ReturnType<typeof overloadProof>>;
