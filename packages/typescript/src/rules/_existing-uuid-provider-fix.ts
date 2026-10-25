/**
 * @fileoverview _existing-uuid-provider-fix — reuse an already-used UUID provider.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

const PACKAGE_STATEMENT_COUNT = 5;
const RECIPE_STATEMENT_COUNT = 4;
const IMPORT_COUNT = 2;
const UUID_TEMPLATE = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";

interface UuidModule {
  provider: TSESTree.VariableDeclarator;
  native: TSESTree.FunctionDeclaration;
  legacy: TSESTree.FunctionDeclaration;
  imported: TSESTree.ImportDeclaration | null;
}

/** Reuse an authored, already-used UUID provider in a closed UUID-only module. */
export function existingUuidProviderFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  reported: TSESTree.CallExpression,
  kind: "package" | "recipe",
): TSESLint.ReportFixFunction | null {
  const module = uuidModule(sourceCode, kind);
  if (module === null || module.provider.id.type !== AST_NODE_TYPES.Identifier)
    return null;
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
    legacy.type !== AST_NODE_TYPES.CallExpression ||
    legacy.callee.type !== AST_NODE_TYPES.Identifier ||
    legacy.arguments.length !== 0 ||
    legacy.optional ||
    legacy.typeArguments !== undefined
  )
    return null;
  const v4 = imported.specifiers.find(
    (specifier) =>
      specifier.type === AST_NODE_TYPES.ImportSpecifier &&
      specifier.imported.type === AST_NODE_TYPES.Identifier &&
      specifier.imported.name === "v4",
  );
  if (
    v4?.type !== AST_NODE_TYPES.ImportSpecifier ||
    !sameBinding(sourceCode, legacy.callee, v4)
  )
    return null;
  const following = sourceCode.getTokenAfter(v4);
  const preceding = sourceCode.getTokenBefore(v4);
  const removal: [number, number] | null =
    following?.value === ","
      ? [
          v4.range[0],
          following.range[1] +
            (sourceCode.text.slice(following.range[1]).match(/^[ \t]*/u)?.[0]
              .length ?? 0),
        ]
      : preceding?.value === ","
        ? [preceding.range[0], v4.range[1]]
        : null;
  if (removal === null) return null;
  return (fixer) => [
    fixer.replaceText(legacy, `${providerName}()`),
    fixer.removeRange(removal),
  ];
}

function uuidModule(
  sourceCode: Readonly<TSESLint.SourceCode>,
  kind: "package" | "recipe",
): UuidModule | null {
  const statements = sourceCode.ast.body;
  if (
    sourceCode.getAllComments().length > 0 ||
    statements.length !==
      (kind === "package" ? PACKAGE_STATEMENT_COUNT : RECIPE_STATEMENT_COUNT)
  )
    return null;
  const offset = kind === "package" ? 1 : 0;
  const imported = kind === "package" ? statements[0] : null;
  const declaration = statements[offset];
  const native = statements[offset + 1];
  const legacy = statements[offset + 2];
  const exported = statements[offset + 3];
  if (
    (imported !== null &&
      imported?.type !== AST_NODE_TYPES.ImportDeclaration) ||
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.kind !== "const" ||
    declaration.declare ||
    declaration.declarations.length !== 1 ||
    !stringFunction(native) ||
    !stringFunction(legacy) ||
    exported?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    exported.specifiers.length !== 0 ||
    exported.source !== null ||
    !arrayFunction(exported.declaration)
  )
    return null;
  const provider = declaration.declarations[0];
  if (
    provider === undefined ||
    !nativeProvider(sourceCode, provider) ||
    !providerRead(sourceCode, returned(native), provider) ||
    !exportedReads(
      sourceCode,
      returned(exported.declaration),
      native,
      legacy,
      imported,
    )
  )
    return null;
  return { provider, native, legacy, imported };
}

function stringFunction(
  node: TSESTree.Node | null | undefined,
): node is TSESTree.FunctionDeclaration {
  return (
    ordinaryFunction(node) &&
    node.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSStringKeyword
  );
}

function arrayFunction(
  node: TSESTree.Node | null | undefined,
): node is TSESTree.FunctionDeclaration {
  if (!ordinaryFunction(node)) return false;
  const annotation = node.returnType?.typeAnnotation;
  return (
    annotation?.type === AST_NODE_TYPES.TSArrayType &&
    annotation.elementType.type === AST_NODE_TYPES.TSStringKeyword
  );
}

function ordinaryFunction(
  node: TSESTree.Node | null | undefined,
): node is TSESTree.FunctionDeclaration {
  return (
    node?.type === AST_NODE_TYPES.FunctionDeclaration &&
    node.id !== null &&
    !node.declare &&
    !node.async &&
    !node.generator &&
    node.typeParameters === undefined &&
    node.params.length === 0 &&
    node.body.body.length === 1 &&
    node.body.body[0]?.type === AST_NODE_TYPES.ReturnStatement &&
    node.body.body[0].argument !== null
  );
}

function returned(node: TSESTree.FunctionDeclaration): TSESTree.Expression {
  const statement = node.body.body[0];
  if (
    statement?.type !== AST_NODE_TYPES.ReturnStatement ||
    statement.argument === null
  )
    throw new Error("Expected the already-validated sole return statement");
  return statement.argument;
}

function nativeProvider(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.VariableDeclarator,
): boolean {
  if (
    node.id.type !== AST_NODE_TYPES.Identifier ||
    node.id.typeAnnotation !== undefined
  )
    return false;
  const call = node.init;
  if (
    call?.type !== AST_NODE_TYPES.CallExpression ||
    call.optional ||
    call.typeArguments !== undefined ||
    call.arguments.length !== 1 ||
    !member(call.callee, "bind") ||
    !member(call.callee.object, "randomUUID")
  )
    return false;
  const receiver = call.callee.object.object;
  const argument = call.arguments[0];
  return (
    receiver.type === AST_NODE_TYPES.Identifier &&
    receiver.name === "crypto" &&
    argument?.type === AST_NODE_TYPES.Identifier &&
    argument.name === "crypto" &&
    (ASTUtils.findVariable(sourceCode.getScope(receiver), "crypto")?.defs
      .length ?? 0) === 0 &&
    (ASTUtils.findVariable(sourceCode.getScope(argument), "crypto")?.defs
      .length ?? 0) === 0
  );
}

function member(
  node: TSESTree.Node,
  property: string,
): node is TSESTree.MemberExpression {
  return (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    !node.optional &&
    node.property.type === AST_NODE_TYPES.Identifier &&
    node.property.name === property
  );
}

function providerRead(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
  declaration: TSESTree.Node,
): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    !node.optional &&
    node.typeArguments === undefined &&
    node.arguments.length === 0 &&
    node.callee.type === AST_NODE_TYPES.Identifier &&
    sameBinding(sourceCode, node.callee, declaration)
  );
}

function sameBinding(
  sourceCode: Readonly<TSESLint.SourceCode>,
  read: TSESTree.Identifier,
  declaration: TSESTree.Node,
): boolean {
  const binding = sourceCode
    .getDeclaredVariables(declaration)
    .find((variable) => variable.name === read.name);
  return (
    binding?.defs.length === 1 &&
    ASTUtils.findVariable(sourceCode.getScope(read), read.name) === binding
  );
}

function exportedReads(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
  native: TSESTree.FunctionDeclaration,
  legacy: TSESTree.FunctionDeclaration,
  imported: TSESTree.ImportDeclaration | null,
): boolean {
  if (
    node.type !== AST_NODE_TYPES.ArrayExpression ||
    node.elements.length !==
      (imported === null ? IMPORT_COUNT : IMPORT_COUNT + 1)
  )
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
    imported.importKind !== "value" ||
    imported.source.value !== "uuid" ||
    imported.attributes.length !== 0 ||
    imported.specifiers.length !== IMPORT_COUNT ||
    nil?.type !== AST_NODE_TYPES.Identifier
  )
    return false;
  const specifiers = imported.specifiers;
  if (
    !specifiers.every(
      (specifier) =>
        specifier.type === AST_NODE_TYPES.ImportSpecifier &&
        specifier.importKind === "value" &&
        specifier.imported.type === AST_NODE_TYPES.Identifier &&
        (specifier.imported.name === "v4" || specifier.imported.name === "NIL"),
    )
  )
    return false;
  const nilImport = specifiers.find(
    (specifier) =>
      specifier.type === AST_NODE_TYPES.ImportSpecifier &&
      specifier.imported.type === AST_NODE_TYPES.Identifier &&
      specifier.imported.name === "NIL",
  );
  return nilImport !== undefined && sameBinding(sourceCode, nil, nilImport);
}

function isUuidRecipe(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Expression,
  reported: TSESTree.CallExpression,
): boolean {
  if (
    node.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.typeArguments !== undefined ||
    !member(node.callee, "replace") ||
    node.callee.object.type !== AST_NODE_TYPES.Literal ||
    node.callee.object.value !== UUID_TEMPLATE ||
    node.arguments.length !== IMPORT_COUNT
  )
    return false;
  const [pattern, callback] = node.arguments;
  if (
    pattern?.type !== AST_NODE_TYPES.Literal ||
    !("regex" in pattern) ||
    pattern.regex.pattern !== "[xy]" ||
    pattern.regex.flags !== "g" ||
    callback?.type !== AST_NODE_TYPES.ArrowFunctionExpression ||
    callback.async ||
    callback.typeParameters !== undefined ||
    callback.returnType !== undefined ||
    callback.params.length !== 1 ||
    callback.params[0]?.type !== AST_NODE_TYPES.Identifier ||
    callback.params[0].typeAnnotation !== undefined ||
    callback.params[0].optional ||
    callback.body.type !== AST_NODE_TYPES.BlockStatement ||
    callback.body.body.length !== IMPORT_COUNT
  )
    return false;
  const parameter = callback.params[0].name;
  const [digit, result] = callback.body.body;
  if (
    digit?.type !== AST_NODE_TYPES.VariableDeclaration ||
    digit.kind !== "const" ||
    digit.declare ||
    digit.declarations.length !== 1 ||
    result?.type !== AST_NODE_TYPES.ReturnStatement ||
    result.argument === null
  )
    return false;
  const variable = digit.declarations[0];
  if (
    variable?.id.type !== AST_NODE_TYPES.Identifier ||
    variable.id.name !== "uuidDigit" ||
    variable.id.typeAnnotation !== undefined ||
    variable.init === null
  )
    return false;
  const signature = (expression: TSESTree.Node): string =>
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
