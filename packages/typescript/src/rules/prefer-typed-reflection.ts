/**
 * @fileoverview prefer-typed-reflection — Prefer typed access when Reflect.get or Reflect.apply discards a known contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-typed-reflection.test.ts
 */

import { getTypeServices } from "./_eslint-rule.js";


import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { stableConstInitializer, typeOnlyReference, writtenMember } from "./_stable-value-binding.js";

export const PREFER_TYPED_REFLECTION_DOCUMENTATION = {
  summary:
    "Prefer typed access when Reflect.get or Reflect.apply discards a known contract.",
  rationale:
    "Reflect.get and Reflect.apply can accept property or argument mistakes that normal typed access catches.",
  remediation:
    "Use direct typed property access or call the typed function, preserving receivers and evaluation semantics.",
  category: "maintainability",
  requiresTypeInformation: true,
  references: [
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reflect-get.ts",
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reflect-apply.ts",
  ],
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Inspects scope-resolved global Reflect.get with a literal key (including no-substitution templates and erased TypeScript wrappers) on a closed object type, and Reflect.apply with a known call signature and a literal argument array or stable, unmodified const tuple. Stable local Reflect aliases are resolved.",
    "Dynamic keys, open dictionaries, unknown/any/generic targets, explicit Reflect.get receivers, mutated/escaping aliases, and unknown argument arrays are excluded. Expanded aliases and tuple containers remain manual. Deliberate proxy or metaprogramming calls need a local suppression. Automatic fixes cover comment-free nonoptional Reflect.get calls with a known existing property on an object. Immediate calls/tags, missing keys and Reflect.apply remain manual to preserve receiver and argument contracts.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            'declare const shipment: { status: string };\nconst status = Reflect.get(shipment, "status");',
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "declare const shipment: { status: string };\nconst status = shipment.status;",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = Reflect.get(target, \"id\");" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = (target)[\"id\"];" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
    {"id": "apply-tuple-before", "scenarioId": "apply-tuple", "title": "Keep the callable contract with a stable tuple — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare function lookup(id: string): string; const args: [string] = [\"u1\"]; Reflect.apply(lookup, undefined, args);"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "apply-tuple-after", "scenarioId": "apply-tuple", "title": "Keep the callable contract with a stable tuple — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare function lookup(id: string): string; const args: [string] = [\"u1\"]; lookup(...args);"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "reflect-alias-before", "scenarioId": "reflect-alias", "title": "Keep the target contract through an alias — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare const target: { id: string }; const reflection = Reflect; const id = reflection.get(target, \"id\");"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "reflect-alias-after", "scenarioId": "reflect-alias", "title": "Keep the target contract through an alias — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare const target: { id: string }; const id = target.id;"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;

function knownType(type: ts.Type): boolean {
  if (type.isUnion()) return type.types.every(knownType);
  return (
    (type.flags &
      (ts.TypeFlags.Any |
        ts.TypeFlags.Unknown |
        ts.TypeFlags.TypeParameter |
        ts.TypeFlags.Never)) ===
    0
  );
}

export default createRule<[], "avoid">({
  name: "prefer-typed-reflection",
  documentation: PREFER_TYPED_REFLECTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: PREFER_TYPED_REFLECTION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "Reflection discards this known contract. Use typed property access or a typed call; preserve the invocation receiver and property semantics.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = getTypeServices(context);
    if (!services.program) return {};
    const checker = services.program.getTypeChecker();
    const safeAliasUses = (variable: TSESLint.Scope.Variable, seen = new Set<TSESLint.Scope.Variable>()): boolean => {
      if (seen.has(variable)) return false;
      seen.add(variable);
      return variable.references.every(reference => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = value.parent;
        if (parent == null) return false;
        if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value)
          return !writtenMember(parent);
        if (parent.type !== AST_NODE_TYPES.VariableDeclarator || parent.init !== value ||
          parent.id.type !== AST_NODE_TYPES.Identifier || parent.parent.kind !== "const") return false;
        const identifier = parent.id;
        const alias = context.sourceCode.getDeclaredVariables(parent).find(binding => binding.identifiers.includes(identifier));
        return alias !== undefined && safeAliasUses(alias, new Set(seen));
      });
    };
    const directReflect = (node: TSESTree.Node): boolean =>
      globalName(node, "Reflect") ||
      (node.type === AST_NODE_TYPES.MemberExpression &&
        ASTUtils.getPropertyName(node) === "Reflect" &&
        globalName(node.object, "globalThis"));
    let globalsAreStable: boolean | undefined;
    const isReflect = (node: TSESTree.Node, seen = new Set<TSESTree.Node>()): boolean => {
      node = unwrapExpression(node);
      if (directReflect(node)) return true;
      if (node.type !== AST_NODE_TYPES.Identifier || seen.has(node)) return false;
      seen.add(node);
      const local = stableConstInitializer(context.sourceCode, node);
      if (local === null || !safeAliasUses(local.variable) || !stableReflectGlobals()) return false;
      return isReflect(local.value, seen);
    };

    const stableReflectGlobals = (): boolean => {
      if (globalsAreStable !== undefined) return globalsAreStable;
      const safeUse = (node: TSESTree.Node): boolean => {
        const value = outerExpression(node);
        const parent = value.parent;
        if (parent == null) return false;
        if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value)
          return !writtenMember(parent);
        if (parent.type !== AST_NODE_TYPES.VariableDeclarator || parent.init !== value ||
          parent.id.type !== AST_NODE_TYPES.Identifier || parent.parent.kind !== "const") return false;
        const identifier = parent.id;
        const alias = context.sourceCode.getDeclaredVariables(parent).find(binding => binding.identifiers.includes(identifier));
        return alias !== undefined && safeAliasUses(alias);
      };
      globalsAreStable = context.sourceCode.scopeManager?.scopes.every(scope => scope.references.every(reference => {
        if (typeOnlyReference(reference)) return true;
        const identifier = reference.identifier;
        if (globalName(identifier, "Reflect")) return safeUse(identifier);
        if (!globalName(identifier, "globalThis")) return true;
        const member = outerExpression(identifier).parent;
        if (member == null) return true;
        return member.type !== AST_NODE_TYPES.MemberExpression || ASTUtils.getPropertyName(member) !== "Reflect" ||
          !writtenMember(member) && safeUse(member);
      })) ?? false;
      return globalsAreStable;
    };

    const globalName = (node: TSESTree.Node, name: string): boolean =>
      node.type === AST_NODE_TYPES.Identifier &&
      node.name === name &&
      !ASTUtils.findVariable(context.sourceCode.getScope(node), name)?.defs
        .length;
    const closedObject = (type: ts.Type): boolean => {
      if (type.isUnion()) return type.types.every(closedObject);
      return (
        knownType(type) &&
        type.getProperties().length > 0 &&
        checker.getIndexInfosOfType(type).length === 0
      );
    };
    const inspectGet = (
      node: TSESTree.CallExpression,
      type: ts.Type,
    ): boolean => {
      const key = node.arguments[1] === undefined ? undefined : unwrapExpression(node.arguments[1]);
      return (
        node.arguments.length === 2 &&
        (staticString(key) !== null || (key?.type === AST_NODE_TYPES.Literal && typeof key.value === "number")) &&
        closedObject(type)
      );
    };

    const knownParameter = (parameter: ts.Symbol, call: TSESTree.CallExpression): boolean => {
      const type = checker.getTypeOfSymbolAtLocation(parameter, services.esTreeNodeToTSNodeMap.get(call));
      return knownType(type) && (call.arguments[2]?.type === AST_NODE_TYPES.ArrayExpression ||
        checker.getIndexInfosOfType(type).every(index => knownType(index.type)));
    };
    const inspectApply = (
      node: TSESTree.CallExpression,
      type: ts.Type,
    ): boolean =>
      node.arguments.length === 3 &&
      (node.arguments[2]?.type === AST_NODE_TYPES.ArrayExpression || tupleArguments(node.arguments[2])) &&
      knownType(type) &&
      type
        .getCallSignatures()
        .some(
          (signature) =>
            signature.typeParameters === undefined &&
            signature.parameters.every((parameter) =>
              knownParameter(parameter, node),
            ),
        );
    const tupleArguments = (node: TSESTree.CallExpressionArgument | undefined): boolean => {
      if (node?.type !== AST_NODE_TYPES.Identifier) return false;
      const local = stableConstInitializer(context.sourceCode, node);
      if (local === null) return false;
      const value = unwrapExpression(local.value);
      if (value.type !== AST_NODE_TYPES.ArrayExpression ||
        value.elements.some(element => element === null || element.type === AST_NODE_TYPES.SpreadElement) ||
        !checker.isTupleType(checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node)))) return false;
      return local.variable.references.every(reference => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        const argument = outerExpression(reference.identifier);
        const call = argument.parent;
        if (call == null) return false;
        return !reference.isWrite() && call.type === AST_NODE_TYPES.CallExpression &&
          call.arguments[2] === argument && call.callee.type === AST_NODE_TYPES.MemberExpression &&
          ASTUtils.getPropertyName(call.callee) === "apply" && isReflect(call.callee.object);
      });
    };
    const getReplacement = (node: TSESTree.CallExpression, type: ts.Type, target: TSESTree.Expression): string | null => {
      if (node.optional || node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.optional ||
        context.sourceCode.getCommentsInside(node).length > 0) return null;
      let outer: TSESTree.Node = node;
      while (outer.parent.type === AST_NODE_TYPES.TSAsExpression || outer.parent.type === AST_NODE_TYPES.TSTypeAssertion ||
        outer.parent.type === AST_NODE_TYPES.TSSatisfiesExpression || outer.parent.type === AST_NODE_TYPES.TSNonNullExpression ||
        outer.parent.type === AST_NODE_TYPES.ChainExpression) outer = outer.parent;
      if ((outer.parent.type === AST_NODE_TYPES.UnaryExpression && outer.parent.operator === "delete") ||
        (outer.parent.type === AST_NODE_TYPES.CallExpression && outer.parent.callee === outer) ||
        (outer.parent.type === AST_NODE_TYPES.TaggedTemplateExpression && outer.parent.tag === outer)) return null;
      const writtenKey = node.arguments[1];
      if (writtenKey === undefined || writtenKey.type === AST_NODE_TYPES.SpreadElement) return null;
      const key = unwrapExpression(writtenKey);
      const name = staticString(key) ?? (key.type === AST_NODE_TYPES.Literal && typeof key.value === "number" ? String(key.value) : null);
      const members = type.isUnion() ? type.types : [type];
      if (name === null || !members.every((member) => (member.flags & ts.TypeFlags.Object) !== 0 && checker.getPropertyOfType(member, name) !== undefined)) return null;
      return `(${context.sourceCode.getText(target)})[${context.sourceCode.getText(writtenKey)}]`;
    };
    return {
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          !isReflect(node.callee.object)
        )
          return;
        const method = ASTUtils.getPropertyName(node.callee);
        const target = node.arguments[0];
        if (
          !target ||
          target.type === AST_NODE_TYPES.SpreadElement ||
          (method !== "get" && method !== "apply")
        )
          return;
        const type = checker.getTypeAtLocation(
          services.esTreeNodeToTSNodeMap.get(target),
        );
        if (
          method === "get" ? inspectGet(node, type) : inspectApply(node, type)
        )
          {
            const replacement = method === "get" && directReflect(node.callee.object) ? getReplacement(node, type, target) : null;
            context.report({ node, messageId: "avoid", fix: replacement === null ? null : (fixer) => fixer.replaceText(node, replacement) });
          }
      },
    };
  },
});
