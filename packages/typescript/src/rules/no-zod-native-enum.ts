/**
 * @fileoverview no-zod-native-enum — `z.nativeEnum` exists to wrap a TypeScript `enum`, which `no-enum` already bans.
 *
 * Port of the 18.x `no-zod-native-enum` rule. Untyped except for one
 * check: whether a `z.enum(identifier)` argument that is not a local enum
 * resolves to an imported one. That check needs tsrs (`tsrsServices`); the walk
 * collects those arguments and `Program:exit` resolves their symbols (and
 * aliases) in two batched requests. Without tsrs only local enums count, as
 * the original does without type information.
 */

import { defineRule, type ESTree, type Node, type Scope, type SourceCode, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsRequest, TsrsServices, TsrsSymbol } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "no-zod-native-enum";

type Identifier = Extract<Node, { type: "Identifier" }>;

interface AliasChecker {
  readonly getAliasedSymbol: { gen(symbol: TsrsSymbol): TsrsRequest<TsrsSymbol> };
}

/** Unwraps `x as const` / `x satisfies T` down to the inner expression. */
function unwrap(node: Node): Node {
  if (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression") return unwrap(node.expression);
  return node;
}

/** Resolves an identifier to a `TSEnumDeclaration` declared in this file. */
function resolvesToLocalEnum(node: Identifier, scope: Scope): boolean {
  let current: Scope | null = scope;
  while (current !== null) {
    const variable = current.variables.find((v) => v.name === node.name);
    if (variable !== undefined) return variable.defs.some((def) => def.node.type === "TSEnumDeclaration");
    current = current.upper;
  }
  return false;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        'Disallow `z.nativeEnum()` (and `z.enum()` over a TypeScript enum); use `z.enum(["a", "b"])` with a string-literal union instead.',
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      nativeEnum:
        '`z.nativeEnum()` exists to wrap a TypeScript `enum`, which `no-enum` bans. Use `z.enum(["a", "b"])` and derive the union with `z.infer<typeof Schema>`.',
      enumOfTsEnum:
        '`z.enum()` is being passed the TypeScript enum `{{name}}`, which `no-enum` bans. Pass a string-literal array instead: `z.enum(["a", "b"])`.',
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    /** Import bindings, not spellings: shadowed locals must not inherit Zod provenance. */
    let zodImportedBindings = new Map<TsVariable, string>();
    let zodNamespaceBindings = new Set<TsVariable>();
    /** `z.enum(identifier)` calls whose argument may be an imported enum. */
    let pending: { readonly node: ESTree.CallExpression; readonly argument: Identifier }[] = [];

    function resolvedBinding(identifier: Identifier): TsVariable | null {
      return findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    /** `"nativeEnum"` or `"enum"` when the call is that Zod API through a recorded import binding. */
    function zodEnumApi(node: ESTree.CallExpression): string | null {
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") {
        const binding = zodImportedBindings.size === 0 ? null : resolvedBinding(callee);
        const api = binding === null ? undefined : zodImportedBindings.get(binding);
        return api === "nativeEnum" || api === "enum" ? api : null;
      }
      if (callee.type !== "MemberExpression" || zodNamespaceBindings.size === 0) return null;
      const api = getPropertyName(callee);
      const receiver = unwrapExpression(callee.object);
      if ((api !== "nativeEnum" && api !== "enum") || receiver.type !== "Identifier") return null;
      const binding = resolvedBinding(receiver);
      return binding !== null && zodNamespaceBindings.has(binding) ? api : null;
    }

    function reportEnum(node: ESTree.CallExpression, argument: Identifier): void {
      context.report({ node, messageId: "enumOfTsEnum", data: { name: argument.name } });
    }

    /** The original's `resolvesToImportedEnum` for every pending argument, in two tsrs requests. */
    function importedEnums(file: TsrsFile): boolean[] {
      const flags = file.sync.SymbolFlags;
      const checker = file.checker as unknown as AliasChecker;
      const symbols = file.symbolsOf(pending.map((entry) => entry.argument));
      const aliases = symbols.filter((symbol) => symbol !== undefined).filter((symbol) => (symbol.flags & flags.Alias) !== 0);
      const targets = file.batch(aliases.map((symbol) => checker.getAliasedSymbol.gen(symbol)));
      const targetOf = new Map(aliases.map((symbol, i) => [symbol, targets[i]]));
      const enumFlags = flags.RegularEnum | flags.ConstEnum | flags.Enum;
      return symbols.map((symbol) => {
        if (symbol === undefined) return false;
        const resolved = (symbol.flags & flags.Alias) !== 0 ? targetOf.get(symbol) : symbol;
        return resolved !== undefined && (resolved.flags & enumFlags) !== 0;
      });
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        tsrs = null;
        zodImportedBindings = new Map();
        zodNamespaceBindings = new Set();
        pending = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        // A test that covers `z.nativeEnum` must call it.
        if (isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        tsrs = tsrsServices(context);
        return true;
      },
      ImportDeclaration(node) {
        if (!isZodModule(node.source.value)) return;
        for (const spec of node.specifiers) {
          if (spec.type === "ImportNamespaceSpecifier" || spec.type === "ImportDefaultSpecifier" ||
            (spec.type === "ImportSpecifier" &&
              (spec.imported.type === "Identifier" ? spec.imported.name === "z" : spec.imported.value === "z"))) {
            const binding = resolvedBinding(spec.local);
            if (binding !== null) zodNamespaceBindings.add(binding);
          }
          if (spec.type === "ImportSpecifier" && spec.imported.type === "Identifier") {
            const binding = resolvedBinding(spec.local);
            if (binding !== null) zodImportedBindings.set(binding, spec.imported.name);
          }
        }
      },
      CallExpression(node) {
        const api = zodEnumApi(node);
        if (api === "nativeEnum") {
          context.report({ node, messageId: "nativeEnum" });
          return;
        }
        if (api !== "enum") return;
        const argument = node.arguments[0];
        if (argument === undefined || argument.type === "SpreadElement") return;
        const arg = unwrap(argument);
        if (arg.type !== "Identifier") return;
        if (resolvesToLocalEnum(arg, sourceCode.getScope(arg))) reportEnum(node, arg);
        else if (tsrs !== null) pending.push({ node, argument: arg });
      },
      "Program:exit"() {
        if (pending.length === 0 || tsrs === null) return;
        const found = tsrs.run(importedEnums);
        pending.forEach((entry, i) => {
          if (found?.[i] === true) reportEnum(entry.node, entry.argument);
        });
      },
    };
  },
});
