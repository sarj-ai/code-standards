/**
 * @fileoverview prefer-discriminated-union — represent correlated tags and payloads as explicit variants.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-discriminated-union.test.ts
 */

import { type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { retainsNamedTypeUses } from "./_type-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { discriminatedUnionReturns, type DiscriminatedReturn } from "./_discriminated-union-returns.js";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "preferDiscriminatedUnion" | "preferProducedVariants";
type Options = readonly [];
type Producer = TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression;

export const PREFER_DISCRIMINATED_UNION_DOCUMENTATION = {
  summary: "Prefer discriminated unions for result contracts and locally proven tag-specific return payloads.",
  defaultLevel: "warning",
  rationale: "A flat object with optional branch data loses the relationship between a tag and its payload. Callers cannot narrow to the required fields, and the type permits incomplete or contradictory combinations.",
  remediation: "If the variants are mutually exclusive, represent each with a literal tag and its required payload. Preserve shared fields on every member, including payload value types and nullability. For a producer returning a subset of a broader wire contract, give the producer a precise domain return type after validation.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "The legacy boolean-result advisory recognizes local status and payload names; those names do not prove that partial-success outcomes are forbidden. Review the domain before changing its representation.",
    "Producer analysis requires a finite literal tag, every declared tag syntactically witnessed, exhaustive simple return paths without literal constant conditions, plain object returns, and consistent optional-field presence for each tag. It resolves only unmerged local aliases/interfaces without inheritance or generics, and the built-in Promise around async returns. This is syntax-only evidence of field presence; explicit undefined, void and null payloads are skipped, while expression value types are not inferred. Dynamic returns, spreads, computed keys, accessors, loops and try statements are deliberately skipped.",
    "A switch producer is supported only for a non-overloaded function declaration when its sole body statement switches on an unchanged direct string or number parameter, has unique same-kind literal labels and a default, and every nonempty case body is a sole object return or throw, optionally inside sole blocks. Empty labels may share the next terminating body; nested conditions, conditional returns, statement prefixes, breaks, other fallthrough, captured/closed inputs and switches under preceding control flow abstain. Broad parameter domains establish input witnesses for each label and the default; this does not infer branch-specific runtime effects or expression value types. Path visits, depth and returned objects are bounded conservatively.",
    "Returned variants prove this producer's key relationships, not all legal consumers of a shared type. Automatic fixes are limited to an unused private nongeneric synchronous function with a direct inline contract and one literal-object conditional return; they preserve original member types and all runtime code. Shared/observed contracts and generated/declaration/test files remain excluded.",
  ],
  references: ["https://functional-architecture.org/make_illegal_states_unrepresentable/", "https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions"],
  examples: [
    { id: "explicit-result-branches", title: "Use explicit result branches", outcome: "no-match", files: [{ path: "src/result.ts", source: "type Result = { ok: true; data: string } | { ok: false; error: string };" }], focusPath: "src/result.ts", expectedCount: 0, public: true },
    { id: "optional-result-payloads", title: "Review optional result payloads", outcome: "match", files: [{ path: "src/result.ts", source: "type Result = { ok: boolean; data?: string; error?: string };" }], focusPath: "src/result.ts", expectedCount: 1, public: true },
    { id: "flat-produced-variants", scenarioId: "produced-variants", title: "Preserve producer variant relationships", outcome: "match", files: [{ path: "src/job.ts", source: 'function job(done: boolean): { phase: "queued" | "complete"; ticket?: string } { return done ? { phase: "complete" } : { phase: "queued", ticket: "t" }; }' }], focusPath: "src/job.ts", expectedCount: 1, public: true },
    { id: "explicit-produced-variants", scenarioId: "produced-variants", title: "Give each produced variant its payload", outcome: "no-match", files: [{ path: "src/job.ts", source: 'function job(done: boolean): { phase: "queued"; ticket: string } | { phase: "complete" } { return done ? { phase: "complete" } : { phase: "queued", ticket: "t" }; }' }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    { id: "flat-switch-producer", scenarioId: "switch-producer", title: "A complete dispatcher preserves each returned variant", outcome: "match", files: [{ path: "src/job.ts", source: 'function job(command: string): { phase: "queued" | "complete"; ticket?: string } { switch (command) { case "start": return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; } }' }], focusPath: "src/job.ts", expectedCount: 1, public: true },
    { id: "explicit-switch-variants", scenarioId: "switch-producer", title: "An explicit dispatcher result supports payload narrowing", outcome: "no-match", files: [{ path: "src/job.ts", source: 'function job(command: string): { phase: "queued"; ticket: string } | { phase: "complete" } { switch (command) { case "start": return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; } }' }], focusPath: "src/job.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Preserve an unused private producer's exact existing variants",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function job(done: boolean): { phase: \"complete\" } | { phase: \"queued\"; ticket: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

/**
 * Boolean-typed member names that read as a success/error status discriminant.
 */
const STATUS_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "success",
  "ok",
]);
const FAILURE_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "error",
  "errors",
  "reason",
  "cause",
]);
const SUCCESS_PAYLOAD_MEMBER_NAMES: ReadonlySet<string> = new Set([
  "data",
  "events",
  "payload",
  "response",
  "result",
  "value",
]);

const REQUIRED_STATUS_MEMBER_COUNT = 1;

const FUNCTION_RETURN_OWNER_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.TSDeclareFunction,
  AST_NODE_TYPES.TSEmptyBodyFunctionExpression,
  AST_NODE_TYPES.TSFunctionType,
  AST_NODE_TYPES.TSMethodSignature,
]);

/**
 * Returns true for the canonical flat result shape: one required positive
 * boolean status plus optional success and failure payloads.
 */
function looksLikeMutuallyExclusiveState(
  typeLiteral: TSESTree.TSTypeLiteral,
): boolean {
  let statusMemberCount = 0;
  let hasFailurePayload = false;
  let hasSuccessPayload = false;
  let hasUnrecognizedMember = false;

  for (const member of typeLiteral.members) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) {
      hasUnrecognizedMember = true;
      continue;
    }

    const name = getMemberName(member);
    if (
      name !== null &&
      STATUS_MEMBER_NAMES.has(name) &&
      isBooleanTyped(member) &&
      !member.optional
    ) {
      statusMemberCount += 1;
      continue;
    }

    if (!member.optional || isBooleanTyped(member) || name === null) {
      hasUnrecognizedMember = true;
      continue;
    }
    if (FAILURE_MEMBER_NAMES.has(name)) {
      hasFailurePayload = true;
    } else if (SUCCESS_PAYLOAD_MEMBER_NAMES.has(name)) {
      hasSuccessPayload = true;
    } else {
      hasUnrecognizedMember = true;
    }
  }

  return (
    statusMemberCount === REQUIRED_STATUS_MEMBER_COUNT &&
    hasFailurePayload &&
    (hasSuccessPayload || !hasUnrecognizedMember)
  );
}

/**
 * Returns the property key name for a member if it is a plain identifier or
 * string-literal property signature, otherwise `null`.
 */
function getMemberName(member: TSESTree.TypeElement): string | null {
  if (member.type !== AST_NODE_TYPES.TSPropertySignature || member.computed) {
    return null;
  }
  const { key } = member;
  if (key.type === AST_NODE_TYPES.Identifier) {
    return key.name;
  }
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

/**
 * Whether a property signature is annotated with `boolean`.
 */
function isBooleanTyped(member: TSESTree.TSPropertySignature): boolean {
  return (
    member.typeAnnotation?.typeAnnotation.type ===
    AST_NODE_TYPES.TSBooleanKeyword
  );
}

/** The whole inline object returned by a function, directly or through `Promise`. */
function inlineReturnTypeLiteral(
  node: TSESTree.TSTypeLiteral,
): TSESTree.TSTypeAnnotation | null {
  let annotation: TSESTree.TSTypeAnnotation | null = null;
  if (node.parent.type === AST_NODE_TYPES.TSTypeAnnotation) {
    annotation = node.parent;
  } else if (
    node.parent.type === AST_NODE_TYPES.TSTypeParameterInstantiation &&
    node.parent.params.length === 1 &&
    node.parent.params[0] === node &&
    node.parent.parent.type === AST_NODE_TYPES.TSTypeReference &&
    node.parent.parent.typeName.type === AST_NODE_TYPES.Identifier &&
    node.parent.parent.typeName.name === "Promise" &&
    node.parent.parent.parent.type === AST_NODE_TYPES.TSTypeAnnotation
  ) {
    annotation = node.parent.parent.parent;
  }
  if (annotation === null) return null;
  const owner = annotation.parent;
  return FUNCTION_RETURN_OWNER_TYPES.has(owner.type) &&
    "returnType" in owner &&
    owner.returnType === annotation
    ? annotation
    : null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-discriminated-union",
  documentation: PREFER_DISCRIMINATED_UNION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Prefer discriminated unions for result contracts and locally proven tag-specific return payloads.",
    },
    schema: [],
    messages: {
      preferProducedVariants:
        "This producer returns tag-specific payloads for `{{tag}}`, but its flat return contract makes them optional. If these variants define the domain, use a discriminated union with each variant's required payload, or give this producer a precise return type separate from the broader contract.",
      preferDiscriminatedUnion:
        "This object type combines a boolean status with optional payloads. If success and failure are mutually exclusive, consider a discriminated union such as `{ ok: true; data: T } | { ok: false; error: E }`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context) ||
      isGeneratedFile(context, context.sourceCode.text)
    ) {
      return {};
    }

    const reportedContracts = new Set<TSESTree.Node>();
    const producers: Producer[] = [];

    function rememberProducer(node: Producer): void {
      producers.push(node);
    }

    function checkProducer(node: Producer): void {
      const result = discriminatedUnionReturns(node, context.sourceCode);
      if (result === undefined || reportedContracts.has(result.reportNode)) return;
      reportedContracts.add(result.reportNode);
      context.report({ node: result.reportNode, messageId: "preferProducedVariants",
        fix: privateVariantReturn(context.sourceCode, context.filename, node, result), data: { tag: result.tag } });
    }

    function checkTypeLiteral(
      typeLiteral: TSESTree.TSTypeLiteral,
      reportNode: TSESTree.Node,
    ): void {
      if (looksLikeMutuallyExclusiveState(typeLiteral) && !reportedContracts.has(reportNode)) {
        reportedContracts.add(reportNode);
        context.report({
          node: reportNode,
          messageId: "preferDiscriminatedUnion",
          fix: inlineProducerFix(reportNode),
        });
      }
    }

    function inlineProducerFix(reportNode: TSESTree.Node): TSESLint.ReportFixFunction | null {
      if (reportNode.type !== AST_NODE_TYPES.TSTypeAnnotation || reportNode.parent.type !== AST_NODE_TYPES.FunctionDeclaration) return null;
      const owner = reportNode.parent;
      const result = discriminatedUnionReturns(owner, context.sourceCode);
      return result === undefined ? null : privateVariantReturn(context.sourceCode, context.filename, owner, result);
    }

    return {
      ArrowFunctionExpression: rememberProducer,
      FunctionDeclaration: rememberProducer,
      FunctionExpression: rememberProducer,
      "Program:exit"(): void {
        // Alias declarations can follow their producers. Always give the legacy
        // contract diagnostic precedence independent of declaration order.
        for (const producer of producers) checkProducer(producer);
      },
      TSInterfaceDeclaration(
        node: TSESTree.TSInterfaceDeclaration,
      ): void {
        if (node.extends.length > 0) {
          return;
        }
        // An interface body is structurally an object type literal; reuse the
        // same membership analysis by treating its `body.body` as members.
        const synthetic: TSESTree.TSTypeLiteral = {
          ...node.body,
          type: AST_NODE_TYPES.TSTypeLiteral,
          members: node.body.body,
        };
        checkTypeLiteral(synthetic, node);
      },
      "TSTypeAliasDeclaration > TSTypeLiteral"(
        node: TSESTree.TSTypeLiteral,
      ): void {
        checkTypeLiteral(node, node.parent);
      },
      TSTypeLiteral(node: TSESTree.TSTypeLiteral): void {
        const annotation = inlineReturnTypeLiteral(node);
        if (annotation !== null) checkTypeLiteral(node, annotation);
      },
    };
  },
});

function privateVariantReturn(sourceCode: Readonly<TSESLint.SourceCode>, filename: string, owner: Producer, result: DiscriminatedReturn): TSESLint.ReportFixFunction | null {
  const annotation = owner.returnType?.typeAnnotation;
  const returned = owner.body?.type === AST_NODE_TYPES.BlockStatement ? owner.body.body[0] : undefined;
  if (owner.type !== AST_NODE_TYPES.FunctionDeclaration || owner.id === null || owner.async || owner.generator || owner.typeParameters !== undefined ||
    annotation?.type !== AST_NODE_TYPES.TSTypeLiteral || result.reportNode !== owner.returnType ||
    owner.body?.body.length !== 1 || returned?.type !== AST_NODE_TYPES.ReturnStatement || returned.argument?.type !== AST_NODE_TYPES.ConditionalExpression ||
    returned.argument.consequent.type !== AST_NODE_TYPES.ObjectExpression || returned.argument.alternate.type !== AST_NODE_TYPES.ObjectExpression ||
    result.returned.length !== 2 || sourceCode.getCommentsInside(owner).length > 0 || !isUnusedPrivateBinding(sourceCode, owner, owner.id, filename) ||
    !retainsNamedTypeUses(sourceCode, annotation)) return null;
  const variants = result.returned.map((properties) => privateVariantType(properties, result, sourceCode));
  if (variants.some((variant) => variant === null)) return null;
  const text = `${variants.join(" | ")}${sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")}`;
  return (fixer) => fixer.replaceText(annotation, text);
}

function privateVariantType(properties: ReadonlyMap<string, TSESTree.Node>, result: DiscriminatedReturn, sourceCode: Readonly<TSESLint.SourceCode>): string | null {
  if ([...properties.values()].some((value) => value.type !== AST_NODE_TYPES.Literal ||
    (typeof value.value === "object" && value.value !== null) || (typeof value.value === "number" && !Number.isFinite(value.value)))) return null;
  const fields: string[] = [];
  for (const [name, member] of result.members) {
    const value = properties.get(name);
    if (value === undefined) continue;
    const annotation = member.typeAnnotation?.typeAnnotation;
    if (annotation === undefined) return null;
    const type = name === result.tag ? sourceCode.getText(value) : sourceCode.getText(annotation);
    fields.push(`${member.readonly ? "readonly " : ""}${sourceCode.getText(member.key)}: ${type}`);
  }
  return `{ ${fields.join("; ")} }`;
}
