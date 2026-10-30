/**
 * @fileoverview no-redundant-consumer-union — retain proven covering private object contracts.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-consumer-union.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { currentNativeSource } from "./_checked-native-source.js";
import { closedObjectContract } from "./_closed-object-contract.js";
import { coveringConsumerFix, retainedConsumerTypeUses, validConsumerFixCalls } from "./_private-consumer-fix.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { consumerAnnotation, directEval, exportedSymbols, nullishPrimitiveUnion, primitiveKeyword, privateScalarConsumer, type ScalarConsumerNode } from "./_private-scalar-consumer.js";

const CONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler"}}' } as const;
const EXAMPLE = 'export {}; interface Animal {readonly name: string} interface Dog extends Animal {readonly breed: string} export type KeptDog = Dog; const dog: Dog = {name: "Ada", breed: "Collie"}; function label(value: Dog | Animal): string {return value.name;} label(dog);';
const NULLABLE_EXAMPLE = EXAMPLE.replace("readonly name: string", "readonly name: string | null").replace("return value.name;", "return value.name ?? '';");

export const NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep the covering object contract in a private scalar consumer union.",
  rationale: "A private consumer can advertise a redundant object alternative even though native assignability proves that the other alternative accepts every covered value. Dog | Animal keeps Animal; requiring Dog would unnecessarily restrict callers.",
  remediation: "Review retaining the covering alternative, or revise the alternatives if distinct cases were intended. Preserve producer types and runtime objects. The safe fix edits only a proven private parameter annotation; public APIs, producer types and runtime objects remain unchanged.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Automatic fixes additionally require every existing identifier caller to be natively assignable to the original contract, without Any, unknown, error or unresolved types on the relevant surface. Comments inside the annotation and TypeScript suppression directives keep the finding manual. Removed named types/imports must retain an independent top-level exported type-alias or direct type-export read. Other removable annotations/assertions, the covering annotation and own-definition/self references cannot keep one another live; otherwise simultaneous fixes can introduce unused-type errors. The exact authored covering type and terminator token sequence are retained; edits that would merge distinct CR and LF terminators remain manual; no producer, call or function body is rewritten.",
    "Only an inline binary parameter union in a strict module's top-level private scalar consumer is supported. Exactly one parameter, an explicit broad primitive return annotation, a single pure returned scalar expression and direct identifier-argument callers are required. Type queries or type-only exports of the callable, public APIs, callbacks, contextual signatures, overloads, generics, decorators, async functions, direct eval and fresh-object callers prevent findings.",
    "Both alternatives must have complete ordinary finite structural surfaces consisting only of explicitly readonly broad string, number, boolean or bigint properties, optionally paired directly with null or undefined in an exact two-part union. Required and optional nullable fields may be read under the same native coverage proof. Aliases, imports, re-exports and ordinary inheritance are resolved by the parser-owned TypeScript checker. Any, unknown, missing imports, open/generic/mapped/indexed types, classes, brands, literal discriminants, methods, properties with scalar type aliases, parenthesized or more complex property unions, callbacks and recursive or nested object fields are unsupported.",
    "Reports only proper native assignability: covered is assignable to covering and the reverse is false. Every covering member, including optional members, must exist in the covered type's enumerated declared surface. Otherwise an existing identifier may carry an incompatible extra field and be rejected after simplification; implicit Object members containing Any also cannot witness coverage. The covering type must declare every read field and a read required field; an all-optional reduced contract can reject existing callers. Identical alternatives and primitive/top/bottom redundancy remain upstream-owned; mutually assignable but nonidentical structures are excluded.",
    "General union simplification can change Extract, conditional types, in-narrowing, fresh-literal checking and public presentation. Those contexts are excluded even when ordinary assignment succeeds. Flat destructuring counts every bound field as read; whole-object escape, mutation, helpers, closures, reflection, serialization, dynamic reads, implicit Object capabilities and JSX prevent findings. Imported Python protocol assignability is not approximated by this rule.",
  ],
  examples: [
    { id: "covered-alternative", title: "The private consumer needs the covering Animal contract", outcome: "match", files: [{ path: "src/case.ts", source: EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "public-contract", title: "A public union retains its observable alternatives", outcome: "no-match", files: [{ path: "src/case.ts", source: EXAMPLE.replace("function label", "export function label") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "nullable-covered-alternative", scenarioId: "nullable-readonly-contract", title: "A nullable name retains the covering Animal contract", outcome: "match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "nullable-domain-contract", scenarioId: "nullable-readonly-contract", title: "A literal breed keeps the authored domain contract", outcome: "no-match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("readonly breed: string", "readonly breed: 'Collie'") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function scalarFields(type: ts.Type, checker: ts.TypeChecker): ReadonlyMap<string, boolean> | null {
  if (!closedObjectContract(type, checker)) return null;
  const fields = new Map<string, boolean>();
  for (const property of type.getProperties()) {
    const declarations = property.getDeclarations();
    if (!declarations?.length || !declarations.every((member) => ts.isPropertySignature(member) && member.name &&
      (ts.isIdentifier(member.name) || ts.isStringLiteralLike(member.name)) && member.modifiers?.length === 1 &&
      member.modifiers[0]?.kind === ts.SyntaxKind.ReadonlyKeyword && (primitiveKeyword(member.type) || nullishPrimitiveUnion(member.type)))) return null;
    fields.set(property.name, (property.flags & ts.SymbolFlags.Optional) === 0);
  }
  return fields.size ? fields : null;
}

/** Build a union edit after checking callers and retained type references. */
function privateUnionFix(sourceCode: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation, proof: {
  readonly candidate: ScalarConsumerNode;
  readonly parameter: ts.ParameterDeclaration;
  readonly annotation: TSESTree.Node;
  readonly covered: ts.TypeNode;
  readonly covering: ts.TypeNode;
  readonly candidateAnnotations: readonly TSESTree.Node[];
}): TSESLint.ReportFixFunction | null {
  const covering = services.tsNodeToESTreeNodeMap.get(proof.covering);
  if (!validConsumerFixCalls(proof.candidate, proof.parameter, sourceCode, services)) return null;
  if (!retainedConsumerTypeUses(sourceCode, services.tsNodeToESTreeNodeMap.get(proof.covered), covering, proof.candidateAnnotations)) return null;
  return coveringConsumerFix(sourceCode, proof.annotation, covering);
}

export default createRule<[], "redundant">({
  name: "no-redundant-consumer-union",
  documentation: NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION,
  meta: { type: "suggestion", fixable: "code", docs: { description: NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION.summary }, schema: [], messages: {
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
        const source = currentNativeSource(context.sourceCode, services);
        if (!source) return;
        const checker = services.program.getTypeChecker();
        const exports = exportedSymbols(source, checker);
        const candidateAnnotations = candidates.flatMap((node) => { const annotation = consumerAnnotation(node); return annotation ? [annotation] : []; });
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
          const reportNode = services.tsNodeToESTreeNodeMap.get(annotation);
          const fix = privateUnionFix(context.sourceCode, services, {candidate, parameter: consumer.parameter,
            annotation: reportNode, covered: coveredNode, covering: coveringNode, candidateAnnotations});
          context.report({ node: reportNode, messageId: "redundant", data: { covered: coveredNode.getText(), covering: coveringNode.getText() }, fix });
        }
      },
    };
  },
});
