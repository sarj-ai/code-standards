/**
 * @fileoverview no-redundant-consumer-union — retain proven covering private object contracts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-consumer-union.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils } from "@typescript-eslint/utils";
import ts from "typescript";

import { closedObjectContract } from "./_closed-object-contract.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { consumerAnnotation, directEval, exportedSymbols, primitiveKeyword, privateScalarConsumer, type ScalarConsumerNode } from "./_private-scalar-consumer.js";

const CONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler"}}' } as const;
const EXAMPLE = 'export {}; interface Animal {readonly name: string} interface Dog extends Animal {readonly breed: string} const dog = {name: "Ada", breed: "Collie"}; function label(value: Dog | Animal): string {return value.name;} label(dog);';

export const NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep the covering object contract in a private scalar consumer union.",
  rationale: "A private consumer can advertise a redundant object alternative even though native assignability proves that the other alternative accepts every covered value. Dog | Animal keeps Animal; requiring Dog would unnecessarily restrict callers.",
  remediation: "Review retaining the covering alternative, or revise the alternatives if distinct cases were intended. Preserve producer types and runtime objects. This warning never rewrites public APIs, annotations or runtime projections automatically.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Only an inline binary parameter union in a strict module's top-level private scalar consumer is supported. Exactly one parameter, an explicit broad primitive return annotation, a single pure returned scalar expression and direct identifier-argument callers are required. Type queries, type-only exports, public APIs, callbacks, contextual signatures, overloads, generics, decorators, async functions, direct eval and fresh-object callers prevent findings.",
    "Both alternatives must have complete ordinary finite structural surfaces consisting only of explicitly readonly broad string, number, boolean or bigint properties. Aliases, imports, re-exports and ordinary inheritance are resolved by the parser-owned TypeScript checker. Any, unknown, missing imports, open/generic/mapped/indexed types, classes, brands, literal discriminants, methods, properties with scalar type aliases, callbacks and recursive or nested object fields are unsupported.",
    "Reports only proper native assignability: covered is assignable to covering and the reverse is false. Every covering member, including optional members, must exist in the covered type's enumerated declared surface. Otherwise an existing identifier may carry an incompatible extra field and be rejected after simplification; implicit Object members containing Any also cannot witness coverage. The covering type must declare every read field and a read required field; an all-optional reduced contract can reject existing callers. Identical alternatives and primitive/top/bottom redundancy remain upstream-owned; mutually assignable but nonidentical structures are excluded.",
    "General union simplification can change Extract, conditional types, in-narrowing, fresh-literal checking and public presentation. Those contexts are excluded even when ordinary assignment succeeds. Flat destructuring counts every bound field as read; whole-object escape, mutation, helpers, closures, reflection, serialization, dynamic reads, implicit Object capabilities and JSX prevent findings. Imported Python protocol assignability is not approximated by this rule.",
  ],
  examples: [
    { id: "covered-alternative", title: "The private consumer needs the covering Animal contract", outcome: "match", files: [{ path: "src/case.ts", source: EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true },
    { id: "public-contract", title: "A public union retains its observable alternatives", outcome: "no-match", files: [{ path: "src/case.ts", source: EXAMPLE.replace("function label", "export function label") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function scalarFields(type: ts.Type, checker: ts.TypeChecker): ReadonlyMap<string, boolean> | null {
  if (!closedObjectContract(type, checker)) return null;
  const fields = new Map<string, boolean>();
  for (const property of type.getProperties()) {
    const declarations = property.getDeclarations();
    if (!declarations?.length || !declarations.every((member) => ts.isPropertySignature(member) && member.name &&
      (ts.isIdentifier(member.name) || ts.isStringLiteralLike(member.name)) && member.modifiers?.length === 1 &&
      member.modifiers[0]?.kind === ts.SyntaxKind.ReadonlyKeyword && primitiveKeyword(member.type))) return null;
    fields.set(property.name, (property.flags & ts.SymbolFlags.Optional) === 0);
  }
  return fields.size ? fields : null;
}

export default createRule<[], "redundant">({
  name: "no-redundant-consumer-union",
  documentation: NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION,
  meta: { type: "suggestion", docs: { description: NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION.summary }, schema: [], messages: {
    redundant: "{{covered}} is already accepted by {{covering}} in this private scalar consumer. Review keeping the covering {{covering}} contract; preserve producer information and runtime objects.",
  } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const candidates: ScalarConsumerNode[] = [];
    let dynamic = false;
    const remember = (node: ScalarConsumerNode): void => {
      const annotation = consumerAnnotation(node);
      if (annotation?.type === AST_NODE_TYPES.TSUnionType && annotation.types.length === 2) candidates.push(node);
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
        const surfaces = new WeakMap<ts.Type, ReadonlyMap<string, boolean> | null>();
        const fieldsOf = (type: ts.Type): ReadonlyMap<string, boolean> | null => {
          if (!surfaces.has(type)) surfaces.set(type, scalarFields(type, checker));
          return surfaces.get(type) ?? null;
        };
        for (const candidate of candidates) {
          const consumer = privateScalarConsumer(candidate, context.sourceCode, services, exports);
          const annotation = consumer?.parameter.type;
          if (!consumer || !annotation || !ts.isUnionTypeNode(annotation) || annotation.types.length !== 2) continue;
          const leftNode = annotation.types[0];
          const rightNode = annotation.types[1];
          if (!leftNode || !rightNode) continue;
          const left = checker.getTypeFromTypeNode(leftNode);
          const right = checker.getTypeFromTypeNode(rightNode);
          const leftFields = fieldsOf(left);
          const rightFields = fieldsOf(right);
          if (!leftFields || !rightFields) continue;
          const forward = checker.isTypeAssignableTo(left, right);
          const reverse = checker.isTypeAssignableTo(right, left);
          if (forward === reverse) continue;
          const [coveredNode, coveringNode, coveredFields, coveringFields] = forward
            ? [leftNode, rightNode, leftFields, rightFields] as const : [rightNode, leftNode, rightFields, leftFields] as const;
          if ([...coveringFields.keys()].some((key) => !coveredFields.has(key)) ||
            [...consumer.reads].some((key) => !coveringFields.has(key)) || ![...consumer.reads].some((key) => coveringFields.get(key))) continue;
          context.report({ node: services.tsNodeToESTreeNodeMap.get(annotation), messageId: "redundant", data: { covered: coveredNode.getText(), covering: coveringNode.getText() } });
        }
      },
    };
  },
});
