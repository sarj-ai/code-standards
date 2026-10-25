/**
 * @fileoverview prefer-minimal-parameter-contract — reduce proven private read-only dependencies.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-minimal-parameter-contract.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils } from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { consumerAnnotation, directEval, exportedSymbols, primitiveKeyword, privateScalarConsumer, type ScalarConsumerNode } from "./_private-scalar-consumer.js";

const CONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler"}}' } as const;
const EXAMPLE = 'export {}; const account = {name: "Ada", email: "a"}; function label(user: {readonly name: string; readonly email: string}): string {return user.name;} label(account);';

export const PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer the proven read-only subset for a private consumer parameter.",
  rationale: "A private scalar consumer can unnecessarily require data it never reads. Removing unused required fields accepts more structural values while preserving the original runtime object and producer information.",
  remediation: "Review a smaller existing contract, Pick or interface containing the read fields and preserving readonly and optional modifiers. Change the consumer annotation; a new runtime projection has different identity and allocation costs. No automatic API or object rewrite is provided.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires parser-owned TypeScript information and a strict external module. Only top-level private function declarations and raw const arrows with exactly one explicit parameter and an independent broad primitive return annotation are supported. Every callable reference must be a direct call with one identifier argument; exports including type-only exports, typeof queries, callbacks, storage, constructors, contextual signatures, overloads, generics, decorators, async functions and direct eval prevent findings.",
    "Only anonymous inline contracts made of explicitly readonly string, number, boolean or bigint properties are supported. Named domain contracts, brands, literal discriminants, classes, methods, callbacks, indexes, mapped types and imported parameter contracts are excluded. At least one read required field and one unread required field must be established; all-optional reduced contracts can reject existing callers through weak-type checks.",
    "The single return expression may use only fixed scalar field reads, flat destructuring, literals, operators and templates. Bound destructured fields count as reads even when their local aliases are unused. Whole-object escape, identity, helper calls, mutation, closures, reflection, serialization, dynamic keys, implicit Object capabilities and JSX are unsupported. Unknown semantic information causes abstention. This is a report-only dependency judgment, not a requirement to minimize every object or discard useful producer fields.",
  ],
  examples: [
    { id: "unused-required-field", title: "A private name consumer unnecessarily requires email", outcome: "match", files: [{ path: "src/case.ts", source: EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true },
    { id: "used-fields", title: "Every required dependency is read", outcome: "no-match", files: [{ path: "src/case.ts", source: EXAMPLE.replace("return user.name;", 'return user.name + user.email;') }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function inlineFields(node: ts.TypeLiteralNode): ReadonlyMap<string, boolean> | null {
  const fields = new Map<string, boolean>();
  for (const member of node.members) {
    if (!ts.isPropertySignature(member) || !member.name || (!ts.isIdentifier(member.name) && !ts.isStringLiteralLike(member.name)) ||
      member.modifiers?.length !== 1 || member.modifiers[0]?.kind !== ts.SyntaxKind.ReadonlyKeyword || !primitiveKeyword(member.type)) return null;
    const key = member.name.text;
    if (fields.has(key)) return null;
    fields.set(key, !member.questionToken);
  }
  return fields;
}

export default createRule<[], "minimal">({
  name: "prefer-minimal-parameter-contract",
  documentation: PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION,
  meta: { type: "suggestion", docs: { description: PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION.summary }, schema: [], messages: {
    minimal: "This private consumer reads only {{used}} but also requires {{unused}}. Review a smaller readonly consumer contract; preserve the original runtime object and producer type.",
  } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const candidates: ScalarConsumerNode[] = [];
    let dynamic = false;
    const remember = (node: ScalarConsumerNode): void => {
      if (consumerAnnotation(node)?.type === AST_NODE_TYPES.TSTypeLiteral) candidates.push(node);
    };
    return {
      FunctionDeclaration: remember,
      ArrowFunctionExpression: remember,
      CallExpression(node): void { if (directEval(node)) dynamic = true; },
      "Program:exit"(): void {
        if (dynamic || !candidates.length) return;
        const services = ESLintUtils.getParserServices(context);
        const checker = services.program.getTypeChecker();
        const exports = exportedSymbols(services.esTreeNodeToTSNodeMap.get(context.sourceCode.ast), checker);
        for (const candidate of candidates) {
          const consumer = privateScalarConsumer(candidate, context.sourceCode, services, exports);
          const annotation = consumer?.parameter.type;
          if (!consumer || !annotation || !ts.isTypeLiteralNode(annotation)) continue;
          const fields = inlineFields(annotation);
          if (!fields || [...consumer.reads].some((key) => !fields.has(key)) || ![...consumer.reads].some((key) => fields.get(key))) continue;
          const unused = [...fields].filter(([key, required]) => required && !consumer.reads.has(key)).map(([key]) => key).sort();
          if (unused.length) context.report({ node: services.tsNodeToESTreeNodeMap.get(annotation), messageId: "minimal", data: { used: [...consumer.reads].sort().join(", "), unused: unused.join(", ") } });
        }
      },
    };
  },
});
