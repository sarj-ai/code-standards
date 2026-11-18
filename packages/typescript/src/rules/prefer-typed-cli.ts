/**
 * @fileoverview prefer-typed-cli — Declare Node CLI arguments with a typed parsing contract.
 */

import { defineRule, tsReference, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableConstInitializer, stableValueBinding, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

const NAME = "prefer-typed-cli";
const PARSING_METHODS: ReadonlySet<string> = new Set(["parse", "safeParse", "parseAsync", "safeParseAsync"]);
const ARRAY_READS = new WeakMap<ESTree.Program, WeakMap<TsVariable, boolean>>();

function processImport(input: Node, source: SourceCode): string | null {
  if (input.type !== "Identifier") return null;
  const binding = findVariable(source.getScope(input), input.name);
  const definition = binding?.defs[0]?.node;
  const declaration = definition === undefined ? null : parentOf(definition);
  if (binding === null || binding.defs.length !== 1 ||
    declaration?.type !== "ImportDeclaration" || declaration.importKind === "type" ||
    !["process", "node:process"].includes(declaration.source.value) || !stableValueBinding(binding)) return null;
  if (definition?.type === "ImportSpecifier" && definition.importKind !== "type") return importSpecifierName(definition);
  return definition?.type === "ImportDefaultSpecifier" || definition?.type === "ImportNamespaceSpecifier" ? "default" : null;
}

function processValue(node: Node, source: SourceCode): boolean {
  if (node.type !== "Identifier") return false;
  return processImport(node, source) === "default" ||
    node.name === "process" && !findVariable(source.getScope(node), node.name)?.defs.length;
}

function integer(node: Node | undefined): number | null {
  return node?.type === "Literal" && typeof node.value === "number" && Number.isSafeInteger(node.value) && node.value >= 0 ? node.value : null;
}

function rawArrayUse(input: Node, source: SourceCode, depth: number): boolean {
  const value = outerExpression(input);
  const parent = parentOf(value);
  if (parent?.type === "VariableDeclarator" && parent.init === value && parent.id.type === "Identifier") {
    const binding = findVariable(source.getScope(parent.id), parent.id.name);
    return binding !== null && parentOf(parent)?.type === "VariableDeclaration" &&
      (parentOf(parent) as ESTree.VariableDeclaration).kind === "const" && stableValueBinding(binding) &&
      arrayReads(binding, source, depth + 1);
  }
  if (parent?.type !== "MemberExpression" || parent.object !== value || parent.optional || writtenMember(parent)) return false;
  if (parent.computed && integer(parent.property) !== null) return true;
  const method = getPropertyName(parent);
  if (method === "length") return true;
  const callee = outerExpression(parent);
  const call = parentOf(callee);
  if (call?.type !== "CallExpression" || call.optional || call.callee !== callee) return false;
  if (method === "slice") return call.arguments.length <= 2 && call.arguments.every(argument => integer(argument) !== null);
  if (method === "at") return call.arguments.length === 1 && integer(call.arguments[0]) !== null;
  return ["includes", "indexOf"].includes(method ?? "") && call.arguments.length === 1 && staticString(call.arguments[0]) !== null;
}

function arrayReads(binding: TsVariable, source: SourceCode, depth = 0): boolean {
  if (depth >= 12) return false;
  let values = ARRAY_READS.get(source.ast);
  if (values === undefined) {
    values = new WeakMap();
    ARRAY_READS.set(source.ast, values);
  }
  const known = values.get(binding);
  if (known !== undefined) return known;
  values.set(binding, false);
  const safe = stableValueBinding(binding) && binding.references.every(reference =>
    !reference.isRead() || typeOnlyReference(reference) || rawArrayUse(reference.identifier, source, depth));
  values.set(binding, safe);
  return safe;
}

function argvOffset(input: Node, source: SourceCode, depth = 0): number | null {
  if (depth >= 12) return null;
  const node = unwrapExpression(input);
  if (node.type === "Identifier") {
    if (processImport(node, source) === "argv") {
      const binding = findVariable(source.getScope(node), node.name);
      return binding !== null && arrayReads(binding, source) ? 0 : null;
    }
    const binding = stableConstInitializer(source, node);
    if (binding === null) return null;
    const offset = argvOffset(binding.value, source, depth + 1);
    return offset !== null && arrayReads(binding.variable, source) ? offset : null;
  }
  if (node.type === "MemberExpression" && !node.optional && getPropertyName(node) === "argv" && processValue(node.object, source)) return 0;
  if (node.type !== "CallExpression" || node.optional || node.arguments.length !== 1 ||
    node.callee.type !== "MemberExpression" || node.callee.optional || getPropertyName(node.callee) !== "slice") return null;
  const offset = argvOffset(node.callee.object, source, depth + 1);
  const start = integer(node.arguments[0]);
  return offset === null || start === null ? null : offset + start;
}

function namespaceStable(source: SourceCode): boolean {
  if (hasIdentifierNamed(source, "eval") || hasIdentifierNamed(source, "Function")) return false;
  return source.scopeManager.scopes.every(scope => scope.references.every(reference => {
    if (typeOnlyReference(tsReference(reference))) return true;
    const node = reference.identifier;
    if (["globalThis", "global", "window", "self"].includes(node.name) && !findVariable(source.getScope(node), node.name)?.defs.length) {
      const value = outerExpression(node);
      const member = parentOf(value);
      return member?.type === "MemberExpression" && member.object === value &&
        getPropertyName(member) !== null && getPropertyName(member) !== "process";
    }
    if (!processValue(node, source)) return true;
    const value = outerExpression(node);
    const member = parentOf(value);
    return member?.type === "MemberExpression" && member.object === value && getPropertyName(member) !== null &&
      (getPropertyName(member) !== "argv" || !writtenMember(member) && rawArrayUse(member, source, 0));
  }));
}

function parsingArgument(input: Node): boolean {
  let value = outerExpression(input);
  for (let parent = parentOf(value); parent?.type === "LogicalExpression" && parent.left === value &&
    (parent.operator === "??" || parent.operator === "||"); parent = parentOf(value)) value = outerExpression(parent);
  const call = parentOf(value);
  if (call?.type !== "CallExpression" || call.optional || call.arguments[0] !== value ||
    call.callee.type !== "MemberExpression" || call.callee.optional) return false;
  const method = getPropertyName(call.callee);
  return PARSING_METHODS.has(method ?? "");
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: 'Declare Node CLI arguments with a typed parsing contract.', url: docsUrl(NAME) },
    schema: [],
    messages: { preferTypedCli: 'Declare Node CLI arguments with a typed parsing contract.' },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text) ||
          (!hasIdentifierNamed(context.sourceCode, "process") && !context.sourceCode.ast.body.some(statement =>
            statement.type === "ImportDeclaration" && ["node:process", "process"].includes(statement.source.value))) ||
          !namespaceStable(context.sourceCode)) return false;
        return undefined;
      },
      MemberExpression(node) {
        if (node.optional || !node.computed || writtenMember(node)) return;
        const offset = argvOffset(node.object, context.sourceCode);
        const index = integer(node.property);
        if (offset !== null && index !== null && offset + index >= 2 && !parsingArgument(node))
          context.report({ node, messageId: "preferTypedCli" });
      },
      CallExpression(node) {
        if (node.optional || node.callee.type !== "MemberExpression" || node.callee.optional) return;
        const offset = argvOffset(node.callee.object, context.sourceCode);
        if (offset === null || node.arguments.length !== 1 || parsingArgument(node)) return;
        const method = getPropertyName(node.callee);
        const index = integer(node.arguments[0]);
        const option = staticString(node.arguments[0]);
        if (method === "at" && index !== null && offset + index >= 2 ||
          ["includes", "indexOf"].includes(method ?? "") && option?.startsWith("-") === true)
          context.report({ node, messageId: "preferTypedCli" });
      },
    };
  },
});
