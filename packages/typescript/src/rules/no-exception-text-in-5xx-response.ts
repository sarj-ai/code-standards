/**
 * @fileoverview no-exception-text-in-5xx-response — keep caught exception details out of public server errors.
 *
 * Port of the 18.x `no-exception-text-in-5xx-response` rule. The rule is untyped, so the port
 * covers all of it. `ASTUtils.getStaticValue(node, scope)` is ported in
 * `_get-static-value.ts`.
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { tsReference } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, staticPropertyName } from "../utils/static-string.js";
import { serverActionErrorResults } from "./_server-action-error-results.js";
import { getStaticValue } from "./_get-static-value.js";

const NAME = "no-exception-text-in-5xx-response";

type Variable = TsVariable;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

type Definition = Variable["defs"][number];

function nextResponseLocals(program: ESTree.Program): readonly string[] {
  return program.body.flatMap((statement) =>
    statement.type === "ImportDeclaration" && statement.source.value === "next/server"
      ? statement.specifiers.flatMap((specifier) =>
        specifier.type === "ImportSpecifier" && specifier.imported.type === "Identifier" &&
          specifier.imported.name === "NextResponse" ? [specifier.local.name] : [])
      : []);
}

function isNextResponseImport(definition: Definition): boolean {
  const specifier = definition.node;
  const statement = definition.parent;
  return definition.type === "ImportBinding" && specifier.type === "ImportSpecifier" &&
    specifier.imported.type === "Identifier" && specifier.imported.name === "NextResponse" &&
    statement?.type === "ImportDeclaration" && statement.source.value === "next/server";
}

/** A `typeof x` or `typeof x.y` query names the binding without using its value. */
function insideTypeQuery(node: Node): boolean {
  let typeName: Node = node;
  for (let up = parentOf(typeName); up?.type === "TSQualifiedName"; up = parentOf(typeName)) typeName = up;
  return parentOf(typeName)?.type === "TSTypeQuery";
}

/** Uses that read the binding without letting the object escape. */
function inertUse(parent: Node, value: Node): boolean {
  return (parent.type === "CatchClause" && parent.param === value) ||
    parent.type === "ImportSpecifier" ||
    (parent.type === "MemberExpression" && parent.object === value) ||
    (parent.type === "BinaryExpression" && parent.operator === "instanceof" && parent.left === value) ||
    (parent.type === "UnaryExpression" && parent.operator === "typeof");
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep caught exception messages and stacks out of returned 5xx JSON responses and Server Action results.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      exceptionText: "Caught exception text enters a returned 5xx JSON response. Return a generic public message and retain details in server-side logs.",
      serverActionExceptionText: "Caught exception text enters an exported Server Action result. Return a stable public error and retain details in server-side diagnostics.",
    },
  },
  createOnce(context) {
    let candidates: { readonly node: ESTree.CallExpression; readonly errors: readonly Variable[] }[] = [];
    let changedErrors = new Set<Variable>();
    let stableBindings = new WeakMap<Variable, boolean>();
    let referenceIdentifiers: WeakSet<Node> | undefined;
    let uncertainSerialization = false;
    // Only catch parameters and response factories can matter, so cheap name checks skip scope lookups.
    let catchNames = new Set<string>();
    let responseNames = new Set<string>();

    function valueReference(node: Identifier): boolean {
      referenceIdentifiers ??= new WeakSet(context.sourceCode.scopeManager?.scopes.flatMap((scope) => scope.references
        .filter((reference) => tsReference(reference).isValueReference !== false)
        .map((reference) => reference.identifier as Node)) ?? []);
      return referenceIdentifiers.has(node);
    }

    function binding(identifier: Identifier): Variable | null {
      return findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function stable(variable: Variable): boolean {
      const cached = stableBindings.get(variable);
      if (cached !== undefined) return cached;
      const result = !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
      stableBindings.set(variable, result);
      return result;
    }

    function ambientGlobal(node: Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== "Identifier" || value.name !== "globalThis") return false;
      const variable = binding(value);
      return variable === null || variable.defs.length === 0;
    }

    function caughtValue(node: Node): Variable | null {
      const value = unwrapExpression(node);
      if (value.type !== "Identifier" || !catchNames.has(value.name)) return null;
      const variable = binding(value);
      const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
      const clause = definition?.node;
      return definition?.type === "CatchClause" && clause?.type === "CatchClause" && clause.param?.type === "Identifier" &&
        variable != null && stable(variable)
        ? variable : null;
    }

    function responseFactory(node: Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== "Identifier" || !responseNames.has(value.name)) return false;
      const variable = binding(value);
      if (variable === null) return value.name === "Response";
      const [definition] = variable.defs;
      if (definition === undefined) return value.name === "Response" && stable(variable);
      return variable.defs.length === 1 && isNextResponseImport(definition) && stable(variable);
    }

    function properties(node: Node): ReadonlyMap<string, Node> | null {
      const value = unwrapExpression(node);
      if (value.type !== "ObjectExpression") return null;
      const fields = new Map<string, Node>();
      for (const property of value.properties) {
        if (property.type !== "Property" || property.method || property.kind !== "init") return null;
        const name = staticPropertyName(property, context.sourceCode);
        if (name === null || name === "toJSON" || name === "__proto__") return null;
        fields.set(name, property.value);
      }
      return fields;
    }

    function serverError(node: Node): boolean {
      const field = properties(node)?.get("status");
      const status = field === undefined ? undefined : unwrapExpression(field);
      return status?.type === "Literal" && typeof status.value === "number" &&
        Number.isInteger(status.value) && status.value >= 500 && status.value <= 599;
    }

    function payloadErrors(node: Node): readonly Variable[] {
      const value = unwrapExpression(node);
      switch (value.type) {
        case "ChainExpression":
          return payloadErrors(value.expression);
        case "MemberExpression":
          return exceptionTextErrors(value);
        case "ObjectExpression":
          return [...properties(value)?.values() ?? []].flatMap(payloadErrors);
        case "ArrayExpression":
          return arrayErrors(value);
        case "TemplateLiteral":
          return value.expressions.flatMap(payloadErrors);
        case "ConditionalExpression":
        case "LogicalExpression":
          return branchValues(value).flatMap(payloadErrors);
        case "BinaryExpression":
          return value.operator === "+" ? [...payloadErrors(value.left), ...payloadErrors(value.right)] : [];
        default:
          return [];
      }
    }

    function exceptionTextErrors(member: ESTree.MemberExpression): readonly Variable[] {
      const name = staticPropertyName(member, context.sourceCode);
      const variable = name === "message" || name === "stack" ? caughtValue(member.object) : null;
      return variable === null ? [] : [variable];
    }

    function arrayErrors(array: ESTree.ArrayExpression): readonly Variable[] {
      return array.elements.some((element) => element?.type === "SpreadElement")
        ? [] : array.elements.flatMap((element) => element === null ? [] : payloadErrors(element));
    }

    function branchValues(value: ESTree.ConditionalExpression | ESTree.LogicalExpression): readonly Node[] {
      const sourceCode = context.sourceCode;
      if (value.type === "ConditionalExpression") {
        const test = getStaticValue(unwrapExpression(value.test), sourceCode.getScope(value.test));
        return test === null ? [value.consequent, value.alternate] : [test.value ? value.consequent : value.alternate];
      }
      const left = getStaticValue(unwrapExpression(value.left), sourceCode.getScope(value.left));
      if (left === null) return value.operator === "&&" ? [value.right] : [value.left, value.right];
      const useRight = value.operator === "??" ? left.value == null : value.operator === "&&" ? Boolean(left.value) : !left.value;
      return useRight ? [value.right] : [];
    }

    function directlyReturned(node: Node): boolean {
      let current = node;
      for (let parent = parentOf(current); parent !== null &&
        (parent.type === "AwaitExpression" || parent.type === "ChainExpression" ||
          unwrapExpression(parent) === current); parent = parentOf(current)) {
        current = parent;
      }
      const parent = parentOf(current);
      return parent?.type === "ReturnStatement" ||
        (parent?.type === "ArrowFunctionExpression" && parent.body === current);
    }

    function recordWrite(target: Node): void {
      const value = unwrapExpression(target);
      if (value.type === "ObjectPattern") {
        for (const property of value.properties) recordWrite(property.type === "RestElement" ? property.argument : property.value);
      } else if (value.type === "ArrayPattern") {
        for (const element of value.elements) if (element !== null) recordWrite(element);
      } else if (value.type === "AssignmentPattern") recordWrite(value.left);
      else if (value.type === "RestElement") recordWrite(value.argument);
      else if (value.type === "MemberExpression") recordMemberWrite(value);
    }

    function recordMemberWrite(member: ESTree.MemberExpression): void {
      const name = staticPropertyName(member, context.sourceCode);
      if (responseFactory(member.object) || name === "toJSON" ||
        (ambientGlobal(member.object) && (name === "Response" || member.computed))) {
        uncertainSerialization = true;
      }
      const error = caughtValue(member.object);
      if (error !== null) changedErrors.add(error);
    }

    /** Passing a factory or caught object to another call loses local mutation proof. */
    function escapesToCall(argument: Node): boolean {
      const value = unwrapExpression(argument);
      return responseFactory(value) || ambientGlobal(value) ||
        (value.type === "MemberExpression" && staticPropertyName(value, context.sourceCode) === "prototype");
    }

    return {
      before() {
        const sourceCode = context.sourceCode;
        if (isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        candidates = [];
        changedErrors = new Set();
        stableBindings = new WeakMap();
        referenceIdentifiers = undefined;
        uncertainSerialization = false;
        catchNames = new Set();
        responseNames = new Set(["Response", ...nextResponseLocals(sourceCode.ast)]);
        return undefined;
      },
      CatchClause(node: ESTree.CatchClause): void {
        if (node.param?.type === "Identifier") catchNames.add(node.param.name);
      },
      Identifier(node: ESTree.IdentifierReference): void {
        if ((!catchNames.has(node.name) && !responseNames.has(node.name)) || !valueReference(node) || insideTypeQuery(node)) return;
        const error = caughtValue(node);
        if (error === null && !responseFactory(node)) return;
        const value = outerExpression(node);
        const parent = parentOf(value);
        if (parent === null || inertUse(parent, value)) return;
        // Aliases, storage and unknown consumers can mutate or sanitize this object.
        if (error !== null) changedErrors.add(error);
        else uncertainSerialization = true;
      },
      AssignmentExpression(node: ESTree.AssignmentExpression): void { recordWrite(node.left); },
      UpdateExpression(node: ESTree.UpdateExpression): void { recordWrite(node.argument); },
      UnaryExpression(node: ESTree.UnaryExpression): void { if (node.operator === "delete") recordWrite(node.argument); },
      ForInStatement(node: ESTree.ForInStatement): void { recordWrite(node.left); },
      ForOfStatement(node: ESTree.ForOfStatement): void { recordWrite(node.left); },
      CallExpression(node: ESTree.CallExpression): void {
        if (node.arguments.some(escapesToCall)) uncertainSerialization = true;
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const error = caughtValue(callee.object);
        if (error !== null) changedErrors.add(error);
        if (!responseFactory(callee.object) || staticPropertyName(callee, context.sourceCode) !== "json" ||
          node.arguments.length !== 2 || !directlyReturned(node)) return;
        const [payload, options] = node.arguments;
        if (payload === undefined || options === undefined || !serverError(options)) return;
        const errors = payloadErrors(payload);
        if (errors.length > 0) candidates.push({ node, errors });
      },
      "Program:exit"(): void {
        if (uncertainSerialization) return;
        for (const node of serverActionErrorResults(context.sourceCode)) context.report({ node, messageId: "serverActionExceptionText" });
        for (const candidate of candidates) {
          if (candidate.errors.some((error) => !changedErrors.has(error))) {
            context.report({ node: candidate.node, messageId: "exceptionText" });
          }
        }
      },
    };
  },
});
