/**
 * @fileoverview no-vague-suppression-description — a suppression reason must name the concrete mismatch or invariant, not merely claim the suppression is needed.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-vague-suppression-description.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds =
  | "vagueDescription"
  | "missingDescription"
  | "missingRules"
  | "lineOnly"
  | "legacyDirective"
  | "restrictedRule"
  | "duplicateRule";
type Options = readonly [];

const OXLINT_DIRECTIVE_RE =
  /^oxlint-(disable-next-line|disable-line|disable|enable)\b(.*)$/u;
const LEGACY_DIRECTIVE_RE =
  /^eslint(?:\s|$|-(?:disable|enable)(?:-next-line|-line)?\b)/u;
const PROTECTED_NATIVE_RULES: ReadonlySet<string> = new Set([
  "no-console",
  "exhaustive-deps",
]);
const PROTECTED_PLUGIN_RULES: ReadonlySet<string> = new Set([
  "sarj-react-hooks/exhaustive-deps",
  "@sarj/no-vague-suppression-description",
]);
const TS_EXPECT_ERROR_WITH_DESCRIPTION_RE =
  /^@ts-expect-error\b(?:(?:\s*(?::|--)\s*)|\s+)(.+?)\s*$/iu;
const VAGUE_RE =
  /^(?:needed|required|intentional(?:ly)?|ignore(?:d)?|false positive|type error|typescript|to satisfy (?:the )?(?:linter|typescript|type checker))\.?$/iu;

export const NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION = {
  summary:
    "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
  rationale:
    "Suppressions must name the affected rules, cover a single line, and explain the concrete risk so reviewers can audit and remove them.",
  remediation:
    "Name the exact type/runtime mismatch, external contract, or safety invariant that makes this suppression acceptable.",
  category: "maintainability",
  limitations: [
    "Oxlint disable comments and TypeScript expect-error descriptions are checked. ESLint directives must be migrated to native Oxlint directives.",
    "The rule uses a small anchored vocabulary and does not score prose quality generally.",
    "Generated files and descriptions outside that exact vocabulary are excluded; an unflagged reason is not proof of a justified suppression. TypeScript ban-ts-comment owns missing expect-error descriptions. Native suppression processing can suppress this rule itself; protected rule directives must also be reviewed.",
  ],
  examples: [
    {
      id: "concrete-runtime-mismatch",
      title: "Explain the concrete runtime contract",
      outcome: "no-match",
      files: [
        {
          path: "src/adapter.ts",
          source:
            "function requestId(response: object) {\n  // @ts-expect-error -- vendor types omit the runtime requestId field\n  return response.requestId;\n}",
        },
      ],
      focusPath: "src/adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "generic-suppression-reason",
      title: "Reject a suppression with no auditable reason",
      outcome: "match",
      files: [
        {
          path: "src/adapter.ts",
          source:
            "function requestId(response: object) {\n  // @ts-expect-error -- false positive\n  return response.requestId;\n}",
        },
      ],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type SuppressionProblem = {
  messageId: MessageIds;
  data?: Record<string, string>;
};

function descriptionProblems(
  description: string | undefined,
): SuppressionProblem[] {
  return description !== undefined && VAGUE_RE.test(description)
    ? [{ messageId: "vagueDescription", data: { description } }]
    : [];
}

function suppressionProblems(text: string): SuppressionProblem[] {
  if (LEGACY_DIRECTIVE_RE.test(text)) return [{ messageId: "legacyDirective" }];
  const directive = OXLINT_DIRECTIVE_RE.exec(text);
  if (directive !== null)
    return nativeDirectiveProblems(directive[1]!, directive[2] ?? "");
  return descriptionProblems(
    TS_EXPECT_ERROR_WITH_DESCRIPTION_RE.exec(text)?.[1]?.trim(),
  );
}

function nativeDirectiveProblems(
  kind: string,
  body: string,
): SuppressionProblem[] {
  if (kind !== "disable-line" && kind !== "disable-next-line")
    return [{ messageId: "lineOnly" }];
  const separator = body.indexOf("--");
  const rules = (separator < 0 ? body : body.slice(0, separator)).trim();
  const description =
    separator < 0 ? undefined : body.slice(separator + 2).trim();
  const problems: SuppressionProblem[] = [];
  if (rules.length === 0) problems.push({ messageId: "missingRules" });
  const seen = new Set<string>();
  for (const rule of rules
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)) {
    if (
      PROTECTED_NATIVE_RULES.has(rule.slice(rule.lastIndexOf("/") + 1)) ||
      PROTECTED_PLUGIN_RULES.has(rule)
    )
      problems.push({ messageId: "restrictedRule", data: { rule } });
    if (seen.has(rule))
      problems.push({ messageId: "duplicateRule", data: { rule } });
    seen.add(rule);
  }
  if (!description) problems.push({ messageId: "missingDescription" });
  return [...problems, ...descriptionProblems(description)];
}

export default createRule<Options, MessageIds>({
  name: "no-vague-suppression-description",
  documentation: NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
    },
    schema: [],
    messages: {
      missingDescription:
        "Oxlint suppressions require a concrete description after `--`.",
      missingRules:
        "Oxlint suppressions must name the individual rules; suppressing every rule is prohibited.",
      lineOnly:
        "Use oxlint-disable-line or oxlint-disable-next-line; range and whole-file directives are prohibited.",
      legacyDirective:
        "Replace this ESLint directive with a native Oxlint line directive and explicit native rule IDs.",
      restrictedRule: "The protected rule `{{rule}}` cannot be disabled.",
      duplicateRule: "Suppression rule `{{rule}}` is listed more than once.",
      vagueDescription:
        "Suppression description `{{description}}` does not explain why the suppressed diagnostic is safe here. Name the concrete type/runtime mismatch, external contract, or invariant.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(
        sourceOrigin(context).filename,
        sourceOrigin(context).text,
      )
    ) {
      return {};
    }
    return {
      Program(): void {
        for (const comment of context.sourceCode.getAllComments()) {
          for (const problem of suppressionProblems(comment.value.trim())) {
            context.report({ loc: comment.loc, ...problem });
          }
        }
      },
    };
  },
});
