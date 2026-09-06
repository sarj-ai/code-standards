/**
 * @fileoverview no-trailing-value-narration — a trailing comment restating the literal beside it drifts the moment someone edits the arithmetic.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-trailing-value-narration.test.ts
 */

import { AST_TOKEN_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { trailingCommentRemovalRange } from "./_comment-edits.js";
import { codeTokens, hasExternalReference, stem } from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "deleteNarration" | "narratesValue" | "removeNarration";
type Options = readonly [];

export const NO_TRAILING_VALUE_NARRATION_DOCUMENTATION = {
  summary: "Flag a trailing comment that repeats the line's numeric value only to name its unit.",
  rationale: "A repeated value can disagree with the expression after either the code or comment changes.",
  remediation: "Put the unit in the identifier and keep comments only when they explain a constraint or non-obvious conversion.",
  category: "maintainability",
  autofix: "suggestion",
  aliases: ["trailing-value-narration"],
  limitations: ["Only attached declaration, property, or assignment values containing numeric tokens and comments with recognized unit words are inspected. Deletion requires a numeric literal and the same unit on its owner. Constraints, additional prose, unknown expressions on unit-bearing owners, and cross-unit annotations are preserved; conversions are not evaluated."],
  examples: [
    {
      id: "explain-constraint",
      title: "Explain a domain constraint",
      outcome: "no-match",
      files: [{ path: "src/timeouts.ts", source: "const timeout = 5 * 60; // 5 minutes for cold starts" }],
      focusPath: "src/timeouts.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeat-duration",
      title: "Do not narrate the numeric duration",
      outcome: "match",
      files: [{ path: "src/timeouts.ts", source: "const staleTime = 5 * 60 * 1000; // 5 minutes" }],
      focusPath: "src/timeouts.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

// A number that is not part of an identifier or a dotted member path.
const NUMBER_RE = /(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])/g;
const WORD_RE = /[\p{L}\p{M}]+(?:'[\p{L}\p{M}]+)?|\d+(?:\.\d+)?/gu;

// Words that name the unit rather than the quantity — the one thing the code
// does not say, and the reason the fix is a *name*, not a deletion.
const UNIT_WORDS: ReadonlySet<string> = new Set([
  "bytes", "characters", "chars", "day", "days", "gb", "hour", "hours", "hr",
  "hrs", "hz", "items", "k", "kb", "khz", "m", "mb", "milliseconds", "min",
  "mins", "minute", "minutes", "ms", "pct", "percent", "px", "retries", "rows",
  "s", "sec", "second", "seconds", "secs", "times", "tokens",
]);

const STOPWORDS: ReadonlySet<string> = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "in", "is", "it",
  "of", "on", "or", "that", "the", "this", "we", "with",
]);

const DIRECTIVE_RE =
  /^\s*(?:eslint\b|eslint-|sarj-noqa\b|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|todo\b|fixme\b|hack\b|xxx\b)/i;

const UNIT_NAME_SUFFIX_RE =
  /(?:_(?:NS|US|MS|S|SEC|SECS|SECOND|SECONDS|MIN|MINS|MINUTE|MINUTES|HOUR|HOURS|DAY|DAYS|BYTE|BYTES|KB|MB|GB|HZ|KHZ|MHZ|PX)|(?:Ns|Us|Ms|Sec|Secs|Second|Seconds|Min|Mins|Minute|Minutes|Hour|Hours|Day|Days|Byte|Bytes|Kb|Mb|Gb|Hz|Khz|Mhz|Px))$/u;

function narratesValue(body: string, code: string, codeNumbers: ReadonlySet<string>): boolean {
  if (body.length === 0 || DIRECTIVE_RE.test(body) || hasExternalReference(body)) return false;
  if (/[^\p{L}\p{M}\p{N}\s.,:()_]/u.test(body)) return false;
  if (codeNumbers.size === 0) return false;
  const words = (body.match(WORD_RE) ?? []).map((word) => word.toLowerCase());
  if (words.length === 0) return false;
  const commentNumbers = numbersIn(body);
  if (commentNumbers.size === 0) return false;
  for (const number of commentNumbers) {
    if (!codeNumbers.has(number)) return false;
  }
  if (!words.some((word) => UNIT_WORDS.has(word))) return false;
  const identifiers = codeTokens(code);
  const stems = new Set<string>();
  for (const token of identifiers) stems.add(stem(token));
  return words.every(
    (word) =>
      STOPWORDS.has(word) ||
      UNIT_WORDS.has(word) ||
      commentNumbers.has(word) ||
      identifiers.has(word) ||
      stems.has(stem(word)),
  );
}

function numbersIn(text: string): Set<string> {
  return new Set(text.match(NUMBER_RE) ?? []);
}

function canonicalUnit(word: string): string {
  switch (word) {
    case "milliseconds": return "ms";
    case "sec": case "secs": case "second": case "seconds": return "s";
    case "mins": case "minute": case "minutes": return "min";
    case "hr": case "hrs": case "hours": return "hour";
    case "days": return "day";
    case "bytes": return "byte";
    default: return word;
  }
}

function identifierUnit(node: TSESTree.Node): string | null {
  if (node.type === "MemberExpression" && !node.computed) return identifierUnit(node.property);
  if (node.type !== "Identifier") return null;
  const suffix = UNIT_NAME_SUFFIX_RE.exec(node.name)?.[0];
  return suffix === undefined ? null : canonicalUnit(suffix.replace(/^_/u, "").toLowerCase());
}

export default createRule<Options, MessageIds>({
  name: "no-trailing-value-narration",
  documentation: NO_TRAILING_VALUE_NARRATION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    docs: {
      description:
        "Flag a trailing comment that repeats the line's numeric value only to name its unit.",
    },
    schema: [],
    messages: {
      deleteNarration:
        "Trailing comment restates the literal and the identifier already names its unit — delete the comment so it cannot drift.",
      narratesValue:
        "Consider putting the unit in the name if this comment only narrates the value; keep conversion details and constraints.",
      removeNarration: "Delete the redundant trailing narration.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;

    function isTrailing(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return before !== null && before.loc.end.line === comment.loc.start.line;
    }

    function isInsideBrackets(comment: TSESTree.Comment): boolean {
      let node: TSESTree.Node | null | undefined = sourceCode.getNodeByRangeIndex(comment.range[0]);
      while (node != null) {
        if (node.type === "BlockStatement" || node.type === "Program") return false;
        if (
          node.type === "ArrayExpression" ||
          node.type === "CallExpression" ||
          node.type === "NewExpression"
        ) {
          return true;
        }
        node = node.parent;
      }
      return false;
    }

    function attachedValue(comment: TSESTree.Comment): { name: TSESTree.Node; value: TSESTree.Node } | null {
      let token = sourceCode.getTokenBefore(comment);
      if (token?.value === ";" || token?.value === ",") token = sourceCode.getTokenBefore(token);
      if (token === null) return null;
      let node = sourceCode.getNodeByRangeIndex(token.range[0]);
      while (node !== null && node.type !== "Program") {
        if (node.range[1] <= comment.range[0]) {
          if (node.type === "VariableDeclarator" && node.id.type === "Identifier" && node.init !== null) {
            return { name: node.id, value: node.init };
          }
          if (node.type === "Property" && !node.computed && node.kind === "init" && node.parent.type === "ObjectExpression") {
            return { name: node.key, value: node.value };
          }
          if (node.type === "PropertyDefinition" && !node.computed && node.value !== null) {
            return { name: node.key, value: node.value };
          }
          if (node.type === "AssignmentExpression" && node.operator === "=") {
            if (node.left.type !== "Identifier" && (node.left.type !== "MemberExpression" || node.left.computed)) return null;
            return { name: node.left, value: node.right };
          }
        }
        node = node.parent ?? null;
      }
      return null;
    }

    return {
      Program(): void {
        for (const comment of sourceCode.getAllComments()) {
          if (!isTrailing(comment) || isInsideBrackets(comment)) continue;
          const attached = attachedValue(comment);
          if (attached === null) continue;
          const code = `${sourceCode.getText(attached.name)} ${sourceCode.getText(attached.value)}`;
          const codeNumbers = new Set(sourceCode.getTokens(attached.value)
            .filter((token) => token.type === AST_TOKEN_TYPES.Numeric)
            .flatMap((token) => [...numbersIn(token.value)]));
          const body = comment.value.replace(/^\*+/, "").replace(/\*+$/, "").trim();
          if (narratesValue(body, code, codeNumbers)) {
            const namedUnit = identifierUnit(attached.name);
            if (namedUnit !== null && (attached.value.type !== "Literal" || typeof attached.value.value !== "number")) continue;
            const units = (body.match(WORD_RE) ?? []).map((word) => word.toLowerCase()).filter((word) => UNIT_WORDS.has(word));
            if (namedUnit !== null && !units.every((word) => canonicalUnit(word) === namedUnit)) continue;
            const canDelete = namedUnit !== null;
            const removal = canDelete
              ? trailingCommentRemovalRange(sourceCode.text, comment)
              : null;
            context.report({
              node: comment,
              messageId: canDelete ? "deleteNarration" : "narratesValue",
              suggest: removal === null
                ? null
                : [
                    {
                      messageId: "removeNarration",
                      fix: (fixer) => fixer.removeRange(removal.range),
                    },
                  ],
            });
          }
        }
      },
    };
  },
});
