/**
 * @fileoverview no-contradictory-overload-return — preserve literal overload input/result relationships.
 *
 * Port of the 18.x `no-contradictory-overload-return` rule. Typed: the
 * original returns no visitors without a program, and reads the TypeScript
 * AST of each top-level implementation and its overloads. Types and that AST
 * come from tsrs only (`_no-contradictory-overload-return-proof.ts`); when
 * `tsrsServices` is null `before()` skips the file.
 *
 * The walk keeps the function declarations whose ESTree shape can pass the
 * original's TypeScript-AST proof (top level, named, one parameter, a sole
 * `return` of a conditional on a strict equality, not async, generator or
 * generic), so files without such a function never build a tsrs program.
 * `Program:exit` runs the original's proof on the tsrs nodes of the rest.
 *
 * ESTree and TypeScript nodes are matched as the typed reference matches them:
 * ESTree to TypeScript by `TsrsFile.tsNode` (same range, or a start after
 * leading modifiers, so `export function` and `export async function` map),
 * TypeScript to ESTree by `TsrsFile.esTreeNode`, the innermost ESTree node
 * with the TypeScript node's `getStart()`..`end` range (an exported
 * implementation maps to its `ExportNamedDeclaration`).
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import type { TsrsFile, TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";
import { type Branch, type LiteralValue, overloadProof, type OverloadProof, type Proof, type RemoteNode } from "./_no-contradictory-overload-return-proof.js";

const NAME = "no-contradictory-overload-return";

type ReportFix = (fixer: Fixer) => Fix[];

const TOP_LEVEL_PARENTS: ReadonlySet<string> = new Set(["Program", "ExportNamedDeclaration", "ExportDefaultDeclaration"]);

/** ESTree shape the original's TypeScript-AST proof requires of an implementation; cheap, and implied by it. */
function candidateShape(node: ESTree.Function): boolean {
  const parent = parentOf(node);
  if (parent === null || !TOP_LEVEL_PARENTS.has(parent.type)) return false;
  if (node.id === null || node.async || node.generator || node.typeParameters != null || node.params.length !== 1) return false;
  const statements = node.body?.body ?? [];
  const returned = statements[0];
  // Oxlint's ESTree drops parentheses, so a parenthesized conditional is a ConditionalExpression here.
  return statements.length === 1 && returned?.type === "ReturnStatement" && returned.argument?.type === "ConditionalExpression";
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Preserve the input/result relationship promised by literal overloads.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      contradictoryReturn:
        "For input {{input}}, this returned literal contradicts the overload result {{expected}}. Preserve the input/result relationship in a checked case map, implementation or variant-specific operation.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    let strictNulls = false;
    let candidates: ESTree.Function[] = [];

    function branchFor(proof: Proof, input: LiteralValue): Branch {
      return (input.value === proof.condition.value) === proof.equal ? proof.yes : proof.no;
    }

    function inspect(file: TsrsFile, tools: OverloadProof, node: ESTree.Function): void {
      const implementation = file.tsNode(node) as RemoteNode | undefined;
      if (implementation === undefined) return;
      const proof = tools.implementationProof(implementation);
      if (proof === undefined || (!strictNulls && proof.cases.some((entry) => entry.input.value === null))) return;
      const fix = privateOverloadFix(file, tools, node, implementation, proof);
      let offerFix = true;
      const reported = new Set<string>();
      for (const entry of proof.cases) {
        const branch = branchFor(proof, entry.input);
        for (const literal of tools.mismatches(branch, entry.output)) {
          const key = `${literal.node.kind}:${literal.node.pos}:${literal.node.end}`;
          if (reported.has(key)) continue;
          reported.add(key);
          const data = { input: JSON.stringify(entry.input.value), expected: tools.typeToString(entry.output) };
          const target = file.esTreeNode(literal.node)!;
          context.report({ node: target, messageId: "contradictoryReturn", data, ...(offerFix && fix !== null && { fix }) });
          offerFix = false;
        }
      }
    }

    function privateOverloadFix(file: TsrsFile, tools: OverloadProof, node: ESTree.Function, implementation: RemoteNode, proof: Proof): ReportFix | null {
      const declarations = [implementation, ...proof.cases.map((entry) => entry.declaration)];
      const owners = declarations.map((declaration) => file.esTreeNode(declaration));
      if (node.id === null || !isUnusedPrivateBinding(sourceCode, node, node.id, context.filename, owners as Node[]) || !proof.oneFile ||
        owners.some((owner) => parentOf(owner!)?.type !== "Program" || sourceCode.getCommentsInside(owner!).length > 0 ||
          sourceCode.getCommentsBefore(owner!).length > 0)) return null;
      const parameter = tools.directParameter(implementation);
      const implementationType = implementation["type"] as RemoteNode | undefined;
      if (parameter === undefined || !tools.primitiveResultSyntax(parameter.type) ||
        (implementationType !== undefined && !tools.directResultSyntax(implementationType)) ||
        proof.cases.some((entry) => {
          const type = entry.declaration["type"] as RemoteNode | undefined;
          return type === undefined || !tools.directResultSyntax(type);
        })) return null;
      const edits: { readonly node: Node; readonly text: string }[] = [];
      for (const entry of proof.cases) {
        const branch = branchFor(proof, entry.input);
        if (tools.mismatches(branch, entry.output).length === 0) continue;
        const annotation = entry.declaration["type"] as RemoteNode | undefined;
        if (annotation === undefined) return null;
        const target = file.esTreeNode(annotation)!;
        edits.push({ node: target, text: `${branchResultType(file, branch)}${sourceCode.getText(target).replace(/[^\r\n]/gu, "")}` });
      }
      return edits.length === 0 ? null : (fixer) => edits.map((edit) => fixer.replaceText(edit.node, edit.text));
    }

    function branchResultType(file: TsrsFile, branch: Branch): string {
      const valueType = (literal: LiteralValue): string => typeof literal.value === "string"
        ? sourceCode.getText(file.esTreeNode(literal.node)) : String(literal.value);
      if (branch.kind === "literal") return valueType(branch.value);
      return `{ ${[...branch.values].map(([key, value]) => `${JSON.stringify(key)}: ${valueType(value)}`).join("; ")} }`;
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        if (tsrs === null) return false;
        const options = tsrs.compilerOptions;
        strictNulls = Boolean(options.strictNullChecks ?? options.strict ?? false);
        return true;
      },
      FunctionDeclaration(node) {
        if (candidateShape(node)) candidates.push(node);
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        tsrs.run((file) => {
          const tools = overloadProof(file);
          for (const node of candidates) inspect(file, tools, node);
        });
      },
    };
  },
});
