/**
 * @fileoverview no-runtime-typeof — prefer explicit boundary schemas and discriminated contracts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-runtime-typeof.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { hasLocalValueBinding } from "./_has-local-value-binding.js";

export const NO_RUNTIME_TYPEOF_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Prefer Zod boundary schemas or discriminated unions over runtime typeof checks.",
  rationale: "Representation checks spread value contracts across control flow. Specific boundary schemas and discriminated unions keep validation and the inferred application contract together.",
  remediation: "Parse external structured input with a specific Zod schema, or model owned variants with a discriminated union. Required raw preprocessors, field-independent utilities, arbitrary metadata walkers and framework primitive unions need an exact-code local suppression explaining their contract.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "This is an explicit design policy, not a claim that runtime typeof is invalid JavaScript. It checks runtime UnaryExpression nodes in authored JavaScript and TypeScript, including type predicates and test implementations; TypeScript type queries, strings and comments remain valid.",
    "Equality or inequality against the literal string undefined is allowed only for an identifier without a local value binding, preserving safe probes for absent globals. Erased aliases, interfaces, type-only namespaces, type parameters and expression wrappers do not create runtime bindings. Parameter initializers do not see body-only declarations. Bound parameters, implicit function arguments, imports, local values, member expressions and dynamic comparisons remain checked.",
    "Generated and vendored sources follow shared exclusions. There is no name-based parser exemption or automatic rewrite: inserting a schema, changing a union or moving a transformation can change accepted input, errors and public contracts.",
  ],
  references: [
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-runtime-typeof.ts",
    "https://zod.dev/api#discriminated-unions",
    "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions",
  ],
  examples: [
    {
      id: "runtime-representation-check",
      title: "Replace a representation check with an explicit contract",
      outcome: "match",
      files: [{ path: "src/input.ts", source: 'function parse(value: unknown) { if (typeof value === "object" && value !== null && !Array.isArray(value) && "id" in value && typeof value.id === "string") return { id: value.id }; throw new Error("Expected a record with a text id"); }' }],
      focusPath: "src/input.ts",
      expectedCount: 2,
      public: true,
    },
    {
      id: "specific-boundary-schema",
      title: "Validate consumed fields at their boundary",
      outcome: "no-match",
      files: [{ path: "src/input.ts", source: 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); function parse(value: unknown) { return UserSchema.parse(value); }' }],
      installedDependencies: [{ module: "zod", version: "4.6.7" }],
      focusPath: "src/input.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "untagged-domain-union",
      scenarioId: "domain-variants",
      title: "Give owned variants a domain discriminator",
      outcome: "match",
      files: [{ path: "src/value.ts", source: 'function render(value: string | number) { return typeof value === "string" ? value : value.toString(); }' }],
      focusPath: "src/value.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "discriminated-domain-union",
      scenarioId: "domain-variants",
      title: "Branch on an owned domain discriminator",
      outcome: "no-match",
      files: [{ path: "src/value.ts", source: 'type Value = { kind: "text"; value: string } | { kind: "count"; value: number }; function render(value: Value) { return value.kind === "text" ? value.value : value.value.toString(); }' }],
      focusPath: "src/value.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bound-undefined-check",
      scenarioId: "global-existence",
      title: "Read a declared value directly when checking undefined",
      outcome: "match",
      files: [{ path: "src/environment.ts", source: 'function missing(value: unknown) { return typeof value === "undefined"; }' }],
      focusPath: "src/environment.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "global-existence-probe",
      scenarioId: "global-existence",
      title: "Probe a potentially absent global without reading it",
      outcome: "no-match",
      files: [{ path: "src/environment.ts", source: 'const isServer = typeof document === "undefined";' }],
      focusPath: "src/environment.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "runtime-query",
      scenarioId: "type-query",
      title: "Keep a type query out of executable code",
      outcome: "match",
      files: [{ path: "src/value.ts", source: 'declare const value: { id: string }; const kind = typeof value;' }],
      focusPath: "src/value.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "type-only-query",
      scenarioId: "type-query",
      title: "Preserve the erased TypeScript type query",
      outcome: "no-match",
      files: [{ path: "src/value.ts", source: 'declare const value: { id: string }; type Value = typeof value;' }],
      focusPath: "src/value.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "runtimeTypeof">({
  name: "no-runtime-typeof",
  documentation: NO_RUNTIME_TYPEOF_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_RUNTIME_TYPEOF_DOCUMENTATION.summary },
    schema: [],
    messages: {
      runtimeTypeof: "Replace runtime typeof with a specific Zod schema at the boundary or an explicit discriminated union. Explain required raw-parser, generic-utility or framework primitive checks in a local suppression.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      UnaryExpression(node: TSESTree.UnaryExpression): void {
        if (node.operator !== "typeof") return;
        const probe = outerExpression(node);
        const parent = probe.parent;
        const argument = unwrapExpression(node.argument);
        if (argument.type === AST_NODE_TYPES.Identifier &&
          parent.type === AST_NODE_TYPES.BinaryExpression &&
          ["===", "!==", "==", "!="].includes(parent.operator)) {
          const other = unwrapExpression(parent.left === probe ? parent.right : parent.left);
          if (other.type === AST_NODE_TYPES.Literal && other.value === "undefined" &&
            !hasLocalValueBinding(context.sourceCode, argument, context.languageOptions.sourceType)) return;
        }
        context.report({ node, messageId: "runtimeTypeof" });
      },
    };
  },
});
