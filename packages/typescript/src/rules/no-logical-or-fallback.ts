/**
 * @fileoverview no-logical-or-fallback — distinguish missing values from empty strings and zero.
 *
 * Port of the 18.x `no-logical-or-fallback` rule. Typed: it needs type
 * information and `strictNullChecks`; without either it skips the file, as the
 * original returns no visitors without a program.
 *
 * Types come from tsrs (`tsrsServices`). The walk only collects `||`
 * candidates; `Program:exit` resolves them all at once, so tsrs answers a file
 * in a few batched requests. Each left-hand type is reduced to a `Member` view,
 * which one decision function reads; the two `ts-api-utils` checks are inlined.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsServices, TsrsSymbol, TsrsType, TsrsTypeFlags } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-logical-or-fallback";
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "window", "self"]);

// View of a type: string/number/bigint/boolean-like, string/number/bigint-like, type parameter.
const PRIMITIVE = 1;
const FALLBACK = 2;
const TYPE_PARAMETER = 4;

interface Member {
  readonly bits: number;
  /** Truthiness of a string, number, boolean or bigint literal; undefined otherwise. */
  readonly truth: boolean | undefined;
  /** Members of an intersection. */
  readonly parts: readonly Member[] | undefined;
}

function primitivePart(member: Member): Member | undefined {
  if ((member.bits & PRIMITIVE) !== 0) return member;
  if (member.parts === undefined || member.parts.some((part) => (part.bits & TYPE_PARAMETER) !== 0)) return undefined;
  return member.parts.find((part) => (part.bits & PRIMITIVE) !== 0);
}

/** The original's check on the left-hand type, given its union members (or the type itself). */
function fallbackType(members: readonly Member[]): boolean {
  const parts = members.map(primitivePart);
  if (parts.some((part) => part === undefined) || !parts.some((part) => part !== undefined && (part.bits & FALLBACK) !== 0)) return false;
  const truthiness = parts.map((part) => part?.truth);
  return !(truthiness.every((value) => value === true) || truthiness.every((value) => value === false));
}

/** A call callee that may be the native `Boolean`: the identifier, or the global receiver of `<receiver>.Boolean`. */
interface BooleanCallee {
  readonly identifier: ESTree.IdentifierReference | null;
  readonly receiver: ESTree.IdentifierReference | null;
}

interface Candidate {
  readonly node: ESTree.LogicalExpression;
  /** Set when the expression is the first argument of a call that may be the native `Boolean`. */
  readonly callee: BooleanCallee | null;
}

function bitsOf(flags: number, table: { readonly primitive: number; readonly fallback: number; readonly typeParameter: number }): number {
  return ((flags & table.primitive) !== 0 ? PRIMITIVE : 0) | ((flags & table.fallback) !== 0 ? FALLBACK : 0) |
    ((flags & table.typeParameter) !== 0 ? TYPE_PARAMETER : 0);
}

/** Left-hand union members (or the type itself) for every node, in at most three batched tsrs requests. */
function tsrsMembers(file: TsrsFile, nodes: readonly Node[]): (readonly Member[] | undefined)[] {
  const table = tsrsTable(file.flags);
  const types = file.typesOf(nodes);
  const unions = [...new Set(types.flatMap((type) => type?.isUnionType() === true ? [type] : []))];
  const unionMembers = file.batch(unions.map((union) => union.getTypes.gen()));
  const membersOf = new Map(unions.map((union, i) => [union, unionMembers[i] ?? []]));
  const views = types.map((type) => type === undefined ? undefined : membersOf.get(type) ?? [type]);
  // primitivePart reads an intersection's members only when the intersection itself is not primitive.
  const intersections = [...new Set(views.flat().flatMap((type) =>
    type !== undefined && (type.flags & table.primitive) === 0 && type.isIntersectionType() ? [type] : []))];
  const intersectionParts = file.batch(intersections.map((intersection) => intersection.getTypes.gen()));
  const partsOf = new Map(intersections.map((intersection, i) => [intersection, intersectionParts[i] ?? []]));
  const leaf = (type: TsrsType): Member => ({ bits: bitsOf(type.flags, table), truth: truth(type), parts: undefined });

  function truth(type: TsrsType): boolean | undefined {
    if (type.isStringLiteralType() || type.isNumberLiteralType()) return Boolean(type.value);
    // TypeScript names boolean literals by intrinsicName; tsrs leaves it unset and gives the value.
    if ((type.flags & table.booleanLiteral) !== 0) return type.value === true;
    if ((type.flags & table.bigIntLiteral) !== 0) return BigInt(type.value) !== 0n;
    return undefined;
  }
  return views.map((view) => view?.map((type) => ({ ...leaf(type), parts: partsOf.get(type)?.map(leaf) })));
}

// tsrs numbers flags as TypeScript 7 does.
function tsrsTable(flags: TsrsTypeFlags) {
  return {
    primitive: flags.StringLike | flags.NumberLike | flags.BigIntLike | flags.BooleanLike,
    fallback: flags.StringLike | flags.NumberLike | flags.BigIntLike,
    typeParameter: flags.TypeParameter,
    booleanLiteral: flags.BooleanLiteral,
    bigIntLiteral: flags.BigIntLiteral,
  };
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Use nullish defaults or explicit falsy-value checks instead of logical OR fallbacks.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      logicalOrFallback:
        "Use ?? for a missing-value default. If an empty string, zero or false should trigger this fallback, test that condition explicitly; replacing || blindly changes behavior.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    /** True or false when the context alone decides; a callee when the native `Boolean` check decides. */
    function booleanContext(node: Node): boolean | BooleanCallee {
      let current = outerExpression(node);
      for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
        switch (parent.type) {
          case "LogicalExpression":
            if (parent.operator === "&&" && parent.left === current) return true;
            current = outerExpression(parent);
            continue;
          case "IfStatement":
          case "WhileStatement":
          case "DoWhileStatement":
          case "ForStatement":
          case "ConditionalExpression":
            return parent.test === current;
          case "UnaryExpression":
            return parent.operator === "!";
          case "CallExpression":
            return parent.arguments[0] === current && (booleanCallee(parent.callee) ?? false);
          default:
            return false;
        }
      }
      return false;
    }

    /** The untyped half of the original's `nativeBoolean`; the symbol check waits for `Program:exit`. */
    function booleanCallee(node: Node): BooleanCallee | null {
      const callee = unwrapExpression(node);
      if (callee.type === "Identifier" && callee.name === "Boolean" && !shadowed(callee)) {
        return { identifier: callee as ESTree.IdentifierReference, receiver: null };
      }
      if (callee.type === "MemberExpression" && getPropertyName(callee) === "Boolean") {
        const receiver = unwrapExpression(callee.object);
        if (receiver.type !== "Identifier" || !GLOBAL_RECEIVERS.has(receiver.name) || shadowed(receiver)) return null;
        return { identifier: null, receiver: receiver as ESTree.IdentifierReference };
      }
      return null;
    }

    function shadowed(node: Node & { readonly name: string }): boolean {
      return (findVariable(context.sourceCode.getScope(node), node.name)?.defs.length ?? 0) !== 0;
    }

    /** Whether each candidate reports. */
    function resolve(file: TsrsFile): boolean[] {
      const members = tsrsMembers(file, candidates.map((candidate) => candidate.node.left));
      const typed = members.map((view) => view !== undefined && fallbackType(view));
      // Only candidates the type check keeps need the native Boolean check.
      const pending = candidates.flatMap((candidate, i) => typed[i] === true && candidate.callee !== null ? [i] : []);
      const identifiers = pending.flatMap((i) => candidates[i]!.callee!.identifier ?? []);
      const receivers = pending.flatMap((i) => candidates[i]!.callee!.receiver ?? []);
      const identifierSymbols = file.symbolsOf(identifiers);
      const receiverTypes = file.typesOf(receivers);
      const present = receiverTypes.filter((type) => type !== undefined);
      const properties = file.batch(present.map((type) => type.getProperty.gen("Boolean")));
      const symbolOf = new Map<Node, TsrsSymbol | undefined>();
      identifiers.forEach((node, i) => symbolOf.set(node, identifierSymbols[i]));
      let next = 0;
      receivers.forEach((node, i) => symbolOf.set(node, receiverTypes[i] === undefined ? undefined : properties[next++]));
      for (const i of pending) {
        const callee = candidates[i]!.callee!;
        if (file.isDefaultLibrarySymbol(symbolOf.get((callee.identifier ?? callee.receiver)!))) typed[i] = false;
      }
      return typed;
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        const options = tsrs?.compilerOptions;
        return options !== undefined && Boolean(options.strictNullChecks ?? options.strict ?? false);
      },
      LogicalExpression(node) {
        if (node.operator !== "||") return;
        const owner = booleanContext(node);
        if (owner !== true) candidates.push({ node, callee: owner === false ? null : owner });
      },
      "Program:exit"() {
        if (tsrs === null || candidates.length === 0) return;
        const found = tsrs.run(resolve);
        if (found === null) return;
        candidates.forEach((candidate, i) => {
          if (found[i] === true) context.report({ node: candidate.node, messageId: "logicalOrFallback" });
        });
      },
    };
  },
});
