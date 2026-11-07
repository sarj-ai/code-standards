/**
 * @fileoverview _uuid-predicate-witness — a closed official UUID schema rejects members of broad string.
 *
 * Port of the 18.x `_uuid-predicate-witness.ts` helper. The installed-zod
 * check asks tsrs for the namespace import's aliased symbol.
 */

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import type { NativeTypes } from "../utils/checked-native-source.js";
import { nativeRuntimeUnchanged } from "../utils/native-runtime-unchanged.js";
import { findVariable } from "../utils/static-string.js";

type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

const DECLARATION_FILE = /\.d\.[cm]?ts$/u;

/** Only this exact parse-success shape supplies a witness; opaque schema behavior is not inferred. */
export function uuidPredicateWitness(
  expression: Node,
  parameter: Identifier,
  sourceCode: SourceCode,
  native: NativeTypes,
): string | undefined {
  const receiver = safeParseReceiver(expression, parameter, sourceCode);
  const schema = receiver === null ? null : binding(receiver, sourceCode);
  const initializer = schema === null ? null : constInitializer(schema);
  if (schema === null || initializer === null) return undefined;
  const namespace = uuidNamespace(initializer, sourceCode, native);
  if (namespace === null || !closedSchema(schema) || !closedNamespace(namespace, initializer) || !nativeRuntimeUnchanged(sourceCode, "RegExp")) return undefined;
  return "not-a-uuid";
}

/** The schema identifier of `schema.safeParse(parameter).success`. */
function safeParseReceiver(expression: Node, parameter: Identifier, sourceCode: SourceCode): Identifier | null {
  const success = unwrapExpression(expression);
  if (success.type !== "MemberExpression" || !member(success, "success")) return null;
  const parse = unwrapExpression(success.object);
  if (parse.type !== "CallExpression" || parse.optional || parse.arguments.length !== 1 || parse.callee.type !== "MemberExpression" || !member(parse.callee, "safeParse")) return null;
  const argument = parse.arguments[0];
  const value = argument === undefined ? undefined : unwrapExpression(argument);
  if (value?.type !== "Identifier" || binding(value, sourceCode) !== binding(parameter, sourceCode)) return null;
  const receiver = unwrapExpression(parse.callee.object);
  return receiver.type === "Identifier" ? receiver : null;
}

/** The unwrapped initializer of a variable's only `const` declarator. */
function constInitializer(variable: TsVariable): Node | null {
  const declaration = variable.defs.length === 1 ? variable.defs[0] : undefined;
  if (declaration?.type !== "Variable" || declaration.node.type !== "VariableDeclarator") return null;
  const declarator = declaration.node;
  if ((parentOf(declarator) as ESTree.VariableDeclaration | null)?.kind !== "const" || declarator.init === null) return null;
  return unwrapExpression(declarator.init);
}

function binding(node: Identifier, sourceCode: SourceCode): TsVariable | null {
  return findVariable(sourceCode.getScope(node), node.name);
}

function member(node: ESTree.MemberExpression, name: string): boolean {
  return !node.optional && !node.computed &&
    node.property.type === "Identifier" && node.property.name === name;
}

/** The installed zod namespace of `z.uuid()`, or of `z.string().uuid()` which zod 3 also accepts. */
function uuidNamespace(initializer: Node, sourceCode: SourceCode, native: NativeTypes): TsVariable | null {
  if (initializer.type !== "CallExpression" || !noArguments(initializer) || initializer.callee.type !== "MemberExpression" || !member(initializer.callee, "uuid")) return null;
  let receiver = unwrapExpression(initializer.callee.object);
  let legacy = false;
  if (receiver.type === "CallExpression" && noArguments(receiver) && receiver.callee.type === "MemberExpression" && member(receiver.callee, "string")) {
    receiver = unwrapExpression(receiver.callee.object);
    legacy = true;
  }
  if (receiver.type !== "Identifier") return null;
  const namespace = binding(receiver, sourceCode);
  const definition = namespace?.defs.length === 1 ? namespace.defs[0] : undefined;
  if (namespace === null || definition === undefined || !isZodNamespaceImport(definition, legacy) || !installedZod(receiver, native))
    return null;
  return namespace;
}

/** `import * as z` or `import { z }` from zod (or zod/v3 for the legacy form), not type-only. */
function isZodNamespaceImport(definition: TsVariable["defs"][number], legacy: boolean): boolean {
  const importDeclaration = definition.parent as ESTree.ImportDeclaration | null | undefined;
  if (definition.type !== "ImportBinding" || importDeclaration?.type !== "ImportDeclaration" ||
    importDeclaration.importKind === "type") return false;
  const module = importDeclaration.source.value;
  if (module !== "zod" && module !== "zod/v4" && !(legacy && module === "zod/v3")) return false;
  const specifier = definition.node;
  return specifier.type === "ImportNamespaceSpecifier" ||
    (specifier.type === "ImportSpecifier" && specifier.importKind !== "type" &&
      specifier.imported.type === "Identifier" && specifier.imported.name === "z");
}

function noArguments(node: ESTree.CallExpression): boolean {
  return !node.optional && node.arguments.length === 0;
}

function installedZod(node: Identifier, native: NativeTypes): boolean {
  const location = native.node(node);
  const symbol = location === undefined ? undefined : native.checker.getSymbolAtLocation(location);
  if (symbol === undefined || (symbol.flags & native.sync.SymbolFlags.Alias) === 0) return false;
  const target = native.checker.getAliasedSymbol(symbol);
  const declarations = target.declarations;
  return declarations.length > 0 && declarations.every(({ path }) =>
    DECLARATION_FILE.test(path) && path.replaceAll("\\", "/").includes("/node_modules/zod/"));
}

function closedSchema(schema: TsVariable): boolean {
  return schema.references.every((reference) => {
    if (reference.isWrite()) return reference.init === true;
    if (reference.isValueReference === false) return true;
    const receiver = outerExpression(reference.identifier);
    const property = parentOf(receiver);
    if (property?.type === "ExportSpecifier" && property.local === receiver) return true;
    if (property?.type !== "MemberExpression" || !member(property, "safeParse") || property.object !== receiver) return false;
    const call = parentOf(property);
    return call?.type === "CallExpression" && call.callee === property && !call.optional &&
      call.arguments.length === 1 && call.arguments[0]?.type !== "SpreadElement";
  });
}

function closedNamespace(namespace: TsVariable, initializer: Node): boolean {
  // Other value uses may replace a factory or obtain a mutable schema prototype.
  // Type-only references cannot mutate the imported runtime namespace.
  return namespace.references.every((reference) => reference.isValueReference === false ||
    (!reference.isWrite() && reference.identifier.range[0] >= initializer.range[0] && reference.identifier.range[1] <= initializer.range[1]));
}
