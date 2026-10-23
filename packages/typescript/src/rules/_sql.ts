/**
 * @fileoverview _sql — shared extraction of statically-resolvable SQL strings, with literal values and comments neutralised before any keyword scan.
 *
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { staticString } from "./_static-string.js";

const SQL_IDENTIFIER_CONTINUATION = /[\w$\u0080-\u{10FFFF}]/u;
const DOLLAR_DELIMITER = /\$(?:[A-Za-z_\u0080-\u{10FFFF}][A-Za-z_0-9\u0080-\u{10FFFF}]*)?\$/uy;
const SQL_LINE_END = /[\r\n]/g;
const CONTINUED_QUOTE = /[ \t\f\v]*(?:--[^\r\n]*)?[\r\n](?:[ \t\f\v\r\n]|--[^\r\n]*[\r\n])*'/y;

interface SqlNoiseOptions {
  readonly preserveQuotedTokens?: boolean;
}

/** Mask SQL values and comments without changing text or line lengths. */
export function stripSqlNoise(text: string, options?: SqlNoiseOptions): string {
  return scanSqlNoise(text, undefined, options?.preserveQuotedTokens === true);
}

export function sqlSingleQuotedRanges(text: string): readonly (readonly [number, number])[] {
  return sqlNoiseInfo(text).singleQuotedRanges;
}

/** Mask SQL and record value ranges together for interpolation analysis. */
export function sqlNoiseInfo(text: string): {
  readonly text: string;
  readonly singleQuotedRanges: readonly (readonly [number, number])[];
} {
  const singleQuotedRanges: Array<readonly [number, number]> = [];
  const masked = scanSqlNoise(text, (start, end) => singleQuotedRanges.push([start, end]));
  return { text: masked, singleQuotedRanges };
}

function scanSqlNoise(text: string, onSingleQuoted?: (start: number, end: number) => void, preserveQuotedTokens = false): string {
  const out = text.split("");
  let index = 0;
  while (index < text.length) {
    const dollarEnd = dollarQuotedSqlEnd(text, index);
    if (dollarEnd !== null) {
      maskSqlRange(text, out, index, dollarEnd);
      if (preserveQuotedTokens) out[index] = "?";
      index = dollarEnd;
      continue;
    }
    const character = text[index];
    if (character === "'" || character === '"') {
      const start = index;
      index = quotedSqlEnd(text, out, index, onSingleQuoted);
      if (preserveQuotedTokens) out[start] = "?";
      continue;
    }
    if (character === "-" && text[index + 1] === "-") {
      SQL_LINE_END.lastIndex = index;
      const end = SQL_LINE_END.exec(text)?.index ?? text.length;
      maskSqlRange(text, out, index, end);
      index = end;
      continue;
    }
    if (character === "/" && text[index + 1] === "*") {
      index = blockSqlCommentEnd(text, out, index);
      continue;
    }
    index += 1;
  }
  return out.join("");
}


function dollarQuotedSqlEnd(text: string, start: number): number | null {
  if (text[start] !== "$" || SQL_IDENTIFIER_CONTINUATION.test(text[start - 1] ?? "")) return null;
  DOLLAR_DELIMITER.lastIndex = start;
  const delimiter = DOLLAR_DELIMITER.exec(text)?.[0];
  if (delimiter === undefined) return null;
  const closing = text.indexOf(delimiter, start + delimiter.length);
  return closing < 0 ? text.length : closing + delimiter.length;
}


function blockSqlCommentEnd(text: string, out: string[], start: number): number {
  out[start] = " ";
  out[start + 1] = " ";
  let index = start + 2;
  let depth = 1;
  while (index < text.length && depth > 0) {
    if ((text[index] === "/" && text[index + 1] === "*") || (text[index] === "*" && text[index + 1] === "/")) {
      depth += text[index] === "/" ? 1 : -1;
      out[index] = " ";
      out[index + 1] = " ";
      index += 2;
      continue;
    }
    if (text[index] !== "\n" && text[index] !== "\r") out[index] = " ";
    index += 1;
  }
  return index;
}


function quotedSqlEnd(text: string, out: string[], start: number, onSingleQuoted?: (start: number, end: number) => void): number {
  const quote = text[start];
  const escapeString = quote === "'" && /[Ee]/u.test(text[start - 1] ?? "") &&
    !SQL_IDENTIFIER_CONTINUATION.test(text[start - 2] ?? "");
  let segmentStart = start;
  out[start] = " ";
  let index = start + 1;
  while (index < text.length) {
    const character = text[index];
    // Generic SQL can use MySQL-style escapes; preserve the established conservative boundary.
    if (character === "\\" && index + 1 < text.length) {
      maskSqlRange(text, out, index, index + 2);
      index += 2;
      continue;
    }
    if (character === quote) {
      out[index] = " ";
      if (index + 1 < text.length && text[index + 1] === quote) {
        out[index + 1] = " ";
        index += 2;
        continue;
      }
      index += 1;
      if (quote === "'") onSingleQuoted?.(segmentStart, index);
      const continuation = escapedSqlContinuation(text, index, escapeString);
      if (continuation !== null) {
        maskSqlRange(text, out, index, continuation);
        segmentStart = continuation - 1;
        index = continuation;
        continue;
      }
      break;
    }
    if (character !== "\n" && character !== "\r") out[index] = " ";
    index += 1;
  }
  return index;
}


/** PostgreSQL carries E-string escaping through newline-separated segments. */
function escapedSqlContinuation(text: string, start: number, escapeString: boolean): number | null {
  if (!escapeString) return null;
  CONTINUED_QUOTE.lastIndex = start;
  return CONTINUED_QUOTE.test(text) ? CONTINUED_QUOTE.lastIndex : null;
}


function maskSqlRange(text: string, out: string[], start: number, end: number): void {
  for (let index = start;index < end;index += 1) {
    if (text[index] !== "\n" && text[index] !== "\r") out[index] = " ";
  }
}

/** The parameter marker a `${...}` substitution is replaced with before scanning. */
const SUBSTITUTION_MARKER = "?";

/** Reconstruct static SQL literals, templates, concatenations, and fragment arrays. */
export function sqlTextOf(node: TSESTree.Node): string | null {
  node = unwrapExpression(node);
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return typeof node.value === "string" ? node.value : null;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.quasis.map((q) => q.value.cooked ?? q.value.raw).join(SUBSTITUTION_MARKER);
    case AST_NODE_TYPES.TaggedTemplateExpression:
      return sqlTextOf(node.quasi);
    case AST_NODE_TYPES.BinaryExpression: {
      if (node.operator !== "+") {
        return null;
      }
      const left = sqlTextOf(node.left);
      const right = sqlTextOf(node.right);
      return left !== null && right !== null ? left + right : null;
    }
    case AST_NODE_TYPES.ArrayExpression:
      return fragmentArrayText(node);
    default:
      return null;
  }
}

/** Reconstruct one fragment array using only its supported native join contract. */
function fragmentArrayText(node: TSESTree.ArrayExpression): string | null {
  const join = joinedFragmentCall(node);
  const separator = join === null ? " " : join.arguments.length === 0 ? "," :
    join.arguments.length === 1 ? staticString(join.arguments[0]) : null;
  if (separator === null) return null;
  const parts: string[] = [];
  for (const element of node.elements) {
    if (element === null || (join !== null && unwrapExpression(element).type === AST_NODE_TYPES.ArrayExpression)) {
      return null;
    }
    const part = sqlTextOf(element);
    if (part === null) {
      return null;
    }
    parts.push(part);
  }
  return parts.length > 0 ? parts.join(separator) : null;
}

/** Return whether an array's fragments are consumed together by `.join(...)`. */
function joinedFragmentCall(node: TSESTree.ArrayExpression): TSESTree.CallExpression | null {
  const value = outerExpression(node);
  const parent = value.parent;
  const callee = parent?.type === AST_NODE_TYPES.MemberExpression ? outerExpression(parent) : null;
  return (
    parent?.type === AST_NODE_TYPES.MemberExpression &&
    parent.object === value &&
    ASTUtils.getPropertyName(parent) === "join" &&
    callee?.parent?.type === AST_NODE_TYPES.CallExpression &&
    callee.parent.callee === callee
  ) ? callee.parent : null;
}

/** Mark only text incorporated into a composite, leaving executed substitutions visible. */
function markConsumed(node: TSESTree.Node, consumed: WeakSet<TSESTree.Node>): void {
  consumed.add(node);
  const value = unwrapExpression(node);
  if (value !== node) { markConsumed(value, consumed); return; }
  if (node.type === AST_NODE_TYPES.BinaryExpression && node.operator === "+") {
    markConsumed(node.left, consumed);
    markConsumed(node.right, consumed);
  } else if (node.type === AST_NODE_TYPES.ArrayExpression) {
    for (const element of node.elements) if (element !== null) markConsumed(element, consumed);
  } else if (node.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    markConsumed(node.quasi, consumed);
  }
}

/** Hand each whole, statically resolvable SQL statement to `handler` once. */
export function createSqlListener(
  handler: (sql: string, node: TSESTree.Node, original: string) => void,
  options?: SqlNoiseOptions,
): TSESLint.RuleListener {
  const consumed = new WeakSet<TSESTree.Node>();

  const visit = (node: TSESTree.Node): void => {
    if (consumed.has(node) || isDiscardedSqlText(node)) {
      return;
    }
    const text = sqlTextOf(node);
    if (text === null) {
      return;
    }
    markConsumed(node, consumed);
    handler(stripSqlNoise(text, options), node, text);
  };

  return {
    BinaryExpression: (node: TSESTree.BinaryExpression): void => {
      visit(node);
    },
    ArrayExpression: (node: TSESTree.ArrayExpression): void => {
      const join = joinedFragmentCall(node);
      if (join === null) return;
      visit(node);
      // Unknown separators do not prove a statement. Their fragments and literal
      // separators are data; nested calls still execute and retain their visitors.
      markConsumed(node, consumed);
      const separator = join.arguments[0];
      if (separator !== undefined && staticString(separator) !== null) markConsumed(separator, consumed);
      const member = unwrapExpression(join.callee);
      if (member.type === AST_NODE_TYPES.MemberExpression && member.computed) markConsumed(member.property, consumed);
    },
    TemplateLiteral: (node: TSESTree.TemplateLiteral): void => {
      visit(node);
    },
    Literal: (node: TSESTree.Literal): void => {
      visit(node);
    },
  };
}

/** Ignore discarded text while still visiting query calls in its interpolations. */
function isDiscardedSqlText(node: TSESTree.Node): boolean {
  let current = outerExpression(node);
  let parent = current.parent;
  while (parent !== undefined && parent !== null) {
    if (parent.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "+") {
      current = outerExpression(parent);
      parent = current.parent;
      continue;
    }
    return parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "void";
  }
  return false;
}
