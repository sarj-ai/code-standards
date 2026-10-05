/**
 * @fileoverview no-zod-native-enum — `z.nativeEnum` exists to wrap a TypeScript `enum`, which `no-enum` already bans.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-zod-native-enum.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { resolveVariable } from "./_scope.js";

type MessageIds = "nativeEnum" | "enumOfTsEnum";
type Options = readonly [];

export const NO_ZOD_NATIVE_ENUM_DOCUMENTATION = {
  summary:
    'Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum(["a", "b"])` with a string-literal union instead.',
  rationale:
    "The project prefers literal-first schema definitions. nativeEnum also accepts plain enum-like objects, so this is an explicit declaration policy, not proof that every call duplicates a TypeScript enum's runtime object.",
  remediation:
    "Pass string literals directly to `z.enum` and derive the TypeScript type with `z.infer`.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Zod calls are identified through imports from zod, its subpaths, or @hono/zod-openapi; local shadows are excluded. z.enum over an imported enum or re-exported Zod wrapper is not resolved across modules.",
    "Migration is manual: replacing an enum-like object with a value array changes the public schema.enum keys and can affect consumers.",
  ],
  examples: [
    {
      id: "zod-literal-enum",
      title: "Declare string values directly in Zod",
      outcome: "no-match",
      files: [
        {
          path: "src/status.ts",
          source:
            'import { z } from "zod"; const S = z.enum(["active", "inactive"]);',
        },
      ],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "zod-native-enum",
      title: "Do not wrap a TypeScript enum",
      outcome: "match",
      files: [
        {
          path: "src/status.ts",
          source:
            'import { z } from "zod"; const S = z.nativeEnum({ Active: "active", Inactive: "inactive" });',
        },
      ],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const IGNORE_PATTERNS: readonly RegExp[] = [
  /[\\/]generated[\\/]/,
  /\.gen\.tsx?$/,
  /\.generated\.tsx?$/,
  /\.d\.ts$/,
];

function isIgnoredFile(filename: string, sourceText: string): boolean {
  if (IGNORE_PATTERNS.some((re) => re.test(filename))) {
    return true;
  }
  return /@generated\b/.test(sourceText.slice(0, 1024));
}

/** `zod`, `zod/v4`, `zod/mini`, `@hono/zod-openapi`, `@/lib/zod`, ... */
function isZodModule(source: string): boolean {
  return (
    source === "zod" ||
    source.startsWith("zod/") ||
    source === "@hono/zod-openapi"
  );
}

/** Unwraps `x as const` / `x satisfies T` / `(x)` down to the inner expression. */
function unwrap(node: ESTree.Expression): ESTree.Expression {
  if (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression") {
    return unwrap(node.expression);
  }
  return node;
}

export default createRule<Options, MessageIds>({
  name: "no-zod-native-enum",
  documentation: NO_ZOD_NATIVE_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        'Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum(["a", "b"])` with a string-literal union instead.',
    },
    schema: [],
    messages: {
      nativeEnum:
        '`z.nativeEnum()` exists to wrap a TypeScript `enum`, which `no-enum` bans. Use `z.enum(["a", "b"])` and derive the union with `z.infer<typeof Schema>`.',
      enumOfTsEnum:
        '`z.enum()` is being passed the TypeScript enum `{{name}}`, which `no-enum` bans. Pass a string-literal array instead: `z.enum(["a", "b"])`.',
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (isIgnoredFile(sourceOrigin(context).filename, sourceCode.getText())) {
      return {};
    }
    // A test that covers `z.nativeEnum` must call it; see @fileoverview.
    if (isTestFile(sourceOrigin(context).filename)) {
      return {};
    }

    const zodImportedBindings = new Map<Variable, string>();
    const zodNamespaceBindings = new Set<Variable>();

    function isZodMemberCall(
      node: ESTree.CallExpression,
      api: string,
    ): boolean {
      const callee = node.callee;
      if (
        callee.type === "MemberExpression" &&
        callee.object.type === "Identifier" &&
        ((callee.property.type === "Identifier" &&
          !callee.computed &&
          callee.property.name === api) ||
          (callee.computed &&
            callee.property.type === "Literal" &&
            callee.property.value === api))
      ) {
        const binding = resolveVariable(sourceCode, callee.object);
        return binding !== null && zodNamespaceBindings.has(binding);
      }
      if (callee.type === "Identifier") {
        const binding = resolveVariable(sourceCode, callee);
        return binding !== null && zodImportedBindings.get(binding) === api;
      }
      return false;
    }

    function registerImport(
      spec: ESTree.ImportDeclaration["specifiers"][number],
    ): void {
      if (spec.type === "ImportSpecifier" && spec.importKind === "type") return;
      const binding = resolveVariable(sourceCode, spec.local);
      if (binding === null) return;
      if (
        spec.type === "ImportNamespaceSpecifier" ||
        spec.type === "ImportDefaultSpecifier"
      ) {
        zodNamespaceBindings.add(binding);
        return;
      }
      const imported =
        spec.imported.type === "Identifier"
          ? spec.imported.name
          : spec.imported.value;
      if (imported === "z") zodNamespaceBindings.add(binding);
      if (spec.imported.type === "Identifier")
        zodImportedBindings.set(binding, spec.imported.name);
    }

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (node.importKind === "type" || !isZodModule(node.source.value)) {
          return;
        }
        for (const spec of node.specifiers) registerImport(spec);
      },

      CallExpression(node: ESTree.CallExpression): void {
        if (isZodMemberCall(node, "nativeEnum")) {
          context.report({
            node,
            messageId: "nativeEnum",
          });
          return;
        }

        if (!isZodMemberCall(node, "enum")) {
          return;
        }
        const argument = node.arguments[0];
        if (argument === undefined || argument.type === "SpreadElement") {
          return;
        }
        const arg = unwrap(argument);
        if (arg.type !== "Identifier") return;
        const isEnum =
          resolveVariable(sourceCode, arg)?.defs.some(
            (definition) => definition.node.type === "TSEnumDeclaration",
          ) === true;
        if (isEnum) {
          context.report({
            node,
            messageId: "enumOfTsEnum",
            data: { name: arg.name },
          });
        }
      },
    };
  },
});
