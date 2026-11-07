/**
 * @fileoverview no-numeric-search-param-coercion — numeric URL search parameters are parsed by a schema, not coerced.
 *
 * Port of the 18.x `no-numeric-search-param-coercion` rule. Typed:
 * without tsrs type services it skips the file, as the original returns no
 * visitors without a program.
 *
 * The visitor runs the original's syntactic checks and collects the calls
 * they leave; `Program:exit` resolves every `get` receiver's non-nullable type
 * and its symbol in three batched tsrs requests.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import type { TsrsFile, TsrsRequest, TsrsServices, TsrsSymbol, TsrsType } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-numeric-search-param-coercion";
const GLOBAL_PARSERS: ReadonlySet<string> = new Set(["parseInt", "parseFloat", "Number"]);
const NUMBER_PARSERS: ReadonlySet<string> = new Set(["parseInt", "parseFloat"]);
const SEARCH_PARAM_TYPES: ReadonlySet<string> = new Set(["URLSearchParams", "ReadonlyURLSearchParams"]);

/** The tsrs requests this rule makes beyond those `TsrsFile` types. */
interface SymbolRequests {
  readonly getNonNullableType: { gen(type: TsrsType): TsrsRequest<TsrsType> };
}
interface TypeSymbols {
  readonly getSymbol: { gen(): TsrsRequest<TsrsSymbol | undefined> };
  readonly getAliasSymbol: { gen(): TsrsRequest<TsrsSymbol | undefined> };
}

function isNumericParser(sourceCode: SourceCode, callee: Node): boolean {
  if (callee.type === "Identifier") return GLOBAL_PARSERS.has(callee.name) && isUnshadowedGlobal(sourceCode, callee);
  return callee.type === "MemberExpression" && !callee.computed && callee.object.type === "Identifier" &&
    callee.object.name === "Number" && callee.property.type === "Identifier" && NUMBER_PARSERS.has(callee.property.name) &&
    isUnshadowedGlobal(sourceCode, callee.object);
}

function isUnshadowedGlobal(sourceCode: SourceCode, node: Node & { readonly name: string }): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function searchParamGetCall(argument: Node): ESTree.CallExpression | null {
  let value: Node = unwrapExpression(argument);
  if (value.type === "AwaitExpression") value = unwrapExpression(value.argument);
  if (value.type === "LogicalExpression" && value.operator === "??") value = unwrapExpression(value.left);
  if (value.type === "ChainExpression") value = value.expression;
  if (
    value.type !== "CallExpression" || value.callee.type !== "MemberExpression" || value.callee.computed ||
    value.callee.property.type !== "Identifier" || value.callee.property.name !== "get"
  ) {
    return null;
  }
  return value;
}

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly receiver: Node;
}

/** Whether each receiver's non-nullable type is named URLSearchParams or ReadonlyURLSearchParams. */
function searchParamReceivers(file: TsrsFile, receivers: readonly Node[]): boolean[] {
  const checker = file.checker as unknown as SymbolRequests;
  const types = file.typesOf(receivers);
  const present = types.filter((type) => type !== undefined);
  const nonNullable = file.batch(present.map((type) => checker.getNonNullableType.gen(type))) as unknown as TypeSymbols[];
  const symbols = file.batch(nonNullable.flatMap((type) => [type.getSymbol.gen(), type.getAliasSymbol.gen()]));
  let next = 0;
  return types.map((type) => {
    if (type === undefined) return false;
    const symbol = symbols[2 * next] ?? symbols[2 * next + 1];
    next++;
    return symbol !== undefined && SEARCH_PARAM_TYPES.has(symbol.name);
  });
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Parse numeric URL search parameters with a schema instead of parseInt or Number.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noNumericSearchParamCoercion:
        "This coerces a URL search parameter with {{parser}}, which turns missing or malformed input into NaN or a truncated number. Parse it with a schema such as z.coerce.number().int().",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];
    return {
      before() {
        candidates = [];
        tsrs = null;
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text) || isTestFile(file)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      CallExpression(node) {
        const [first] = node.arguments;
        if (first === undefined || !isNumericParser(context.sourceCode, node.callee)) return;
        const call = searchParamGetCall(first);
        if (call === null || call.callee.type !== "MemberExpression") return;
        candidates.push({ node, receiver: call.callee.object });
      },
      "Program:exit"() {
        if (tsrs === null || candidates.length === 0) return;
        const found = tsrs.run((file) => searchParamReceivers(file, candidates.map(({ receiver }) => receiver)));
        if (found === null) return;
        candidates.forEach(({ node }, i) => {
          if (found[i] !== true) return;
          context.report({
            node,
            messageId: "noNumericSearchParamCoercion",
            data: { parser: context.sourceCode.getText(node.callee) },
          });
        });
      },
    };
  },
});
