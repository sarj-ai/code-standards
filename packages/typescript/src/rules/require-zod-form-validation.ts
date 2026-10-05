/**
 * @fileoverview require-zod-form-validation — `formData.get(k)` hands back an attacker-controlled `FormDataEntryValue | null`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-zod-form-validation.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context, Scope, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { isZodModule, ZOD_SCHEMA_NAME_RE } from "./_zod.js";

type MessageIds = "missingZodValidation";
type Options = readonly [];

export const REQUIRE_ZOD_FORM_VALIDATION_DOCUMENTATION = {
  summary:
    "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
  rationale:
    "FormData values are untrusted strings or files and need runtime validation before use.",
  remediation:
    "Read the value inside a Zod schema's `parse` or `safeParse` input.",
  category: "security",
  limitations: [
    "Tests are excluded; imported schema-shaped names are trusted when their implementation is outside the linted file.",
    "Delayed raw-value use is accepted only after an unconditional successful parse in the same block; safeParse remains valid when the raw binding has no unvalidated consumer.",
    "An enclosing parse does not validate an earlier call or deferred callback that consumes its input. Direct object/array construction, unshadowed Object.fromEntries and native Number/String/Boolean coercion remain supported; arbitrary preprocessing needs an explicitly reviewed boundary.",
  ],
  examples: [
    {
      id: "validated-form-value",
      title: "Validate the form value",
      outcome: "no-match",
      files: [
        {
          path: "src/action.ts",
          source:
            "const input = UserSchema.parse({ name: formData.get('name') });",
        },
      ],
      focusPath: "src/action.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "raw-form-value",
      title: "Do not use a raw form value",
      outcome: "match",
      files: [
        { path: "src/action.ts", source: "const name = formData.get('name');" },
      ],
      focusPath: "src/action.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type Ctx = Readonly<Context>;
const ZOD_PARSE_METHODS: ReadonlySet<string> = new Set([
  "parse",
  "safeParse",
  "parseAsync",
  "safeParseAsync",
]);
const FORM_VALUE_METHODS: ReadonlySet<string> = new Set(["get", "getAll"]);

/** Recognize the supported Zod receiver naming conventions. */
const zodReceiverRoot = (
  node: ESTree.Node,
): ESTree.BindingIdentifier | null => {
  let current: ESTree.Node = node;
  while (true) {
    if (current.type === "Identifier") {
      return current;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    if (current.type === "MemberExpression") {
      current = current.object;
      continue;
    }
    return null;
  }
};

/** Match an optionally awaited `<x>.formData()` call. */
const isFormDataMethodCall = (node: ESTree.Node): boolean => {
  let current: ESTree.Node = node;
  if (current.type === "AwaitExpression") {
    current = current.argument;
  }
  if (current.type !== "CallExpression") return false;
  const callee = current.callee;
  return (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    callee.property.name === "formData"
  );
};

export default createRule<Options, MessageIds>({
  name: "require-zod-form-validation",
  documentation: REQUIRE_ZOD_FORM_VALIDATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
    },
    schema: [],
    messages: {
      missingZodValidation:
        "FormData parsing must use Zod schema validation (e.g., Schema.parse() / Schema.safeParse())",
    },
  },
  defaultOptions: [],
  create(context: Ctx) {
    if (isTestFile(sourceOrigin(context).filename)) {
      return {};
    }

    const zodBindings = new Set<Variable>();

    const resolvedBinding = (
      identifier: ESTree.BindingIdentifier,
    ): Variable | null =>
      findVariable(context.sourceCode.getScope(identifier), identifier.name);

    const isFormDataGetCall = (node: ESTree.CallExpression): boolean => {
      const callee = node.callee;
      if (callee.type !== "MemberExpression") return false;
      if (
        callee.property.type !== "Identifier" ||
        !FORM_VALUE_METHODS.has(callee.property.name)
      ) {
        return false;
      }
      return isFormSourceIdentifier(callee.object);
    };

    // Recognize conventional names and bindings initialized by `.formData()`.
    const isFormSourceIdentifier = (node: ESTree.Node): boolean => {
      if (node.type !== "Identifier") return false;
      const conventionalName = /formdata/i.test(node.name);

      let scope: Scope | null = context.sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.set.get(node.name);
        if (variable !== undefined && variable.defs.length === 1) {
          const def = variable.defs[0];
          if (
            def !== undefined &&
            def.type === "Variable" &&
            def.node.type === "VariableDeclarator" &&
            def.node.init !== null
          ) {
            return isFormDataMethodCall(def.node.init);
          }
          return def?.type === "Parameter" && conventionalName;
        }
        scope = scope.upper;
      }
      return conventionalName;
    };

    const zodParseAncestor = (
      node: ESTree.Node,
    ): ESTree.CallExpression | null => {
      let parent: ESTree.Node | null | undefined = node.parent;
      while (parent !== null && parent !== undefined) {
        if (isZodParseCall(parent)) return parent as ESTree.CallExpression;
        if (
          parent.type === "CallExpression" &&
          parent.callee.type === "Identifier" &&
          ["Number", "String", "Boolean"].includes(parent.callee.name) &&
          parent.arguments.length === 1 &&
          (resolvedBinding(parent.callee)?.defs.length ?? 0) === 0
        ) {
          parent = parent.parent;
          continue;
        }
        if (
          parent.type === "CallExpression" &&
          parent.callee.type === "MemberExpression" &&
          !parent.callee.computed &&
          parent.callee.object.type === "Identifier" &&
          parent.callee.object.name === "Object" &&
          parent.callee.property.type === "Identifier" &&
          parent.callee.property.name === "fromEntries" &&
          (resolvedBinding(parent.callee.object)?.defs.length ?? 0) === 0
        ) {
          parent = parent.parent;
          continue;
        }
        if (
          parent.type === "CallExpression" ||
          parent.type === "NewExpression" ||
          parent.type === "TaggedTemplateExpression" ||
          parent.type === "ArrowFunctionExpression" ||
          parent.type === "FunctionExpression" ||
          parent.type === "FunctionDeclaration"
        )
          return null;
        parent = parent.parent;
      }
      return null;
    };

    const isZodParseCall = (node: ESTree.Node): boolean => {
      if (node.type !== "CallExpression") return false;
      const callee = node.callee;
      if (
        callee.type !== "MemberExpression" ||
        callee.computed ||
        callee.property.type !== "Identifier" ||
        !ZOD_PARSE_METHODS.has(callee.property.name)
      ) {
        return false;
      }
      const root = zodReceiverRoot(callee.object);
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return (
        (binding !== null && zodBindings.has(binding)) ||
        ((root.name === "z" || ZOD_SCHEMA_NAME_RE.test(root.name)) &&
          !isProvablyNonZodLocal(root))
      );
    };

    /** Reject only bindings that are provably ordinary values; imported schemas remain supported. */
    const isProvablyNonZodLocal = (
      identifier: ESTree.BindingIdentifier,
    ): boolean => {
      const binding = resolvedBinding(identifier);
      if (
        binding === null ||
        zodBindings.has(binding) ||
        binding.defs.length !== 1
      ) {
        return false;
      }
      const definition = binding.defs[0];
      if (
        definition?.type !== "Variable" ||
        definition.node.type !== "VariableDeclarator" ||
        definition.node.type !== "VariableDeclarator"
      ) {
        return false;
      }
      const init = definition.node.init;
      return (
        init?.type === "ObjectExpression" ||
        init?.type === "ArrayExpression" ||
        init?.type === "Literal" ||
        init?.type === "ArrowFunctionExpression" ||
        init?.type === "FunctionExpression"
      );
    };

    const hasZodParseAncestor = (node: ESTree.Node): boolean =>
      zodParseAncestor(node) !== null;

    const isInstanceofNarrowing = (node: ESTree.Node): boolean => {
      const parent: ESTree.Node | null | undefined = node.parent;
      return (
        parent !== null &&
        parent !== undefined &&
        parent.type === "BinaryExpression" &&
        parent.operator === "instanceof" &&
        parent.left === node &&
        parent.right.type === "Identifier" &&
        (parent.right.name === "File" || parent.right.name === "Blob")
      );
    };

    /** The identifier this `.get(...)` call is bound to, or null. */
    const boundDeclarator = (
      node: ESTree.CallExpression,
    ): ESTree.VariableDeclarator | null => {
      let current: ESTree.Node = node;
      let parent = current.parent;
      while (
        (parent.type === "TSAsExpression" ||
          parent.type === "TSSatisfiesExpression" ||
          parent.type === "TSNonNullExpression" ||
          parent.type === "ChainExpression") &&
        parent.expression === current
      ) {
        current = parent;
        parent = current.parent;
      }
      if (
        parent.type === "VariableDeclarator" &&
        parent.init === current &&
        parent.id.type === "Identifier"
      ) {
        return parent;
      }
      return null;
    };

    const containingStatement = (
      node: ESTree.Node,
    ): ESTree.Statement | null => {
      let current = node;
      while (current.parent != null) {
        const parent = current.parent;
        if (parent.type === "BlockStatement" || parent.type === "Program") {
          return current as ESTree.Statement;
        }
        current = parent;
      }
      return null;
    };

    /** Return an unconditional, success-guaranteeing validation statement. */
    const guaranteedValidationStatement = (
      declarator: ESTree.VariableDeclarator,
      reference: ESTree.BindingIdentifier,
    ): ESTree.Statement | null => {
      const parse = zodParseAncestor(reference);
      if (parse === null) return null;
      const declarationStatement = containingStatement(declarator);
      const validationStatement = containingStatement(parse);
      if (
        declarationStatement === null ||
        validationStatement === null ||
        declarationStatement.parent !== validationStatement.parent ||
        validationStatement.range[0] <= declarationStatement.range[1] ||
        hasConditionalAncestorBeforeStatement(parse, validationStatement)
      ) {
        return null;
      }
      if (
        validationStatement.type !== "VariableDeclaration" &&
        validationStatement.type !== "ExpressionStatement"
      ) {
        return null;
      }
      const method = zodParseMethod(parse);
      if (method === "parse") return validationStatement;
      if (
        method === "parseAsync" &&
        isAwaitedBeforeStatement(parse, validationStatement)
      ) {
        return validationStatement;
      }
      return null;
    };

    const isAwaitedBeforeStatement = (
      node: ESTree.Node,
      statement: ESTree.Statement,
    ): boolean => {
      let current = node.parent;
      while (current != null && current !== statement) {
        if (current.type === "AwaitExpression") return true;
        current = current.parent;
      }
      return false;
    };

    const hasConditionalAncestorBeforeStatement = (
      node: ESTree.Node,
      statement: ESTree.Statement,
    ): boolean => {
      let current = node.parent;
      while (current != null && current !== statement) {
        if (
          current.type === "LogicalExpression" ||
          current.type === "ConditionalExpression"
        ) {
          return true;
        }
        current = current.parent;
      }
      return false;
    };

    const zodParseMethod = (call: ESTree.CallExpression): string | null => {
      const callee = call.callee;
      return callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier"
        ? callee.property.name
        : null;
    };

    const isSafePrevalidationInspection = (
      identifier: ESTree.BindingIdentifier,
    ): boolean => {
      const parent = identifier.parent;
      if (parent.type === "UnaryExpression" && parent.operator === "typeof") {
        return true;
      }
      if (parent.type !== "BinaryExpression" || parent.left !== identifier) {
        return false;
      }
      if (parent.operator === "instanceof") {
        return (
          parent.right.type === "Identifier" &&
          (parent.right.name === "File" || parent.right.name === "Blob")
        );
      }
      return (
        ["===", "!==", "==", "!="].includes(parent.operator) &&
        ((parent.right.type === "Literal" && parent.right.value === null) ||
          (parent.right.type === "Identifier" &&
            parent.right.name === "undefined"))
      );
    };

    const isDescendantOf = (
      node: ESTree.Node,
      ancestor: ESTree.Node,
    ): boolean => {
      let current: ESTree.Node | null | undefined = node;
      while (current !== undefined && current !== null) {
        if (current === ancestor) return true;
        current = current.parent;
      }
      return false;
    };

    const blockTerminates = (node: ESTree.Statement): boolean => {
      if (node.type === "ReturnStatement" || node.type === "ThrowStatement") {
        return true;
      }
      if (node.type !== "BlockStatement" || node.body.length === 0)
        return false;
      const last = node.body.at(-1);
      return last !== undefined && blockTerminates(last);
    };

    const narrowingIf = (
      identifier: ESTree.BindingIdentifier,
    ): {
      readonly branch: ESTree.IfStatement;
      readonly positive: boolean;
    } | null => {
      const comparison = identifier.parent;
      if (
        comparison?.type !== "BinaryExpression" ||
        comparison.operator !== "instanceof" ||
        comparison.left !== identifier ||
        comparison.right.type !== "Identifier" ||
        (comparison.right.name !== "File" && comparison.right.name !== "Blob")
      ) {
        return null;
      }
      const maybeNegation = comparison.parent;
      const negated =
        maybeNegation?.type === "UnaryExpression" &&
        maybeNegation.operator === "!";
      const test = negated ? maybeNegation : comparison;
      const branch = test.parent;
      return branch?.type === "IfStatement" && branch.test === test
        ? { branch, positive: !negated }
        : null;
    };

    const useDominatedByNarrowing = (
      use: ESTree.BindingIdentifier,
      narrowings: readonly {
        readonly branch: ESTree.IfStatement;
        readonly positive: boolean;
      }[],
    ): boolean =>
      narrowings.some(({ branch, positive }) => {
        if (positive) return isDescendantOf(use, branch.consequent);
        if (!blockTerminates(branch.consequent)) return false;
        const branchStatement = containingStatement(branch);
        const useStatement = containingStatement(use);
        return (
          branchStatement !== null &&
          useStatement !== null &&
          branchStatement.parent === useStatement.parent &&
          branchStatement.range[1] < useStatement.range[0]
        );
      });

    /** Find the statement directly owned by `block` that contains `node`. */
    const statementWithinBlock = (
      node: ESTree.Node,
      block: ESTree.Node,
    ): ESTree.Statement | null => {
      let current = node;
      while (current.parent != null && current.parent !== block) {
        current = current.parent;
      }
      return current.parent === block ? (current as ESTree.Statement) : null;
    };

    /** Is every consuming use either validated itself or dominated by a successful parse? */
    const bindingIsValidated = (
      declarator: ESTree.VariableDeclarator,
    ): boolean => {
      const variable = context.sourceCode.getDeclaredVariables(declarator)[0];
      if (variable === undefined) return false;
      const references = variable.references
        .filter((reference) => !reference.isWriteOnly())
        .map((reference) => reference.identifier)
        .filter(
          (identifier): identifier is ESTree.BindingIdentifier =>
            identifier.type === "Identifier",
        );
      if (references.length === 0) return false;
      const narrowings = references
        .map(narrowingIf)
        .filter(
          (
            value,
          ): value is {
            readonly branch: ESTree.IfStatement;
            readonly positive: boolean;
          } => value !== null,
        );
      const validationStatements = references
        .map((reference) =>
          guaranteedValidationStatement(declarator, reference),
        )
        .filter(
          (statement): statement is ESTree.Statement => statement !== null,
        );
      const declarationStatement = containingStatement(declarator);
      const declarationBlock = declarationStatement?.parent;
      return references.every((reference) => {
        if (
          zodParseAncestor(reference) !== null ||
          isSafePrevalidationInspection(reference) ||
          useDominatedByNarrowing(reference, narrowings)
        ) {
          return true;
        }
        if (declarationBlock === undefined) return false;
        const useStatement = statementWithinBlock(reference, declarationBlock);
        return (
          useStatement !== null &&
          validationStatements.some(
            (statement) => statement.range[1] < useStatement.range[0],
          )
        );
      });
    };

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              (specifier.imported.type === "Identifier"
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          ) {
            const binding = resolvedBinding(specifier.local);
            if (binding !== null) zodBindings.add(binding);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!isFormDataGetCall(node)) return;

        if (hasZodParseAncestor(node) || isInstanceofNarrowing(node)) return;

        const declarator = boundDeclarator(node);
        if (declarator !== null && bindingIsValidated(declarator)) return;

        context.report({
          node,
          messageId: "missingZodValidation",
        });
      },
    };
  },
});
