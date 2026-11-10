/**
 * @fileoverview require-assert-never — a switch over a union whose `default` does no runtime work stops being exhaustive the day the union grows.
 *
 * Port of the 18.x `require-assert-never` rule. Typed: without tsrs type
 * services it skips the file, as the original returns no visitors without a
 * program.
 *
 * The visitor runs the original's syntactic checks and collects the switches
 * they leave; `Program:exit` proves exhaustiveness for all of them at once,
 * in a few batched tsrs requests (discriminant and case types, union members,
 * then literal display names and native unique-symbol identities). The fix helper is
 * `_empty-assertion-fix.ts`.
 */

import { defineRule, type ESTree, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import type { TsrsFile, TsrsServices, TsrsTypeFlags } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { emptyAssertionFix } from "./_empty-assertion-fix.js";

const NAME = "require-assert-never";

/** Empty statements and empty blocks are not runtime handling. */
function isRuntimeHandlingStatement(statement: ESTree.Statement): boolean {
  if (statement.type === "EmptyStatement") return false;
  if (statement.type === "BreakStatement") return statement.label !== null;
  if (statement.type === "TSTypeAliasDeclaration" || statement.type === "TSInterfaceDeclaration") return false;
  if (statement.type === "BlockStatement") return statement.body.some(isRuntimeHandlingStatement);
  return true;
}

/** An empty non-final default falls through to a case that handles it. */
function isFallthroughDefault(node: ESTree.SwitchStatement, defaultIndex: number): boolean {
  const defaultCase = node.cases[defaultIndex];
  return defaultCase !== undefined && defaultCase.consequent.length === 0 && defaultIndex < node.cases.length - 1;
}

/** Honor a comment that makes an empty default an intentional no-op. */
function isCommentOnlyNoopDefault(defaultCase: ESTree.SwitchCase, sourceCode: SourceCode): boolean {
  if (defaultCase.consequent.length === 0) {
    const defaultToken = sourceCode.getFirstToken(defaultCase);
    const colonToken = defaultToken ? sourceCode.getTokenAfter(defaultToken) : null;
    return colonToken !== null && sourceCode.getCommentsAfter(colonToken).length > 0;
  }
  const only = defaultCase.consequent[0];
  if (
    only !== undefined && defaultCase.consequent.length === 1 && only.type === "BlockStatement" &&
    !only.body.some(isRuntimeHandlingStatement)
  ) {
    return sourceCode.getCommentsInside(only).length > 0;
  }
  return false;
}

interface Candidate {
  readonly node: ESTree.SwitchStatement;
  readonly defaultCase: ESTree.SwitchCase;
}

/** Which candidates have explicit cases covering every finite constituent of the discriminant, in batched requests. */
function exhaustiveSwitches(file: TsrsFile, candidates: readonly Candidate[]): boolean[] {
  const finite = finiteFlags(file.flags);
  const discriminants = file.typesOf(candidates.map(({ node }) => node.discriminant));
  const unions = discriminants.map((type) => type?.isUnionType() === true ? type : undefined);
  const present = unions.filter((type) => type !== undefined);
  const memberLists = file.batch(present.map((type) => type.getTypes.gen()));
  let next = 0;
  const constituents = unions.map((type) => type === undefined ? undefined : memberLists[next++] ?? []);
  // A fully covered boolean switch has no evolving domain for assertNever to
  // guard, so requiring a default assertion would only add ceremony.
  const open = constituents.map((members) => members === undefined || members.length < 2 ||
    members.every((member) => (member.flags & file.flags.BooleanLiteral) !== 0) ||
    members.some((member) => (member.flags & finite) === 0));
  const tests = candidates.map(({ node }, i) => open[i] === true ? [] : node.cases.flatMap((caseNode) => caseNode.test ?? []));
  const testTypes = file.typesOf(tests.flat());
  // A union-valued expression evaluates to one value, not every alternative.
  const finiteTests = testTypes.map((type) => type !== undefined && !type.isUnionType() && (type.flags & finite) !== 0 ? type : undefined);
  const named = [...new Set([
    ...constituents.flatMap((members, i) => open[i] === true ? [] : members ?? []),
    ...finiteTests.filter((type) => type !== undefined),
  ])];
  const printable = named.filter((type) => (type.flags & file.flags.UniqueESSymbol) === 0);
  const names = printable.length === 0 ? [] : file.batch(printable.map((type) => file.checker.typeToString.gen(type)));
  const nameOf = new Map(printable.map((type, i) => [type, names[i]]));
  let offset = 0;
  return candidates.map((_candidate, i) => {
    const caseTypes = finiteTests.slice(offset, offset + (tests[i]?.length ?? 0));
    offset += tests[i]?.length ?? 0;
    if (open[i] === true) return false;
    const symbols = new Set(caseTypes.flatMap((type) =>
      type !== undefined && (type.flags & file.flags.UniqueESSymbol) !== 0 ? [type.id] : []));
    const handled = new Set(caseTypes.flatMap((type) => {
      if (type === undefined || (type.flags & file.flags.UniqueESSymbol) !== 0) return [];
      const name = nameOf.get(type);
      return name === undefined ? [] : [name];
    }));
    return (constituents[i] ?? []).every((member) => {
      if ((member.flags & file.flags.UniqueESSymbol) !== 0) return symbols.has(member.id);
      const name = nameOf.get(member);
      return name !== undefined && handled.has(name);
    });
  });
}

function finiteFlags(flags: TsrsTypeFlags): number {
  return flags.StringLiteral | flags.NumberLiteral | flags.BooleanLiteral | flags.EnumLiteral | flags.UniqueESSymbol |
    flags.Null | flags.Undefined;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Require a never witness in empty switch defaults so discriminated unions remain exhaustive at compile time.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      missingAssertNever:
        "Empty switch `default` case — add runtime handling or a never witness so the discriminated union is exhaustively checked at compile time.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    function report(exhaustive: readonly boolean[]): void {
      candidates.forEach(({ node, defaultCase }, i) => {
        if (exhaustive[i] !== true) return;
        const fix = emptyAssertionFix(context.sourceCode, node, defaultCase);
        context.report({ node: defaultCase, messageId: "missingAssertNever", ...(fix !== null && { fix }) });
      });
    }

    return {
      before() {
        candidates = [];
        // Exhaustiveness cannot be proven from syntax alone; without types the rule stays silent.
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      SwitchStatement(node) {
        const defaultIndex = node.cases.findIndex((caseNode) => caseNode.test === null);
        // Only present no-op defaults opt into this syntactic check.
        if (defaultIndex === -1) return;
        const defaultCase = node.cases[defaultIndex];
        if (defaultCase === undefined) return;
        // Any runtime work, including assertNever(), handles the default.
        if (defaultCase.consequent.some(isRuntimeHandlingStatement)) return;
        // A non-final empty default is handled by its following case.
        if (isFallthroughDefault(node, defaultIndex)) return;
        // Comments distinguish deliberate no-ops without requiring type info.
        if (isCommentOnlyNoopDefault(defaultCase, context.sourceCode)) return;
        candidates.push({ node, defaultCase });
      },
      "Program:exit"() {
        if (tsrs === null || candidates.length === 0) return;
        const exhaustive = tsrs.run((file) => exhaustiveSwitches(file, candidates));
        if (exhaustive === null) return;
        report(exhaustive);
      },
    };
  },
});
