/**
 * @fileoverview no-zod-native-enum — `z.nativeEnum` exists to wrap a TypeScript `enum`, which `no-enum` already bans.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-zod-native-enum.test.ts
 */

import {
  ESLintUtils,
  type TSESLint,
  type TSESTree,
  type ParserServicesWithTypeInformation,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "nativeEnum" | "enumOfTsEnum";
type Options = readonly [];

export const noZodNativeEnumDocumentation = {
  summary:
    "Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum([\"a\", \"b\"])` with a string-literal union instead.",
  rationale: "Wrapping a TypeScript enum preserves its emitted runtime object and duplicates the schema's value definition across two constructs.",
  remediation: "Pass string literals directly to `z.enum` and derive the TypeScript type with `z.infer`.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Automatic fixes are limited to inline object literals whose unique values are all string literals."],
  examples: [
    {
      id: "zod-literal-enum",
      title: "Declare string values directly in Zod",
      outcome: "no-match",
      files: [{ path: "src/status.ts", source: "import { z } from \"zod\"; const S = z.enum([\"active\", \"inactive\"]);" }],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "zod-native-enum",
      title: "Do not wrap a TypeScript enum",
      outcome: "match",
      files: [{ path: "src/status.ts", source: "import { z } from \"zod\"; const S = z.nativeEnum({ Active: \"active\", Inactive: \"inactive\" });" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
      fixedFiles: [{ path: "src/status.ts", source: "import { z } from \"zod\"; const S = z.enum([\"active\", \"inactive\"]);" }],
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
  return /(^|[/@-])zod([/-]|$)/.test(source);
}

/** Unwraps `x as const` / `x satisfies T` / `(x)` down to the inner expression. */
function unwrap(node: TSESTree.Expression): TSESTree.Expression {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression
  ) {
    return unwrap(node.expression);
  }
  return node;
}

/** Returns unique string-literal values when the object can be safely rewritten. */
function stringValueTexts(
  node: TSESTree.ObjectExpression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): string[] | null {
  const texts: string[] = [];
  for (const prop of node.properties) {
    if (prop.type !== AST_NODE_TYPES.Property) {
      return null;
    }
    if (prop.computed || prop.shorthand || prop.method || prop.kind !== "init") {
      return null;
    }
    const value = prop.value;
    if (
      value.type !== AST_NODE_TYPES.Literal ||
      typeof value.value !== "string"
    ) {
      return null;
    }
    const text = sourceCode.getText(value);
    if (!texts.includes(text)) {
      texts.push(text);
    }
  }
  return texts.length > 0 ? texts : null;
}

/** Resolves an identifier to a `TSEnumDeclaration` declared in this file. */
function resolvesToLocalEnum(
  node: TSESTree.Identifier,
  scope: TSESLint.Scope.Scope,
): boolean {
  let current: TSESLint.Scope.Scope | null = scope;
  while (current !== null) {
    const variable = current.variables.find((v) => v.name === node.name);
    if (variable !== undefined) {
      return variable.defs.some(
        (def) => def.node.type === AST_NODE_TYPES.TSEnumDeclaration,
      );
    }
    current = current.upper;
  }
  return false;
}

const ENUM_SYMBOL_FLAGS =
  ts.SymbolFlags.RegularEnum | ts.SymbolFlags.ConstEnum | ts.SymbolFlags.Enum;

function resolvesToImportedEnum(
  node: TSESTree.Identifier,
  services: ParserServicesWithTypeInformation,
): boolean {
  const checker = services.program.getTypeChecker();
  const tsNode = services.esTreeNodeToTSNodeMap.get(node);
  let symbol = checker.getSymbolAtLocation(tsNode);
  if (symbol === undefined) {
    return false;
  }
  if ((symbol.flags & ts.SymbolFlags.Alias) !== 0) {
    symbol = checker.getAliasedSymbol(symbol);
  }
  return (symbol.flags & ENUM_SYMBOL_FLAGS) !== 0;
}

export default createRule<Options, MessageIds>({
  name: "no-zod-native-enum",
  documentation: noZodNativeEnumDocumentation,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum([\"a\", \"b\"])` with a string-literal union instead.",
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
    if (isIgnoredFile(context.filename, sourceCode.getText())) {
      return {};
    }
    // A test that covers `z.nativeEnum` must call it; see @fileoverview.
    if (isTestFile(context.filename)) {
      return {};
    }

    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }

    /** Local names imported from a zod module, e.g. `nativeEnum`, `enum_`. */
    const zodImportedNames = new Map<string, string>();
    const zodNamespaces = new Set<string>();

    function isZodMemberCall(node: TSESTree.CallExpression, api: string): boolean {
      const callee = node.callee;
      if (
        callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.object.type === AST_NODE_TYPES.Identifier &&
        zodNamespaces.has(callee.object.name) &&
        callee.property.type === AST_NODE_TYPES.Identifier
      ) {
        return callee.property.name === api;
      }
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return zodImportedNames.get(callee.name) === api;
      }
      return false;
    }

    function buildFix(
      node: TSESTree.CallExpression,
    ): TSESLint.ReportFixFunction | null {
      const callee = node.callee;
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.property.type !== AST_NODE_TYPES.Identifier
      ) {
        return null;
      }
      const arg = node.arguments[0];
      if (
        arg === undefined ||
        node.arguments.length !== 1 ||
        arg.type === AST_NODE_TYPES.SpreadElement
      ) {
        return null;
      }
      const inner = unwrap(arg);
      if (inner.type !== AST_NODE_TYPES.ObjectExpression) {
        return null;
      }
      const values = stringValueTexts(inner, sourceCode);
      if (values === null) {
        return null;
      }
      const property = callee.property;
      const replacementArg = `[${values.join(", ")}]`;
      return (fixer) => [
        fixer.replaceText(property, "enum"),
        fixer.replaceText(arg, replacementArg),
      ];
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) {
          return;
        }
        for (const spec of node.specifiers) {
          if (
            spec.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            spec.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (spec.type === AST_NODE_TYPES.ImportSpecifier &&
              (spec.imported.type === AST_NODE_TYPES.Identifier
                ? spec.imported.name === "z"
                : spec.imported.value === "z"))
          ) {
            zodNamespaces.add(spec.local.name);
          }
          if (
            spec.type === AST_NODE_TYPES.ImportSpecifier &&
            spec.imported.type === AST_NODE_TYPES.Identifier
          ) {
            zodImportedNames.set(spec.local.name, spec.imported.name);
          }
        }
      },

      CallExpression(node: TSESTree.CallExpression): void {
        if (isZodMemberCall(node, "nativeEnum")) {
          const fix = buildFix(node);
          context.report({
            node,
            messageId: "nativeEnum",
            ...(fix === null ? {} : { fix }),
          });
          return;
        }

        if (!isZodMemberCall(node, "enum")) {
          return;
        }
        const argument = node.arguments[0];
        if (argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement) {
          return;
        }
        const arg = unwrap(argument);
        if (arg.type !== AST_NODE_TYPES.Identifier) return;
        const isEnum =
          resolvesToLocalEnum(arg, sourceCode.getScope(arg)) ||
          (services !== null && resolvesToImportedEnum(arg, services));
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
