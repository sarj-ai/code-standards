/**
 * @fileoverview prefer-zod-parse-output-type — a hand-written return contract can drift from the Zod schema that produces it.
 *
 * Port of the 18.x `prefer-zod-parse-output-type` rule. Typed: without
 * tsrs type services it skips the file, as the original returns no visitors
 * without a program.
 *
 * The walk collects local schemas and parse-return candidates, as the
 * original does. `Program:exit` first drops candidates whose schema name
 * matches no local schema (their symbols cannot match either), so files
 * without one never build a tsrs program; the rest are checked against tsrs
 * one by one, in the original's order. The typed helpers live in
 * `_prefer-zod-parse-output-type-contracts.ts`.
 *
 * The original compares `typeParameters` to `undefined`; Oxlint gives null
 * there. Ported checks accept both, including the shared
 * `preferZodInferOwnsDefaultTwin` from the `prefer-zod-infer` port, so under
 * Oxlint the original never defers a same-module twin to `prefer-zod-infer`
 * and never fixes, while this port does both as the original does under ESLint.
 */

import type { FixFn } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";
import { isZodModule } from "../utils/zod.js";
import type { Contracts, TsNode, TsSymbol } from "./_prefer-zod-parse-output-type-contracts.js";
import { contractsOf, equivalentZodOutputContracts, hasAuthoritativeOutputContract } from "./_prefer-zod-parse-output-type-contracts.js";
import {
  collectConstrainedNames,
  isModuleLevelConst,
  isPreferZodInferModuleReshaper,
  isPreferZodInferTypeConstraintName,
  preferZodInferOwnsDefaultTwin,
} from "./prefer-zod-infer.js";

const NAME = "prefer-zod-parse-output-type";

interface LocalSchema {
  readonly identifier: ESTree.BindingIdentifier;
  readonly initializer: Node;
  readonly name: string;
}

interface ParsedReturnCandidate {
  readonly call: ESTree.CallExpression;
  readonly method: "parse" | "safeParse";
  readonly output: Node;
  readonly schema: ESTree.IdentifierReference;
  readonly typeName: string;
  readonly typeReference: ESTree.TSTypeReference;
}

interface Eligible {
  readonly candidate: ParsedReturnCandidate;
  readonly contract: number;
  readonly schema: LocalSchema;
  readonly schemaSymbol: number;
}

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

/** True only for a call chain rooted at `z.object()` or `z.strictObject()`. */
function isLocalZodObjectSchema(node: Node, namespaces: ReadonlySet<string>): boolean {
  let current = node;
  while (current.type === "CallExpression") {
    const callee = unwrapExpression(current.callee);
    if (callee.type !== "MemberExpression") return false;
    const name = getPropertyName(callee);
    if (name === null) return false;
    const calleeReceiver = unwrapExpression(callee.object);
    if (calleeReceiver.type === "Identifier") {
      return namespaces.has(calleeReceiver.name) && (name === "object" || name === "strictObject");
    }
    current = calleeReceiver;
  }
  return false;
}

interface ZodParseCall {
  readonly call: ESTree.CallExpression;
  readonly method: "parse" | "safeParse";
  readonly schema: ESTree.IdentifierReference;
}

function zodParseCall(node: ESTree.CallExpression): ZodParseCall | null {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return null;
  const calleeReceiver = unwrapExpression(callee.object);
  if (calleeReceiver.type !== "Identifier") return null;
  const method = getPropertyName(callee);
  if (method !== "parse" && method !== "safeParse") return null;
  return { call: node, method, schema: calleeReceiver as ESTree.IdentifierReference };
}

function returnedOutputCandidate(parsed: ZodParseCall, output: Node): ParsedReturnCandidate | null {
  const owner = directReturnOwner(output);
  if (owner === null || enclosingFunction(parsed.call) !== owner) return null;
  const annotation = owner.returnType?.typeAnnotation;
  if (!isPresent(annotation)) return null;
  const typeReference = returnContractReference(annotation);
  if (typeReference === null || typeReference.typeName.type !== "Identifier") return null;
  return {
    call: parsed.call,
    method: parsed.method,
    output,
    schema: parsed.schema,
    typeName: typeReference.typeName.name,
    typeReference,
  };
}

function directParseReturnCandidate(node: ESTree.CallExpression): ParsedReturnCandidate | null {
  const parsed = zodParseCall(node);
  return parsed?.method === "parse" ? returnedOutputCandidate(parsed, node) : null;
}

function localParseReturnCandidates(node: ESTree.VariableDeclarator, sourceCode: SourceCode): readonly ParsedReturnCandidate[] {
  const declaration = parentOf(node);
  if (node.id.type !== "Identifier" || node.init?.type !== "CallExpression" || declaration?.type !== "VariableDeclaration" ||
    declaration.kind !== "const") return [];
  const parsed = zodParseCall(node.init);
  if (parsed === null || enclosingFunction(node.init) === null) return [];
  const variable = sourceCode.getDeclaredVariables(node)[0];
  if (variable === undefined) return [];
  const candidates: ParsedReturnCandidate[] = [];
  for (const reference of variable.references) {
    const output = parsedOutput(parsed, reference.identifier);
    const candidate = output === null ? null : returnedOutputCandidate(parsed, output);
    if (candidate !== null) candidates.push(candidate);
  }
  return candidates;
}

/** The parsed value a reference to the result reads: the binding for `parse`, `.data` for `safeParse`. */
function parsedOutput(parsed: ZodParseCall, identifier: Node): Node | null {
  if (parsed.method === "parse") return identifier;
  const parent = parentOf(identifier);
  return parent?.type === "MemberExpression" && parent.object === identifier && getPropertyName(parent) === "data"
    ? parent
    : null;
}

/** Returns the owning function only through wrappers that preserve the parsed value. */
function directReturnOwner(node: Node): FunctionNode | null {
  let current: Node = node;
  for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
    if (parent.type === "ReturnStatement") return parent.argument === current ? enclosingFunction(parent) : null;
    if (parent.type === "ArrowFunctionExpression" && parent.expression && parent.body === current) return parent;
    if (parent.type === "AwaitExpression" && parent.argument === current) {
      current = parent;
      continue;
    }
    if (parent.type === "ConditionalExpression") {
      const parsedWhenTrue = parent.consequent === current && isNullishExpression(parent.alternate);
      const parsedWhenFalse = parent.alternate === current && isNullishExpression(parent.consequent);
      if (parsedWhenTrue || parsedWhenFalse) {
        current = parent;
        continue;
      }
    }
    return null;
  }
  return null;
}

/** `function f(): Contract { return schema.parse(x); }`: a plain declaration whose only statement returns the parse. */
function soleParseReturnFunction(candidate: ParsedReturnCandidate): ESTree.Function | null {
  const owner = directReturnOwner(candidate.output);
  if (
    owner?.type !== "FunctionDeclaration" || owner.async || owner.generator || isPresent(owner.typeParameters) ||
    owner.returnType?.typeAnnotation !== candidate.typeReference
  ) {
    return null;
  }
  const statements = owner.body?.body ?? [];
  const [statement] = statements;
  return statements.length === 1 && statement?.type === "ReturnStatement" && statement.argument === candidate.call ? owner : null;
}

function isNullishExpression(node: Node): boolean {
  return (node.type === "Literal" && (node as { value: unknown }).value === null) ||
    (node.type === "Identifier" && node.name === "undefined");
}

/** Unwraps `Promise<T>` and nullish unions to one non-generic named contract. */
function returnContractReference(node: ESTree.TSType): ESTree.TSTypeReference | null {
  if (node.type === "TSUnionType") {
    return soleReturnContract(node.types.filter((member) => member.type !== "TSNullKeyword" && member.type !== "TSUndefinedKeyword"));
  }
  if (node.type === "TSTypeReference" && node.typeName.type === "Identifier" && node.typeName.name === "Promise") {
    return soleReturnContract(node.typeArguments?.params ?? []);
  }
  return node.type === "TSTypeReference" && node.typeName.type === "Identifier" && (node.typeArguments?.params.length ?? 0) === 0
    ? node
    : null;
}

function soleReturnContract(types: readonly ESTree.TSType[]): ESTree.TSTypeReference | null {
  const [only] = types;
  return types.length === 1 && only !== undefined ? returnContractReference(only) : null;
}

function recordZodNamespaces(node: ESTree.Program, namespaces: Set<string>): void {
  for (const statement of node.body) {
    if (statement.type !== "ImportDeclaration" || !isZodModule(statement.source.value)) continue;
    for (const specifier of statement.specifiers) {
      if (
        specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier" ||
        (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "z")
      ) {
        namespaces.add(specifier.local.name);
      }
    }
  }
}

/** The single plain object interface or type literal alias declaring this symbol. */
function handWrittenObjectDeclaration(env: Contracts, symbol: TsSymbol): TsNode | null {
  const declarations = symbol.declarations ?? [];
  const [handle] = declarations;
  if (declarations.length !== 1 || handle === undefined) return null;
  const kinds = env.kinds.SyntaxKind;
  if (handle.kind !== kinds["InterfaceDeclaration"] && handle.kind !== kinds["TypeAliasDeclaration"]) return null;
  const declaration = handle.resolve();
  return declaration !== undefined && isPlainObjectDeclaration(kinds, declaration) ? declaration : null;
}

/** A non-generic `interface X { … }` without heritage, or `type X = { … }`, with only plain property members. */
function isPlainObjectDeclaration(kinds: Contracts["kinds"]["SyntaxKind"], declaration: TsNode): boolean {
  if (declaration.typeParameters !== undefined) return false;
  if (declaration.kind === kinds["InterfaceDeclaration"]) {
    return declaration.heritageClauses === undefined && hasPlainMembers(kinds, declaration.members);
  }
  return declaration.kind === kinds["TypeAliasDeclaration"] && declaration.type?.kind === kinds["TypeLiteral"] &&
    hasPlainMembers(kinds, declaration.type?.members);
}

/** At least one member, each a typed, writable property signature. */
function hasPlainMembers(kinds: Contracts["kinds"]["SyntaxKind"], members: readonly TsNode[] | undefined): boolean {
  return members !== undefined && members.length > 0 && members.every((member) =>
    member.kind === kinds["PropertySignature"] && member.type !== undefined &&
    member.modifiers?.some((modifier) => modifier.kind === kinds["ReadonlyKeyword"]) !== true);
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Consider deriving validated return contracts from the Zod schema when the schema owns the contract.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      handWrittenParsedOutput:
        "`{{typeName}}` matches the validated output returned from `{{schemaName}}.{{methodName}}()`. If the schema owns this contract, consider `z.output<typeof {{schemaName}}>`. Preserve independent domain and public API contracts.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let namespaces = new Set<string>();
    let constrainedTypeNames = new Set<string>();
    let reshapedSchemas = new Set<string>();
    let schemas: LocalSchema[] = [];
    let candidates: ParsedReturnCandidate[] = [];

    /** The candidates whose schema symbol is a local schema's and whose contract matches its output. */
    function eligibleCandidates(file: TsrsFile, pending: readonly ParsedReturnCandidate[]): Eligible[] {
      const env = contractsOf(file);
      const symbolId = (node: Node): number | undefined => {
        const tsNode = file.tsNode(node) as TsNode | undefined;
        return tsNode === undefined ? undefined : env.checker.getSymbolAtLocation(tsNode)?.id;
      };
      const schemaSymbols = new Map<number, LocalSchema>();
      for (const schema of schemas) {
        const symbol = symbolId(schema.identifier);
        if (symbol !== undefined) schemaSymbols.set(symbol, schema);
      }
      const eligible: Eligible[] = [];
      for (const candidate of pending) {
        const schemaSymbol = symbolId(candidate.schema);
        const schema = schemaSymbol === undefined ? undefined : schemaSymbols.get(schemaSymbol);
        if (schemaSymbol === undefined || schema === undefined) continue;
        const contract = eligibleContract(file, env, candidate, schema);
        if (contract !== null) eligible.push({ candidate, contract, schema, schemaSymbol });
      }
      return eligible;
    }

    /** The candidate's contract symbol id when the original would report it, in its order of checks; else null. */
    function eligibleContract(file: TsrsFile, env: Contracts, candidate: ParsedReturnCandidate, schema: LocalSchema): number | null {
      const { checker } = env;
      const handWritten = handWrittenContract(file, env, candidate);
      if (handWritten === null) return null;
      const { contract, declaration, source, symbol } = handWritten;
      const tsOutput = file.tsNode(candidate.output) as TsNode | undefined;
      if (tsOutput === undefined) return null;
      const parsed = checker.getTypeAtLocation(tsOutput);
      if (hasAuthoritativeOutputContract(env, tsOutput, symbol)) return null;
      // A `z.ZodType<Contract>` constraint deliberately makes the TypeScript
      // contract authoritative over the schema.
      const constrained = constrainedTypeNames.has(candidate.typeName) ||
        (parsed.getAliasSymbol() ?? parsed.getSymbol())?.id === symbol.id;
      if (constrained) return null;
      if (source.fileName === file.sourceFile.fileName && deferredToPreferZodInfer(file, candidate, schema, declaration, constrained)) return null;
      if (!equivalentZodOutputContracts(env, checker.getNonNullableType(parsed), checker.getNonNullableType(contract))) return null;
      return symbol.id;
    }

    /** The return contract's type, symbol and plain object declaration, when that declaration is hand-written source. */
    function handWrittenContract(file: TsrsFile, env: Contracts, candidate: ParsedReturnCandidate) {
      const tsReference = file.outerTsNode(candidate.typeReference) as TsNode | undefined;
      if (tsReference === undefined) return null;
      const contract = env.checker.getTypeAtLocation(tsReference);
      const symbol = contract.getAliasSymbol() ?? contract.getSymbol();
      if (symbol === undefined) return null;
      const declaration = handWrittenObjectDeclaration(env, symbol);
      if (declaration === null) return null;
      const source = declaration.getSourceFile();
      if (source.isDeclarationFile || isGeneratedFile({ filename: source.fileName, cwd: context.cwd }, source.text)) return null;
      return { contract, declaration, source, symbol };
    }

    /** Whether `prefer-zod-infer` owns this same-module contract (it reports the twin instead). */
    function deferredToPreferZodInfer(file: TsrsFile, candidate: ParsedReturnCandidate, schema: LocalSchema, declaration: TsNode, constrained: boolean): boolean {
      const estreeDeclaration = file.esTreeNode(declaration);
      return (estreeDeclaration?.type === "TSInterfaceDeclaration" || estreeDeclaration?.type === "TSTypeAliasDeclaration") &&
        preferZodInferOwnsDefaultTwin({
          constrained,
          declaration: estreeDeclaration,
          initializer: schema.initializer,
          reshaped: reshapedSchemas.has(schema.name),
          schemaName: schema.name,
          typeName: candidate.typeName,
          zodNamespaces: namespaces,
        });
    }

    /** Report each contract once, and only when a single schema produces it. */
    function report(eligible: readonly Eligible[]): void {
      const schemasByContract = new Map<number, Set<number>>();
      const candidatesByContract = new Map<number, number>();
      for (const { contract, schemaSymbol } of eligible) {
        const contractSchemas = schemasByContract.get(contract) ?? new Set<number>();
        contractSchemas.add(schemaSymbol);
        schemasByContract.set(contract, contractSchemas);
        candidatesByContract.set(contract, (candidatesByContract.get(contract) ?? 0) + 1);
      }
      const reported = new Set<number>();
      for (const { candidate, contract, schema } of eligible) {
        if (reported.has(contract) || schemasByContract.get(contract)?.size !== 1) continue;
        reported.add(contract);
        context.report({
          node: candidate.typeReference,
          messageId: "handWrittenParsedOutput",
          ...privateParsedOutputFix(candidate, schema, candidatesByContract.get(contract)),
          data: { methodName: candidate.method, schemaName: schema.name, typeName: candidate.typeName },
        });
      }
    }

    function privateParsedOutputFix(candidate: ParsedReturnCandidate, schema: LocalSchema, candidateCount: number | undefined) {
      const sourceCode = context.sourceCode;
      const directParse = candidateCount === 1 && candidate.method === "parse" && candidate.output === candidate.call;
      const owner = directParse ? soleParseReturnFunction(candidate) : null;
      if (
        owner === null || owner.id === null || sourceCode.getCommentsInside(owner).length > 0 ||
        !retainsNamedTypeUses(sourceCode, candidate.typeReference) ||
        !isUnusedPrivateBinding(sourceCode, owner, owner.id, context.filename)
      ) {
        return null;
      }
      const namespace = schemaZodNamespace(schema, candidate.typeReference);
      if (namespace === null) return null;
      const fix: FixFn = (fixer) => fixer.replaceText(candidate.typeReference,
        `${sourceCode.getText(namespace)}.output<typeof ${sourceCode.getText(schema.identifier)}>`);
      return { fix };
    }

    /** The imported Zod namespace the schema is built from, when the type reference sees the same binding. */
    function schemaZodNamespace(schema: LocalSchema, typeReference: ESTree.TSTypeReference): Node | null {
      const { sourceCode } = context;
      const initializer = unwrapExpression(schema.initializer);
      const callee = initializer.type === "CallExpression" ? unwrapExpression(initializer.callee) : null;
      const namespace = callee?.type === "MemberExpression" ? unwrapExpression(callee.object) : null;
      if (namespace?.type !== "Identifier" || !namespaces.has(namespace.name)) return null;
      const binding = findVariable(sourceCode.getScope(namespace), namespace.name);
      return binding?.defs.length === 1 && binding.defs[0]?.type === "ImportBinding" &&
        findVariable(sourceCode.getScope(typeReference), namespace.name) === binding
        ? namespace
        : null;
    }

    return {
      before() {
        tsrs = null;
        namespaces = new Set();
        constrainedTypeNames = new Set();
        reshapedSchemas = new Set();
        schemas = [];
        candidates = [];
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isStoryFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      Program(node) {
        recordZodNamespaces(node, namespaces);
      },
      VariableDeclarator(node) {
        if (node.id.type === "Identifier" && node.init !== null && isModuleLevelConst(node) && isLocalZodObjectSchema(node.init, namespaces)) {
          schemas.push({ identifier: node.id, initializer: node.init, name: node.id.name });
        }
        candidates.push(...localParseReturnCandidates(node, context.sourceCode));
      },
      CallExpression(node) {
        const candidate = directParseReturnCandidate(node);
        if (candidate !== null) candidates.push(candidate);
      },
      MemberExpression(node) {
        if (node.object.type === "Identifier" && node.property.type === "Identifier" && isPreferZodInferModuleReshaper(node.property.name)) {
          reshapedSchemas.add(node.object.name);
        }
      },
      TSTypeReference(node) {
        const { typeName } = node;
        const name = typeName.type === "Identifier"
          ? typeName.name
          : typeName.type === "TSQualifiedName" && typeName.right.type === "Identifier" ? typeName.right.name : null;
        if (name === null || !isPreferZodInferTypeConstraintName(name)) return;
        for (const argument of node.typeArguments?.params ?? []) collectConstrainedNames(argument, constrainedTypeNames);
      },
      "Program:exit"() {
        if (tsrs === null) return;
        // A candidate whose schema name matches no local schema cannot match one by symbol either.
        const schemaNames = new Set(schemas.map((schema) => schema.name));
        const pending = candidates.filter((candidate) => schemaNames.has(candidate.schema.name));
        if (pending.length === 0) return;
        const eligible = tsrs.run((file) => eligibleCandidates(file, pending));
        if (eligible !== null) report(eligible);
      },
    };
  },
});
