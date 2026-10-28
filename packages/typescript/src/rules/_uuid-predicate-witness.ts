/** @fileoverview _uuid-predicate-witness — a closed official UUID schema rejects members of broad string. */

import { AST_NODE_TYPES, ASTUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { nativeRuntimeUnchanged } from "./_native-runtime-unchanged.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Variable = TSESLint.Scope.Variable;

/** Only this exact parse-success shape supplies a witness; opaque schema behavior is not inferred. */
export function uuidPredicateWitness(
  expression: TSESTree.Expression,
  parameter: TSESTree.Identifier,
  sourceCode: TSESLint.SourceCode,
  services: ParserServicesWithTypeInformation,
): string | undefined {
  const success = unwrapExpression(expression);
  if (!member(success, "success")) return undefined;
  const parse = unwrapExpression(success.object);
  if (parse.type !== AST_NODE_TYPES.CallExpression || parse.optional || parse.arguments.length !== 1 || !member(parse.callee, "safeParse")) return undefined;
  const argument = parse.arguments[0];
  if (argument === undefined || unwrapExpression(argument).type !== AST_NODE_TYPES.Identifier) return undefined;
  const value = unwrapExpression(argument);
  if (value.type !== AST_NODE_TYPES.Identifier || binding(value, sourceCode) !== binding(parameter, sourceCode)) return undefined;
  const receiver = unwrapExpression(parse.callee.object);
  if (receiver.type !== AST_NODE_TYPES.Identifier) return undefined;
  const schema = binding(receiver, sourceCode);
  const declaration = schema?.defs.length === 1 ? schema.defs[0] : undefined;
  if (schema === null || declaration?.type !== "Variable" || declaration.node.type !== AST_NODE_TYPES.VariableDeclarator ||
    declaration.node.parent.kind !== "const" || declaration.node.init === null) return undefined;
  const initializer = unwrapExpression(declaration.node.init);
  const namespace = uuidNamespace(initializer, sourceCode, services);
  if (namespace === null || !closedSchema(schema) || !closedNamespace(namespace, initializer) || !nativeRuntimeUnchanged(sourceCode, "RegExp")) return undefined;
  return "not-a-uuid";
}

function binding(node: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): Variable | null {
  return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
}

function member(node: TSESTree.Node | undefined, name: string): node is TSESTree.MemberExpression {
  return node?.type === AST_NODE_TYPES.MemberExpression && !node.optional && !node.computed &&
    node.property.type === AST_NODE_TYPES.Identifier && node.property.name === name;
}

function uuidNamespace(initializer: TSESTree.Node, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation): Variable | null {
  if (!noArguments(initializer) || !member(initializer.callee, "uuid")) return null;
  let receiver = unwrapExpression(initializer.callee.object);
  let legacy = false;
  if (noArguments(receiver) && member(receiver.callee, "string")) {
    receiver = unwrapExpression(receiver.callee.object);
    legacy = true;
  }
  if (receiver.type !== AST_NODE_TYPES.Identifier) return null;
  const namespace = binding(receiver, sourceCode);
  const definition = namespace?.defs.length === 1 ? namespace.defs[0] : undefined;
  if (definition?.type !== "ImportBinding" || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
    definition.parent.importKind === "type") return null;
  const module = definition.parent.source.value;
  if (module !== "zod" && module !== "zod/v4" && !(legacy && module === "zod/v3")) return null;
  const specifier = definition.node;
  if (specifier.type !== AST_NODE_TYPES.ImportNamespaceSpecifier &&
    (specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type" ||
      specifier.imported.type !== AST_NODE_TYPES.Identifier || specifier.imported.name !== "z")) return null;
  if (!installedZod(receiver, services)) return null;
  return namespace ?? null;
}

function noArguments(node: TSESTree.Node): node is TSESTree.CallExpression {
  return node.type === AST_NODE_TYPES.CallExpression && !node.optional && node.arguments.length === 0;
}

function installedZod(node: TSESTree.Identifier, services: ParserServicesWithTypeInformation): boolean {
  const checker = services.program.getTypeChecker();
  const symbol = checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(node));
  if (symbol === undefined || (symbol.flags & ts.SymbolFlags.Alias) === 0) return false;
  const target = checker.getAliasedSymbol(symbol);
  const declarations = target.getDeclarations();
  return declarations !== undefined && declarations.length > 0 && declarations.every((declaration) => {
    const source = declaration.getSourceFile();
    return source.isDeclarationFile && source.fileName.replaceAll("\\", "/").includes("/node_modules/zod/");
  });
}

function closedSchema(schema: Variable): boolean {
  return schema.references.every((reference) => {
    if (reference.isWrite()) return reference.init === true;
    if (reference.isValueReference === false) return true;
    const receiver = outerExpression(reference.identifier);
    const property = receiver.parent;
    if (property?.type === AST_NODE_TYPES.ExportSpecifier && property.local === receiver) return true;
    if (!member(property, "safeParse") || property.object !== receiver) return false;
    const call = property.parent;
    return call?.type === AST_NODE_TYPES.CallExpression && call.callee === property && !call.optional &&
      call.arguments.length === 1 && call.arguments[0]?.type !== AST_NODE_TYPES.SpreadElement;
  });
}

function closedNamespace(namespace: Variable, initializer: TSESTree.Node): boolean {
  // Other value uses may replace a factory or obtain a mutable schema prototype.
  // Type-only references cannot mutate the imported runtime namespace.
  return namespace.references.every((reference) => reference.isValueReference === false ||
    (!reference.isWrite() && reference.identifier.range[0] >= initializer.range[0] && reference.identifier.range[1] <= initializer.range[1]));
}
