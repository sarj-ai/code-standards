/**
 * @fileoverview prefer-zod-parse-output-type — a hand-written return contract can drift from the Zod schema that produces it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-zod-parse-output-type.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import {
  isGlobalReference,
  resolveVariable,
  unwrapExpression,
} from "./_scope.js";
import {
  preferZodInferOwnsDefaultTwin,
  sameStaticObjectShape,
} from "./prefer-zod-infer.js";

type MessageIds = "handWrittenParsedOutput";
type Options = readonly [];

export const PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION = {
  summary:
    "Derive a function's return contract from the local Zod schema whose parsed output it returns.",
  rationale:
    "A hand-written contract can drift from the runtime-validated value even while each declaration remains locally valid.",
  remediation:
    "Export or colocate the schema and derive the contract with `z.output<typeof Schema>`.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only same-file manual interfaces/object aliases and immutable module-level schemas rooted in actual Zod imports are checked. Primitive, optional and nullable fields must positively match in syntax; nested, collection, imported and inferred shapes are not resolved.",
    "Direct parse returns, safeParse.data and one immutable local result binding are followed. Casts, mutable bindings, multiple schema owners, transforms, explicit schema constraints and unrelated return branches are excluded.",
    "Canonical local twins remain owned by prefer-zod-infer. This companion checks renamed contracts proven by returned local schema output; it does not establish cross-module assignability or safeParse success narrowing.",
    "The rule is report-only; deriving a domain contract from its validation schema requires review of ownership and schema input versus output.",
  ],
  examples: [
    {
      id: "schema-derived-return",
      title: "Derive the validated return contract",
      outcome: "no-match",
      files: [
        {
          path: "src/row.ts",
          source:
            'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); type Row = z.output<typeof RowSchema>; function load(): Row { return RowSchema.parse({}); }',
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
          path: "src/row.ts",
          source:
            'import { z } from "zod"; interface ParsedRow { id: string } const RowSchema = z.object({ id: z.string() }); function load(): ParsedRow { return RowSchema.parse({}); }',
        },
      ],
      focusPath: "src/row.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

interface LocalSchema {
  readonly declaration: ESTree.VariableDeclarator;
  readonly variable: Variable;
  readonly namespaces: ReadonlySet<string>;
}
interface ParsedOutput {
  readonly schema: LocalSchema;
  readonly method: "parse" | "safeParse";
}
interface ReturnFrame {
  readonly reference: ESTree.TSTypeReference | null;
  readonly contract:
    | ESTree.TSInterfaceDeclaration
    | ESTree.TSTypeAliasDeclaration
    | null;
  readonly outputs: ParsedOutput[];
  opaque: boolean;
}
type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

const SHAPE_PRESERVING: ReadonlySet<string> = new Set([
  "describe",
  "refine",
  "superRefine",
  "check",
  "meta",
  "nullable",
  "optional",
  "nullish",
]);

function parsedOutput(
  source: SourceCode,
  value: ESTree.Node,
  followBinding = true,
): ParsedOutput | null {
  if (
    value.type === "TSAsExpression" ||
    value.type === "TSTypeAssertion" ||
    value.type === "TSSatisfiesExpression"
  )
    return null;
  const expression = unwrapExpression(value);
  if (expression.type === "AwaitExpression")
    return parsedOutput(source, expression.argument, followBinding);
  const direct = parsedCall(source, expression, "parse");
  if (direct !== null) return direct;
  if (
    expression.type === "MemberExpression" &&
    !expression.computed &&
    expression.property.type === "Identifier" &&
    expression.property.name === "data"
  ) {
    const safe = parsedCall(source, expression.object, "safeParse");
    if (safe !== null) return safe;
    if (expression.object.type === "Identifier" && followBinding) {
      const initializer = immutableInitializer(source, expression.object);
      return initializer === null
        ? null
        : parsedCall(source, initializer, "safeParse");
    }
  }
  if (expression.type === "Identifier" && followBinding) {
    const initializer = immutableInitializer(source, expression);
    return initializer === null
      ? null
      : parsedOutput(source, initializer, false);
  }
  return null;
}

function immutableInitializer(
  source: SourceCode,
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
): ESTree.Expression | null {
  const variable = resolveVariable(source, identifier);
  if (
    variable?.defs.length !== 1 ||
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return null;
  const declaration = variable.defs[0]?.node;
  return declaration?.type === "VariableDeclarator" &&
    declaration.parent.type === "VariableDeclaration" &&
    declaration.parent.kind === "const"
    ? declaration.init
    : null;
}

function returnReference(
  source: SourceCode,
  type: ESTree.TSType,
): ESTree.TSTypeReference | null {
  if (type.type === "TSUnionType") {
    const substantive = type.types.filter(
      (member) =>
        member.type !== "TSNullKeyword" && member.type !== "TSUndefinedKeyword",
    );
    return substantive.length === 1
      ? returnReference(source, substantive[0]!)
      : null;
  }
  if (type.type !== "TSTypeReference" || type.typeName.type !== "Identifier")
    return null;
  if (
    type.typeName.name === "Promise" &&
    isGlobalReference(source, type.typeName, "Promise") &&
    type.typeArguments?.params.length === 1
  )
    return returnReference(source, type.typeArguments.params[0]!);
  return type.typeArguments?.params.length ? null : type;
}

function parsedCall(
  source: SourceCode,
  expression: ESTree.Node,
  method: "parse" | "safeParse",
): ParsedOutput | null {
  if (
    expression.type !== "CallExpression" ||
    expression.callee.type !== "MemberExpression" ||
    expression.callee.computed ||
    expression.callee.object.type !== "Identifier" ||
    expression.callee.property.type !== "Identifier" ||
    expression.callee.property.name !== method
  )
    return null;
  const schema = localSchema(source, expression.callee.object);
  return schema === null ? null : { schema, method };
}

function localSchema(
  source: SourceCode,
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
): LocalSchema | null {
  const variable = resolveVariable(source, identifier);
  if (
    variable?.defs.length !== 1 ||
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return null;
  const declaration = variable.defs[0]?.node;
  if (
    declaration?.type !== "VariableDeclarator" ||
    declaration.id.type !== "Identifier" ||
    declaration.id.typeAnnotation ||
    declaration.parent.type !== "VariableDeclaration" ||
    declaration.parent.kind !== "const" ||
    declaration.init === null
  )
    return null;
  const container = declaration.parent.parent;
  if (
    container.type !== "Program" &&
    !(
      container.type === "ExportNamedDeclaration" &&
      container.parent.type === "Program"
    )
  )
    return null;
  let root = unwrapExpression(declaration.init);

  while (
    root.type === "CallExpression" &&
    root.callee.type === "MemberExpression" &&
    !root.callee.computed &&
    root.callee.property.type === "Identifier" &&
    SHAPE_PRESERVING.has(root.callee.property.name)
  )
    root = unwrapExpression(root.callee.object);
  if (
    root.type !== "CallExpression" ||
    root.callee.type !== "MemberExpression" ||
    root.callee.computed ||
    root.callee.object.type !== "Identifier" ||
    root.callee.property.type !== "Identifier" ||
    !["object", "strictObject"].includes(root.callee.property.name) ||
    !isZodNamespace(source, root.callee.object)
  )
    return null;
  return {
    declaration,
    variable,
    namespaces: new Set([root.callee.object.name]),
  };
}

function isZodNamespace(
  source: SourceCode,
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
): boolean {
  const definitions = resolveVariable(source, identifier)?.defs;
  if (definitions?.length !== 1) return false;
  const specifier = definitions[0]?.node;
  if (
    specifier?.type !== "ImportNamespaceSpecifier" &&
    specifier?.type !== "ImportDefaultSpecifier" &&
    specifier?.type !== "ImportSpecifier"
  )
    return false;
  const declaration = specifier.parent;
  if (
    declaration.type !== "ImportDeclaration" ||
    declaration.importKind === "type" ||
    !(
      declaration.source.value === "zod" ||
      declaration.source.value.startsWith("zod/") ||
      declaration.source.value === "@hono/zod-openapi"
    )
  )
    return false;
  return (
    specifier.type !== "ImportSpecifier" ||
    (specifier.importKind !== "type" &&
      (specifier.imported.type === "Identifier"
        ? specifier.imported.name === "z"
        : specifier.imported.value === "z"))
  );
}
export default createRule<Options, MessageIds>({
  name: "prefer-zod-parse-output-type",
  documentation: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      handWrittenParsedOutput:
        "`{{typeName}}` repeats the local schema fields returned from `{{schemaName}}.{{methodName}}()`. Derive the validated contract with `z.output<typeof {{schemaName}}>` instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isStoryFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    )
      return {};
    const source = context.sourceCode;
    const frames: ReturnFrame[] = [];
    const candidates: Array<{ frame: ReturnFrame; output: ParsedOutput }> = [];
    function inspect(value: ESTree.Node): void {
      const frame = frames.at(-1);
      if (!frame?.contract) return;
      if (value.type === "ConditionalExpression") {
        inspect(value.consequent);
        inspect(value.alternate);
        return;
      }
      if (nullish(value)) return;
      const output = parsedOutput(source, value);
      if (output === null) frame.opaque = true;
      else frame.outputs.push(output);
    }
    const nullish = (node: ESTree.Node): boolean =>
      (node.type === "Literal" && node.value === null) ||
      (node.type === "Identifier" &&
        isGlobalReference(source, node, "undefined"));
    function enter(node: FunctionNode): void {
      const reference =
        !node.typeParameters && node.returnType
          ? returnReference(source, node.returnType.typeAnnotation)
          : null;
      const definitions =
        reference?.typeName.type === "Identifier"
          ? resolveVariable(source, reference.typeName)?.defs
          : null;
      const declaration =
        definitions?.length === 1 ? definitions[0]?.node : null;
      const contract =
        declaration?.type === "TSInterfaceDeclaration" ||
        declaration?.type === "TSTypeAliasDeclaration"
          ? declaration
          : null;
      frames.push({ reference, contract, outputs: [], opaque: false });
      if (node.body && node.body.type !== "BlockStatement") inspect(node.body);
    }
    function leave(): void {
      const frame = frames.pop();
      if (frame?.opaque || !frame?.reference || !frame.contract) return;
      for (const output of frame.outputs) {
        const schema = output.schema;
        if (
          !schema.declaration.init ||
          schema.declaration.id.type !== "Identifier" ||
          !sameStaticObjectShape(
            schema.declaration.init,
            frame.contract,
            schema.namespaces,
          )
        )
          continue;
        if (
          preferZodInferOwnsDefaultTwin({
            constrained: false,
            declaration: frame.contract,
            initializer: schema.declaration.init,
            reshaped: false,
            schemaName: schema.declaration.id.name,
            typeName: frame.contract.id.name,
            zodNamespaces: schema.namespaces,
          })
        )
          continue;
        candidates.push({ frame, output });
      }
    }
    return {
      FunctionDeclaration: enter,
      FunctionExpression: enter,
      ArrowFunctionExpression: enter,
      "FunctionDeclaration:exit": leave,
      "FunctionExpression:exit": leave,
      "ArrowFunctionExpression:exit": leave,
      ReturnStatement(node): void {
        if (node.argument) inspect(node.argument);
      },
      "Program:exit"(): void {
        const owners = new Map<ESTree.Node, Set<Variable>>();
        for (const { frame, output } of candidates) {
          const declarations =
            owners.get(frame.contract!) ?? new Set<Variable>();
          declarations.add(output.schema.variable);
          owners.set(frame.contract!, declarations);
        }
        const reported = new Set<ESTree.Node>();
        for (const { frame, output } of candidates) {
          if (
            !frame.contract ||
            !frame.reference ||
            owners.get(frame.contract)?.size !== 1 ||
            reported.has(frame.contract) ||
            output.schema.declaration.id.type !== "Identifier"
          )
            continue;
          reported.add(frame.contract);
          context.report({
            node: frame.reference,
            messageId: "handWrittenParsedOutput",
            data: {
              methodName: output.method,
              schemaName: output.schema.declaration.id.name,
              typeName: frame.contract.id.name,
            },
          });
        }
      },
    };
  },
});
