/**
 * @fileoverview prefer-minimal-parameter-contract — prefer the proven read-only subset for a private consumer parameter.
 *
 * Port of the 18.x `prefer-minimal-parameter-contract` rule. Typed:
 * without tsrs types it reports nothing, as the original returns no visitors
 * without a program. The walk collects inline-annotated consumers; their
 * proofs run against tsrs in `Program:exit`, as the original's do.
 */

import type { FixFn } from "@oxlint/plugins";
import type { TypeLiteralNode } from "tsrs/ast";

import { defineRule, type Node } from "../types.js";
import { nativeTypes, type NativeAst } from "../utils/checked-native-source.js";
import { minimalConsumerFix, validConsumerFixCalls } from "../utils/private-consumer-fix.js";
import {
  consumerAnnotation,
  directEval,
  exportedSymbols,
  nullishPrimitiveUnion,
  optionalMember,
  primitiveKeyword,
  privateScalarConsumer,
  type ScalarConsumerNode,
} from "../utils/private-scalar-consumer.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-minimal-parameter-contract";

function inlineFields(ast: NativeAst, node: TypeLiteralNode, reads: ReadonlySet<string>): ReadonlyMap<string, boolean> | null {
  const fields = new Map<string, boolean>();
  for (const member of node.members) {
    if (!ast.isPropertySignatureDeclaration(member) || !member.name || (!ast.isIdentifier(member.name) && !ast.isStringLiteralLikeNode(member.name)) ||
      !readonlyAtMost(ast, member.modifiers ?? [])) return null;
    const key = member.name.text;
    if (!primitiveKeyword(ast, member.type) && (!nullishPrimitiveUnion(ast, member.type) || (optionalMember(ast, member) && !reads.has(key)))) return null;
    if (fields.has(key)) return null;
    fields.set(key, !optionalMember(ast, member));
  }
  return fields;
}

/** No modifier, or only `readonly`. */
function readonlyAtMost(ast: NativeAst, modifiers: readonly { readonly kind: number }[]): boolean {
  return modifiers.length <= 1 && modifiers.every((modifier) => modifier.kind === ast.SyntaxKind.ReadonlyKeyword);
}

interface Finding {
  readonly node: Node;
  readonly used: string;
  readonly unused: string;
  readonly fix: FixFn | null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: "Prefer the proven read-only subset for a private consumer parameter.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      minimal: "This private consumer reads only {{used}} but also requires {{unused}}. Review a smaller consumer contract; preserve the original runtime object and producer type.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: ScalarConsumerNode[] = [];
    let dynamic = false;
    const remember = (node: ScalarConsumerNode): void => {
      if (consumerAnnotation(node, true)?.type === "TSTypeLiteral") candidates.push(node);
    };
    return {
      before() {
        tsrs = null;
        candidates = [];
        dynamic = false;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      FunctionDeclaration: remember,
      ArrowFunctionExpression: remember,
      CallExpression(node) {
        if (directEval(node)) dynamic = true;
      },
      "Program:exit"() {
        if (dynamic || !candidates.length || tsrs === null) return;
        const sourceCode = context.sourceCode;
        const findings = tsrs.run((file) => {
          const native = nativeTypes(file);
          const findings: Finding[] = [];
          const { ast } = native;
          const exports = exportedSymbols(native, native.source);
          for (const candidate of candidates) {
            const consumer = privateScalarConsumer(native, candidate, sourceCode, exports, { scalarCalls: true, auxiliaryScalars: true });
            const annotation = consumer?.parameter.type;
            if (!consumer || !annotation || !ast.isTypeLiteralNode(annotation)) continue;
            const fields = inlineFields(ast, annotation, consumer.reads);
            if (!fields || [...consumer.reads].some((key) => !fields.has(key)) || ![...consumer.reads].some((key) => fields.get(key))) continue;
            const unused = [...fields].filter(([key, required]) => required && !consumer.reads.has(key)).map(([key]) => key).sort();
            if (!unused.length) continue;
            // The selected parameter's annotation is the candidate's consumer annotation.
            const reportNode = consumerAnnotation(candidate, true);
            if (reportNode === undefined) continue;
            const removed = annotation.members.filter((member) => ast.isPropertySignatureDeclaration(member) && member.name &&
              (ast.isIdentifier(member.name) || ast.isStringLiteralLikeNode(member.name)) && unused.includes(member.name.text))
              .map((member) => ({ start: member.getStart(native.source), end: member.getEnd() }));
            const fix = validConsumerFixCalls(native, candidate, consumer.parameter, sourceCode)
              ? minimalConsumerFix(sourceCode, reportNode, removed) : null;
            findings.push({ node: reportNode, used: [...consumer.reads].sort().join(", "), unused: unused.join(", "), fix });
          }
          return findings;
        });
        if (findings === null) return;
        for (const { node, used, unused, fix } of findings) {
          const report = { node: node, messageId: "minimal", data: { used, unused } };
          context.report(fix === null ? report : { ...report, fix });
        }
      },
    };
  },
});
