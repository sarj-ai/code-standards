/** @fileoverview _owned-sql-projection-fix — expand a closed owned literal SQL projection. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Identifier, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { soleConstDeclarator } from "./_closed-module.js";

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
  readonly imported: ESTree.ImportSpecifier;
  readonly declaration: ESTree.VariableDeclaration;
  readonly variable: ESTree.VariableDeclarator;
  readonly constructor: Identifier;
  readonly receivers: readonly Identifier[];
  readonly literal: ESTree.StringLiteral;
}

/** Expand only a complete literal relation consumed by a fresh default pg Client. */
export function ownedSqlProjectionFix(
  sourceCode: Readonly<SourceCode>,
  node: Node,
  original: string,
): FixFn | null {
  if (
    node.type !== "Literal" ||
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

function ownedLiteral(sourceCode: Readonly<SourceCode>): Owner | null {
  const [imported, exported] = sourceCode.ast.body;
  const specifier = imported?.type === "ImportDeclaration" ? pgClientSpecifier(sourceCode, imported) : null;
  if (
    specifier === null ||
    exported?.type !== "ExportNamedDeclaration" ||
    exported.declaration?.type !== "FunctionDeclaration" ||
    exported.specifiers.length !== 0 ||
    exported.source !== null
  )
    return null;
  const owner = exported.declaration;
  const [declaration, attempted] = plainOwnerBody(owner)?.body ?? [];
  if (
    declaration?.type !== "VariableDeclaration" ||
    attempted?.type !== "TryStatement" ||
    attempted.handler !== null ||
    attempted.block.body.length !== 2 ||
    attempted.finalizer?.body.length !== 1
  )
    return null;
  const variable = soleConstDeclarator(declaration);
  const constructor = defaultClient(variable, owner.id?.name);
  if (variable === null || constructor === null || variable.id.type !== "Identifier")
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

/** The only specifier of a plain `import { Client } from "pg"`. */
function pgClientSpecifier(sourceCode: Readonly<SourceCode>, imported: ESTree.ImportDeclaration): ESTree.ImportSpecifier | null {
  const specifier = imported.specifiers[0];
  if (
    (imported.importKind ?? "value") !== "value" ||
    imported.source.value !== "pg" ||
    imported.specifiers.length !== 1 ||
    imported.attributes.length !== 0 ||
    specifier?.type !== "ImportSpecifier" ||
    (specifier.importKind ?? "value") !== "value" ||
    specifier.imported.type !== "Identifier" ||
    specifier.imported.name !== "Client" ||
    specifier.local.name !== "Client" ||
    sourceCode.getText(specifier) !== "Client"
  )
    return null;
  return specifier;
}

function plainOwnerBody(owner: ESTree.Function): ESTree.FunctionBody | null {
  return (
    owner.async &&
    owner.declare !== true &&
    !owner.generator &&
    owner.id !== null &&
    owner.id.name !== "Client" &&
    ASCII_NAME.test(owner.id.name) &&
    owner.params.length === 0 &&
    !isPresent(owner.typeParameters) &&
    !isPresent(owner.returnType) &&
    owner.body?.body.length === 2
  ) ? owner.body : null;
}

function defaultClient(
  variable: ESTree.VariableDeclarator | null,
  owner: string | undefined,
): Identifier | null {
  if (
    variable?.id.type !== "Identifier" ||
    isPresent(variable.id.typeAnnotation) ||
    !ASCII_NAME.test(variable.id.name) ||
    variable.id.name === "Client" ||
    variable.id.name === owner ||
    variable.init?.type !== "NewExpression" ||
    isPresent(variable.init.typeArguments) ||
    variable.init.arguments.length !== 0 ||
    variable.init.callee.type !== "Identifier" ||
    variable.init.callee.name !== "Client"
  )
    return null;
  return variable.init.callee;
}

function methodReceiver(
  node: Node,
  receiver: string,
  method: string,
): Identifier | null {
  if (
    node.type !== "CallExpression" ||
    node.optional ||
    isPresent(node.typeArguments) ||
    node.callee.type !== "MemberExpression" ||
    node.callee.optional ||
    node.callee.computed ||
    node.callee.property.type !== "Identifier" ||
    node.callee.property.name !== method ||
    node.callee.object.type !== "Identifier" ||
    node.callee.object.name !== receiver
  )
    return null;
  return node.callee.object;
}

function awaitedMethod(
  node: ESTree.Statement | undefined,
  receiver: string,
  method: string,
): Identifier | null {
  if (
    node?.type !== "ExpressionStatement" ||
    node.expression.type !== "AwaitExpression" ||
    node.expression.argument.type !== "CallExpression" ||
    node.expression.argument.arguments.length !== 0
  )
    return null;
  return methodReceiver(node.expression.argument, receiver, method);
}

function returnedQuery(
  node: ESTree.Statement | undefined,
  receiver: string,
): {
  readonly receiver: Identifier;
  readonly literal: ESTree.StringLiteral;
} | null {
  if (
    node?.type !== "ReturnStatement" ||
    node.argument?.type !== "MemberExpression" ||
    node.argument.optional ||
    node.argument.computed ||
    node.argument.property.type !== "Identifier" ||
    node.argument.property.name !== "rows" ||
    node.argument.object.type !== "AwaitExpression" ||
    node.argument.object.argument.type !== "CallExpression" ||
    node.argument.object.argument.arguments.length !== 1
  )
    return null;
  const call = node.argument.object.argument;
  const binding = methodReceiver(call, receiver, "query");
  const literal = call.arguments[0];
  if (binding === null || literal?.type !== "Literal" || typeof literal.value !== "string")
    return null;
  return { receiver: binding, literal };
}

function ownedBindings(
  sourceCode: Readonly<SourceCode>,
  owner: Owner,
): boolean {
  const imported = findVariable(sourceCode.getScope(owner.constructor), "Client");
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
      (receiver) => findVariable(sourceCode.getScope(receiver), receiver.name) === binding,
    )
  );
}
