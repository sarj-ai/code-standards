/**
 * @fileoverview no-known-value-widening — keep locally known values out of ambiguous widened dictionary slots.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-known-value-widening.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

import {
  classifyUnsafeDictionaryValue,
  classifyWideningTarget,
  createTypeEnvironment,
  isKnownEvidenceExpression,
  type TypeEnvironment,
  type WideningTarget,
} from "./_dictionary-types.js";
import {
  containsUnknownType,
  functionParameterBindingName,
  functionParameterTypeAnnotation,
} from "./_function-parameters.js";
import { resolveVariable } from "./_scope.js";
import { resolvedTypeMatches } from "./_type-alias-resolution.js";

import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";

type FunctionExpression = ESTree.ArrowFunctionExpression | ESTree.Function;

function unwrapExpression(expression: ESTree.Expression): ESTree.Expression {
  let current = expression;
  while (
    current.type === "ParenthesizedExpression" ||
    current.type === "TSAsExpression" ||
    current.type === "TSSatisfiesExpression" ||
    current.type === "TSTypeAssertion" ||
    current.type === "TSNonNullExpression"
  ) {
    current = current.expression;
  }
  return current;
}

function variableDeclarator(
  variable: Variable,
): ESTree.VariableDeclarator | null {
  if (variable.defs.length !== 1) return null;
  const [definition] = variable.defs;
  return definition?.type === "Variable" &&
    definition.node.type === "VariableDeclarator" &&
    definition.node.id.type === "Identifier"
    ? definition.node
    : null;
}

function isStableConstVariable(
  variable: Variable,
  declarator: ESTree.VariableDeclarator,
): boolean {
  return (
    declarator.parent.type === "VariableDeclaration" &&
    declarator.parent.kind === "const" &&
    variable.references.every(
      (reference) => reference.init || !reference.isWrite(),
    )
  );
}

function hasKnownEvidence(
  sourceCode: SourceCode,
  expression: ESTree.Expression,
  environment: TypeEnvironment,
  visitedVariables = new Set<Variable>(),
): boolean {
  if (isKnownEvidenceExpression(expression)) return true;
  const unwrapped = unwrapExpression(expression);
  if (unwrapped.type !== "Identifier") return false;
  const variable = resolveVariable(sourceCode, unwrapped);
  if (variable === null || visitedVariables.has(variable)) return false;
  const annotation = variableTypeAnnotation(sourceCode, variable);
  if (
    annotation !== null &&
    resolvedTypeMatches(
      annotation.typeAnnotation,
      environment.typeAliases,
      (type) =>
        type.type === "TSTypeLiteral" &&
        type.members.some((member) => member.type !== "TSIndexSignature"),
    )
  )
    return true;
  const declarator = variableDeclarator(variable);
  if (
    declarator === null ||
    declarator.init === null ||
    !isStableConstVariable(variable, declarator)
  ) {
    return false;
  }
  visitedVariables.add(variable);
  return hasKnownEvidence(
    sourceCode,
    declarator.init,
    environment,
    visitedVariables,
  );
}

function hasOnlyKnownWrites(
  sourceCode: SourceCode,
  variable: Variable,
  environment: TypeEnvironment,
): boolean {
  return variable.references.every(
    (reference) =>
      !reference.isWrite() ||
      (reference.writeExpr !== null &&
        hasKnownCallArgumentEvidence(
          sourceCode,
          reference.writeExpr,
          environment,
        )),
  );
}

function isFunctionExpression(node: ESTree.Node): node is FunctionExpression {
  return (
    node.type === "ArrowFunctionExpression" ||
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "TSDeclareFunction" ||
    node.type === "TSEmptyBodyFunctionExpression"
  );
}

function localFunctionForCall(
  sourceCode: SourceCode,
  callee: ESTree.Expression,
): FunctionExpression | null {
  const unwrapped = unwrapExpression(callee);
  if (isFunctionExpression(unwrapped)) return unwrapped;
  if (unwrapped.type !== "Identifier") return null;
  const variable = resolveVariable(sourceCode, unwrapped);
  if (variable === null || variable.defs.length !== 1) return null;
  const [definition] = variable.defs;
  if (definition === undefined) return null;
  if (
    definition.type === "FunctionName" &&
    isFunctionExpression(definition.node)
  ) {
    return definition.node;
  }
  if (
    definition.type !== "Variable" ||
    definition.node.type !== "VariableDeclarator"
  ) {
    return null;
  }
  const initializer = definition.node.init;
  if (initializer === null) return null;
  const unwrappedInitializer = unwrapExpression(initializer);
  return isFunctionExpression(unwrappedInitializer)
    ? unwrappedInitializer
    : null;
}

function hasKnownCallArgumentEvidence(
  sourceCode: SourceCode,
  expression: ESTree.Expression,
  environment: TypeEnvironment,
  visitedVariables = new Set<Variable>(),
): boolean {
  if (
    expression.type === "ParenthesizedExpression" ||
    expression.type === "TSNonNullExpression"
  ) {
    return hasKnownCallArgumentEvidence(
      sourceCode,
      expression.expression,
      environment,
      visitedVariables,
    );
  }
  if (
    expression.type === "TSAsExpression" ||
    expression.type === "TSTypeAssertion"
  ) {
    return hasInformativeType(expression.typeAnnotation, environment);
  }
  if (expression.type === "TSSatisfiesExpression") {
    return hasKnownCallArgumentEvidence(
      sourceCode,
      expression.expression,
      environment,
      visitedVariables,
    );
  }
  if (expression.type === "CallExpression") {
    const owner = localFunctionForCall(sourceCode, expression.callee);
    const returnType = owner?.returnType?.typeAnnotation;
    return (
      returnType !== undefined && hasInformativeType(returnType, environment)
    );
  }
  if (expression.type !== "Identifier")
    return isKnownEvidenceExpression(expression);
  const variable = resolveVariable(sourceCode, expression);
  if (variable === null || visitedVariables.has(variable)) return false;
  const annotation = variableTypeAnnotation(sourceCode, variable);
  if (annotation !== null) {
    return hasInformativeType(annotation.typeAnnotation, environment);
  }
  const declarator = variableDeclarator(variable);
  if (
    declarator === null ||
    declarator.init === null ||
    !isStableConstVariable(variable, declarator)
  ) {
    return false;
  }
  visitedVariables.add(variable);
  return hasKnownCallArgumentEvidence(
    sourceCode,
    declarator.init,
    environment,
    visitedVariables,
  );
}

function typePredicateSubjectIndex(
  sourceCode: SourceCode,
  owner: FunctionExpression,
): number | null {
  const predicate = owner.returnType?.typeAnnotation;
  if (
    predicate?.type !== "TSTypePredicate" ||
    predicate.parameterName.type !== "Identifier"
  ) {
    return null;
  }
  const predicateParameterName = predicate.parameterName.name;
  const index = owner.params.findIndex(
    (parameter) =>
      functionParameterBindingName(parameter, sourceCode) ===
      predicateParameterName,
  );
  return index === -1 ? null : index;
}

function annotationTarget(
  annotation: ESTree.TSTypeAnnotation | null | undefined,
  environment: TypeEnvironment,
): WideningTarget | null {
  return annotation === null || annotation === undefined
    ? null
    : classifyWideningTarget(annotation.typeAnnotation, environment);
}

function enclosingFunction(node: ESTree.Node): FunctionExpression | null {
  let current: ESTree.Node | null = node.parent;
  while (current !== null && current.type !== "Program") {
    if (
      current.type === "ArrowFunctionExpression" ||
      current.type === "FunctionDeclaration" ||
      current.type === "FunctionExpression"
    ) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

function sourceKeyName(
  sourceCode: SourceCode,
  key: ESTree.PropertyKey,
): string {
  if (key.type === "Identifier" || key.type === "PrivateIdentifier")
    return key.name;
  if (key.type === "Literal") return String(key.value);
  return sourceCode.getText(key);
}

function functionName(
  sourceCode: SourceCode,
  owner: FunctionExpression | null,
): string {
  if (owner === null) return "anonymous function";
  if (owner.id !== null) return owner.id.name;
  const parent = owner.parent;
  if (parent.type === "VariableDeclarator" && parent.id.type === "Identifier")
    return parent.id.name;
  if (parent.type === "MethodDefinition")
    return sourceKeyName(sourceCode, parent.key);
  return "anonymous function";
}

function isEmptyObjectExpression(expression: ESTree.Expression): boolean {
  const unwrapped = unwrapExpression(expression);
  return (
    unwrapped.type === "ObjectExpression" && unwrapped.properties.length === 0
  );
}

function isDictionaryAccumulatorTarget(destination: WideningTarget): boolean {
  return (
    destination.kind === "open dictionary" ||
    destination.kind === "generic container"
  );
}

function hasParentAssertion(node: ESTree.Node): boolean {
  return (
    node.parent?.type === "TSAsExpression" ||
    node.parent?.type === "TSTypeAssertion"
  );
}

export const NO_KNOWN_VALUE_WIDENING_DOCUMENTATION = {
  summary:
    "Preserve a known value's contract instead of widening a local binding to unknown, object, or an unknown-valued dictionary.",
  rationale:
    "Erasing a typed value's fields forces downstream code to rediscover the same contract through casts, reflection, or representation checks.",
  remediation:
    "Keep the inferred type, select the required domain fields, or use satisfies to check compatibility without erasing evidence.",
  category: "maintainability",
  limitations: [
    "Local AST and lexical type aliases identify broad unknown/object/anonymous dictionary annotations, assertions, assignments, return values and local type-predicate calls.",
    "Known expressions include literals, object/array/function expressions, immutable initializer aliases and explicitly declared local object contracts resolved through lexical type aliases. A mutable unknown binding is checked only when every lexical write has known evidence; explicit opaque ingress annotations are preserved. Return annotations require every explicit return to have known evidence; informative anonymous object returns are preserved. Imported type contracts, destructured members and inferred call results are not resolved for ordinary widening.",
    "Broad string-key dictionaries are intentionally stricter than the old unknown-valued-only policy; use finite keys, inference, satisfies or a named owner contract. No autofix changes boundaries.",
  ],
  examples: [
    {
      id: "erased-tool",
      title: "A dictionary erases a known tool contract",
      outcome: "match",
      files: [
        {
          path: "src/tool.ts",
          source:
            "const tool = { name: 'launch', enabled: true };\nconst fields: Record<string, unknown> = tool;",
        },
      ],
      focusPath: "src/tool.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "retained-tool",
      title: "Retain the tool's fields",
      outcome: "no-match",
      files: [
        {
          path: "src/tool.ts",
          source:
            "const tool = { name: 'launch', enabled: true };\nconst fields = tool;",
        },
      ],
      focusPath: "src/tool.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function variableTypeAnnotation(
  sourceCode: SourceCode,
  variable: Variable,
): ESTree.TSTypeAnnotation | null {
  if (variable.defs.length !== 1) return null;
  const [definition] = variable.defs;
  if (definition === undefined) return null;
  if (
    definition.type === "Variable" &&
    definition.node.type === "VariableDeclarator" &&
    definition.node.id.type === "Identifier"
  ) {
    return definition.node.id.typeAnnotation ?? null;
  }
  if (
    definition.type !== "Parameter" ||
    !isFunctionExpression(definition.node)
  ) {
    return null;
  }
  const parameter = definition.node.params.find(
    (candidate) =>
      functionParameterBindingName(candidate, sourceCode) === variable.name,
  );
  return parameter === undefined
    ? null
    : (functionParameterTypeAnnotation(parameter) ?? null);
}

function hasInformativeType(
  type: ESTree.TSType,
  environment: TypeEnvironment,
): boolean {
  return classifyUnsafeDictionaryValue(type, environment) === null;
}
/** Detect sound syntactic cases where a known value is explicitly widened and loses evidence. */
export default createRule({
  name: "no-known-value-widening",
  documentation: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION,
  defaultOptions: [],
  meta: {
    type: "problem",
    docs: {
      description: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION.summary,
    },
    messages: {
      widening:
        "The explicit {{target}} type on {{subject}} discards known type evidence. Keep inference, validate with `satisfies`, or use a named owner contract.",
    },
  },
  createOnce(context) {
    let environment: TypeEnvironment | null = null;
    const returns = new Map<
      FunctionExpression,
      Array<ESTree.Expression | null>
    >();

    const reportFlow = (
      expression: ESTree.Expression,
      destination: WideningTarget | null,
      subject: string,
    ) => {
      if (destination === null) return;
      if (
        isDictionaryAccumulatorTarget(destination) &&
        isEmptyObjectExpression(expression)
      ) {
        return;
      }
      if (
        environment === null ||
        !hasKnownEvidence(context.sourceCode, expression, environment)
      )
        return;
      context.report({
        node: expression,
        messageId: "widening",
        data: { subject, target: destination.kind },
      });
    };

    const targetFromAnnotation = (
      annotation: ESTree.TSTypeAnnotation | null | undefined,
    ) =>
      environment === null ? null : annotationTarget(annotation, environment);

    return {
      Program(node) {
        returns.clear();
        environment = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
          ? null
          : createTypeEnvironment(node, context.sourceCode.visitorKeys);
      },
      "Program:exit"() {
        const returnEnvironment = environment;
        if (returnEnvironment === null) return;
        for (const [owner, expressions] of returns) {
          if (
            targetFromAnnotation(owner.returnType)?.kind === "anonymous object"
          )
            continue;
          if (
            !expressions.every(
              (expression) =>
                expression !== null &&
                hasKnownEvidence(
                  context.sourceCode,
                  expression,
                  returnEnvironment,
                ),
            )
          )
            continue;
          for (const expression of expressions) {
            if (expression !== null)
              reportFlow(
                expression,
                targetFromAnnotation(owner.returnType),
                `return value of \`${functionName(context.sourceCode, owner)}\``,
              );
          }
        }
        returns.clear();
      },
      VariableDeclarator(node) {
        if (node.init === null || node.id.type !== "Identifier") return;
        const destination = targetFromAnnotation(node.id.typeAnnotation);
        const variable = resolveVariable(context.sourceCode, node.id);
        if (
          destination?.kind === "unknown" &&
          node.parent.type === "VariableDeclaration" &&
          node.parent.kind !== "const" &&
          variable !== null &&
          environment !== null &&
          !hasOnlyKnownWrites(context.sourceCode, variable, environment)
        )
          return;
        reportFlow(node.init, destination, `binding \`${node.id.name}\``);
      },
      PropertyDefinition(node) {
        if (node.value === null) return;
        reportFlow(
          node.value,
          targetFromAnnotation(node.typeAnnotation),
          `property \`${sourceKeyName(context.sourceCode, node.key)}\``,
        );
      },
      AccessorProperty(node) {
        if (node.value === null) return;
        reportFlow(
          node.value,
          targetFromAnnotation(node.typeAnnotation),
          `property \`${sourceKeyName(context.sourceCode, node.key)}\``,
        );
      },
      AssignmentExpression(node) {
        if (node.operator !== "=" || node.left.type !== "Identifier") return;
        const variable = resolveVariable(context.sourceCode, node.left);
        if (variable === null) return;
        const declarator = variableDeclarator(variable);
        if (declarator === null || declarator.id.type !== "Identifier") return;
        const destination = targetFromAnnotation(declarator.id.typeAnnotation);
        if (
          destination?.kind === "unknown" &&
          declarator.parent.type === "VariableDeclaration" &&
          declarator.parent.kind !== "const" &&
          environment !== null &&
          !hasOnlyKnownWrites(context.sourceCode, variable, environment)
        )
          return;
        reportFlow(
          node.right,
          destination,
          `binding \`${declarator.id.name}\``,
        );
      },
      CallExpression(node) {
        if (environment === null) return;
        const owner = localFunctionForCall(context.sourceCode, node.callee);
        if (owner === null) return;
        const parameterIndex = typePredicateSubjectIndex(
          context.sourceCode,
          owner,
        );
        if (parameterIndex === null) return;
        const parameter = owner.params[parameterIndex];
        const argument = node.arguments[parameterIndex];
        if (
          parameter === undefined ||
          argument === undefined ||
          argument.type === "SpreadElement"
        ) {
          return;
        }
        const parameterAnnotation = functionParameterTypeAnnotation(parameter);
        if (
          parameterAnnotation === null ||
          parameterAnnotation === undefined ||
          !containsUnknownType(parameterAnnotation.typeAnnotation)
        ) {
          return;
        }
        if (
          !hasKnownCallArgumentEvidence(
            context.sourceCode,
            argument,
            environment,
          )
        ) {
          return;
        }
        context.report({
          node: argument,
          messageId: "widening",
          data: {
            subject: `argument for parameter \`${functionParameterBindingName(parameter, context.sourceCode)}\` of \`${functionName(context.sourceCode, owner)}\``,
            target: "unknown",
          },
        });
      },
      ReturnStatement(node) {
        if (environment === null) return;
        const owner = enclosingFunction(node);
        if (owner === null) return;
        const expressions = returns.get(owner) ?? [];
        expressions.push(node.argument);
        returns.set(owner, expressions);
      },
      ArrowFunctionExpression(node) {
        if (node.body.type === "BlockStatement") return;
        if (targetFromAnnotation(node.returnType)?.kind === "anonymous object")
          return;
        reportFlow(
          node.body,
          targetFromAnnotation(node.returnType),
          `return value of \`${functionName(context.sourceCode, node)}\``,
        );
      },
      TSAsExpression(node) {
        if (environment === null || hasParentAssertion(node)) return;
        reportFlow(
          node.expression,
          classifyWideningTarget(node.typeAnnotation, environment),
          "assertion",
        );
      },
      TSTypeAssertion(node) {
        if (environment === null || hasParentAssertion(node)) return;
        reportFlow(
          node.expression,
          classifyWideningTarget(node.typeAnnotation, environment),
          "assertion",
        );
      },
    };
  },
});
