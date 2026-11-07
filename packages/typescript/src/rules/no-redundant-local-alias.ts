/**
 * @fileoverview no-redundant-local-alias — pass the original local into an object field instead of creating a single-use rename.
 *
 * Port of the 18.x `no-redundant-local-alias` rule. Same algorithm;
 * generated files are skipped and the module-syntax flag is computed in
 * `before()`. Optional fields (`typeAnnotation`, `typeParameters`,
 * `returnType`) are `null` in TypeScript files and absent in JavaScript, so
 * those checks accept both.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type Scope, type SourceCode, type TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

const NAME = "no-redundant-local-alias";

type ReportFix = (fixer: Fixer) => Fix[];

function stableSource(variable: TsVariable, alias: ESTree.VariableDeclarator): boolean {
  const definition = variable.defs[0];
  if (variable.defs.length !== 1 || definition === undefined || variable.references.some(reference => reference.isWrite() && !reference.init)) return false;
  return definition.type === "Parameter" || (
    definition.node.type === "VariableDeclarator" &&
    (parentOf(definition.node) as ESTree.VariableDeclaration).kind === "const" && definition.node.init !== null &&
    definition.node.range[1] < alias.range[0]
  );
}

const PRIMITIVE_PARAMETERS: ReadonlySet<string> = new Set([
  "TSStringKeyword", "TSNumberKeyword", "TSBooleanKeyword",
  "TSBigIntKeyword", "TSSymbolKeyword",
]);

const LINE_ENDING_RE = /\r\n|[\r\n\u2028\u2029]/gu;

type Identifier = Extract<Node, { type: "Identifier" }>;

function closedPrimitiveReturnFix(
  sourceCode: SourceCode,
  node: ESTree.VariableDeclarator,
  property: ESTree.ObjectProperty,
  source: TsVariable,
  target: TsVariable,
): ReportFix | null {
  const statement = parentOf(node) as ESTree.VariableDeclaration;
  const closed = closedOwner(statement);
  if (closed === null || node.id.type !== "Identifier" || node.id.name === "__proto__" || node.init?.type !== "Identifier" ||
    sourceCode.getCommentsInside(closed.owner).length !== 0 || hasIdentifierNamed(sourceCode, "eval")) return null;
  const { owner, body } = closed;
  const parameter = owner.params[0];
  if (parameter?.type !== "Identifier" || !isRequiredPrimitive(parameter) || !returnsOnly(body, property) ||
    !renamesParameter(sourceCode, { parameter, init: node.init, property, source, target }) ||
    !hasUniqueFunctionBinding(sourceCode, owner)) return null;
  const span: readonly [number, number] = [body.range[0] + 1, statement.range[1]];
  const boundaries = sourceCode.text.slice(...span).replace(/[^\r\n\u2028\u2029]/gu, "");
  if (!keepsLineEndings(sourceCode.text, span, boundaries)) return null;
  const key = sourceCode.getText(property.key);
  const value = sourceCode.getText(node.init);
  return fixer => [fixer.replaceTextRange([...span], boundaries), fixer.replaceText(property, `${key}: ${value}`)];
}

/** The alias statement opens a non-generic, untyped-return, single-parameter top-level function of two statements. */
function closedOwner(statement: ESTree.VariableDeclaration): { owner: ESTree.Function & { id: Identifier }; body: ESTree.BlockStatement } | null {
  const body = parentOf(statement);
  if (body?.type !== "BlockStatement") return null;
  const owner = parentOf(body);
  if (owner?.type !== "FunctionDeclaration" || parentOf(owner)?.type !== "Program" || owner.id === null ||
    owner.async || owner.generator || owner.typeParameters != null || owner.returnType != null) return null;
  return owner.params.length === 1 && body.body.length === 2 && body.body[0] === statement ? { owner: owner as ESTree.Function & { id: Identifier }, body } : null;
}

function isRequiredPrimitive(parameter: Identifier): boolean {
  return (parameter as { optional?: boolean }).optional !== true &&
    parameter.typeAnnotation != null && PRIMITIVE_PARAMETERS.has(parameter.typeAnnotation.typeAnnotation.type);
}

/** The parameter and the alias initializer both bind `source`, and neither binding is used as a type. */
function renamesParameter(sourceCode: SourceCode, alias: {
  readonly parameter: Identifier;
  readonly init: Identifier;
  readonly property: ESTree.ObjectProperty;
  readonly source: TsVariable;
  readonly target: TsVariable;
}): boolean {
  const { parameter, init, property, source, target } = alias;
  return findVariable(sourceCode.getScope(parameter), parameter.name) === source &&
    findVariable(sourceCode.getScope(property), init.name) === source &&
    !source.references.some(reference => reference.isTypeReference) && !target.references.some(reference => reference.isTypeReference);
}

/** The second statement returns the object literal whose only member is `property`. */
function returnsOnly(body: ESTree.BlockStatement, property: ESTree.ObjectProperty): boolean {
  const returned = body.body[1];
  const object = parentOf(property);
  return returned?.type === "ReturnStatement" && returned.argument === object &&
    object?.type === "ObjectExpression" && object.properties.length === 1;
}

/** The function name has one value binding, declared only by `owner`, with no type references. */
function hasUniqueFunctionBinding(sourceCode: SourceCode, owner: ESTree.Function & { id: Identifier }): boolean {
  const name = owner.id.name;
  const bindings = sourceCode.getDeclaredVariables(owner).filter(binding => binding.name === name);
  const binding = bindings[0];
  return bindings.length === 1 && binding !== undefined && binding.defs.length === 1 && binding.defs[0]?.node === owner &&
    !tsVariable(binding).references.some(reference => reference.isTypeReference);
}

/** Removing `span` keeps every line ending, including the characters on either side. */
function keepsLineEndings(text: string, span: readonly [number, number], boundaries: string): boolean {
  const neighbor = Math.max(0, span[0] - 1);
  const before = text.slice(neighbor, span[1] + 1).match(LINE_ENDING_RE) ?? [];
  const after = (text.slice(neighbor, span[0]) + boundaries + text.slice(span[1], span[1] + 1)).match(LINE_ENDING_RE) ?? [];
  return before.length === after.length && before.every((ending, index) => ending === after[index]);
}

/** The lone shorthand `{ alias }` object property that is the alias's only read, in the alias's own function. */
function shorthandFieldRead(target: TsVariable, variableScope: Scope): ESTree.ObjectProperty | null {
  const reads = target.references.filter(reference => reference.isRead());
  const read = reads[0];
  if (reads.length !== 1 || read === undefined || target.references.some(reference => reference.isWrite() && !reference.init) ||
    read.from.variableScope !== variableScope) return null;
  const property = parentOf(read.identifier);
  if (property?.type !== "Property" || !property.shorthand || property.value !== read.identifier ||
    parentOf(property)?.type !== "ObjectExpression" || property.computed || property.method || property.kind !== "init") return null;
  return property as ESTree.ObjectProperty;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Pass the original local into an object field instead of creating a single-use rename.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { redundantAlias: "This alias is read only by its matching object field; pass `{{source}}` directly as `{{target}}: {{source}}`." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let hasModuleSyntax = false;
    return {
      before(): boolean | void {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        sourceCode = context.sourceCode;
        hasModuleSyntax = sourceCode.ast.body.some(candidate => candidate.type === "ImportDeclaration" ||
          candidate.type === "ExportNamedDeclaration" || candidate.type === "ExportDefaultDeclaration" ||
          candidate.type === "ExportAllDeclaration");
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        const declaration = parentOf(node) as ESTree.VariableDeclaration;
        if (declaration.kind !== "const" || declaration.declarations.length !== 1 ||
          node.id.type !== "Identifier" || node.id.typeAnnotation != null ||
          node.init?.type !== "Identifier") return;
        const scope = sourceCode.getScope(node);
        if (scope.variableScope.type !== "function") return;
        const target = findVariable(scope, node.id.name);
        const source = findVariable(scope, node.init.name);
        if (target === null || source === null || !stableSource(source, node)) return;
        const property = shorthandFieldRead(target, scope.variableScope);
        if (property === null) return;
        const fix = hasModuleSyntax ? closedPrimitiveReturnFix(sourceCode, node, property, source, target) : null;
        context.report({ node, messageId: "redundantAlias", ...(fix !== null && { fix }), data: { source: node.init.name, target: node.id.name } });
      },
    };
  },
});
