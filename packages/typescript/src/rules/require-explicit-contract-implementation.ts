/**
 * @fileoverview require-explicit-contract-implementation — Detect structural substitutes rejected by nominal runtime guards.
 *
 * Port of the 18.x `require-explicit-contract-implementation` rule.
 * Typed: the original returns no visitors without a program, and reads the
 * TypeScript AST and checker of the whole program. Both come from tsrs only
 * (`_require-explicit-contract-implementation-typed.ts`); when `tsrsServices`
 * is null `before()` skips the file.
 *
 * The walk keeps the `new` expressions with a `new` expression argument (the
 * original only inspects those arguments), so files without one never build
 * a tsrs program; `Program:exit` runs the original's proof on the rest.
 */

import { defineRule, type ESTree, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import type { TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { closedNominalInheritanceFix } from "./_closed-nominal-inheritance-fix.js";
import { contractFindings, type RemoteNode } from "./_require-explicit-contract-implementation-typed.js";

const NAME = "require-explicit-contract-implementation";

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Require nominal inheritance when an injected abstract class is rejected by an instanceof guard.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      declareActualContract:
        "`{{implementation}}` structurally matches `{{contract}}` but fails the rejecting instanceof guard; use nominal inheritance or make the boundary structural.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    let candidates: { readonly node: ESTree.NewExpression; readonly arguments: readonly number[] }[] = [];

    return {
      before() {
        sourceCode = context.sourceCode;
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      NewExpression(node) {
        const indexes = node.arguments.flatMap((argument, index) => argument.type === "NewExpression" ? [index] : []);
        if (indexes.length > 0) candidates.push({ node, arguments: indexes });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        tsrs.run((file) => {
          for (const candidate of candidates) {
            const call = file.tsNode(candidate.node) as RemoteNode | undefined;
            if (call === undefined) continue;
            for (const finding of contractFindings(file, context.cwd, call, candidate.arguments)) {
              const fix = finding.fix === null ? null : closedNominalInheritanceFix(sourceCode, file,
                finding.fix.call, finding.fix.consumer, finding.fix.implementation, finding.fix.contract);
              const report = {
                node: candidate.node.arguments[finding.argument]!,
                messageId: "declareActualContract",
                data: { implementation: finding.implementation, contract: finding.contract },
              } as const;
              if (fix === null) context.report(report);
              else context.report({ ...report, fix });
            }
          }
        });
      },
    };
  },
});
