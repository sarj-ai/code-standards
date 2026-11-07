/**
 * @fileoverview existing-uuid-provider-fix — reuse an already-used UUID provider.
 *
 * Port of the 18.x `_existing-uuid-provider-fix.ts` helper. Oxlint sets absent
 * optional TS fields (`typeParameters`, `returnType`, `typeArguments`,
 * `typeAnnotation`) to `null` where TS-ESTree leaves them `undefined`, and
 * omits `importKind` and `declare` in JS files where TS-ESTree reports
 * `"value"` and `false`. The checks below accept both shapes.
 */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Identifier, Node, SourceCode } from "../types.js";
import { findVariable } from "./static-string.js";

const PACKAGE_STATEMENT_COUNT = 5;
const RECIPE_STATEMENT_COUNT = 4;
const IMPORT_COUNT = 2;
const UUID_TEMPLATE = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";

interface UuidModule {
  provider: ESTree.VariableDeclarator;
  native: ESTree.Function;
  legacy: ESTree.Function;
  imported: ESTree.ImportDeclaration | null;
}

/** Reuse an authored, already-used UUID provider in a closed UUID-only module. */
export function existingUuidProviderFix(
  sourceCode: Readonly<SourceCode>,
  reported: ESTree.CallExpression,
  kind: "package" | "recipe",
): FixFn | null {
  const module = uuidModule(sourceCode, kind);
  if (module === null || module.provider.id.type !== "Identifier") return null;
  const providerName = module.provider.id.name;
  const legacy = returned(module.legacy);
  if (kind === "recipe") {
    if (!isUuidRecipe(sourceCode, legacy, reported)) return null;
    return (fixer) => fixer.replaceText(legacy, `${providerName}()`);
  }
  const imported = module.imported;
  if (
    imported === null ||
    legacy !== reported ||
    legacy.type !== "CallExpression" ||
    legacy.callee.type !== "Identifier" ||
    legacy.arguments.length !== 0 ||
    legacy.optional ||
    legacy.typeArguments != null
  )
    return null;
  const v4 = imported.specifiers.find(
    (specifier) =>
      specifier.type === "ImportSpecifier" &&
      specifier.imported.type === "Identifier" &&
      specifier.imported.name === "v4",
  );
  if (v4?.type !== "ImportSpecifier" || !sameBinding(sourceCode, legacy.callee, v4)) return null;
  const following = sourceCode.getTokenAfter(v4);
  const preceding = sourceCode.getTokenBefore(v4);
  const removal: [number, number] | null =
    following?.value === ","
      ? [
          v4.range[0],
          following.range[1] + (sourceCode.text.slice(following.range[1]).match(/^[ \t]*/u)?.[0].length ?? 0),
        ]
      : preceding?.value === ","
        ? [preceding.range[0], v4.range[1]]
        : null;
  if (removal === null) return null;
  return (fixer) => [
    fixer.replaceText(legacy, `${providerName}()`),
    fixer.removeRange([...removal]),
  ];
}

function uuidModule(sourceCode: Readonly<SourceCode>, kind: "package" | "recipe"): UuidModule | null {
  const statements = sourceCode.ast.body;
  if (
    sourceCode.getAllComments().length > 0 ||
    statements.length !== (kind === "package" ? PACKAGE_STATEMENT_COUNT : RECIPE_STATEMENT_COUNT)
  )
    return null;
  const offset = kind === "package" ? 1 : 0;
  const imported = kind === "package" ? statements[0] : null;
  const declaration = statements[offset];
  const native = statements[offset + 1];
  const legacy = statements[offset + 2];
  const exported = statements[offset + 3];
  if (
    (imported !== null && imported?.type !== "ImportDeclaration") ||
    declaration?.type !== "VariableDeclaration" ||
    declaration.kind !== "const" ||
    declaration.declare === true ||
    declaration.declarations.length !== 1 ||
    native?.type !== "FunctionDeclaration" || !stringFunction(native) ||
    legacy?.type !== "FunctionDeclaration" || !stringFunction(legacy) ||
    exported?.type !== "ExportNamedDeclaration" ||
    exported.specifiers.length !== 0 ||
    exported.source !== null ||
    exported.declaration?.type !== "FunctionDeclaration" || !arrayFunction(exported.declaration)
  )
    return null;
  const provider = declaration.declarations[0];
  if (
    provider === undefined ||
    !nativeProvider(sourceCode, provider) ||
    !providerRead(sourceCode, returned(native), provider) ||
    !exportedReads(sourceCode, returned(exported.declaration), native, legacy, imported)
  )
    return null;
  return { provider, native, legacy, imported };
}

function stringFunction(node: ESTree.Function): boolean {
  return ordinaryFunction(node) && node.returnType?.typeAnnotation.type === "TSStringKeyword";
}

function arrayFunction(node: ESTree.Function): boolean {
  if (!ordinaryFunction(node)) return false;
  const annotation = node.returnType?.typeAnnotation;
  return annotation?.type === "TSArrayType" && annotation.elementType.type === "TSStringKeyword";
}

function ordinaryFunction(node: ESTree.Function): boolean {
  return (
    node.id !== null &&
    node.declare !== true &&
    !node.async &&
    !node.generator &&
    node.typeParameters == null &&
    node.params.length === 0 &&
    node.body !== null &&
    node.body.body.length === 1 &&
    node.body.body[0]?.type === "ReturnStatement" &&
    node.body.body[0].argument !== null
  );
}

function returned(node: ESTree.Function): ESTree.Expression {
  const statement = node.body?.body[0];
  if (statement?.type !== "ReturnStatement" || statement.argument === null)
    throw new Error("Expected the already-validated sole return statement");
  return statement.argument;
}

function nativeProvider(sourceCode: Readonly<SourceCode>, node: ESTree.VariableDeclarator): boolean {
  if (node.id.type !== "Identifier" || node.id.typeAnnotation != null) return false;
  const call = node.init;
  if (
    call?.type !== "CallExpression" ||
    call.optional ||
    call.typeArguments != null ||
    call.arguments.length !== 1 ||
    call.callee.type !== "MemberExpression" ||
    !member(call.callee, "bind") ||
    call.callee.object.type !== "MemberExpression" ||
    !member(call.callee.object, "randomUUID")
  )
    return false;
  const receiver = call.callee.object.object;
  const argument = call.arguments[0];
  return (
    receiver.type === "Identifier" &&
    receiver.name === "crypto" &&
    argument?.type === "Identifier" &&
    argument.name === "crypto" &&
    (findVariable(sourceCode.getScope(receiver), "crypto")?.defs.length ?? 0) === 0 &&
    (findVariable(sourceCode.getScope(argument), "crypto")?.defs.length ?? 0) === 0
  );
}

function member(node: ESTree.MemberExpression, property: string): boolean {
  return !node.computed && !node.optional && node.property.type === "Identifier" && node.property.name === property;
}

function providerRead(sourceCode: Readonly<SourceCode>, node: Node, declaration: Node): boolean {
  return (
    node.type === "CallExpression" &&
    !node.optional &&
    node.typeArguments == null &&
    node.arguments.length === 0 &&
    node.callee.type === "Identifier" &&
    sameBinding(sourceCode, node.callee, declaration)
  );
}

function sameBinding(sourceCode: Readonly<SourceCode>, read: Identifier, declaration: Node): boolean {
  const binding = sourceCode.getDeclaredVariables(declaration).find((variable) => variable.name === read.name);
  return binding?.defs.length === 1 && findVariable(sourceCode.getScope(read), read.name) === binding;
}

function exportedReads(
  sourceCode: Readonly<SourceCode>,
  node: Node,
  native: ESTree.Function,
  legacy: ESTree.Function,
  imported: ESTree.ImportDeclaration | null,
): boolean {
  if (node.type !== "ArrayExpression" || node.elements.length !== (imported === null ? IMPORT_COUNT : IMPORT_COUNT + 1))
    return false;
  const [first, second, nil] = node.elements;
  if (
    first === null ||
    first === undefined ||
    second === null ||
    second === undefined ||
    !providerRead(sourceCode, first, native) ||
    !providerRead(sourceCode, second, legacy)
  )
    return false;
  if (imported === null) return true;
  if (
    (imported.importKind ?? "value") !== "value" ||
    imported.source.value !== "uuid" ||
    imported.attributes.length !== 0 ||
    imported.specifiers.length !== IMPORT_COUNT ||
    nil?.type !== "Identifier"
  )
    return false;
  const specifiers = imported.specifiers;
  if (
    !specifiers.every(
      (specifier) =>
        specifier.type === "ImportSpecifier" &&
        (specifier.importKind ?? "value") === "value" &&
        specifier.imported.type === "Identifier" &&
        (specifier.imported.name === "v4" || specifier.imported.name === "NIL"),
    )
  )
    return false;
  const nilImport = specifiers.find(
    (specifier) =>
      specifier.type === "ImportSpecifier" &&
      specifier.imported.type === "Identifier" &&
      specifier.imported.name === "NIL",
  );
  return nilImport !== undefined && sameBinding(sourceCode, nil, nilImport);
}

function isUuidRecipe(sourceCode: Readonly<SourceCode>, node: ESTree.Expression, reported: ESTree.CallExpression): boolean {
  if (
    node.type !== "CallExpression" ||
    node.optional ||
    node.typeArguments != null ||
    node.callee.type !== "MemberExpression" ||
    !member(node.callee, "replace") ||
    node.callee.object.type !== "Literal" ||
    node.callee.object.value !== UUID_TEMPLATE ||
    node.arguments.length !== IMPORT_COUNT
  )
    return false;
  const [pattern, callback] = node.arguments;
  if (
    pattern?.type !== "Literal" ||
    !("regex" in pattern) ||
    pattern.regex === undefined ||
    pattern.regex.pattern !== "[xy]" ||
    pattern.regex.flags !== "g" ||
    callback?.type !== "ArrowFunctionExpression" ||
    callback.async ||
    callback.typeParameters != null ||
    callback.returnType != null ||
    callback.params.length !== 1 ||
    callback.params[0]?.type !== "Identifier" ||
    callback.params[0].typeAnnotation != null ||
    callback.params[0].optional ||
    callback.body.type !== "BlockStatement" ||
    callback.body.body.length !== IMPORT_COUNT
  )
    return false;
  const parameter = callback.params[0].name;
  const [digit, result] = callback.body.body;
  if (
    digit?.type !== "VariableDeclaration" ||
    digit.kind !== "const" ||
    digit.declare === true ||
    digit.declarations.length !== 1 ||
    result?.type !== "ReturnStatement" ||
    result.argument === null
  )
    return false;
  const variable = digit.declarations[0];
  if (
    variable?.id.type !== "Identifier" ||
    variable.id.name !== "uuidDigit" ||
    variable.id.typeAnnotation != null ||
    variable.init === null
  )
    return false;
  const signature = (expression: Node): string =>
    sourceCode
      .getTokens(expression)
      .map((token) => (token.value === '"x"' ? "'x'" : token.value))
      .join(" ");
  return (
    signature(variable.init) === "Math . random ( ) * 16 | 0" &&
    signature(result.argument) ===
      `( ${parameter} === 'x' ? uuidDigit : ( uuidDigit & 3 ) | 8 ) . toString ( 16 )` &&
    variable.init.range[0] <= reported.range[0] &&
    variable.init.range[1] >= reported.range[1]
  );
}
