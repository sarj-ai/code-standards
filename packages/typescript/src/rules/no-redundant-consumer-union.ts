/**
 * @fileoverview no-redundant-consumer-union — keep the covering object contract in a private scalar consumer union.
 *
 * Port of the 18.x `no-redundant-consumer-union` rule. Typed: without
 * tsrs types it reports nothing, as the original returns no visitors without
 * a program. The walk collects consumers annotated with a two-member union;
 * their proofs run against tsrs in `Program:exit`, as the original's do.
 */

import type { FixFn } from "@oxlint/plugins";
import type { ParameterDeclaration, TypeNode } from "tsrs/ast";
import type { Type } from "tsrs/sync";

import { defineRule, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { declarationNode, nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { closedObjectContract } from "../utils/closed-object-contract.js";
import { coveringConsumerFix, retainedConsumerTypeUses, validConsumerFixCalls } from "../utils/private-consumer-fix.js";
import {
  consumerAnnotation,
  directEval,
  exportedSymbols,
  nullishPrimitiveUnion,
  primitiveKeyword,
  privateScalarConsumer,
  type ScalarConsumerNode,
} from "../utils/private-scalar-consumer.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { typeBinding } from "../utils/type-binding.js";

const NAME = "no-redundant-consumer-union";

function scalarFields(native: NativeTypes, type: Type): ReadonlyMap<string, boolean> | null {
  const { ast, sync } = native;
  if (!closedObjectContract(native, type, true)) return null;
  const fields = new Map<string, boolean>();
  for (const property of type.getProperties()) {
    const declarations = property.declarations;
    if (!declarations.length || !declarations.every((handle) => {
      const member = declarationNode(native, handle);
      return member !== undefined && ast.isPropertySignatureDeclaration(member) && member.name &&
        (ast.isIdentifier(member.name) || ast.isStringLiteralLikeNode(member.name)) && member.modifiers?.length === 1 &&
        member.modifiers[0]?.kind === ast.SyntaxKind.ReadonlyKeyword && (primitiveKeyword(ast, member.type) || nullishPrimitiveUnion(ast, member.type));
    })) return null;
    fields.set(property.name, (property.flags & sync.SymbolFlags.Optional) === 0);
  }
  return fields.size ? fields : null;
}

/** Local proof excludes declarations introduced by namespaces or global augmentation. */
function moduleTypeDeclaration(node: Node): boolean {
  const parent = parentOf(node);
  if (parent?.type === "Program") return true;
  if (parent?.type !== "ExportNamedDeclaration" && parent?.type !== "ExportDefaultDeclaration") return false;
  return parentOf(parent)?.type === "Program";
}

interface Finding {
  readonly node: Node;
  readonly covered: string;
  readonly covering: string;
  readonly fix: FixFn | null;
}

/** What every candidate of one file shares. */
interface FileFacts {
  readonly native: NativeTypes;
  readonly sourceCode: SourceCode;
  readonly exports: ReturnType<typeof exportedSymbols>;
  readonly candidateAnnotations: readonly Node[];
  readonly fieldsOf: (type: Type) => ReadonlyMap<string, boolean> | null;
}

/** The candidate's covered union alternative, when its private consumer reads only what the other one covers. */
function redundantAlternative(facts: FileFacts, candidate: ScalarConsumerNode): Finding | null {
  const { native, sourceCode } = facts;
  const consumer = privateScalarConsumer(native, candidate, sourceCode, facts.exports, { scalarCalls: true });
  const alternatives = consumer ? binaryUnion(native, consumer.parameter.type) : null;
  if (!consumer || !alternatives) return null;
  const { left: leftNode, right: rightNode } = alternatives;
  const coverage = coveringAlternative(native, leftNode, rightNode, facts.fieldsOf, consumer.reads);
  if (!coverage) return null;
  // The selected parameter's annotation is the candidate's union annotation, member for member.
  const reportNode = consumerAnnotation(candidate);
  if (reportNode?.type !== "TSUnionType") return null;
  if (coverage.mutual && !localContractBindings(native, reportNode.types, sourceCode)) return null;
  const [first, second] = reportNode.types;
  if (!first || !second) return null;
  const [covered, covering] = coverage.covered === leftNode ? [first, second] : [second, first];
  const fix = privateUnionFix(native, sourceCode, {
    candidate, parameter: consumer.parameter, annotation: reportNode, covered, covering, candidateAnnotations: facts.candidateAnnotations,
  });
  return { node: reportNode, covered: coverage.covered.getText(native.source), covering: coverage.covering.getText(native.source), fix };
}

/** The two member type nodes of a two-member union annotation. */
function binaryUnion(native: NativeTypes, annotation: TypeNode | undefined): { readonly left: TypeNode; readonly right: TypeNode } | null {
  if (!annotation || !native.ast.isUnionTypeNode(annotation) || annotation.types.length !== 2) return null;
  const [left, right] = annotation.types;
  return left && right ? { left, right } : null;
}

/** Build a union edit after checking callers and retained type references. */
function privateUnionFix(native: NativeTypes, sourceCode: SourceCode, proof: {
  readonly candidate: ScalarConsumerNode;
  readonly parameter: ParameterDeclaration;
  readonly annotation: Node;
  readonly covered: Node;
  readonly covering: Node;
  readonly candidateAnnotations: readonly Node[];
}): FixFn | null {
  if (!validConsumerFixCalls(native, proof.candidate, proof.parameter, sourceCode)) return null;
  if (!retainedConsumerTypeUses(sourceCode, proof.covered, proof.covering, proof.candidateAnnotations)) return null;
  return coveringConsumerFix(sourceCode, proof.annotation, proof.covering);
}

/** Select the native covering contract after proving its complete declared/read surface. */
function coveringAlternative(native: NativeTypes, leftNode: TypeNode, rightNode: TypeNode,
  fieldsOf: (type: Type) => ReadonlyMap<string, boolean> | null, reads: ReadonlySet<string>): {
  readonly covered: TypeNode;
  readonly covering: TypeNode;
  readonly mutual: boolean;
} | null {
  const { checker } = native;
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
  return coversSurface(coveredFields, coveringFields, mutual, reads) ? { covered, covering, mutual } : null;
}

/** The covering fields are a subset of the covered ones that holds every read, at least one of them required. */
function coversSurface(coveredFields: ReadonlyMap<string, boolean>, coveringFields: ReadonlyMap<string, boolean>,
  mutual: boolean, reads: ReadonlySet<string>): boolean {
  return [...coveringFields.keys()].every((key) => coveredFields.has(key)) &&
    !(mutual && [...coveredFields].some(([key, required]) => required && !coveringFields.has(key))) &&
    [...reads].every((key) => coveringFields.has(key)) && [...reads].some((key) => coveringFields.get(key));
}

/** Follow only the local declarations whose unambiguous type bindings are available. */
function localContractBindings(native: NativeTypes, roots: readonly Node[], source: SourceCode): boolean {
  const pending: Node[] = [...roots];
  const visited = new Set<Node>();
  for (let index = 0; index < pending.length; index++) {
    const node = pending[index];
    if (!node || visited.has(node)) continue;
    visited.add(node);
    const references = localContractReferences(native, node, source);
    if (references === null) return false;
    pending.push(...references);
  }
  return true;
}

function localContractReferences(native: NativeTypes, node: Node, source: SourceCode): readonly Node[] | null {
  switch (node.type) {
    case "TSTypeLiteral": return [];
    case "TSIntersectionType": return node.types;
    case "TSTypeReference":
      return !node.typeArguments && node.typeName.type === "Identifier" ? [node.typeName] : null;
    case "Identifier": return localBindingReferences(native, node, source);
    default: return null;
  }
}

function localBindingReferences(native: NativeTypes, identifier: Node & { readonly name: string }, source: SourceCode): readonly Node[] | null {
  const definitions = typeBinding(source, identifier)?.defs.filter((definition) => definition.isTypeDefinition).map((definition) => definition.node);
  if (!definitions?.length || !definitions.every(moduleTypeDeclaration)) return null;
  const first = definitions[0];
  if (definitions.length === 1 && first?.type === "TSTypeAliasDeclaration" && !first.typeParameters) return [first.typeAnnotation];
  const interfaces = definitions.filter((definition) => definition.type === "TSInterfaceDeclaration");
  if (interfaces.length !== definitions.length || interfaces.some((declaration) => declaration.typeParameters)) return null;
  if (interfaces.length > 1) {
    const symbolOf = (node: Node) => {
      const tsNode = native.node(node);
      return tsNode === undefined ? undefined : native.checker.getSymbolAtLocation(tsNode);
    };
    const symbol = symbolOf(identifier);
    if (!symbol || interfaces.some((declaration) => symbolOf(declaration.id)?.id !== symbol.id)) return null;
  }
  const bases = interfaces.flatMap((declaration) => declaration.extends.map((base) => base.expression as Node));
  return bases.every((base) => base.type === "Identifier") ? bases : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: "Keep the covering object contract in a private scalar consumer union.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      redundant: "{{covered}} is already accepted by {{covering}} in this private scalar consumer. Review keeping the covering {{covering}} contract; preserve producer information and runtime objects.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: ScalarConsumerNode[] = [];
    let dynamic = false;
    const remember = (node: ScalarConsumerNode): void => {
      const annotation = consumerAnnotation(node);
      if (annotation?.type === "TSUnionType" && annotation.types.length === 2) candidates.push(node);
    };
    return {
      before() {
        tsrs = null;
        candidates = [];
        dynamic = false;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      FunctionDeclaration: remember,
      ArrowFunctionExpression: remember,
      CallExpression(node) {
        if (directEval(node)) dynamic = true;
      },
      "Program:exit"() {
        if (dynamic || !candidates.length || tsrs === null) return;
        const sourceCode = context.sourceCode;
        const findings = tsrs.run((file) => {
          const native = nativeTypes(file);
          const surfaces = new Map<Type, ReadonlyMap<string, boolean> | null>();
          const facts: FileFacts = {
            native,
            sourceCode,
            exports: exportedSymbols(native, native.source),
            candidateAnnotations: candidates.flatMap((node) => consumerAnnotation(node) ?? []),
            fieldsOf(type) {
              if (!surfaces.has(type)) surfaces.set(type, scalarFields(native, type));
              return surfaces.get(type) ?? null;
            },
          };
          return candidates.flatMap((candidate) => redundantAlternative(facts, candidate) ?? []);
        });
        if (findings === null) return;
        for (const { node, covered, covering, fix } of findings) {
          const report = { node: node, messageId: "redundant", data: { covered, covering } };
          context.report(fix === null ? report : { ...report, fix });
        }
      },
    };
  },
});
