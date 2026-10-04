/**
 * @fileoverview require-explicit-contract-implementation — detect structural substitutes rejected by nominal runtime guards.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-explicit-contract-implementation.test.ts
 */

import type { ESTree, SourceCode } from "@oxlint/plugins";
import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { resolveVariable, unwrapExpression } from "./_scope.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import {
  createTypeAliasEnvironment,
  resolvedTypeMatches,
  type TypeAliasEnvironment,
} from "./_type-alias-resolution.js";

type MessageIds = "declareActualContract";
type Options = readonly [];

export const REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Require nominal inheritance when an injected abstract class is rejected by an instanceof guard.",
  rationale:
    "A structurally assignable fake can still fail a constructor's nominal runtime guard. Pure structural interfaces do not require an implements clause.",
  remediation:
    "Use an implementation inheriting the existing abstract class, or remove the nominal guard if the boundary is intentionally structural.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires direct construction of both owned consumer and collaborator classes, with a first-statement consumer constructor guard rejecting the exact parameter with if (!(parameter instanceof Contract)) throw.",
    "The contract must resolve to an abstract class without decorators, unresolved ancestors, or custom computed static members in its resolved hierarchy.",
    "Structural interfaces, non-rejecting branches, reassignment before the guard, casts, unresolved heritage, dynamic factories, explicit implementation constructors or initializers, modules referencing prototype-mutator members or assigning prototypes, and third-party classes are excluded. Imported declarations and signatures not proven from same-file syntax remain unresolved; no type checker is fabricated.",
  ],
  examples: [
    {
      id: "runtime-nominal-guard-with-structural-fake",
      title:
        "A structurally compatible fake fails the constructor's runtime guard",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "runtime-nominal-guard-with-inherited-fake",
      title: "The fake satisfies the existing nominal runtime contract",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function localClass(
  source: SourceCode,
  identifier: ESTree.Node,
): ESTree.Class | null {
  if (identifier.type !== "Identifier") return null;
  const definitions = resolveVariable(source, identifier)?.defs;
  const declaration = definitions?.length === 1 ? definitions[0]?.node : null;
  return declaration?.type === "ClassDeclaration" ? declaration : null;
}

function hasPrototypeMutation(node: ESTree.Node): boolean {
  const member = memberName(node);
  if (
    member === "setPrototypeOf" ||
    member === "__proto__" ||
    member === "hasInstance"
  )
    return true;
  if (
    node.type === "AssignmentExpression" &&
    memberName(node.left) === "prototype"
  )
    return true;
  let mutation = false;
  forEachOwnAstChild(node, (child) => {
    if (hasPrototypeMutation(child)) mutation = true;
  });
  return mutation;
}

function memberName(node: ESTree.Node): string | null {
  if (node.type !== "MemberExpression") return null;
  if (!node.computed && node.property.type === "Identifier")
    return node.property.name;
  return node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
    ? node.property.value
    : null;
}

function ordinaryHierarchy(
  source: SourceCode,
  declaration: ESTree.Class,
  seen = new Set<ESTree.Class>(),
): boolean {
  if (seen.has(declaration) || declaration.decorators.length > 0) return false;
  seen.add(declaration);
  if (
    declaration.body.body.some(
      (member) => "computed" in member && member.computed && member.static,
    )
  )
    return false;
  if (declaration.superClass === null) return true;
  const parent = localClass(source, declaration.superClass);
  return parent !== null && ordinaryHierarchy(source, parent, seen);
}

function nominallyInherits(
  source: SourceCode,
  declaration: ESTree.Class,
  target: ESTree.Class,
  seen = new Set<ESTree.Class>(),
): boolean | null {
  if (
    seen.has(declaration) ||
    declaration.decorators.length > 0 ||
    declaration.body.body.some(
      (member) =>
        (member.type === "MethodDefinition" && member.kind === "constructor") ||
        (member.type === "PropertyDefinition" && member.value !== null),
    )
  )
    return null;
  seen.add(declaration);
  if (declaration.superClass === null) return false;
  const parent = localClass(source, declaration.superClass);
  return parent === null
    ? null
    : parent === target || nominallyInherits(source, parent, target, seen);
}

function constructorOf(
  declaration: ESTree.Class,
): ESTree.MethodDefinition | null {
  const member = declaration.body.body.find(
    (member) =>
      member.type === "MethodDefinition" && member.kind === "constructor",
  );
  return member?.type === "MethodDefinition" ? member : null;
}

function parameterIdentifier(
  parameter: ESTree.ParamPattern | undefined,
): ESTree.BindingIdentifier | null {
  if (parameter?.type === "TSParameterProperty")
    parameter = parameter.parameter;
  if (parameter?.type === "AssignmentPattern") parameter = parameter.left;
  return parameter?.type === "Identifier" ? parameter : null;
}

function annotatedContract(
  source: SourceCode,
  parameter: ESTree.BindingIdentifier,
  types: TypeAliasEnvironment,
): ESTree.Class | null {
  const type = parameter.typeAnnotation?.typeAnnotation;
  if (type == null) return null;
  let contract: ESTree.Class | null = null;
  const resolved = resolvedTypeMatches(type, types, (current, matches) => {
    if (current.type === "TSUnionType") {
      const members = current.types.filter(
        (member) =>
          member.type !== "TSNullKeyword" &&
          member.type !== "TSUndefinedKeyword",
      );
      return (
        members.length === 1 && members[0] !== undefined && matches(members[0])
      );
    }
    if (
      current.type !== "TSTypeReference" ||
      current.typeName.type !== "Identifier" ||
      current.typeArguments?.params.length
    )
      return false;
    const declaration = localClass(source, current.typeName);
    if (declaration?.abstract !== true) return false;
    contract = declaration;
    return true;
  });
  return resolved ? contract : null;
}

function rejectsStructuralArgument(
  source: SourceCode,
  constructor: ESTree.MethodDefinition,
  parameter: ESTree.BindingIdentifier,
  contract: ESTree.Class,
): boolean {
  const first = constructor.value.body?.body[0];
  if (first?.type !== "IfStatement" || !alwaysThrows(first.consequent))
    return false;
  const condition = unwrapExpression(first.test);
  if (condition.type !== "UnaryExpression" || condition.operator !== "!")
    return false;
  const comparison = unwrapExpression(condition.argument);
  return (
    comparison.type === "BinaryExpression" &&
    comparison.operator === "instanceof" &&
    comparison.left.type === "Identifier" &&
    resolveVariable(source, comparison.left) ===
      resolveVariable(source, parameter) &&
    localClass(source, comparison.right) === contract
  );
}

function alwaysThrows(statement: ESTree.Statement): boolean {
  return (
    statement.type === "ThrowStatement" ||
    (statement.type === "BlockStatement" &&
      statement.body.length === 1 &&
      statement.body[0]?.type === "ThrowStatement")
  );
}

const PRIMITIVE_TYPES: ReadonlySet<string> = new Set([
  "TSStringKeyword",
  "TSNumberKeyword",
  "TSBooleanKeyword",
  "TSBigIntKeyword",
  "TSSymbolKeyword",
]);

/** Require a same-file behavioral surface without guessing assignability. */
function hasMatchingBehavior(
  source: SourceCode,
  declaration: ESTree.Class,
  contract: ESTree.Class,
): boolean {
  const actual = new Map<string, ESTree.MethodDefinition>();
  const required = new Map<string, ESTree.MethodDefinition>();
  const collect = (
    current: ESTree.Class,
    methods: typeof actual,
    seen: Set<ESTree.Class>,
  ): boolean => {
    if (seen.has(current)) return false;
    seen.add(current);
    for (const member of current.body.body) {
      if ("static" in member && member.static) continue;
      if (
        (member.type !== "MethodDefinition" &&
          member.type !== "TSAbstractMethodDefinition") ||
        member.kind !== "method"
      ) {
        if (methods === required) return false;
        continue;
      }
      const name = publicMethodName(member);
      if (name === null) return false;
      if (!methods.has(name)) methods.set(name, member);
    }
    if (current.superClass === null) return true;
    const parent = localClass(source, current.superClass);
    return parent !== null && collect(parent, methods, seen);
  };
  if (
    !collect(contract, required, new Set()) ||
    !collect(declaration, actual, new Set()) ||
    required.size === 0
  )
    return false;
  return [...required].every(([name, method]) => {
    const implementation = actual.get(name);
    if (
      !implementation ||
      method.value.params.length !== implementation.value.params.length
    )
      return false;
    const result = method.value.returnType?.typeAnnotation;
    // A zero-parameter void operation accepts an inferred implementation return.
    if (method.value.params.length === 0 && result?.type === "TSVoidKeyword")
      return true;
    if (
      result?.type !== "TSVoidKeyword" &&
      (!result ||
        !PRIMITIVE_TYPES.has(result.type) ||
        implementation.value.returnType?.typeAnnotation.type !== result.type)
    )
      return false;
    return method.value.params.every((parameter, index) => {
      const expected = parameterIdentifier(parameter);
      const supplied = parameterIdentifier(implementation.value.params[index]);
      const expectedType = expected?.typeAnnotation?.typeAnnotation;
      return (
        expected !== null &&
        supplied !== null &&
        expected.optional === supplied.optional &&
        expectedType != null &&
        PRIMITIVE_TYPES.has(expectedType.type) &&
        supplied.typeAnnotation?.typeAnnotation.type === expectedType.type
      );
    });
  });
}

function publicMethodName(member: ESTree.MethodDefinition): string | null {
  if (
    member.computed ||
    member.key.type !== "Identifier" ||
    member.accessibility === "private" ||
    member.accessibility === "protected"
  )
    return null;
  return member.key.name;
}

export default createRule<Options, MessageIds>({
  name: "require-explicit-contract-implementation",
  documentation: REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      declareActualContract:
        "`{{implementation}}` structurally matches `{{contract}}` but fails the rejecting instanceof guard; use nominal inheritance or make the boundary structural.",
    },
  },
  defaultOptions: [],
  create(context) {
    const origin = sourceOrigin(context);
    if (
      isGeneratedFile(origin.filename, origin.text) ||
      hasPrototypeMutation(context.sourceCode.ast)
    )
      return {};
    const source = context.sourceCode;
    const types = createTypeAliasEnvironment(source.ast, source.visitorKeys);
    return {
      NewExpression(node): void {
        const consumer = localClass(source, node.callee);
        if (
          consumer === null ||
          consumer.decorators.length > 0 ||
          node.typeArguments?.params.length
        )
          return;
        const constructor = constructorOf(consumer);
        if (constructor === null) return;
        for (const [index, argument] of node.arguments.entries()) {
          if (
            argument.type !== "NewExpression" ||
            argument.typeArguments?.params.length
          )
            continue;
          const implementation = localClass(source, argument.callee);
          const parameter = parameterIdentifier(
            constructor.value.params[index],
          );
          const contract =
            parameter === null
              ? null
              : annotatedContract(source, parameter, types);
          if (
            implementation === null ||
            parameter === null ||
            contract === null ||
            !ordinaryHierarchy(source, contract) ||
            !rejectsStructuralArgument(
              source,
              constructor,
              parameter,
              contract,
            ) ||
            nominallyInherits(source, implementation, contract) !== false ||
            !hasMatchingBehavior(source, implementation, contract)
          )
            continue;
          context.report({
            node: argument,
            messageId: "declareActualContract",
            data: {
              implementation: implementation.id?.name ?? "class",
              contract: contract.id?.name ?? "class",
            },
          });
        }
      },
    };
  },
});
