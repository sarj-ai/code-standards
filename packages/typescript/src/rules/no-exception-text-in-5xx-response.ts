/**
 * @fileoverview no-exception-text-in-5xx-response — keep caught exception details out of public server errors.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-exception-text-in-5xx-response.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { staticPropertyName } from "./_static-string.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Variable = TSESLint.Scope.Variable;
type MessageIds = "exceptionText";

export const NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION = {
  summary: "Keep caught exception messages and stacks out of returned 5xx JSON responses.",
  rationale: "Exception details can contain database, provider, filesystem or credential information that belongs in server-side diagnostics rather than a client response.",
  remediation: "Return a generic public error and retain diagnostic details in server-side logs. Keep intentional public domain errors in their reviewed client-error contract.",
  category: "security",
  defaultLevel: "warning",
  autofix: "none",
  references: ["https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html", "https://nextjs.org/docs/app/api-reference/functions/next-response"],
  limitations: [
    "Only directly returned Response.json calls and named NextResponse imports from next/server, with an explicit literal integer 500–599 status, are inspected.",
    "Caught message/stack fields are followed through literal objects, arrays, interpolation and conditional expressions. Mutable or escaped catch values, shadowed factories and local factory/serializer overrides are excluded.",
    "Client errors, dynamic status codes, aliases, response wrappers, custom sanitizer calls, spreads, uncertain properties or serialization hooks, tests and generated files are excluded. Interprocedural mutations and runtime monkeypatches are not resolved.",
    "A warning requests review; syntax does not prove the exception contains a secret. There is no automatic replacement for an application's public error contract.",
  ],
  examples: [
    {
      id: "generic-server-error",
      title: "Keep internal failure details server-side",
      outcome: "no-match",
      files: [{ path: "src/route.ts", source: "function handle() { try { run(); } catch (error) { return Response.json({ error: 'Internal server error' }, { status: 500 }); } }" }],
      focusPath: "src/route.ts", expectedCount: 0, public: true,
    },
    {
      id: "caught-message-in-server-error",
      title: "Do not return a caught message as a server error",
      outcome: "match",
      files: [{ path: "src/route.ts", source: "function handle() { try { run(); } catch (error) { return Response.json({ error: error instanceof Error ? error.message : 'Internal server error' }, { status: 500 }); } }" }],
      focusPath: "src/route.ts", expectedCount: 1, public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<readonly [], MessageIds>({
  name: "no-exception-text-in-5xx-response",
  documentation: NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      exceptionText: "Caught exception text enters a returned 5xx JSON response. Return a generic public message and retain details in server-side logs.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, sourceCode.text)) return {};

    const candidates: { readonly node: TSESTree.CallExpression; readonly errors: readonly Variable[] }[] = [];
    const changedErrors = new Set<Variable>();
    const stableBindings = new WeakMap<Variable, boolean>();
    const referenceIdentifiers = new WeakSet(sourceCode.scopeManager?.scopes.flatMap((scope) => scope.references.filter((reference) => reference.isValueReference !== false).map((reference) => reference.identifier)) ?? []);
    let uncertainSerialization = false;

    function binding(identifier: TSESTree.Identifier): Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    function stable(variable: Variable): boolean {
      const cached = stableBindings.get(variable);
      if (cached !== undefined) return cached;
      const result = !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
      stableBindings.set(variable, result);
      return result;
    }

    function ambientGlobal(node: TSESTree.Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== AST_NODE_TYPES.Identifier || value.name !== "globalThis") return false;
      const variable = binding(value);
      return variable === null || variable.defs.length === 0;
    }

    function caughtValue(node: TSESTree.Node): Variable | null {
      const value = unwrapExpression(node);
      if (value.type !== AST_NODE_TYPES.Identifier) return null;
      const variable = binding(value);
      const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
      return definition?.type === "CatchClause" && definition.node.param?.type === AST_NODE_TYPES.Identifier &&
        variable !== null && stable(variable)
        ? variable : null;
    }

    function responseFactory(node: TSESTree.Node): boolean {
      const value = unwrapExpression(node);
      if (value.type !== AST_NODE_TYPES.Identifier) return false;
      const variable = binding(value);
      if (value.name === "Response" && (variable === null || variable.defs.length === 0)) {
        return variable === null || stable(variable);
      }
      const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
      return definition?.type === "ImportBinding" && definition.node.type === AST_NODE_TYPES.ImportSpecifier &&
        definition.node.imported.type === AST_NODE_TYPES.Identifier && definition.node.imported.name === "NextResponse" &&
        definition.parent.type === AST_NODE_TYPES.ImportDeclaration && definition.parent.source.value === "next/server" &&
        variable !== null && stable(variable);
    }

    function properties(node: TSESTree.Node): ReadonlyMap<string, TSESTree.Node> | null {
      const value = unwrapExpression(node);
      if (value.type !== AST_NODE_TYPES.ObjectExpression) return null;
      const fields = new Map<string, TSESTree.Node>();
      for (const property of value.properties) {
        if (property.type !== AST_NODE_TYPES.Property || property.method || property.kind !== "init") return null;
        const name = staticPropertyName(property, sourceCode);
        if (name === null || name === "toJSON" || name === "__proto__") return null;
        fields.set(name, property.value);
      }
      return fields;
    }

    function serverError(node: TSESTree.Node): boolean {
      const field = properties(node)?.get("status");
      const status = field === undefined ? undefined : unwrapExpression(field);
      return status?.type === AST_NODE_TYPES.Literal && typeof status.value === "number" &&
        Number.isInteger(status.value) && status.value >= 500 && status.value <= 599;
    }

    function payloadErrors(node: TSESTree.Node): readonly Variable[] {
      const value = unwrapExpression(node);
      switch (value.type) {
        case AST_NODE_TYPES.ChainExpression:
          return payloadErrors(value.expression);
        case AST_NODE_TYPES.MemberExpression: {
          const name = staticPropertyName(value, sourceCode);
          const variable = name === "message" || name === "stack" ? caughtValue(value.object) : null;
          return variable === null ? [] : [variable];
        }
        case AST_NODE_TYPES.ObjectExpression:
          return [...properties(value)?.values() ?? []].flatMap(payloadErrors);
        case AST_NODE_TYPES.ArrayExpression:
          return value.elements.some((element) => element?.type === AST_NODE_TYPES.SpreadElement)
            ? [] : value.elements.flatMap((element) => element === null ? [] : payloadErrors(element));
        case AST_NODE_TYPES.TemplateLiteral:
          return value.expressions.flatMap(payloadErrors);
        case AST_NODE_TYPES.ConditionalExpression:
        case AST_NODE_TYPES.LogicalExpression:
          return branchValues(value).flatMap(payloadErrors);
        case AST_NODE_TYPES.BinaryExpression:
          return value.operator === "+" ? [...payloadErrors(value.left), ...payloadErrors(value.right)] : [];
        default:
          return [];
      }
    }

    function branchValues(value: TSESTree.ConditionalExpression | TSESTree.LogicalExpression): readonly TSESTree.Expression[] {
      if (value.type === AST_NODE_TYPES.ConditionalExpression) {
        const test = ASTUtils.getStaticValue(unwrapExpression(value.test), sourceCode.getScope(value.test));
        return test === null ? [value.consequent, value.alternate] : [test.value ? value.consequent : value.alternate];
      }
      const left = ASTUtils.getStaticValue(unwrapExpression(value.left), sourceCode.getScope(value.left));
      if (left === null) return value.operator === "&&" ? [value.right] : [value.left, value.right];
      const useRight = value.operator === "??" ? left.value == null : value.operator === "&&" ? Boolean(left.value) : !left.value;
      return useRight ? [value.right] : [];
    }

    function directlyReturned(node: TSESTree.Node): boolean {
      let current = node;
      while (current.parent !== undefined &&
        (current.parent.type === AST_NODE_TYPES.AwaitExpression || current.parent.type === AST_NODE_TYPES.ChainExpression ||
          unwrapExpression(current.parent) === current)) {
        current = current.parent;
      }
      return current.parent?.type === AST_NODE_TYPES.ReturnStatement ||
        (current.parent?.type === AST_NODE_TYPES.ArrowFunctionExpression && current.parent.body === current);
    }

    function recordWrite(target: TSESTree.Node): void {
      const value = unwrapExpression(target);
      if (value.type === AST_NODE_TYPES.ObjectPattern) {
        for (const property of value.properties) recordWrite(property.type === AST_NODE_TYPES.RestElement ? property.argument : property.value);
      } else if (value.type === AST_NODE_TYPES.ArrayPattern) {
        for (const element of value.elements) if (element !== null) recordWrite(element);
      } else if (value.type === AST_NODE_TYPES.AssignmentPattern) recordWrite(value.left);
      else if (value.type === AST_NODE_TYPES.RestElement) recordWrite(value.argument);
      if (value.type !== AST_NODE_TYPES.MemberExpression) return;
      if (responseFactory(value.object) || staticPropertyName(value, sourceCode) === "toJSON" ||
        (ambientGlobal(value.object) && (staticPropertyName(value, sourceCode) === "Response" || value.computed))) {
        uncertainSerialization = true;
      }
      const error = caughtValue(value.object);
      if (error !== null) changedErrors.add(error);
    }

    return {
      Identifier(node): void {
        if (!referenceIdentifiers.has(node)) return;
        let typeName: TSESTree.Node = node;
        while (typeName.parent?.type === AST_NODE_TYPES.TSQualifiedName) typeName = typeName.parent;
        if (typeName.parent?.type === AST_NODE_TYPES.TSTypeQuery) return;
        const error = caughtValue(node);
        const factory = error === null && responseFactory(node);
        if (error === null && !factory) return;
        const value = outerExpression(node);
        const parent = value.parent;
        if ((parent.type === AST_NODE_TYPES.CatchClause && parent.param === value) ||
          parent.type === AST_NODE_TYPES.ImportSpecifier ||
          (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value) ||
          (parent.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "instanceof" && parent.left === value) ||
          (parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof")) return;
        // Aliases, storage and unknown consumers can mutate or sanitize this object.
        if (error !== null) changedErrors.add(error);
        else uncertainSerialization = true;
      },
      AssignmentExpression(node): void { recordWrite(node.left); },
      UpdateExpression(node): void { recordWrite(node.argument); },
      UnaryExpression(node): void { if (node.operator === "delete") recordWrite(node.argument); },
      ForInStatement(node): void { recordWrite(node.left); },
      ForOfStatement(node): void { recordWrite(node.left); },
      CallExpression(node): void {
        // Passing a factory or caught object to another call loses local mutation proof.
        for (const argument of node.arguments) {
          const value = unwrapExpression(argument);
          if (responseFactory(value) || ambientGlobal(value) ||
            (value.type === AST_NODE_TYPES.MemberExpression && staticPropertyName(value, sourceCode) === "prototype")) uncertainSerialization = true;
        }
        const callee = unwrapExpression(node.callee);
        if (callee.type === AST_NODE_TYPES.MemberExpression) {
          const error = caughtValue(callee.object);
          if (error !== null) changedErrors.add(error);
        }
        if (callee.type !== AST_NODE_TYPES.MemberExpression || !responseFactory(callee.object) ||
          staticPropertyName(callee, sourceCode) !== "json" || node.arguments.length !== 2 || !directlyReturned(node)) return;
        const [payload, options] = node.arguments;
        if (payload === undefined || options === undefined || !serverError(options)) return;
        const errors = payloadErrors(payload);
        if (errors.length > 0) candidates.push({ node, errors });
      },
      "Program:exit"(): void {
        if (uncertainSerialization) return;
        for (const candidate of candidates) {
          if (candidate.errors.some((error) => !changedErrors.has(error))) {
            context.report({ node: candidate.node, messageId: "exceptionText" });
          }
        }
      },
    };
  },
});
