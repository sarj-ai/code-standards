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
import { typeBinding } from "./_type-binding.js";

const CONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler"}}' } as const;
const EXAMPLE = 'export {}; interface Animal {readonly name: string} interface Dog extends Animal {readonly breed: string} export type KeptDog = Dog; const dog: Dog = {name: "Ada", breed: "Collie"}; function label(value: Dog | Animal): string {return value.name;} label(dog);';
const NULLABLE_EXAMPLE = EXAMPLE.replace("readonly name: string", "readonly name: string | null").replace("return value.name;", "return value.name ?? '';");
const OPTIONAL_EXAMPLE = EXAMPLE.replace("readonly breed: string", "readonly breed?: string");
const SCALAR_HELPER_EXAMPLE = EXAMPLE.replace("return value.name;", "return formatName(value.name);").replace("function label", "function formatName(value: string): string {return '[' + value + ']';} function label");
const WHOLE_OBJECT_HELPER_EXAMPLE = EXAMPLE.replace("return value.name;", "return formatAnimal(value);").replace("function label", "function formatAnimal(value: Animal): string {return value.name;} function label");

export const NO_REDUNDANT_CONSUMER_UNION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep the covering object contract in a private scalar consumer union.",
  rationale: "A private consumer can advertise a redundant object alternative even though native assignability proves that the other alternative accepts every covered value. Dog | Animal keeps Animal; requiring Dog would unnecessarily restrict callers.",
  remediation: "Review retaining the covering alternative, or revise the alternatives if distinct cases were intended. Preserve producer types and runtime objects. The safe fix edits only a proven private parameter annotation; public APIs, producer types and runtime objects remain unchanged.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Automatic fixes additionally require every existing identifier caller to be natively assignable to the original contract, without Any, unknown, error or unresolved types on the relevant surface. Comments inside the annotation and TypeScript suppression directives keep the finding manual. Removed named types/imports must retain an independent top-level exported type-alias or direct type-export read. Other removable annotations/assertions, the covering annotation and own-definition/self references cannot keep one another live; otherwise simultaneous fixes can introduce unused-type errors. The exact authored covering type and terminator token sequence are retained; edits that would merge distinct CR and LF terminators remain manual; no producer, call or function body is rewritten.",
    "Only an inline binary parameter union in a strict module's top-level private scalar consumer is supported. Exactly one parameter, an explicit broad primitive return annotation, a single supported returned scalar expression and direct identifier-argument callers are required. Type queries or type-only exports of the callable, public APIs, callbacks, contextual signatures, overloads, generics, decorators, async functions, direct eval and fresh-object callers prevent findings.",
    "Scalar values may pass through one implemented same-file top-level function or raw const-arrow helper with an explicit scalar return annotation and the exact native resolved signature. Every argument must already satisfy the scalar read view; the containing source must pass the existing native checked-source proof. Imported, ambient, aliased, overloaded, generic or contextually typed helpers, member calls, optional calls, spread arguments and whole-object arguments remain unsupported. Helper permission does not add auxiliary consumer parameters or replace the required object-field read anchor. Helper bodies need not be pure because no call or body is rewritten.",
    "Both alternatives must have complete ordinary finite structural surfaces consisting only of explicitly readonly broad string, number, boolean or bigint properties, optionally paired directly with null or undefined in an exact two-part union. Required and optional nullable fields may be read under the same native coverage proof. Every field must have one actual declaration origin throughout each alternative's inheritance/intersection graph. Shared ancestors retain that origin; repeated merged fields, explicit overrides and independently declared overlapping fields abstain, including valid compatible declarations. This excludes recovered conflicting properties without claiming whole-source health. Aliases, imports, re-exports and ordinary inheritance are resolved by the parser-owned TypeScript checker. Any, unknown, missing imports, open/generic/mapped/indexed types, classes, brands, literal discriminants, methods, properties with scalar type aliases, parenthesized or more complex property unions, callbacks and recursive or nested object fields are unsupported.",
    "Reports proper native assignability, where covered is assignable to covering and the reverse is false, or mutual native assignability with a strict smaller declared covering surface and only optional covered-only members. Every covering member, including optional members, must exist in the covered type's enumerated declared surface. Otherwise an existing identifier may carry an incompatible extra field and be rejected after simplification; implicit Object members containing Any cannot replace explicit declared coverage or the native Optional requirement. The covering type must declare every read field and a read required field; an all-optional reduced contract can reject existing callers. Identical alternatives and primitive/top/bottom redundancy remain upstream-owned; equal-key and incomparable mutually assignable structures are excluded. The mutual case additionally requires inline contracts or locally bound interfaces/type aliases whose alias and heritage references can be traced through the parser-owned type scope. Merged interface fragments must all resolve to the reference's same native symbol; mixed exported/local recovery abstains. Imported, global and qualified-namespace references in that path abstain; proper one-way coverage retains its existing alias/import support.",
    "General union simplification can change Extract, conditional types, in-narrowing, fresh-literal checking and public presentation. Those contexts are excluded even when ordinary assignment succeeds. Flat destructuring counts every bound field as read; whole-object escape, mutation, unproved helper calls, closures, reflection, serialization, dynamic reads, implicit Object capabilities and JSX prevent findings. Imported Python protocol assignability is not approximated by this rule.",
  ],
  examples: [
    { id: "local-scalar-helper", scenarioId: "local-scalar-helper", title: "A local helper receives only the required name", outcome: "match", files: [{ path: "src/case.ts", source: SCALAR_HELPER_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: SCALAR_HELPER_EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "whole-object-helper", scenarioId: "local-scalar-helper", title: "Passing the whole object remains outside the scalar helper proof", outcome: "no-match", files: [{ path: "src/case.ts", source: WHOLE_OBJECT_HELPER_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "covered-alternative", title: "The private consumer needs the covering Animal contract", outcome: "match", files: [{ path: "src/case.ts", source: EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "public-contract", title: "A public union retains its observable alternatives", outcome: "no-match", files: [{ path: "src/case.ts", source: EXAMPLE.replace("function label", "export function label") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "optional-covered-alternative", scenarioId: "optional-readonly-contract", title: "An unread optional breed retains the smaller Animal surface", outcome: "match", files: [{ path: "src/case.ts", source: OPTIONAL_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: OPTIONAL_EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "optional-public-contract", scenarioId: "optional-readonly-contract", title: "A public optional union retains its observable alternatives", outcome: "no-match", files: [{ path: "src/case.ts", source: OPTIONAL_EXAMPLE.replace("function label", "export function label") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "nullable-covered-alternative", scenarioId: "nullable-readonly-contract", title: "A nullable name retains the covering Animal contract", outcome: "match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("Dog | Animal", "Animal") }] },
    { id: "nullable-domain-contract", scenarioId: "nullable-readonly-contract", title: "A literal breed keeps the authored domain contract", outcome: "no-match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("readonly breed: string", "readonly breed: 'Collie'") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function scalarFields(type: ts.Type, checker: ts.TypeChecker): ReadonlyMap<string, boolean> | null {
  if (!closedObjectContract(type, checker, true)) return null;
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

type LocalContractNode = TSESTree.TypeNode | TSESTree.Identifier;

/** Follow only the local declarations whose unambiguous type bindings are available. */
function localContractBindings(roots: readonly TSESTree.TypeNode[], source: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): boolean {
  const pending: LocalContractNode[] = [...roots];
  const visited = new Set<LocalContractNode>();
  for (let index = 0; index < pending.length; index++) {
    const node = pending[index];
    if (!node || visited.has(node)) continue;
    visited.add(node);
    const references = localContractReferences(node, source, services);
    if (references === null) return false;
    pending.push(...references);
  }
  return true;
}

function localContractReferences(node: LocalContractNode, source: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): readonly LocalContractNode[] | null {
  switch (node.type) {
    case AST_NODE_TYPES.TSTypeLiteral: return [];
    case AST_NODE_TYPES.TSIntersectionType: return node.types;
    case AST_NODE_TYPES.TSTypeReference:
      return !node.typeArguments && node.typeName.type === AST_NODE_TYPES.Identifier ? [node.typeName] : null;
    case AST_NODE_TYPES.Identifier: return localBindingReferences(node, source, services);
    default: return null;
  }
}

function localBindingReferences(identifier: TSESTree.Identifier, source: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): readonly LocalContractNode[] | null {
  const definitions = typeBinding(source, identifier)?.defs.filter((definition) => definition.isTypeDefinition).map((definition) => definition.node);
  if (!definitions?.length || !definitions.every(moduleTypeDeclaration)) return null;
  const first = definitions[0];
  if (definitions.length === 1 && first?.type === AST_NODE_TYPES.TSTypeAliasDeclaration && !first.typeParameters) return [first.typeAnnotation];
  const interfaces = definitions.filter((definition): definition is TSESTree.TSInterfaceDeclaration => definition.type === AST_NODE_TYPES.TSInterfaceDeclaration);
  if (interfaces.length !== definitions.length || interfaces.some((declaration) => declaration.typeParameters)) return null;
  if (interfaces.length > 1) {
    const checker = services.program.getTypeChecker();
    const symbol = checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(identifier));
    if (!symbol || interfaces.some((declaration) => checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(declaration.id)) !== symbol)) return null;
  }
  const bases = interfaces.flatMap((declaration) => declaration.extends.map((base) => base.expression));
  return bases.every((base): base is TSESTree.Identifier => base.type === AST_NODE_TYPES.Identifier) ? bases : null;
}

/** Local proof excludes declarations introduced by namespaces or global augmentation. */
function moduleTypeDeclaration(node: TSESTree.Node): boolean {
  const parent = node.parent;
  if (parent?.type === AST_NODE_TYPES.Program) return true;
  if (parent?.type !== AST_NODE_TYPES.ExportNamedDeclaration && parent?.type !== AST_NODE_TYPES.ExportDefaultDeclaration) return false;
  return parent.parent.type === AST_NODE_TYPES.Program;
}

/** Select the native covering contract after proving its complete declared/read surface. */
function coveringAlternative(leftNode: ts.TypeNode, rightNode: ts.TypeNode, checker: ts.TypeChecker,
  fieldsOf: (type: ts.Type) => ReadonlyMap<string, boolean> | null, reads: ReadonlySet<string>): {
  readonly covered: ts.TypeNode;
  readonly covering: ts.TypeNode;
  readonly mutual: boolean;
} | null {
  const left = checker.getTypeFromTypeNode(leftNode);
  const right = checker.getTypeFromTypeNode(rightNode);
  const leftFields = fieldsOf(left);
  const rightFields = fieldsOf(right);
  if (!leftFields || !rightFields) return null;
  const forward = checker.isTypeAssignableTo(left, right);
  const reverse = checker.isTypeAssignableTo(right, left);
  const mutual = forward && reverse;
  if ((!forward && !reverse) || (mutual && leftFields.size === rightFields.size)) return null;
  const [covered, covering, coveredFields, coveringFields] = forward && (!reverse || leftFields.size > rightFields.size)
    ? [leftNode, rightNode, leftFields, rightFields] as const : [rightNode, leftNode, rightFields, leftFields] as const;
  if ([...coveringFields.keys()].some((key) => !coveredFields.has(key)) ||
    (mutual && [...coveredFields].some(([key, required]) => required && !coveringFields.has(key))) ||
    [...reads].some((key) => !coveringFields.has(key)) || ![...reads].some((key) => coveringFields.get(key))) return null;
  return { covered, covering, mutual };
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
          const consumer = privateScalarConsumer(candidate, context.sourceCode, services, exports, { scalarCalls: true });
          const annotation = consumer?.parameter.type;
          if (!consumer || !annotation || !ts.isUnionTypeNode(annotation) || annotation.types.length !== 2) continue;
          const leftNode = annotation.types[0];
          const rightNode = annotation.types[1];
          if (!leftNode || !rightNode) continue;
          const coverage = coveringAlternative(leftNode, rightNode, checker, fieldsOf, consumer.reads);
          if (!coverage) continue;
          const reportNode = services.tsNodeToESTreeNodeMap.get(annotation);
          if (coverage.mutual && (reportNode.type !== AST_NODE_TYPES.TSUnionType || !localContractBindings(reportNode.types, context.sourceCode, services))) continue;
          const {covered: coveredNode, covering: coveringNode} = coverage;
          const fix = privateUnionFix(context.sourceCode, services, {candidate, parameter: consumer.parameter,
            annotation: reportNode, covered: coveredNode, covering: coveringNode, candidateAnnotations});
          context.report({ node: reportNode, messageId: "redundant", data: { covered: coveredNode.getText(), covering: coveringNode.getText() }, fix });
        }
      },
    };
  },
});
