/**
 * @fileoverview no-typed-doc-sections — typed signatures do not need parameter or return tables.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-typed-doc-sections.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { documentsTypedFunction, proseGroups } from "./_prose-budget.js";

type MessageIds = "typedSection";
type Options = readonly [];

const TYPED_TAG_RE = /^\s*@(arg|argument|param|return|returns|yield|yields)\b(.*)$/iu;
const PARAM_TAGS: ReadonlySet<string> = new Set(["arg", "argument", "param"]);
const PARAMETER_FILLER: ReadonlySet<string> = new Set([
  "a", "an", "argument", "given", "input", "parameter", "passed", "provided", "the", "value",
]);
const RESULT_FILLER: ReadonlySet<string> = new Set([
  "a", "an", "array", "boolean", "generator", "number", "object", "output", "promise", "result",
  "return", "returned", "returns", "string", "the", "value",
]);

interface TypedTag {
  readonly kind: string;
  readonly name: string | null;
  readonly description: string;
}

function hasVacuousTypedTag(text: string): boolean {
  const tags = typedTags(text);
  return tags.length > 0 && tags.some(isVacuousTag);
}

function typedTags(text: string): TypedTag[] {
  const tags: Array<{ kind: string; payload: string }> = [];
  for (const raw of text.split("\n")) {
    const match = TYPED_TAG_RE.exec(raw);
    if (match !== null) {
      tags.push({ kind: (match[1] ?? "").toLowerCase(), payload: (match[2] ?? "").trim() });
    } else if (tags.length > 0 && raw.trim().length > 0 && !raw.trim().startsWith("@")) {
      const last = tags.at(-1)!;
      last.payload = `${last.payload} ${raw.trim()}`.trim();
    }
  }
  return tags.map(({ kind, payload }) => {
    let rest = payload.replace(/^\{[^}\n]+\}\s*/u, "").trim();
    if (!PARAM_TAGS.has(kind)) {
      return { kind, name: null, description: rest.replace(/^-\s*/u, "").trim() };
    }
    const match = /^(\[[^\]]+\]|[A-Za-z_$][\w$.[\]-]*)(?:\s+-\s*|\s+)?(.*)$/u.exec(rest);
    if (match === null) return { kind, name: null, description: "" };
    const rawName = (match[1] ?? "").replace(/^\[/u, "").replace(/\]$/u, "").split("=")[0] ?? "";
    rest = (match[2] ?? "").trim();
    return { kind, name: rawName, description: rest };
  });
}

function isVacuousTag(tag: TypedTag): boolean {
  const description = words(tag.description).map(canonicalWord);
  if (description.length === 0) return true;
  if (tag.name === null) return description.every((word) => RESULT_FILLER.has(word));
  const nameWords = new Set(words(tag.name).map(canonicalWord));
  return description.every((word) => PARAMETER_FILLER.has(word) || nameWords.has(word));
}

function words(text: string): string[] {
  return text
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .toLowerCase()
    .match(/[a-z][a-z0-9]*/gu) ?? [];
}

function canonicalWord(word: string): string {
  if (["identifier", "identifiers", "ids"].includes(word)) return "id";
  if (word.endsWith("s") && word.length > 3) return word.slice(0, -1);
  return word;
}

export const noTypedDocSectionsDocumentation = {
  summary: "Reject typed-signature repetition while preserving behavior that types cannot express.",
  rationale:
    "Parameter and return tags repeat typed signatures and can drift without adding runtime behavior or constraints.",
  remediation: "Remove repeated parameter and return tags; retain documentation for behavior, failures, and external contracts.",
  category: "maintainability",
  limitations: ["Description-free or name-restating parameter and return tags are reported only when the documented function has corresponding explicit TypeScript types."],
  examples: [
    {
      id: "behavioral-documentation",
      title: "Keep behavior that the signature cannot express",
      outcome: "no-match",
      files: [{ path: "src/client.ts", source: "/** Retries when the vendor returns 429. */\nexport function fetchValue(id: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-parameter",
      title: "Do not expand a typed parameter's name",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "/** @param userId the user identifier */\nexport function fetchValue(userId: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-typed-doc-sections",
  documentation: noTypedDocSectionsDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Reject typed-signature repetition while preserving behavior that types cannot express." },
    schema: [],
    messages: {
      typedSection:
        "Typed JSDoc repeats parameters or returns — delete the repeated tags; if the signature still needs explanation, improve its names or types. Keep constraints and rationale.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode, true)) {
          if (
            group.hasTypedTags &&
            hasVacuousTypedTag(group.text) &&
            documentsTypedFunction(context.sourceCode, group.comment)
          ) {
            context.report({ node: group.comment, messageId: "typedSection" });
          }
        }
      },
    };
  },
});
