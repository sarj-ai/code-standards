/**
 * @fileoverview require-use-form-default-values — controlled react-hook-form fields need a stable initial value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-use-form-default-values.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "requireUseFormDefaultValues";
type Options = readonly [];
type ScopeVariable = NonNullable<ReturnType<typeof ASTUtils.findVariable>>;
type HookKind = "Controller" | "useController" | "useForm";

export const REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION = {
  summary: "Require explicit form-level initialization or a field default for directly bound Controller fields.",
  rationale: "React Hook Form exposes form-level defaultValues/values and field-level defaultValue as its explicit initialization mechanisms. A directly bound controlled field should not omit both mechanisms.",
  remediation: "Provide a non-undefined defaultValues or values option to useForm, or a non-undefined defaultValue on the associated Controller/useController field.",
  category: "correctness",
  limitations: [
    "The rule proves only that an explicit form-level initialization option or field default is present; it does not prove that a particular field path occurs inside a defaultValues/values object.",
    "The rule reports only scope-resolved Controller/useController fields explicitly bound to a directly created useForm control. FormProvider context, wrapper hooks, dynamic options, spreads, computed properties, and interprocedural flows are intentionally left unreported.",
  ],
  examples: [
    {
      id: "controlled-field-with-form-defaults",
      title: "Initialize controlled fields at form level",
      outcome: "no-match",
      files: [{ path: "profile-form.tsx", source: "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm({ defaultValues: { name: '' } }); return <Controller control={form.control} name='name' render={() => null} />; }" }],
      focusPath: "profile-form.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "controlled-field-without-default",
      title: "Do not leave a controlled field uninitialized",
      outcome: "match",
      files: [{ path: "profile-form.tsx", source: "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm(); return <Controller control={form.control} name='name' render={() => null} />; }" }],
      focusPath: "profile-form.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function staticPropertyName(property: TSESTree.Property): string | null {
  if (property.computed) return null;
  if (property.key.type === AST_NODE_TYPES.Identifier) return property.key.name;
  if (property.key.type === AST_NODE_TYPES.Literal && typeof property.key.value === "string") return property.key.value;
  return null;
}

function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion
  ) return unwrapExpression(node.expression);
  return node;
}

export default createRule<Options, MessageIds>({
  name: "require-use-form-default-values",
  documentation: REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION.summary },
    schema: [],
    messages: { requireUseFormDefaultValues: "Add non-undefined defaultValues/values to the associated useForm call or non-undefined defaultValue to this field." },
  },
  defaultOptions: [],
  create(context) {
    const imported = new Map<ScopeVariable, HookKind>();
    const uninitializedForms = new Set<ScopeVariable>();
    const uninitializedControls = new Set<ScopeVariable>();
    const bindingNamed = (node: TSESTree.Node, name: string): ScopeVariable | null => ASTUtils.findVariable(context.sourceCode.getScope(node), name);
    const bindingOf = (node: TSESTree.Identifier): ScopeVariable | null => bindingNamed(node, node.name);
    const stable = (variable: ScopeVariable): boolean => !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
    const importedKind = (node: TSESTree.Identifier): HookKind | null => {
      const variable = bindingOf(node);
      return variable !== null && stable(variable) ? imported.get(variable) ?? null : null;
    };
    const importedJsxKind = (node: TSESTree.JSXIdentifier): HookKind | null => {
      const variable = bindingNamed(node, node.name);
      return variable !== null && stable(variable) ? imported.get(variable) ?? null : null;
    };
    const isDefinitelyUndefined = (node: TSESTree.Node): boolean => {
      const value = unwrapExpression(node);
      return (value.type === AST_NODE_TYPES.UnaryExpression && value.operator === "void") ||
        (value.type === AST_NODE_TYPES.Identifier && value.name === "undefined" && (bindingOf(value)?.defs.length ?? 0) === 0);
    };
    const initializationState = (node: TSESTree.Node | undefined): "initialized" | "uninitialized" | "unknown" => {
      if (node === undefined) return "uninitialized";
      if (node.type !== AST_NODE_TYPES.ObjectExpression) return "unknown";
      const initialization = new Map<string, boolean>();
      for (const property of node.properties) {
        if (property.type === AST_NODE_TYPES.SpreadElement || property.computed) return "unknown";
        if (property.type !== AST_NODE_TYPES.Property) continue;
        const name = staticPropertyName(property);
        if (name === "defaultValues" || name === "values") initialization.set(name, !isDefinitelyUndefined(property.value));
      }
      return [...initialization.values()].some(Boolean) ? "initialized" : "uninitialized";
    };
    const uninitializedUseFormCall = (node: TSESTree.Node): boolean => {
      if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.Identifier || importedKind(node.callee) !== "useForm") return false;
      const options = node.arguments[0];
      return options?.type !== AST_NODE_TYPES.SpreadElement && initializationState(options) === "uninitialized";
    };
    const isUninitializedForm = (node: TSESTree.Node): boolean => {
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      const variable = bindingOf(node);
      return variable !== null && stable(variable) && uninitializedForms.has(variable);
    };
    const isUninitializedControl = (node: TSESTree.Node): boolean => {
      if (node.type === AST_NODE_TYPES.Identifier) {
        const variable = bindingOf(node);
        return variable !== null && stable(variable) && uninitializedControls.has(variable);
      }
      return node.type === AST_NODE_TYPES.MemberExpression && !node.computed &&
        node.property.type === AST_NODE_TYPES.Identifier && node.property.name === "control" && isUninitializedForm(node.object);
    };
    const fieldOptionsNeedDefault = (node: TSESTree.Node | undefined): boolean => {
      if (node?.type !== AST_NODE_TYPES.ObjectExpression) return false;
      let control: TSESTree.Node | null = null;
      let hasDefault = false;
      for (const property of node.properties) {
        if (property.type === AST_NODE_TYPES.SpreadElement || property.computed) return false;
        if (property.type !== AST_NODE_TYPES.Property) continue;
        const name = staticPropertyName(property);
        if (name === "control") control = property.value;
        if (name === "defaultValue") hasDefault = !isDefinitelyUndefined(property.value);
      }
      return control !== null && isUninitializedControl(control) && !hasDefault;
    };
    const jsxAttribute = (node: TSESTree.JSXOpeningElement, name: string): TSESTree.JSXAttribute | null => {
      let result: TSESTree.JSXAttribute | null = null;
      for (const attribute of node.attributes) {
        if (attribute.type === AST_NODE_TYPES.JSXSpreadAttribute) return null;
        if (attribute.name.type === AST_NODE_TYPES.JSXIdentifier && attribute.name.name === name) result = attribute;
      }
      return result;
    };
    const trackDestructuredControl = (pattern: TSESTree.ObjectPattern): void => {
      for (const property of pattern.properties) {
        if (property.type !== AST_NODE_TYPES.Property || staticPropertyName(property) !== "control" || property.value.type !== AST_NODE_TYPES.Identifier) continue;
        const variable = bindingOf(property.value);
        if (variable !== null) uninitializedControls.add(variable);
      }
    };

    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "react-hook-form") return;
        for (const specifier of node.specifiers) {
          if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) continue;
          const name = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
          if (name !== "Controller" && name !== "useController" && name !== "useForm") continue;
          const variable = bindingOf(specifier.local);
          if (variable !== null) imported.set(variable, name);
        }
      },
      VariableDeclarator(node): void {
        if (node.init === null) return;
        if (uninitializedUseFormCall(node.init)) {
          if (node.id.type === AST_NODE_TYPES.Identifier) {
            const variable = bindingOf(node.id);
            if (variable !== null) uninitializedForms.add(variable);
          } else if (node.id.type === AST_NODE_TYPES.ObjectPattern) {
            trackDestructuredControl(node.id);
          }
          return;
        }
        if (node.id.type === AST_NODE_TYPES.ObjectPattern && isUninitializedForm(node.init)) {
          trackDestructuredControl(node.id);
          return;
        }
        if (node.id.type === AST_NODE_TYPES.Identifier && node.init.type === AST_NODE_TYPES.MemberExpression && !node.init.computed &&
          node.init.property.type === AST_NODE_TYPES.Identifier && node.init.property.name === "control" && isUninitializedForm(node.init.object)) {
          const variable = bindingOf(node.id);
          if (variable !== null) uninitializedControls.add(variable);
        }
      },
      CallExpression(node): void {
        if (node.callee.type !== AST_NODE_TYPES.Identifier || importedKind(node.callee) !== "useController" ||
          !fieldOptionsNeedDefault(node.arguments[0]?.type === AST_NODE_TYPES.SpreadElement ? undefined : node.arguments[0])) return;
        context.report({ node, messageId: "requireUseFormDefaultValues" });
      },
      JSXOpeningElement(node): void {
        if (node.name.type !== AST_NODE_TYPES.JSXIdentifier || importedJsxKind(node.name) !== "Controller") return;
        if (node.attributes.some((attribute) => attribute.type === AST_NODE_TYPES.JSXSpreadAttribute)) return;
        const control = jsxAttribute(node, "control");
        if (control?.value?.type !== AST_NODE_TYPES.JSXExpressionContainer || control.value.expression.type === AST_NODE_TYPES.JSXEmptyExpression || !isUninitializedControl(control.value.expression)) return;
        const defaultValue = jsxAttribute(node, "defaultValue");
        if (defaultValue !== null && (defaultValue.value === null || defaultValue.value.type !== AST_NODE_TYPES.JSXExpressionContainer ||
          (defaultValue.value.expression.type !== AST_NODE_TYPES.JSXEmptyExpression && !isDefinitelyUndefined(defaultValue.value.expression)))) return;
        context.report({ node, messageId: "requireUseFormDefaultValues" });
      },
    } satisfies TSESLint.RuleListener;
  },
});
