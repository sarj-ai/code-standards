/**
 * @fileoverview no-typed-doc-sections — typed signatures do not need parameter or return tables.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-typed-doc-sections.test.ts
 */

import type { TSESLint, TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { proseGroups } from "./_prose-budget.js";

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
  readonly explicitType: string | null;
}

type Signature = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression | TSESTree.TSDeclareFunction | TSESTree.TSMethodSignature | TSESTree.TSEmptyBodyFunctionExpression;

function parameterTarget(parameter: TSESTree.Parameter): TSESTree.Node {
  if (parameter.type === "TSParameterProperty") return parameterTarget(parameter.parameter);
  return parameter.type === "AssignmentPattern" ? parameter.left : parameter;
}

function documentedSignature(sourceCode: Readonly<TSESLint.SourceCode>, comment: TSESTree.Comment): Signature | null {
  const before = sourceCode.getTokenBefore(comment);
  if (before?.loc.end.line === comment.loc.start.line) return null;
  const token = sourceCode.getTokenAfter(comment);
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return null;
  let node = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node !== null && node.type !== "Program" && node.type !== "BlockStatement" && node.type !== "ClassBody") {
    const signature = functionSignature(node);
    if (signature !== null) {
      return signature.returnType !== undefined && signature.params.every((parameter) => {
        const target = parameterTarget(parameter);
        return "typeAnnotation" in target && target.typeAnnotation != null;
      }) ? signature : null;
    }
    node = node.parent ?? null;
  }
  return null;
}

function functionSignature(node: TSESTree.Node): Signature | null {
  switch (node.type) {
    case "ExportNamedDeclaration":
    case "ExportDefaultDeclaration":
      return node.declaration === null ? null : functionSignature(node.declaration);
    case "FunctionDeclaration":
    case "FunctionExpression":
    case "ArrowFunctionExpression":
    case "TSDeclareFunction":
    case "TSMethodSignature":
      return node;
    case "MethodDefinition":
      return node.value;
    case "VariableDeclaration": {
      const init = node.declarations.length === 1 ? node.declarations[0]?.init : null;
      return init?.type === "ArrowFunctionExpression" || init?.type === "FunctionExpression" ? init : null;
    }
    default:
      return null;
  }
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
    const typeMatch = /^\{([^}\n]+)\}\s*/u.exec(payload);
    const explicitType = typeMatch?.[1]?.trim() ?? null;
    let rest = payload.slice(typeMatch?.[0].length ?? 0).trim();
    if (!PARAM_TAGS.has(kind)) {
      return { kind, name: null, description: rest.replace(/^-\s+/u, "").trim(), explicitType };
    }
    const match = /^(\[[^\]]+\]|[A-Za-z_$][\w$.[\]-]*)(?:\s+-\s+|\s+)?(.*)$/u.exec(rest);
    const rawName = match?.[1] ?? "";
    if (match === null || !/^[A-Za-z_$][\w$]*$/u.test(rawName)) return { kind, name: null, description: rest, explicitType };
    rest = (match[2] ?? "").trim();
    return { kind, name: rawName, description: rest, explicitType };
  });
}

function isVacuousTag(tag: TypedTag, signature: Signature, sourceCode: Readonly<TSESLint.SourceCode>): boolean {
  let annotation = signature.returnType;
  if (PARAM_TAGS.has(tag.kind)) {
    const parameter = signature.params.map(parameterTarget).find((node) => node.type === "Identifier" && node.name === tag.name);
    if (parameter?.type !== "Identifier") return false;
    annotation = parameter.typeAnnotation;
  }
  if (annotation === undefined) return false;
  if (tag.explicitType !== null && (
    !/^(?:string|number|boolean|bigint|symbol|unknown|never|void|null|undefined)$/u.test(tag.explicitType) ||
    sourceCode.getText(annotation.typeAnnotation) !== tag.explicitType
  )) return false;
  if (/[^\p{L}\p{M}\s.,]/u.test(tag.description)) return false;
  const description = words(tag.description).map(canonicalWord);
  if (description.length === 0) return tag.description.length === 0;
  if (tag.name === null) return description.every((word) => RESULT_FILLER.has(word));
  const nameWords = new Set(words(tag.name).map(canonicalWord));
  return description.every((word) => PARAMETER_FILLER.has(word) || nameWords.has(word));
}

function words(text: string): string[] {
  return text
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .toLowerCase()
    .match(/[\p{L}\p{M}][\p{L}\p{M}\p{N}]*/gu) ?? [];
}

function canonicalWord(word: string): string {
  if (["identifier", "identifiers", "ids"].includes(word)) return "id";
  if (word.endsWith("s") && word.length > 3) return word.slice(0, -1);
  return word;
}

export const NO_TYPED_DOC_SECTIONS_DOCUMENTATION = {
  summary: "Reject typed-signature repetition while preserving behavior that types cannot express.",
  rationale:
    "Parameter and return tags repeat typed signatures and can drift without adding runtime behavior or constraints.",
  remediation: "Remove repeated parameter and return tags; retain documentation for behavior, failures, and external contracts.",
  category: "maintainability",
  limitations: ["Description-free or name-restating tags require the adjacent explicitly typed signature and a corresponding parameter name. Optional/defaulted or nested parameter tags and unproven explicit JSDoc types are preserved."],
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
  documentation: NO_TYPED_DOC_SECTIONS_DOCUMENTATION,
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
          const signature = documentedSignature(context.sourceCode, group.comment);
          if (
            group.hasTypedTags &&
            signature !== null &&
            typedTags(group.text).some((tag) => isVacuousTag(tag, signature, context.sourceCode))
          ) {
            context.report({ node: group.comment, messageId: "typedSection" });
          }
        }
      },
    };
  },
});
