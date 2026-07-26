/**
 * @fileoverview Disallow `z.nativeEnum(...)` in zod schemas; use
 * `z.enum(["a", "b"])` and derive the type with `z.infer<typeof Schema>`.
 *
 * Rationale — this is the schema-layer sibling of the `no-enum` rule. Zod's
 * `nativeEnum` exists for exactly one purpose: to wrap a TypeScript `enum`,
 * which `no-enum` already bans (enums emit runtime code, have unintuitive
 * numeric defaults, and don't tree-shake). Reaching for `nativeEnum` is
 * therefore either (a) importing a banned construct through the back door, or
 * (b) wrapping an `as const` object, in which case `z.enum` over the value list
 * is the shorter, better-inferring form. Either way the target state is the
 * same string-literal union `no-enum` prescribes, so the two rules point at one
 * destination.
 *
 * Two shapes fire:
 *
 * 1. **`z.nativeEnum(x)`** — always. Autofixable ONLY when the argument is an
 *    inline object literal (optionally `as const`) whose every value is a
 *    string literal: that set is fully known at the call site, so the rewrite
 *    to `z.enum([...])` is mechanical and value-preserving. A numeric member
 *    (`{ A: 1 }`) is NOT fixed — `z.enum` accepts strings only, so rewriting
 *    would silently change the accepted input. A spread, computed key, shorthand
 *    property, method, or an empty object is not fixed either (the member set
 *    isn't statically known, and `z.enum([])` is not a valid schema). An
 *    identifier argument (`z.nativeEnum(Fruits)`) is reported without a fix:
 *    inlining the values at the call site would duplicate the literal set that
 *    the named object exists to own, so the correct edit is a human one.
 *
 * 2. **`z.enum(SomeTsEnum)`** — zod v4 lets `z.enum` take a TS enum directly,
 *    which is `nativeEnum` under a friendlier name and re-opens the same hole.
 *    Detected two ways: lexical resolution of the identifier to a
 *    `TSEnumDeclaration` in the same file, and — when type information is
 *    available — the resolved symbol carrying an enum flag, which also catches
 *    an enum imported from another module. `z.enum(COLORS)` where `COLORS` is a
 *    `readonly string[]` / `as const` array is the prescribed pattern and never
 *    fires.
 *
 * False positives handled: a bare `nativeEnum(...)` call fires only when the
 * name is imported from a zod module, so a same-named local helper is not
 * flagged. Generated files (`*.gen.ts`, `**\/generated/**`, `*.d.ts`, or a
 * `@generated` marker) opt out, matching `no-enum` — codegen from an OpenAPI
 * spec legitimately emits enums and the schemas that wrap them.
 *
 * TEST FILES ARE EXEMPT. Corpus sweep (2220 files across zod / TanStack Query /
 * react-router / swr / zustand, 2026-07): 32 raw hits, 32 of them in test files
 * and 100% false positives. A test that covers `z.nativeEnum` has to CALL
 * `z.nativeEnum` — `zod/packages/zod/src/v3/tests/nativeEnum.test.ts:12`
 * (`const fruitEnum = z.nativeEnum(Fruits)`) is not importing a banned construct
 * through the back door, it is the coverage for the construct. The same applies
 * to any consumer pinning the migration behaviour of a legacy enum schema, and
 * it mirrors the exemption `no-enum` already grants generated code: the rule
 * targets the DECISION to model a domain with an enum, and a fixture makes no
 * such decision.
 */

import {
  ESLintUtils,
  type TSESLint,
  type TSESTree,
  type ParserServicesWithTypeInformation,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

import { isTestFile } from "./_paths.js";

type MessageIds = "nativeEnum" | "enumOfTsEnum";
type Options = readonly [];

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

/**
 * The string values of an object literal whose every property is a plain
 * `key: "literal"` pair, as raw source text (so quote style survives the fix).
 * Returns null when any member is a spread, a computed key, a method, a
 * shorthand, or a non-string value — those sets are not statically rewritable.
 */
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

/**
 * Whether the identifier's resolved symbol is a TypeScript enum, following
 * import aliases. Catches `import { Status } from "./types"; z.enum(Status)`,
 * which lexical resolution alone cannot see.
 */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-zod-native-enum",
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

    function isZodMemberCall(node: TSESTree.CallExpression, api: string): boolean {
      const callee = node.callee;
      if (
        callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
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
      // A bare `nativeEnum(...)` imported from zod cannot be renamed in place —
      // `enum` is a reserved word, so there is no bare callee to rewrite to.
      // Rewriting only the argument would leave a `nativeEnum` call taking an
      // array, so this shape is report-only.
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
        const arg = node.arguments[0];
        if (arg === undefined || arg.type !== AST_NODE_TYPES.Identifier) {
          return;
        }
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
