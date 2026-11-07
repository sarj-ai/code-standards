/**
 * @fileoverview _closed-nominal-inheritance-fix — port of
 * the 18.x `_closed-nominal-inheritance-fix.ts` helper: repair closed local nominal constructions.
 *
 * The original reads TypeScript nodes; these are the same nodes from tsrs
 * (`_require-explicit-contract-implementation-typed.ts`), compared by file,
 * kind and range instead of object identity. Only this rule uses the helper.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import type { SourceCode } from "../types.js";
import { findVariable } from "../utils/static-string.js";
import { nullTolerantAst, type TsrsFile } from "../utils/tsrs-services.js";
import { type Ast as TypedAst, type RemoteNode, same, sourceOf } from "./_require-explicit-contract-implementation-typed.js";

type Field = RemoteNode | undefined;
type List = readonly RemoteNode[] | undefined;
type Ast = TypedAst & Readonly<Record<string, unknown>>;
type Is = (node: RemoteNode | undefined) => boolean;

/** Repair one closed local construction against its already authored nominal runtime authority. */
export function closedNominalInheritanceFix(
  sourceCode: Readonly<SourceCode>,
  file: TsrsFile,
  call: RemoteNode,
  consumer: RemoteNode,
  implementation: RemoteNode,
  contract: RemoteNode,
): ((fixer: Fixer) => Fix) | null {
  const a = nullTolerantAst<Ast>(file);
  const k = a.SyntaxKind;
  const is = (name: string): Is => a[name] as Is;
  const text = (node: Field): string | undefined => node?.["text"] as string | undefined;
  const source = sourceOf(call);
  if (!isClosedLayout()) return null;
  const contractName = contract["name"] as Field;
  const implementationName = implementation["name"] as Field;
  const names = classNames(contractName, consumer["name"] as Field, implementationName);
  const method = emptyContractMethod(contract);
  if (names === null || contractName === undefined || implementationName === undefined || method === null ||
    !emptyImplementation(implementation, method) || !exactConsumer(consumer, names.contract) ||
    !exactConstruction(call, names.consumer, names.implementation)) return null;
  const base = source.text.slice(contractName.getStart(source), contractName.end);
  const range: [number, number] = [implementationName.getStart(source), implementationName.end];
  return (fixer) => fixer.insertTextAfterRange(range, ` extends ${base}`);

  /** Contract, consumer, implementation and the construction, in that order, plus one `export {}`, in one comment-free file. */
  function isClosedLayout(): boolean {
    const statementsOf = source.statements;
    if (source.text !== sourceCode.text || statementsOf.length !== 5 || sourceCode.getAllComments().length > 0 ||
      [consumer, implementation, contract].some((node) => sourceOf(node).fileName !== source.fileName)) return false;
    const markers = statementsOf.filter((node) => is("isExportDeclaration")(node));
    if (markers.length !== 1 || markers[0] === undefined || !emptyModuleMarker(markers[0])) return false;
    const statements = statementsOf.filter((node) => !is("isExportDeclaration")(node));
    const construction = statements[3];
    return same(statements[0], contract) && same(statements[1], consumer) && same(statements[2], implementation) &&
      construction !== undefined && is("isExpressionStatement")(construction) && same(construction["expression"] as Field, call);
  }

  /** The three distinct names of the plain classes: an abstract contract, the consumer and the implementation. */
  function classNames(
    contractName: Field,
    consumerName: Field,
    implementationName: Field,
  ): { readonly contract: string; readonly consumer: string; readonly implementation: string } | null {
    if (!plainClass(contract, k["AbstractKeyword"]!) || !plainClass(consumer, null) || !plainClass(implementation, null)) return null;
    const [contractText, consumerText, implementationText] = [text(contractName), text(consumerName), text(implementationName)];
    if (contractText === undefined || consumerText === undefined || implementationText === undefined ||
      new Set([contractText, consumerText, implementationText]).size !== 3) return null;
    return { contract: contractText, consumer: consumerText, implementation: implementationText };
  }

  function emptyModuleMarker(node: RemoteNode): boolean {
    const clause = node["exportClause"] as Field;
    return node["isTypeOnly"] !== true && node["moduleSpecifier"] === undefined && node["attributes"] === undefined &&
      clause !== undefined && is("isNamedExports")(clause) && (clause["elements"] as List ?? []).length === 0;
  }

  function plainClass(node: RemoteNode, modifier: number | null): boolean {
    const all = node["modifiers"] as List ?? [];
    const modifiers = all.filter((item) => item.kind !== k["Decorator"]);
    const decorators = all.filter((item) => item.kind === k["Decorator"]);
    return node["name"] !== undefined && node["typeParameters"] === undefined && node["heritageClauses"] === undefined &&
      decorators.length === 0 && modifiers.length === (modifier === null ? 0 : 1) &&
      (modifier === null || modifiers[0]?.kind === modifier);
  }

  function emptyContractMethod(node: RemoteNode): string | null {
    const members = node["members"] as List ?? [];
    const member = members[0];
    const name = member?.["name"] as Field;
    const modifiers = member?.["modifiers"] as List;
    if (members.length !== 1 || member === undefined || !is("isMethodDeclaration")(member) || !is("isIdentifier")(name) ||
      text(name) === "constructor" || (member["parameters"] as List ?? []).length !== 0 || member["typeParameters"] !== undefined ||
      member["questionToken"] !== undefined || member["asteriskToken"] !== undefined || member["body"] !== undefined ||
      (member["type"] as Field)?.kind !== k["VoidKeyword"] || modifiers?.length !== 1 || modifiers[0]?.kind !== k["AbstractKeyword"]) return null;
    return text(name)!;
  }

  function emptyImplementation(node: RemoteNode, key: string): boolean {
    const members = node["members"] as List ?? [];
    const member = members[0];
    const type = member?.["type"] as Field;
    return members.length === 1 && member !== undefined && is("isMethodDeclaration")(member) && is("isIdentifier")(member["name"] as Field) &&
      text(member["name"] as Field) === key && (member["parameters"] as List ?? []).length === 0 && member["typeParameters"] === undefined &&
      member["questionToken"] === undefined && member["asteriskToken"] === undefined && member["modifiers"] === undefined &&
      (type === undefined || type.kind === k["VoidKeyword"]) &&
      (((member["body"] as Field)?.["statements"] as List)?.length ?? -1) === 0;
  }

  function exactConsumer(node: RemoteNode, base: string): boolean {
    const members = node["members"] as List ?? [];
    const constructor = members[0];
    const parameters = constructor?.["parameters"] as List ?? [];
    const bodyStatements = (constructor?.["body"] as Field)?.["statements"] as List;
    if (members.length !== 1 || constructor === undefined || !is("isConstructorDeclaration")(constructor) ||
      constructor["modifiers"] !== undefined || parameters.length !== 1 || bodyStatements?.length !== 1) return false;
    const parameterName = readonlyParameterName(parameters[0], base);
    return parameterName !== null && instanceofGuard(bodyStatements[0], parameterName, base);
  }

  /** The name of a required `readonly name: Base` parameter property. */
  function readonlyParameterName(parameter: Field, base: string): string | null {
    const parameterName = parameter?.["name"] as Field;
    const parameterModifiers = parameter?.["modifiers"] as List;
    if (parameter === undefined || !is("isIdentifier")(parameterName) || text(parameterName) === base ||
      parameter["initializer"] !== undefined || parameter["questionToken"] !== undefined || parameter["dotDotDotToken"] !== undefined ||
      parameterModifiers?.length !== 1 || parameterModifiers[0]?.kind !== k["ReadonlyKeyword"] ||
      !namesType(parameter["type"] as Field, base)) return null;
    return text(parameterName) ?? null;
  }

  /** A bare `Base` type reference. */
  function namesType(type: Field, base: string): boolean {
    const typeName = type?.["typeName"] as Field;
    return type !== undefined && is("isTypeReferenceNode")(type) && is("isIdentifier")(typeName) && text(typeName) === base &&
      type["typeArguments"] === undefined;
  }

  /** `if (!(parameter instanceof Base)) throw new TypeError("…");` with no else branch. */
  function instanceofGuard(guard: Field, parameterName: string, base: string): boolean {
    if (guard === undefined || !is("isIfStatement")(guard) || guard["elseStatement"] !== undefined) return false;
    const condition = unparenthesized(guard["expression"] as RemoteNode);
    if (!is("isPrefixUnaryExpression")(condition) || condition["operator"] !== k["ExclamationToken"]) return false;
    const comparison = unparenthesized(condition["operand"] as RemoteNode);
    const left = comparison["left"] as Field;
    const right = comparison["right"] as Field;
    return is("isBinaryExpression")(comparison) && (comparison["operatorToken"] as Field)?.kind === k["InstanceOfKeyword"] &&
      is("isIdentifier")(left) && text(left) === parameterName && is("isIdentifier")(right) && text(right) === base &&
      exactRejection(guard["thenStatement"] as RemoteNode);
  }

  function unparenthesized(node: RemoteNode): RemoteNode {
    let expression = node;
    while (is("isParenthesizedExpression")(expression)) expression = expression["expression"] as RemoteNode;
    return expression;
  }

  function exactRejection(statement: RemoteNode): boolean {
    const inner = statement["statements"] as List;
    const rejected = is("isBlock")(statement) && inner?.length === 1 ? inner[0] : statement;
    const thrown = rejected?.["expression"] as Field;
    const constructor = thrown?.["expression"] as Field;
    const args = thrown?.["arguments"] as List;
    if (rejected === undefined || !is("isThrowStatement")(rejected) || thrown === undefined || !is("isNewExpression")(thrown) ||
      !is("isIdentifier")(constructor) || text(constructor) !== "TypeError" || thrown["typeArguments"] !== undefined ||
      args?.length !== 1 || args[0] === undefined || !is("isStringLiteral")(args[0])) return false;
    const identifier = sourceCode.getNodeByRangeIndex(constructor!.getStart(source));
    return identifier?.type === "Identifier" && identifier.name === "TypeError" &&
      (findVariable(sourceCode.getScope(identifier), identifier.name)?.defs.length ?? 0) === 0;
  }

  function exactConstruction(node: RemoteNode, consumerText: string, implementationText: string): boolean {
    const expression = node["expression"] as Field;
    const args = node["arguments"] as List;
    if (!is("isIdentifier")(expression) || text(expression) !== consumerText || node["typeArguments"] !== undefined || args?.length !== 1) return false;
    const argument = args[0];
    const constructed = argument?.["expression"] as Field;
    return argument !== undefined && is("isNewExpression")(argument) && is("isIdentifier")(constructed) &&
      text(constructed) === implementationText && argument["typeArguments"] === undefined &&
      (argument["arguments"] as List)?.length === 0;
  }
}
