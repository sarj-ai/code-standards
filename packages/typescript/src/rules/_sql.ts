/**
 * @fileoverview _sql — shared extraction of statically-resolvable SQL strings, with literal values and comments neutralised before any keyword scan.
 *
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

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
export function sqlTextOf(node: TSESTree.Node): string | null {
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
    case AST_NODE_TYPES.ArrayExpression: {
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
function isJoinedFragmentArray(node: TSESTree.ArrayExpression): boolean {
  const parent = node.parent;
  return (
    parent?.type === AST_NODE_TYPES.MemberExpression &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === AST_NODE_TYPES.Identifier &&
    parent.property.name === "join" &&
    parent.parent?.type === AST_NODE_TYPES.CallExpression
  );
}

/** Every string-bearing descendant that a composite node has already absorbed. */
function markConsumed(node: TSESTree.Node, consumed: WeakSet<TSESTree.Node>): void {
  consumed.add(node);
  for (const key of Object.keys(node)) {
    if (key === "parent") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    for (const child of Array.isArray(value) ? value : [value]) {
      if (child !== null && typeof child === "object" && "type" in child) {
        markConsumed(child as TSESTree.Node, consumed);
      }
    }
  }
}

/** Hand each whole, statically resolvable SQL statement to `handler` once. */
export function createSqlListener(
  handler: (sql: string, node: TSESTree.Node) => void,
): TSESLint.RuleListener {
  const consumed = new WeakSet<TSESTree.Node>();

  const visit = (node: TSESTree.Node): void => {
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
    BinaryExpression: (node: TSESTree.BinaryExpression): void => {
      visit(node);
    },
    ArrayExpression: (node: TSESTree.ArrayExpression): void => {
      if (isJoinedFragmentArray(node)) {
        visit(node);
      }
    },
    TemplateLiteral: (node: TSESTree.TemplateLiteral): void => {
      visit(node);
    },
    Literal: (node: TSESTree.Literal): void => {
      visit(node);
    },
  };
}
