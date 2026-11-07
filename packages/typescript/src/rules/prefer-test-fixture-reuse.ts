/**
 * @fileoverview prefer-test-fixture-reuse — reuse a requested test fixture instead of constructing another instance of its class.
 *
 * Port of the 18.x `prefer-test-fixture-reuse` rule. Same algorithm;
 * non-test and generated files are skipped in `before()`, and parents are read
 * with `parentOf()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsDefinition, type TsVariable } from "../types.js";
import { directArgumentCall, forEachAstChild, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "prefer-test-fixture-reuse";

type Identifier = Extract<Node, { type: "Identifier" }>;
type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type FixtureConstructors = ReadonlyMap<string, TsVariable>;
interface FixtureExtension {
  readonly receiver: Node;
  readonly declarations: ESTree.ObjectExpression;
}
const MAX_DEPTH = 8;
const FRAMEWORKS: ReadonlySet<string> = new Set(["vitest", "@playwright/test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "concurrent", "sequential"]);

function stableBinding(source: SourceCode, identifier: Identifier): TsVariable | null {
  const variable = findVariable(source.getScope(identifier), identifier.name);
  if (variable?.defs.length !== 1 || variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
  return variable;
}

/** The initializer of a `const` declarator that ends before `before`. */
function earlierConstInit(declaration: Node | undefined, before: number): ESTree.Expression | null {
  if (declaration?.type !== "VariableDeclarator" || (parentOf(declaration) as ESTree.VariableDeclaration).kind !== "const" ||
      declaration.range[1] >= before) return null;
  return declaration.init;
}

/** The import declaration of a value (not `import type`) import binding. */
function valueImport(definition: TsDefinition): ESTree.ImportDeclaration | null {
  if (definition.type !== "ImportBinding" || definition.parent?.type !== "ImportDeclaration" || definition.parent.importKind === "type" ||
      (definition.node.type === "ImportSpecifier" && definition.node.importKind === "type")) return null;
  return definition.parent;
}

function constructorBinding(source: SourceCode, node: Node, depth = 0): TsVariable | null {
  node = unwrapExpression(node);
  if (node.type !== "Identifier" || depth >= MAX_DEPTH) return null;
  const variable = stableBinding(source, node);
  const definition = variable?.defs[0];
  if (variable === null || definition === undefined) return null;
  if (definition.type === "ClassName" || valueImport(definition) !== null) return variable;
  const init = earlierConstInit(definition.node, node.range[0]);
  return init === null ? null : constructorBinding(source, init, depth + 1);
}

function fixtureApi(source: SourceCode, expression: Node, depth = 0): FixtureConstructors | null {
  const node = unwrapExpression(expression);
  if (node.type !== "Identifier" || depth >= MAX_DEPTH) return null;
  const variable = stableBinding(source, node);
  const definition = variable?.defs[0];
  if (variable === null || definition === undefined) return null;
  if (importedFixtureApi(variable)) return new Map();
  const extension = fixtureExtension(definition.node, node.range[0]);
  if (extension === null || !fixtureApiStable(variable)) return null;
  const inherited = fixtureApi(source, extension.receiver, depth + 1);
  return inherited === null ? null : fixtureConstructors(source, extension.declarations, inherited);
}

function importedFixtureApi(variable: TsVariable): boolean {
  const [definition] = variable.defs;
  const declaration = definition === undefined ? null : valueImport(definition);
  if (declaration === null || !FRAMEWORKS.has(declaration.source.value) || definition?.node.type !== "ImportSpecifier") return false;
  const name = importSpecifierName(definition.node);
  return name === "test" || name === "it";
}

function fixtureExtension(declaration: Node, before: number): FixtureExtension | null {
  const init = earlierConstInit(declaration, before);
  if (init === null) return null;
  const initial = unwrapExpression(init);
  if (initial.type !== "CallExpression" || initial.optional || initial.arguments.length !== 1 ||
      initial.callee.type !== "MemberExpression" || initial.callee.optional ||
      getPropertyName(initial.callee) !== "extend") return null;
  const declarations = initial.arguments[0];
  if (declarations?.type !== "ObjectExpression" || declarations.properties.some(property => property.type !== "Property" || property.computed || property.kind !== "init")) return null;
  return { receiver: initial.callee.object, declarations };
}

function fixtureApiStable(variable: TsVariable): boolean {
  return !variable.references.some(reference => {
    if (reference.isWrite() || reference.isTypeReference && !reference.isValueReference) return false;
    let use: Node = reference.identifier;
    let parent = parentOf(use);
    while (parent?.type === "MemberExpression" && parent.object === use) {
      use = parent;
      parent = parentOf(use);
    }
    return parent?.type !== "CallExpression" || parent.callee !== use;
  });
}

function fixtureConstructors(source: SourceCode, declarations: ESTree.ObjectExpression, inherited: FixtureConstructors): FixtureConstructors {
  const result = new Map(inherited);
  for (const property of declarations.properties) {
    if (property.type !== "Property" || property.computed || (property.value as Node).type === "AssignmentPattern") continue;
    const name = getPropertyName(property);
    if (name === null || property.value.type === "TSEmptyBodyFunctionExpression") continue;
    const constructor = fixtureConstructor(source, property.value);
    if (constructor === null) result.delete(name);
    else result.set(name, constructor);
  }
  return result;
}

function fixtureConstructor(source: SourceCode, value: Node): TsVariable | null {
  value = unwrapExpression(value);
  if (value.type !== "ArrowFunctionExpression" && value.type !== "FunctionExpression") return newConstructor(source, value);
  const use = value.params[1];
  if (use?.type !== "Identifier") return null;
  const binding = stableBinding(source, use);
  const calls = scopeNodes(value.body as Node, source).filter(node => node.type === "CallExpression").filter((node) =>
    !node.optional && node.arguments.length === 1 &&
    node.callee.type === "Identifier" && stableBinding(source, node.callee) === binding);
  if (calls.length !== 1 || binding === null) return null;
  const argument = calls[0]?.arguments[0];
  return argument === undefined || argument.type === "SpreadElement" ? null : newConstructor(source, argument);
}

function newConstructor(source: SourceCode, expression: Node): TsVariable | null {
  const value = unwrapExpression(expression);
  if (value.type === "NewExpression") return constructorBinding(source, value.callee);
  if (value.type !== "Identifier") return null;
  const init = earlierConstInit(stableBinding(source, value)?.defs[0]?.node, value.range[0]);
  const initial = init === null ? null : unwrapExpression(init);
  return initial?.type === "NewExpression" ? constructorBinding(source, initial.callee) : null;
}

function scopeNodes(root: Node, source: SourceCode): Node[] {
  const result: Node[] = [];
  const pending = [root];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    result.push(node);
    if (node !== root && (node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression" ||
        node.type === "FunctionDeclaration" || node.type === "ClassDeclaration" || node.type === "ClassExpression")) continue;
    forEachAstChild(node, source.visitorKeys, child => { pending.push(child); });
  }
  return result;
}

function testApiCallee(expression: Node): Node {
  let node = unwrapExpression(expression);
  while (node.type === "MemberExpression" && !node.optional && TEST_MODIFIERS.has(getPropertyName(node) ?? "")) node = unwrapExpression(node.object);
  return node;
}

function requestingFunction(node: Node): FunctionNode | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "ArrowFunctionExpression" || current.type === "FunctionExpression") return current;
    if (current.type === "FunctionDeclaration") return null;
  }
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Reuse a requested test fixture instead of constructing another instance of its class.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { reuseFixture: "This class is already supplied by the requested `{{fixture}}` fixture; reuse it or request a typed factory for independent instances." },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
      },
      NewExpression(node: ESTree.NewExpression): void {
        const functionNode = requestingFunction(node);
        const call = functionNode === null ? null : directArgumentCall(functionNode);
        if (functionNode === null || call === null) return;
        const parameter = functionNode.params[0];
        if (parameter?.type !== "ObjectPattern") return;
        const entries = fixtureApi(context.sourceCode, testApiCallee(call.callee));
        const constructor = constructorBinding(context.sourceCode, node.callee);
        if (entries === null || constructor === null) return;
        for (const property of parameter.properties) {
          if (property.type !== "Property" || property.computed) continue;
          const name = getPropertyName(property);
          if (name !== null && entries.get(name) === constructor) {
            context.report({ node, messageId: "reuseFixture", data: { fixture: name } });
            return;
          }
        }
      },
    };
  },
});
