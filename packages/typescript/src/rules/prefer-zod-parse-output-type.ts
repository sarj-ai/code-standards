/**
 * @fileoverview prefer-zod-parse-output-type — a hand-written return contract can drift from the Zod schema that produces it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-zod-parse-output-type.test.ts
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";
import {
  isPreferZodInferModuleReshaper,
  isPreferZodInferTypeConstraintName,
  preferZodInferOwnsDefaultTwin,
} from "./prefer-zod-infer.js";

type MessageIds = "handWrittenParsedOutput";
type Options = readonly [];

export const PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION = {
  summary: "Derive a function's return contract from the local Zod schema whose parsed output it returns.",
  rationale: "A hand-written contract can drift from the runtime-validated value even while each declaration remains locally valid.",
  remediation: "Export or colocate the schema and derive the contract with `z.output<typeof Schema>`.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Requires TypeScript type information and a returned output from a module-level local Zod object schema's `.parse()` or `.safeParse()` result.",
    "Same-module name-correlated twins that `prefer-zod-infer` can prove are left to that established rule; this companion owns richer or renamed same-module and cross-module contracts proven by parse-return data flow.",
    "Only a single plain non-generic object interface or object type alias with exact property keys and bidirectional assignability is reported.",
    "Direct returns, nullish conditional branches, and one immutable local parse-result binding are followed; second aliases, assignments, helper calls, imported schemas, and other indirect data flow are intentionally excluded.",
    "Contracts returned from more than one distinct local schema are excluded because no single schema has unambiguous ownership.",
    "Readonly, augmented, indexed, callable, generated, constrained, any, unknown, and never contracts are excluded rather than guessed.",
    "The rule is report-only because moving or exporting a schema changes module ownership and requires human review.",
  ],
  examples: [
    {
      id: "schema-derived-return",
      title: "Derive the validated return contract",
      outcome: "no-match",
      files: [
        {
          path: "src/row.ts",
          source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); type Row = z.output<typeof RowSchema>; function load(): Row { return RowSchema.parse({}); }',
        },
      ],
      focusPath: "src/row.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "hand-written-parsed-return",
      title: "Do not hand-write the parsed return shape",
      outcome: "match",
      files: [
        {
          path: "src/contracts.ts",
          source: "export interface ParsedRow { id: string }",
        },
        {
          path: "src/row.ts",
          source: 'import { z } from "zod"; import type { ParsedRow } from "./contracts.js"; const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }',
        },
      ],
      focusPath: "src/row.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

interface LocalSchema {
  readonly identifier: TSESTree.Identifier;
  readonly initializer: TSESTree.Node;
  readonly name: string;
}

interface ParsedReturnCandidate {
  readonly call: TSESTree.CallExpression;
  readonly method: "parse" | "safeParse";
  readonly output: TSESTree.Node;
  readonly schema: TSESTree.Identifier;
  readonly typeName: string;
  readonly typeReference: TSESTree.TSTypeReference;
}

type FunctionNode =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;

function isModuleLevelConst(node: TSESTree.VariableDeclarator): boolean {
  const declaration = node.parent;
  if (
    declaration.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.kind !== "const"
  ) {
    return false;
  }
  const container = declaration.parent;
  return (
    container.type === AST_NODE_TYPES.Program ||
    (container.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      container.parent.type === AST_NODE_TYPES.Program)
  );
}

/** True only for a call chain rooted at `z.object()` or `z.strictObject()`. */
function isLocalZodObjectSchema(
  node: TSESTree.Node,
  namespaces: ReadonlySet<string>,
): boolean {
  let current = node;
  while (current.type === AST_NODE_TYPES.CallExpression) {
    const { callee } = current;
    if (
      callee.type !== AST_NODE_TYPES.MemberExpression ||
      callee.computed ||
      callee.property.type !== AST_NODE_TYPES.Identifier
    ) {
      return false;
    }
    if (callee.object.type === AST_NODE_TYPES.Identifier) {
      return (
        namespaces.has(callee.object.name) &&
        (callee.property.name === "object" || callee.property.name === "strictObject")
      );
    }
    current = callee.object;
  }
  return false;
}

interface ZodParseCall {
  readonly call: TSESTree.CallExpression;
  readonly method: "parse" | "safeParse";
  readonly schema: TSESTree.Identifier;
}

function zodParseCall(node: TSESTree.CallExpression): ZodParseCall | null {
  const { callee } = node;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.object.type !== AST_NODE_TYPES.Identifier ||
    callee.property.type !== AST_NODE_TYPES.Identifier ||
    (callee.property.name !== "parse" && callee.property.name !== "safeParse")
  ) {
    return null;
  }
  return {
    call: node,
    method: callee.property.name,
    schema: callee.object,
  };
}

function returnedOutputCandidate(
  parsed: ZodParseCall,
  output: TSESTree.Node,
): ParsedReturnCandidate | null {
  const owner = directReturnOwner(output);
  if (owner === null || enclosingFunction(parsed.call) !== owner) return null;
  const annotation = owner?.returnType?.typeAnnotation;
  if (annotation === undefined) return null;
  const typeReference = returnContractReference(annotation);
  if (typeReference === null || typeReference.typeName.type !== AST_NODE_TYPES.Identifier) {
    return null;
  }
  return {
    call: parsed.call,
    method: parsed.method,
    output,
    schema: parsed.schema,
    typeName: typeReference.typeName.name,
    typeReference,
  };
}

function directParseReturnCandidate(
  node: TSESTree.CallExpression,
): ParsedReturnCandidate | null {
  const parsed = zodParseCall(node);
  return parsed?.method === "parse" ? returnedOutputCandidate(parsed, node) : null;
}

function localParseReturnCandidates(
  node: TSESTree.VariableDeclarator,
  sourceCode: Readonly<TSESLint.SourceCode>,
): readonly ParsedReturnCandidate[] {
  if (
    node.id.type !== AST_NODE_TYPES.Identifier ||
    node.init?.type !== AST_NODE_TYPES.CallExpression ||
    node.parent.type !== AST_NODE_TYPES.VariableDeclaration ||
    node.parent.kind !== "const" ||
    enclosingFunction(node.init) === null
  ) {
    return [];
  }
  const parsed = zodParseCall(node.init);
  if (parsed === null) return [];
  const variable = sourceCode.getDeclaredVariables(node)[0];
  if (variable === undefined) return [];
  const candidates: ParsedReturnCandidate[] = [];
  for (const reference of variable.references) {
    const identifier = reference.identifier;
    const parent = identifier.parent;
    const output =
      parsed.method === "parse"
        ? identifier
        : parent.type === AST_NODE_TYPES.MemberExpression &&
            parent.object === identifier &&
            !parent.computed &&
            parent.property.type === AST_NODE_TYPES.Identifier &&
            parent.property.name === "data"
          ? parent
          : null;
    if (output === null) continue;
    const candidate = returnedOutputCandidate(parsed, output);
    if (candidate !== null) candidates.push(candidate);
  }
  return candidates;
}

/** Returns the owning function only through wrappers that preserve the parsed value. */
function directReturnOwner(node: TSESTree.Node): FunctionNode | null {
  let current: TSESTree.Node = node;
  while (current.parent !== undefined) {
    const parent: TSESTree.Node = current.parent;
    if (parent.type === AST_NODE_TYPES.ReturnStatement) {
      return parent.argument === current ? enclosingFunction(parent) : null;
    }
    if (
      parent.type === AST_NODE_TYPES.ArrowFunctionExpression &&
      parent.expression &&
      parent.body === current
    ) {
      return parent;
    }
    if (parent.type === AST_NODE_TYPES.AwaitExpression && parent.argument === current) {
      current = parent;
      continue;
    }
    if (parent.type === AST_NODE_TYPES.ConditionalExpression) {
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

function isNullishExpression(node: TSESTree.Node): boolean {
  return (
    (node.type === AST_NODE_TYPES.Literal && node.value === null) ||
    (node.type === AST_NODE_TYPES.Identifier && node.name === "undefined")
  );
}

function enclosingFunction(node: TSESTree.Node): FunctionNode | null {
  let current = node.parent;
  while (current != null) {
    if (
      current.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      current.type === AST_NODE_TYPES.FunctionDeclaration ||
      current.type === AST_NODE_TYPES.FunctionExpression
    ) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

/** Unwraps `Promise<T>` and nullish unions to one non-generic named contract. */
function returnContractReference(node: TSESTree.TypeNode): TSESTree.TSTypeReference | null {
  if (node.type === AST_NODE_TYPES.TSUnionType) {
    const substantive = node.types.filter(
      (member) =>
        member.type !== AST_NODE_TYPES.TSNullKeyword &&
        member.type !== AST_NODE_TYPES.TSUndefinedKeyword,
    );
    const [only] = substantive;
    return substantive.length === 1 && only !== undefined
      ? returnContractReference(only)
      : null;
  }
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    node.typeName.name === "Promise"
  ) {
    const parameters = node.typeArguments?.params ?? [];
    const [only] = parameters;
    return parameters.length === 1 && only !== undefined
      ? returnContractReference(only)
      : null;
  }
  return node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    (node.typeArguments?.params.length ?? 0) === 0
    ? node
    : null;
}

function recordZodNamespaces(
  node: TSESTree.Program,
  namespaces: Set<string>,
): void {
  for (const statement of node.body) {
    if (
      statement.type !== AST_NODE_TYPES.ImportDeclaration ||
      !isZodModule(statement.source.value)
    ) {
      continue;
    }
    for (const specifier of statement.specifiers) {
      if (
        specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
        specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
        (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
          specifier.imported.type === AST_NODE_TYPES.Identifier &&
          specifier.imported.name === "z")
      ) {
        namespaces.add(specifier.local.name);
      }
    }
  }
}

function collectConstrainedNames(node: TSESTree.TypeNode, names: Set<string>): void {
  if (node.type === AST_NODE_TYPES.TSTypeReference) {
    if (node.typeName.type === AST_NODE_TYPES.Identifier) names.add(node.typeName.name);
    for (const argument of node.typeArguments?.params ?? []) {
      collectConstrainedNames(argument, names);
    }
    return;
  }
  if (node.type === AST_NODE_TYPES.TSArrayType) {
    collectConstrainedNames(node.elementType, names);
    return;
  }
  if (
    node.type === AST_NODE_TYPES.TSUnionType ||
    node.type === AST_NODE_TYPES.TSIntersectionType
  ) {
    for (const member of node.types) collectConstrainedNames(member, names);
  }
}

function reportCandidates(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  services: ParserServicesWithTypeInformation,
  schemas: readonly LocalSchema[],
  candidates: readonly ParsedReturnCandidate[],
  zodNamespaces: ReadonlySet<string>,
  reshapedSchemas: ReadonlySet<string>,
  constrainedTypeNames: ReadonlySet<string>,
): void {
  const checker = services.program.getTypeChecker();
  const schemaSymbols = new Map<ts.Symbol, LocalSchema>();
  for (const schema of schemas) {
    const tsIdentifier = services.esTreeNodeToTSNodeMap.get(schema.identifier);
    const symbol = checker.getSymbolAtLocation(tsIdentifier);
    if (symbol !== undefined) schemaSymbols.set(symbol, schema);
  }
  const eligible: Array<{
    readonly candidate: ParsedReturnCandidate;
    readonly contractSymbol: ts.Symbol;
    readonly schema: LocalSchema;
    readonly schemaSymbol: ts.Symbol;
  }> = [];
  const reported = new Set<ts.Symbol>();
  for (const candidate of candidates) {
    const tsSchema = services.esTreeNodeToTSNodeMap.get(candidate.schema);
    const schemaSymbol = checker.getSymbolAtLocation(tsSchema);
    if (schemaSymbol === undefined) continue;
    const schema = schemaSymbols.get(schemaSymbol);
    if (schema === undefined) continue;
    const tsReference = services.esTreeNodeToTSNodeMap.get(candidate.typeReference);
    const contract = checker.getTypeAtLocation(tsReference);
    const contractSymbol = contract.aliasSymbol ?? contract.getSymbol();
    if (contractSymbol === undefined) continue;
    const declaration = handWrittenObjectDeclaration(contractSymbol);
    if (declaration === null || declaration.getSourceFile().isDeclarationFile) continue;
    const source = declaration.getSourceFile();
    if (isGeneratedFile(source.fileName, source.text)) continue;
    const tsOutput = services.esTreeNodeToTSNodeMap.get(candidate.output);
    const parsed = checker.getTypeAtLocation(tsOutput);
    // A `z.ZodType<Contract>` constraint deliberately makes the TypeScript
    // contract authoritative over the schema.
    const constrained =
      constrainedTypeNames.has(candidate.typeName) ||
      (parsed.aliasSymbol ?? parsed.getSymbol()) === contractSymbol;
    if (constrained) continue;
    if (declaration.getSourceFile() === tsSchema.getSourceFile()) {
      const estreeDeclaration = services.tsNodeToESTreeNodeMap.get(declaration);
      if (
        (estreeDeclaration.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
          estreeDeclaration.type === AST_NODE_TYPES.TSTypeAliasDeclaration) &&
        preferZodInferOwnsDefaultTwin({
          constrained,
          declaration: estreeDeclaration,
          initializer: schema.initializer,
          reshaped: reshapedSchemas.has(schema.name),
          schemaName: schema.name,
          typeName: candidate.typeName,
          zodNamespaces,
        })
      ) {
        continue;
      }
    }
    if (
      !exactObjectTypes(
        checker,
        checker.getNonNullableType(parsed),
        checker.getNonNullableType(contract),
      )
    ) {
      continue;
    }
    eligible.push({ candidate, contractSymbol, schema, schemaSymbol });
  }
  const schemasByContract = new Map<ts.Symbol, Set<ts.Symbol>>();
  for (const { contractSymbol, schemaSymbol } of eligible) {
    const contractSchemas = schemasByContract.get(contractSymbol) ?? new Set<ts.Symbol>();
    contractSchemas.add(schemaSymbol);
    schemasByContract.set(contractSymbol, contractSchemas);
  }
  for (const { candidate, contractSymbol, schema } of eligible) {
    if (reported.has(contractSymbol) || schemasByContract.get(contractSymbol)?.size !== 1) continue;
    reported.add(contractSymbol);
    context.report({
      node: candidate.typeReference,
      messageId: "handWrittenParsedOutput",
      data: {
        methodName: candidate.method,
        schemaName: schema.name,
        typeName: candidate.typeName,
      },
    });
  }
}

function handWrittenObjectDeclaration(
  symbol: ts.Symbol,
): ts.InterfaceDeclaration | ts.TypeAliasDeclaration | null {
  const declarations = symbol.getDeclarations() ?? [];
  const [declaration] = declarations;
  if (declarations.length !== 1 || declaration === undefined) return null;
  const plainMembers = (members: ts.NodeArray<ts.TypeElement>): boolean =>
    members.length > 0 &&
    members.every(
      (member) =>
        ts.isPropertySignature(member) &&
        member.type !== undefined &&
        member.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ReadonlyKeyword) !== true,
    );
  if (
    ts.isInterfaceDeclaration(declaration) &&
    declaration.typeParameters === undefined &&
    declaration.heritageClauses === undefined &&
    plainMembers(declaration.members)
  ) {
    return declaration;
  }
  if (
    ts.isTypeAliasDeclaration(declaration) &&
    declaration.typeParameters === undefined &&
    ts.isTypeLiteralNode(declaration.type) &&
    plainMembers(declaration.type.members)
  ) {
    return declaration;
  }
  return null;
}

function exactObjectTypes(
  checker: ts.TypeChecker,
  parsed: ts.Type,
  contract: ts.Type,
): boolean {
  const unsafeFlags = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never;
  if ((parsed.flags & unsafeFlags) !== 0 || (contract.flags & unsafeFlags) !== 0) return false;
  if (
    checker.getIndexInfosOfType(parsed).length > 0 ||
    checker.getIndexInfosOfType(contract).length > 0 ||
    checker.getSignaturesOfType(parsed, ts.SignatureKind.Call).length > 0 ||
    checker.getSignaturesOfType(contract, ts.SignatureKind.Call).length > 0
  ) {
    return false;
  }
  const names = (type: ts.Type): string[] =>
    checker.getPropertiesOfType(type).map((property) => property.getName()).sort();
  const parsedNames = names(parsed);
  const contractNames = names(contract);
  return (
    parsedNames.length > 0 &&
    parsedNames.length === contractNames.length &&
    parsedNames.every((name, index) => name === contractNames[index]) &&
    checker.isTypeAssignableTo(parsed, contract) &&
    checker.isTypeAssignableTo(contract, parsed)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-zod-parse-output-type",
  documentation: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Derive a function's return contract from the local Zod schema whose parsed output it returns.",
    },
    schema: [],
    messages: {
      handWrittenParsedOutput:
        "`{{typeName}}` exactly restates the validated output returned from `{{schemaName}}.{{methodName}}()`. Export or colocate the schema and derive the contract with `z.output<typeof {{schemaName}}>` so the runtime and compile-time shapes cannot drift.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      isStoryFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
      return {};
    }
    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }
    if (services === null) return {};

    const namespaces = new Set<string>();
    const constrainedTypeNames = new Set<string>();
    const reshapedSchemas = new Set<string>();
    const schemas: LocalSchema[] = [];
    const candidates: ParsedReturnCandidate[] = [];
    return {
      Program(node): void {
        recordZodNamespaces(node, namespaces);
      },
      VariableDeclarator(node): void {
        if (
          node.id.type === AST_NODE_TYPES.Identifier &&
          node.init !== null &&
          isModuleLevelConst(node) &&
          isLocalZodObjectSchema(node.init, namespaces)
        ) {
          schemas.push({ identifier: node.id, initializer: node.init, name: node.id.name });
        }
        candidates.push(...localParseReturnCandidates(node, context.sourceCode));
      },
      CallExpression(node): void {
        const candidate = directParseReturnCandidate(node);
        if (candidate !== null) candidates.push(candidate);
      },
      "MemberExpression[computed=false]"(node: TSESTree.MemberExpression): void {
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.property.type === AST_NODE_TYPES.Identifier &&
          isPreferZodInferModuleReshaper(node.property.name)
        ) {
          reshapedSchemas.add(node.object.name);
        }
      },
      TSTypeReference(node): void {
        const { typeName } = node;
        const name =
          typeName.type === AST_NODE_TYPES.Identifier
            ? typeName.name
            : typeName.type === AST_NODE_TYPES.TSQualifiedName &&
                typeName.right.type === AST_NODE_TYPES.Identifier
              ? typeName.right.name
              : null;
        if (name === null || !isPreferZodInferTypeConstraintName(name)) return;
        for (const argument of node.typeArguments?.params ?? []) {
          collectConstrainedNames(argument, constrainedTypeNames);
        }
      },
      "Program:exit"(): void {
        reportCandidates(
          context,
          services,
          schemas,
          candidates,
          namespaces,
          reshapedSchemas,
          constrainedTypeNames,
        );
      },
    };
  },
});
