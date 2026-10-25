/**
 * @fileoverview _owned-sql-projection-fix — expand a closed owned literal SQL projection.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

const IDENTIFIER = '"[A-Za-z_][A-Za-z0-9_]{0,62}"';
const INTEGER = "[0-9]{1,9}";
const SPACE = "[ \\t]*";
const QUERY_PATTERN = new RegExp(
  `${SPACE}SELECT[ \\t]+(?<star>\\*)[ \\t]+FROM[ \\t]+` +
    `\\(${SPACE}VALUES[ \\t]+\\(${SPACE}(?<values>${INTEGER}(?:${SPACE},${SPACE}${INTEGER}){0,7})` +
    `${SPACE}\\)${SPACE}\\)[ \\t]+AS[ \\t]+(?<alias>${IDENTIFIER})${SPACE}` +
    `\\(${SPACE}(?<labels>${IDENTIFIER}(?:${SPACE},${SPACE}${IDENTIFIER}){0,7})${SPACE}\\)` +
    `${SPACE};?${SPACE}$`,
  "iu",
);
const ASCII_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/u;
const ASCII_TEXT = /^\p{ASCII}*$/u;
const QUERY_LIMIT = 2048;

interface Projection {
  readonly offset: number;
  readonly replacement: string;
}

interface Owner {
  readonly imported: TSESTree.ImportSpecifier;
  readonly declaration: TSESTree.VariableDeclaration;
  readonly variable: TSESTree.VariableDeclarator;
  readonly constructor: TSESTree.Identifier;
  readonly receivers: readonly TSESTree.Identifier[];
  readonly literal: TSESTree.StringLiteral;
}

/** Expand only a complete literal relation consumed by a fresh default pg Client. */
export function ownedSqlProjectionFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
  original: string,
): TSESLint.ReportFixFunction | null {
  if (
    node.type !== AST_NODE_TYPES.Literal ||
    typeof node.value !== "string" ||
    sourceCode.getAllComments().length !== 0 ||
    sourceCode.ast.body.length !== 2
  )
    return null;
  const raw = sourceCode.getText(node);
  if (
    !raw.startsWith("'") ||
    !raw.endsWith("'") ||
    /['\\\r\n]/u.test(raw.slice(1, -1)) ||
    !ASCII_TEXT.test(raw) ||
    raw.slice(1, -1) !== original ||
    node.value !== original
  )
    return null;
  const owner = ownedLiteral(sourceCode);
  const projection = literalProjection(original);
  if (
    owner === null ||
    owner.literal !== node ||
    !ownedBindings(sourceCode, owner) ||
    projection === null
  )
    return null;
  const offset = node.range[0] + 1 + projection.offset;
  return (fixer) =>
    fixer.replaceTextRange([offset, offset + 1], projection.replacement);
}

function literalProjection(query: string): Projection | null {
  if (query.length > QUERY_LIMIT) return null;
  const matched = QUERY_PATTERN.exec(query);
  const { alias, values, labels } = matched?.groups ?? {};
  if (
    matched === null ||
    matched[0] !== query ||
    alias === undefined ||
    values === undefined ||
    labels === undefined
  )
    return null;
  const names = labels.split(",").map((part) => part.trim());
  if (names.length !== values.split(",").length || new Set(names).size !== names.length)
    return null;
  return {
    offset: query.indexOf("*"),
    replacement: names.map((name) => `${alias}.${name}`).join(", "),
  };
}

function ownedLiteral(sourceCode: Readonly<TSESLint.SourceCode>): Owner | null {
  const [imported, exported] = sourceCode.ast.body;
  if (
    imported?.type !== AST_NODE_TYPES.ImportDeclaration ||
    imported.importKind !== "value" ||
    imported.source.value !== "pg" ||
    imported.specifiers.length !== 1 ||
    imported.attributes.length !== 0 ||
    exported?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    exported.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration ||
    exported.specifiers.length !== 0 ||
    exported.source !== null
  )
    return null;
  const specifier = imported.specifiers[0];
  if (
    specifier?.type !== AST_NODE_TYPES.ImportSpecifier ||
    specifier.importKind !== "value" ||
    specifier.imported.type !== AST_NODE_TYPES.Identifier ||
    specifier.imported.name !== "Client" ||
    specifier.local.name !== "Client" ||
    sourceCode.getText(specifier) !== "Client"
  )
    return null;
  const owner = exported.declaration;
  if (!plainOwner(owner)) return null;
  const [declaration, attempted] = owner.body.body;
  if (
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.kind !== "const" ||
    declaration.declare ||
    declaration.declarations.length !== 1 ||
    attempted?.type !== AST_NODE_TYPES.TryStatement ||
    attempted.handler !== null ||
    attempted.block.body.length !== 2 ||
    attempted.finalizer?.body.length !== 1
  )
    return null;
  const variable = declaration.declarations[0];
  const constructor = defaultClient(variable, owner.id?.name);
  if (variable === undefined || constructor === null || variable.id.type !== AST_NODE_TYPES.Identifier)
    return null;
  const [connected, returned] = attempted.block.body;
  const connection = awaitedMethod(connected, variable.id.name, "connect");
  const ended = awaitedMethod(attempted.finalizer.body[0], variable.id.name, "end");
  const query = returnedQuery(returned, variable.id.name);
  if (connection === null || ended === null || query === null) return null;
  return {
    imported: specifier,
    declaration,
    variable,
    constructor,
    receivers: [connection, query.receiver, ended],
    literal: query.literal,
  };
}

function plainOwner(owner: TSESTree.FunctionDeclaration): boolean {
  return (
    owner.async &&
    !owner.declare &&
    !owner.generator &&
    owner.id !== null &&
    owner.id.name !== "Client" &&
    ASCII_NAME.test(owner.id.name) &&
    owner.params.length === 0 &&
    owner.typeParameters === undefined &&
    owner.returnType === undefined &&
    owner.body.body.length === 2
  );
}

function defaultClient(
  variable: TSESTree.VariableDeclarator | undefined,
  owner: string | undefined,
): TSESTree.Identifier | null {
  if (
    variable?.id.type !== AST_NODE_TYPES.Identifier ||
    variable.id.typeAnnotation !== undefined ||
    !ASCII_NAME.test(variable.id.name) ||
    variable.id.name === "Client" ||
    variable.id.name === owner ||
    variable.init?.type !== AST_NODE_TYPES.NewExpression ||
    variable.init.typeArguments !== undefined ||
    variable.init.arguments.length !== 0 ||
    variable.init.callee.type !== AST_NODE_TYPES.Identifier ||
    variable.init.callee.name !== "Client"
  )
    return null;
  return variable.init.callee;
}

function methodReceiver(
  node: TSESTree.Node,
  receiver: string,
  method: string,
): TSESTree.Identifier | null {
  if (
    node.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.typeArguments !== undefined ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.optional ||
    node.callee.computed ||
    node.callee.property.type !== AST_NODE_TYPES.Identifier ||
    node.callee.property.name !== method ||
    node.callee.object.type !== AST_NODE_TYPES.Identifier ||
    node.callee.object.name !== receiver
  )
    return null;
  return node.callee.object;
}

function awaitedMethod(
  node: TSESTree.Statement | undefined,
  receiver: string,
  method: string,
): TSESTree.Identifier | null {
  if (
    node?.type !== AST_NODE_TYPES.ExpressionStatement ||
    node.expression.type !== AST_NODE_TYPES.AwaitExpression ||
    node.expression.argument.type !== AST_NODE_TYPES.CallExpression ||
    node.expression.argument.arguments.length !== 0
  )
    return null;
  return methodReceiver(node.expression.argument, receiver, method);
}

function returnedQuery(
  node: TSESTree.Statement | undefined,
  receiver: string,
): {
  readonly receiver: TSESTree.Identifier;
  readonly literal: TSESTree.StringLiteral;
} | null {
  if (
    node?.type !== AST_NODE_TYPES.ReturnStatement ||
    node.argument?.type !== AST_NODE_TYPES.MemberExpression ||
    node.argument.optional ||
    node.argument.computed ||
    node.argument.property.type !== AST_NODE_TYPES.Identifier ||
    node.argument.property.name !== "rows" ||
    node.argument.object.type !== AST_NODE_TYPES.AwaitExpression ||
    node.argument.object.argument.type !== AST_NODE_TYPES.CallExpression ||
    node.argument.object.argument.arguments.length !== 1
  )
    return null;
  const call = node.argument.object.argument;
  const binding = methodReceiver(call, receiver, "query");
  const literal = call.arguments[0];
  if (binding === null || literal?.type !== AST_NODE_TYPES.Literal || typeof literal.value !== "string")
    return null;
  return { receiver: binding, literal };
}

function ownedBindings(
  sourceCode: Readonly<TSESLint.SourceCode>,
  owner: Owner,
): boolean {
  const imported = ASTUtils.findVariable(sourceCode.getScope(owner.constructor), "Client");
  const binding = sourceCode.getDeclaredVariables(owner.declaration)[0];
  return (
    imported?.defs.length === 1 &&
    imported.defs[0]?.node === owner.imported &&
    imported.references.every((reference) => reference.identifier === owner.constructor) &&
    binding !== undefined &&
    binding.defs.length === 1 &&
    binding.defs[0]?.node === owner.variable &&
    binding.references.every(
      (reference) => reference.identifier === owner.variable.id ||
        owner.receivers.some((receiver) => receiver === reference.identifier),
    ) &&
    owner.receivers.every(
      (receiver) => ASTUtils.findVariable(sourceCode.getScope(receiver), receiver.name) === binding,
    )
  );
}
