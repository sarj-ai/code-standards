/**
 * @fileoverview prefer-minimal-parameter-contract — reduce proven private read-only dependencies.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-minimal-parameter-contract.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils } from "@typescript-eslint/utils";
import ts from "typescript";

import { currentNativeSource } from "./_checked-native-source.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { minimalConsumerFix, validConsumerFixCalls } from "./_private-consumer-fix.js";
import { consumerAnnotation, directEval, exportedSymbols, nullishPrimitiveUnion, primitiveKeyword, privateScalarConsumer, type ScalarConsumerNode } from "./_private-scalar-consumer.js";

const CONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler"}}' } as const;
const EXAMPLE = 'export {}; const account = {name: "Ada", email: "a"}; function label(user: {readonly email: string; readonly name: string}): string {return user.name;} label(account);';
const HELPER_EXAMPLE = 'export {}; const account = {name: "Ada", email: "a"}; function formatName(name: string): string {return name.toUpperCase();} function label(user: {email: string; name: string}): string {return formatName(user.name);} label(account);';
const NULLABLE_EXAMPLE = 'export {}; const account = {name: "Ada", email: null}; function label(user: {email: string | null; name: string}): string {return user.name;} label(account);';
const READ_NULLABLE_EXAMPLE = EXAMPLE.replace('name: "Ada"', "name: null").replace("readonly name: string", "readonly name: string | null").replace("return user.name;", 'return user.name ?? "";');
const AUXILIARY_EXAMPLE = EXAMPLE.replaceAll("readonly ", "").replace("function label(user:", 'const prefix = "Hello "; function label(prefix: string, user:')
  .replace("return user.name;", "return prefix + user.name;").replace("label(account);", "label(prefix, account);");

export const PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer the proven read-only subset for a private consumer parameter.",
  rationale: "A private scalar consumer can unnecessarily require data it never reads. Removing unused required fields accepts more structural values while preserving the original runtime object and producer information.",
  remediation: "Review a smaller existing contract, Pick or interface containing the read fields and preserving readonly and optional modifiers. Change the consumer annotation; a new runtime projection has different identity and allocation costs. The safe fix removes only proven unused required property signatures from the private inline annotation; producer objects, calls and function bodies remain unchanged.",
  category: "architecture",
  autofix: "safe",
  limitations: [
    "Automatic fixes additionally require every existing identifier argument to be natively assignable to its corresponding original parameter contract, without Any, unknown, error or unresolved types on the relevant surface. Comments inside the annotation and TypeScript suppression directives keep the finding manual. Only unread required object property signatures are removed; every read or optional member, modifier and terminator token is preserved. Auxiliary annotations and argument order stay unchanged. Edits that would merge distinct CR and LF terminators remain manual.",
    "Requires parser-owned TypeScript information and a strict external module. Only top-level private function declarations and raw const arrows with one explicit inline object parameter and an independent broad primitive return annotation are supported. Other parameters must be required identifiers annotated directly as string, number, boolean or bigint; optional, default, rest, destructured, domain-specific and explicit this auxiliaries are excluded. Every callable reference must be a direct call with an identifier argument for every parameter; exports including type-only exports, typeof queries, callbacks, storage, constructors, contextual signatures, overloads, generics, decorators, async functions and direct eval prevent findings.",
    "Only anonymous inline contracts made of broad string, number, boolean or bigint property types are supported. A read field or an unread required field may additionally have exactly one such keyword and null or undefined in a direct two-part union; unread optional nullable fields and more complex unions remain excluded. Fields may be plain or readonly; the consumer body must still prove read-only usage. Every read field keeps its exact type, modifiers and optionality. Named domain contracts, brands, literal discriminants, classes, methods, callbacks, indexes, mapped types and imported parameter contracts are excluded. At least one read required field and one unread required field must be established; all-optional reduced contracts can reject existing callers through weak-type checks.",
    "The single return expression may use only fixed scalar field reads, flat destructuring, literals, operators, templates and scalar calls to same-file implemented top-level functions or raw const arrows with an explicit return annotation. These calls require one native resolved declaration, no generic or predicate signature, scalar arguments/result and complete active native checking of the local implementation file. Their helper bodies need not be pure because only scalar values cross the call and only an erased parameter annotation changes. Imported, aliased, ambient, overloaded, optional, spread and member calls remain unsupported. Bound destructured fields count as reads even when their local aliases are unused. Whole-object escape, identity, mutation, closures, reflection, serialization, dynamic keys, implicit Object capabilities and JSX are unsupported. Unknown semantic information causes abstention. Findings outside the fix proof remain manual; this is not a requirement to minimize every object or discard useful producer fields.",
  ],
  examples: [
    { id: "unused-required-field", title: "A private name consumer unnecessarily requires email", outcome: "match", files: [{ path: "src/case.ts", source: EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: EXAMPLE.replace("readonly email: string;", "") }] },
    { id: "used-fields", title: "Every required dependency is read", outcome: "no-match", files: [{ path: "src/case.ts", source: EXAMPLE.replace("return user.name;", 'return user.name + user.email;') }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "scalar-helper", scenarioId: "local-scalar-helper", title: "Only the name crosses a local scalar helper call", outcome: "match", files: [{ path: "src/case.ts", source: HELPER_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: HELPER_EXAMPLE.replace("email: string;", "") }] },
    { id: "helper-and-other-field", scenarioId: "local-scalar-helper", title: "The consumer still requires a separately read field", outcome: "no-match", files: [{ path: "src/case.ts", source: HELPER_EXAMPLE.replace("return formatName(user.name);", "return formatName(user.name) + user.email;") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "unread-nullable-field", scenarioId: "nullable-private-field", title: "A required nullable field is never inspected", outcome: "match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("email: string | null;", "") }] },
    { id: "read-nullable-field", scenarioId: "nullable-private-field", title: "An inspected nullable field keeps its contract", outcome: "no-match", files: [{ path: "src/case.ts", source: NULLABLE_EXAMPLE.replace("return user.name;", "return user.email ?? user.name;") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "retained-nullable-read", scenarioId: "retained-nullable-field", title: "A nullable name remains while an unread email requirement is removed", outcome: "match", files: [{ path: "src/case.ts", source: READ_NULLABLE_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: READ_NULLABLE_EXAMPLE.replace("readonly email: string;", "") }] },
    { id: "retained-nullable-all-used", scenarioId: "retained-nullable-field", title: "Both requirements remain when the nullable view reads email too", outcome: "no-match", files: [{ path: "src/case.ts", source: READ_NULLABLE_EXAMPLE.replace('return user.name ?? "";', "return user.name ?? user.email;") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
    { id: "auxiliary-scalar", scenarioId: "auxiliary-scalar-parameter", title: "A scalar prefix does not require the object's unread email", outcome: "match", files: [{ path: "src/case.ts", source: AUXILIARY_EXAMPLE }, CONFIG], focusPath: "src/case.ts", expectedCount: 1, public: true, fixedFiles: [{ path: "src/case.ts", source: AUXILIARY_EXAMPLE.replace("email: string;", "") }] },
    { id: "auxiliary-all-used", scenarioId: "auxiliary-scalar-parameter", title: "Reading both object fields retains their requirements", outcome: "no-match", files: [{ path: "src/case.ts", source: AUXILIARY_EXAMPLE.replace("return prefix + user.name;", "return prefix + user.name + user.email;") }, CONFIG], focusPath: "src/case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function inlineFields(node: ts.TypeLiteralNode, reads: ReadonlySet<string>): ReadonlyMap<string, boolean> | null {
  const fields = new Map<string, boolean>();
  for (const member of node.members) {
    if (!ts.isPropertySignature(member) || !member.name || (!ts.isIdentifier(member.name) && !ts.isStringLiteralLike(member.name)) ||
      (member.modifiers?.length ?? 0) > 1 || member.modifiers?.some((modifier) => modifier.kind !== ts.SyntaxKind.ReadonlyKeyword)) return null;
    const key = member.name.text;
    if (!primitiveKeyword(member.type) && (!nullishPrimitiveUnion(member.type) || (member.questionToken && !reads.has(key)))) return null;
    if (fields.has(key)) return null;
    fields.set(key, !member.questionToken);
  }
  return fields;
}

export default createRule<[], "minimal">({
  name: "prefer-minimal-parameter-contract",
  documentation: PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION,
  meta: { type: "suggestion", fixable: "code", docs: { description: PREFER_MINIMAL_PARAMETER_CONTRACT_DOCUMENTATION.summary }, schema: [], messages: {
    minimal: "This private consumer reads only {{used}} but also requires {{unused}}. Review a smaller consumer contract; preserve the original runtime object and producer type.",
  } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const candidates: ScalarConsumerNode[] = [];
    let dynamic = false;
    const remember = (node: ScalarConsumerNode): void => {
      if (consumerAnnotation(node, true)?.type === AST_NODE_TYPES.TSTypeLiteral) candidates.push(node);
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
        for (const candidate of candidates) {
          const consumer = privateScalarConsumer(candidate, context.sourceCode, services, exports, { scalarCalls: true, auxiliaryScalars: true });
          const annotation = consumer?.parameter.type;
          if (!consumer || !annotation || !ts.isTypeLiteralNode(annotation)) continue;
          const fields = inlineFields(annotation, consumer.reads);
          if (!fields || [...consumer.reads].some((key) => !fields.has(key)) || ![...consumer.reads].some((key) => fields.get(key))) continue;
          const unused = [...fields].filter(([key, required]) => required && !consumer.reads.has(key)).map(([key]) => key).sort();
          if (!unused.length) continue;
          const reportNode = services.tsNodeToESTreeNodeMap.get(annotation);
          const removed = annotation.members.filter((member) => ts.isPropertySignature(member) && member.name &&
            (ts.isIdentifier(member.name) || ts.isStringLiteralLike(member.name)) && unused.includes(member.name.text))
            .map((member) => ({ start: member.getStart(), end: member.getEnd() }));
          const fix = validConsumerFixCalls(candidate, consumer.parameter, context.sourceCode, services)
            ? minimalConsumerFix(context.sourceCode, reportNode, removed) : null;
          context.report({ node: reportNode, messageId: "minimal", data: { used: [...consumer.reads].sort().join(", "), unused: unused.join(", ") }, fix });
        }
      },
    };
  },
});
