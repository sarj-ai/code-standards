/**
 * @fileoverview prefer-module-level-refined-schema — hoist closed Zod scalar, format, and wrapper schemas.
 *
 * Port of the 18.x `prefer-module-level-refined-schema` rule. Same
 * algorithm; test, benchmark and generated files are skipped in `before()`,
 * which also resets the per-file Zod bindings. The closure checks shared with
 * prefer-module-level-schema come from that rule.
 */

import type { Variable } from "@oxlint/plugins";

import { defineRule, tsVariable, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { isErasedExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";
import {
  buildsLocalizedText,
  closesOverNothing,
  FUNCTION_TYPES,
  outermostEnclosingFunction,
  readsReceiver,
  subtreeSome,
} from "./prefer-module-level-schema.js";

const NAME = "prefer-module-level-refined-schema";

type Identifier = Extract<Node, { type: "Identifier" }>;

const BENCHMARK_PATH_RE = /(^|[/\\])(?:benchmarks?|bench)[/\\]/;

// Factories already owned by prefer-module-level-schema stay out of this rule.
// lazy is intentionally absent because its callback defers construction.
const FACTORIES: ReadonlySet<string> = new Set([
  "array", "base64", "base64url", "bigint", "boolean", "cidrv4",
  "cidrv6", "codec", "custom", "date", "datetime", "duration", "email",
  "emoji", "enum", "file",
  "function", "hash", "hex", "hostname", "instanceof", "ipv4", "ipv6",
  "json", "jwt", "literal", "map", "nan", "nativeEnum", "never", "null",
  "nullable", "nullish", "number", "optional", "partialRecord", "preprocess",
  "promise", "set", "string", "stringbool", "symbol", "templateLiteral",
  "time", "undefined", "url", "uuid", "void",
]);
const COMPOSITE_FACTORIES: ReadonlySet<string> = new Set([
  "discriminatedUnion", "intersection", "looseObject", "object", "record",
  "strictObject", "tuple", "union",
]);
const SCHEMA_FACTORIES: ReadonlySet<string> = new Set([...FACTORIES, ...COMPOSITE_FACTORIES]);
const FACTORY_NAMESPACES: ReadonlySet<string> = new Set(["coerce", "iso"]);
const NON_SCHEMA_TERMINALS: ReadonlySet<string> = new Set([
  "decode", "decodeAsync", "encode", "encodeAsync", "flattenError",
  "formatError", "implement", "isNullable", "isOptional", "parse",
  "parseAsync", "prettifyError", "registry", "safeDecode",
  "safeDecodeAsync", "safeEncode", "safeEncodeAsync", "safeParse",
  "safeParseAsync", "spa", "toJSONSchema", "treeifyError",
]);
const MEMO_CALLEES: ReadonlySet<string> = new Set([
  "lazy", "memo", "once", "useMemo",
]);

function calleeChainRoot(node: Node): Identifier | null {
  let current = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "Identifier") return current;
    if (current.type === "MemberExpression") {
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    return null;
  }
}

function chainMemberNames(node: Node): readonly string[] {
  const names: string[] = [];
  let current = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "MemberExpression") {
      const name = getPropertyName(current);
      if (name === null) return [];
      names.push(name);
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    break;
  }
  names.reverse();
  return names;
}

/** The schema expression around a factory call: its builder-method chain and erased type wrappers. */
function schemaExpression(node: ESTree.CallExpression): Node {
  let current: Node = node;
  for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
    if (isErasedExpression(parent)) {
      current = parent;
      continue;
    }
    const call = parentOf(parent);
    const method = parent.type === "MemberExpression" && parent.object === current ? getPropertyName(parent) : null;
    if (method === null || call?.type !== "CallExpression" || call.callee !== parent || NON_SCHEMA_TERMINALS.has(method)) break;
    current = call;
  }
  return current;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Declare closed Zod scalar, format, and wrapper schemas at module scope.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      hoistRefinedSchema:
        "Move this closed Zod schema to module scope, give it a PascalCase Schema name, and reuse it for parsing.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let zodBindings = new Set<TsVariable>();

    function resolvedBinding(
      identifier: Identifier,
    ): TsVariable | null {
      return findVariable(
        sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function recordZodBinding(identifier: Identifier): void {
      const binding = resolvedBinding(identifier);
      if (binding !== null) zodBindings.add(binding);
    }

    /** The factory a `z.<factory>(…)` or `z.coerce.<factory>(…)` call names, when `allowed` has it. */
    function factoryName(
      node: ESTree.CallExpression,
      allowed: ReadonlySet<string>,
    ): string | null {
      if (zodBindings.size === 0) return null;
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression") return null;
      const names = chainMemberNames(callee);
      const [first = "", second = ""] = names;
      const factory = names.length === 1 ? first : names.length === 2 && FACTORY_NAMESPACES.has(first) ? second : null;
      if (factory === null || !allowed.has(factory)) return null;
      const root = calleeChainRoot(callee);
      const binding = root === null ? null : resolvedBinding(root);
      return binding !== null && zodBindings.has(binding) ? factory : null;
    }

    function isSchemaConstruction(node: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression") return false;
      const name = getPropertyName(callee);
      if (name === null || NON_SCHEMA_TERMINALS.has(name)) return false;
      const calleeReceiver = unwrapExpression(callee.object);
      if (calleeReceiver.type === "CallExpression") return isSchemaConstruction(calleeReceiver);
      return factoryName(node, SCHEMA_FACTORIES) !== null;
    }

    function hasEagerComputation(node: Node): boolean {
      return subtreeSome(node, (inner) =>
        inner.type === "NewExpression" ||
        inner.type === "TaggedTemplateExpression" ||
        (inner.type === "CallExpression" && !isSchemaConstruction(inner)), true);
    }

    function isSharedEnumDomain(
      node: ESTree.CallExpression,
      factory: string,
    ): boolean {
      if (factory !== "enum") return false;
      const [argument] = node.arguments;
      return (
        argument?.type === "ArrayExpression" &&
        argument.elements.length >= 2 &&
        argument.elements.every(
          (element) =>
            element?.type === "Literal" &&
            typeof element.value === "string",
        )
      );
    }

    function isNestedInOwnedFactory(node: ESTree.CallExpression): boolean {
      for (let current = parentOf(node); current !== null; current = parentOf(current)) {
        if (FUNCTION_TYPES.has(current.type)) return false;
        if (current.type === "CallExpression" && factoryName(current, SCHEMA_FACTORIES) !== null) return true;
      }
      return false;
    }

    function isMemoized(node: Node): boolean {
      for (let current = parentOf(node); current !== null; current = parentOf(current)) {
        if (current.type !== "CallExpression") continue;
        const { callee } = current;
        if (callee.type === "Identifier" && MEMO_CALLEES.has(callee.name)) return true;
        if (callee.type === "MemberExpression" && MEMO_CALLEES.has(getPropertyName(callee) ?? "")) return true;
      }
      return false;
    }

    const isZodBinding = (_identifier: Node, resolved: Variable): boolean => zodBindings.has(tsVariable(resolved));

    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        if (
          isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          BENCHMARK_PATH_RE.test(context.filename) ||
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)
        )
          return false;
        zodBindings = new Set<TsVariable>();
      },
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportDefaultSpecifier" ||
            specifier.type === "ImportNamespaceSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              importSpecifierName(specifier) === "z")
          )
            recordZodBinding(specifier.local);
        }
      },
      CallExpression(node): void {
        const factory = factoryName(node, FACTORIES);
        if (
          factory === null ||
          isSharedEnumDomain(node, factory) ||
          isNestedInOwnedFactory(node) ||
          isMemoized(node)
        )
          return;
        const enclosing = outermostEnclosingFunction(node);
        if (enclosing === undefined) return;
        const expression = schemaExpression(node);
        if (
          hasEagerComputation(expression) ||
          readsReceiver(expression) ||
          buildsLocalizedText(expression) ||
          !closesOverNothing(sourceCode, expression, enclosing, isZodBinding)
        )
          return;
        context.report({ node, messageId: "hoistRefinedSchema" });
      },
    };
  },
});
