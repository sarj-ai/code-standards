/**
 * @fileoverview prefer-switch-for-repeated-equality — long equality dispatch chains obscure a finite set of cases.
 *
 * Port of the 18.x `prefer-switch-for-repeated-equality` rule. Reports
 * without types; types only gate the autofix of a chain without a final else
 * (the discriminant must have an open type). Those chains wait for
 * `Program:exit`, where tsrs types every discriminant in a few batched
 * requests. Without tsrs such a chain is reported without a fix, as the
 * original does without type information.
 */

import { defineRule, type ESTree, type Node, type Scope, type SourceCode } from "../types.js";
import { forEachOwnAstChild } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import type { TsrsFile, TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-switch-for-repeated-equality";

type Expression = ESTree.Expression | ESTree.PrivateIdentifier;

interface SwitchCase {
  readonly value: Expression;
  readonly branch: ESTree.Statement;
}

interface Chain {
  readonly discriminant: Expression;
  readonly cases: readonly SwitchCase[];
  readonly fallback: ESTree.Statement | null;
}

function discriminantName(test: Node): string | null {
  if (test.type !== "BinaryExpression" || test.operator !== "===") return null;
  const leftIsCase = isCaseValue(test.left);
  const rightIsCase = isCaseValue(test.right);
  if (leftIsCase === rightIsCase) return null;
  const discriminant = leftIsCase ? test.right : test.left;
  return discriminant.type === "Identifier" ? discriminant.name : null;
}

function isCaseValue(node: Expression): boolean {
  return node.type === "Literal" && !("regex" in node && node.regex !== undefined && node.regex !== null);
}

/** The chain the fix would convert, or null when comments, break statements or function declarations rule it out. */
function convertibleChain(node: ESTree.IfStatement, sourceCode: SourceCode): Chain | null {
  if (sourceCode.getCommentsInside(node).length > 0 || hasUnsafeSwitchControl(node)) return null;
  return switchCases(node);
}

function switchText(chain: Chain, sourceCode: SourceCode): string {
  const block = (branch: ESTree.Statement): string =>
    branch.type === "BlockStatement" ? sourceCode.getText(branch) : `{ ${sourceCode.getText(branch)} }`;
  const chunks = chain.cases.map(({ value, branch }) => `case ${sourceCode.getText(value)}: ${block(branch)}`);
  if (chain.fallback !== null) chunks.push(`default: ${block(chain.fallback)}`);
  return `switch (${sourceCode.getText(chain.discriminant)}) {\n${chunks.join("\n")}\n}`;
}

function switchCases(node: ESTree.IfStatement): Chain | null {
  if (node.test.type !== "BinaryExpression") return null;
  const discriminant = isCaseValue(node.test.left) ? node.test.right : node.test.left;
  const cases: SwitchCase[] = [];
  let current = node;
  while (true) {
    if (current.test.type !== "BinaryExpression" || !terminatesBranch(current.consequent)) return null;
    const test = current.test;
    const value = isCaseValue(test.left) ? test.left : test.right;
    cases.push({ value, branch: current.consequent });
    const alternate = current.alternate;
    if (alternate?.type !== "IfStatement") return { discriminant, cases, fallback: alternate };
    current = alternate;
  }
}

function terminatesBranch(statement: ESTree.Statement | undefined): boolean {
  if (statement === undefined) return false;
  if (statement.type === "ReturnStatement" || statement.type === "ThrowStatement" ||
    statement.type === "ContinueStatement") return true;
  if (statement.type === "BlockStatement") return terminatesBranch(statement.body.at(-1));
  return statement.type === "IfStatement" && statement.alternate !== null &&
    terminatesBranch(statement.consequent) && terminatesBranch(statement.alternate);
}

function hasUnsafeSwitchControl(node: Node): boolean {
  return node.type === "BreakStatement" || node.type === "FunctionDeclaration" ||
    forEachOwnAstChild(node, hasUnsafeSwitchControl);
}

/** Whether each discriminant's type (or one of its union members) is open, in at most two tsrs requests. */
function openDiscriminants(file: TsrsFile, nodes: readonly Node[]): boolean[] {
  const flags = file.flags;
  const openFlags = flags.Any | flags.Unknown | flags.String | flags.Number | flags.BigInt | flags.ESSymbol;
  const types = file.typesOf(nodes);
  const unions = [...new Set(types.filter((type) => type !== undefined).filter((type) => type.isUnionType()))];
  const members = file.batch(unions.map((union) => union.getTypes.gen()));
  const membersOf = new Map(unions.map((union, i) => [union, members[i] ?? []]));
  return types.map((type) => type !== undefined &&
    (membersOf.get(type) ?? [type]).some((part) => (part.flags & openFlags) !== 0));
}

/** How many `else if` links compare `discriminant`, or 0 when one of them compares something else. */
function chainLength(node: ESTree.IfStatement, discriminant: string): number {
  let count = 1;
  for (let current = node.alternate; current?.type === "IfStatement"; current = current.alternate) {
    if (discriminantName(current.test) !== discriminant) return 0;
    count += 1;
  }
  return count;
}

/** A single parameter or variable declaration outside the global scope. */
function isLocalBinding(scope: Scope, name: string): boolean {
  const binding = findVariable(scope, name);
  if (binding === null || binding.defs.length !== 1 || binding.scope.type === "global") return false;
  const [definition] = binding.defs;
  return definition?.type === "Parameter" || definition?.type === "Variable";
}

interface Pending {
  readonly node: ESTree.IfStatement;
  readonly discriminant: string;
  readonly chain: Chain;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Prefer switch over long if/else-if chains that compare one value for strict equality.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferSwitch: "This if/else-if chain repeatedly compares `{{discriminant}}`; use a switch for the finite cases.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let pending: Pending[] = [];

    function report(node: ESTree.IfStatement, discriminant: string, replacement: string | null): void {
      context.report({
        node, messageId: "preferSwitch", data: { discriminant },
        ...(replacement !== null && { fix: (fixer) => fixer.replaceText(node, replacement) }),
      });
    }

    return {
      before() {
        tsrs = null;
        pending = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return undefined;
      },
      IfStatement(node) {
        const parent = node.parent;
        if (parent.type === "IfStatement" && parent.alternate === node) return;
        const first = discriminantName(node.test);
        if (first === null) return;
        if (chainLength(node, first) < 3 || !isLocalBinding(context.sourceCode.getScope(node), first)) return;
        const sourceCode = context.sourceCode;
        const chain = convertibleChain(node, sourceCode);
        if (chain === null) return report(node, first, null);
        if (chain.fallback !== null) return report(node, first, switchText(chain, sourceCode));
        // Without a final else, only an open discriminant type keeps the switch's unmatched path the same.
        if (tsrs === null) return report(node, first, null);
        pending.push({ node, discriminant: first, chain });
      },
      "Program:exit"() {
        if (pending.length === 0 || tsrs === null) return;
        const open = tsrs.run((file) => openDiscriminants(file, pending.map((item) => item.chain.discriminant))) ?? [];
        const sourceCode = context.sourceCode;
        pending.forEach((item, i) =>
          report(item.node, item.discriminant, open[i] === true ? switchText(item.chain, sourceCode) : null));
      },
    };
  },
});
