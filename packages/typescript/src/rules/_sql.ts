/**
 * @fileoverview _sql — shared extraction of statically-resolvable SQL strings, with literal values and comments neutralised before any keyword scan.
 *
 */

import type { ESTree, Visitor } from "@oxlint/plugins";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";

/** Mask SQL values and comments without changing text or line lengths. */
export function stripSqlNoise(text: string): string {
  return scanSqlNoise(text);
}

export function sqlSingleQuotedRanges(text: string): readonly (readonly [number, number])[] {
  const ranges: Array<readonly [number, number]> = [];
  scanSqlNoise(text, (start, end) => ranges.push([start, end]));
  return ranges;
}

function scanSqlNoise(text: string, onSingleQuoted?: (start: number, end: number) => void): string {
  const out = text.split("");
  let index = 0;
  while (index < text.length) {
    const dollarEnd = dollarQuotedSqlEnd(text, index);
    if (dollarEnd !== null) {
      maskSqlRange(text, out, index, dollarEnd);
      index = dollarEnd;
      continue;
    }
    const character = text[index];
    if (character === "'" || character === '"') {
      index = quotedSqlEnd(text, out, index, onSingleQuoted);
      continue;
    }
    if (character === "-" && text[index + 1] === "-") {
      const newline = text.indexOf("\n", index);
      const end = newline === -1 ? text.length : newline;
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
  if (text[start] !== "$" || /[\w$]/u.test(text[start - 1] ?? "")) return null;
  const delimiter = /^\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$/u.exec(text.slice(start))?.[0];
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
    if (text[index] !== "\n") out[index] = " ";
    index += 1;
  }
  return index;
}


function quotedSqlEnd(text: string, out: string[], start: number, onSingleQuoted?: (start: number, end: number) => void): number {
  const quote = text[start];
  out[start] = " ";
  let index = start + 1;
  while (index < text.length) {
    const character = text[index];
    if (character === quote) {
      out[index] = " ";
      if (index + 1 < text.length && text[index + 1] === quote) {
        out[index + 1] = " ";
        index += 2;
        continue;
      }
      index += 1;
      if (quote === "'") onSingleQuoted?.(start, index);
      break;
    }
    if (character !== "\n") out[index] = " ";
    index += 1;
  }
  return index;
}


function maskSqlRange(text: string, out: string[], start: number, end: number): void {
  for (let index = start;index < end;index += 1) {
    if (text[index] !== "\n") out[index] = " ";
  }
}

/** The parameter marker a `${...}` substitution is replaced with before scanning. */
const SUBSTITUTION_MARKER = "?";

/** Reconstruct static SQL literals, templates, concatenations, and fragment arrays. */
export function sqlTextOf(node: ESTree.Node): string | null {
  switch (node.type) {
    case "Literal":
      return typeof node.value === "string" ? node.value : null;
    case "TemplateLiteral":
      return node.quasis.map((q) => q.value.cooked ?? q.value.raw).join(SUBSTITUTION_MARKER);
    case "TaggedTemplateExpression":
      return sqlTextOf(node.quasi);
    case "BinaryExpression": {
      if (node.operator !== "+") {
        return null;
      }
      const left = sqlTextOf(node.left);
      const right = sqlTextOf(node.right);
      return left !== null && right !== null ? left + right : null;
    }
    case "ArrayExpression": {
      const parts: string[] = [];
      for (const element of node.elements) {
        if (element === null) {
          return null;
        }
        const part = sqlTextOf(element);
        if (part === null) {
          return null;
        }
        parts.push(part);
      }
      return parts.length > 0 ? parts.join(" ") : null;
    }
    default:
      return null;
  }
}

/** Return whether an array's fragments are consumed together by `.join(...)`. */
function isJoinedFragmentArray(node: ESTree.ArrayExpression): boolean {
  const parent = node.parent;
  return (
    parent?.type === "MemberExpression" &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === "Identifier" &&
    parent.property.name === "join" &&
    parent.parent?.type === "CallExpression"
  );
}

/** Every string-bearing descendant that a composite node has already absorbed. */
function markConsumed(node: ESTree.Node, consumed: WeakSet<ESTree.Node>): void {
  consumed.add(node);
  forEachOwnAstChild(node, child => markConsumed(child, consumed));
}

/** Hand each whole, statically resolvable SQL statement to `handler` once. */
export function createSqlListener(
  handler: (sql: string, node: ESTree.Node) => void,
): Visitor {
  const consumed = new WeakSet<ESTree.Node>();

  const visit = (node: ESTree.Node): void => {
    if (consumed.has(node)) {
      return;
    }
    const text = sqlTextOf(node);
    if (text === null) {
      return;
    }
    markConsumed(node, consumed);
    handler(stripSqlNoise(text), node);
  };

  return {
    BinaryExpression: (node: ESTree.BinaryExpression): void => {
      visit(node);
    },
    ArrayExpression: (node: ESTree.ArrayExpression): void => {
      if (isJoinedFragmentArray(node)) {
        visit(node);
      }
    },
    TemplateLiteral: (node: ESTree.TemplateLiteral): void => {
      visit(node);
    },
    Literal: (node: (ESTree.BooleanLiteral | ESTree.NullLiteral | ESTree.NumericLiteral | ESTree.StringLiteral | ESTree.BigIntLiteral | ESTree.RegExpLiteral)): void => {
      visit(node);
    },
  };
}
