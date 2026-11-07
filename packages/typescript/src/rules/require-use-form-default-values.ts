/**
 * @fileoverview require-use-form-default-values — directly bound Controller fields need form-level initialization or a field default.
 *
 * Port of the 18.x `require-use-form-default-values` rule. Same
 * algorithm; the `react-hook-form` import gate and per-file state reset run in
 * `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-use-form-default-values.test.ts
 */

import { defineRule, type ESTree, type Node, type TsReference, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";

const NAME = "require-use-form-default-values";
type HookKind = "Controller" | "useController" | "useForm";
type Identifier = Extract<Node, { type: "Identifier" }>;
const UNSAFE_FORM_MEMBERS: ReadonlySet<string> = new Set(["__defineGetter__", "__defineSetter__", "__proto__", "valueOf"]);

/** A non-computed property's static name. */
function staticPropertyName(property: ESTree.ObjectProperty | ESTree.AssignmentTargetProperty | ESTree.BindingProperty): string | null {
  return property.computed ? null : getPropertyName(property);
}

function readonlyFormReference(reference: TsReference): boolean {
  if (typeOnlyReference(reference)) return true;
  const receiver = outerExpression(reference.identifier);
  const parent = parentOf(receiver);
  if (parent?.type === "VariableDeclarator" && parent.init === receiver) return parent.id.type === "ObjectPattern";
  if (parent?.type !== "MemberExpression" || parent.object !== receiver) {
    return parent?.type === "UnaryExpression" && parent.operator === "typeof";
  }
  const name = getPropertyName(parent);
  return name !== null && !UNSAFE_FORM_MEMBERS.has(name) && !memberWrite(parent);
}

/** Whether a member is written directly or as part of a destructuring target. */
function memberWrite(node: Node): boolean {
  let current = outerExpression(node);
  let parent = parentOf(current);
  while (parent !== null && widensTarget(parent, current)) {
    current = parent;
    parent = parentOf(current);
  }
  return parent !== null && writesTarget(parent, current);
}

/** `parent` is a pattern that writes `current` when it is written. */
function widensTarget(parent: Node, current: Node): boolean {
  return (parent.type === "Property" && parent.value === current) ||
    parent.type === "ObjectPattern" || parent.type === "ArrayPattern" || parent.type === "RestElement" ||
    (parent.type === "AssignmentPattern" && parent.left === current);
}

function writesTarget(parent: Node, target: Node): boolean {
  return (parent.type === "AssignmentExpression" && parent.left === target) ||
    (parent.type === "UpdateExpression" && parent.argument === target) ||
    (parent.type === "UnaryExpression" && parent.operator === "delete") ||
    ((parent.type === "ForOfStatement" || parent.type === "ForInStatement") && parent.left === target);
}

function stableForm(variable: TsVariable): boolean {
  return !variable.defs.some((definition) => {
    if (definition.type !== "Variable") return false;
    const declaration = definition.parent;
    return declaration !== null && parentOf(declaration)?.type === "ExportNamedDeclaration";
  }) && stableValueBinding(variable, readonlyFormReference);
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require explicit form-level initialization or a field default for directly bound Controller fields.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { requireUseFormDefaultValues: "Add non-undefined defaultValues/values to the associated useForm call or non-undefined defaultValue to this field." },
  },
  createOnce(context) {
    const imported = new Map<TsVariable, HookKind>();
    const uninitializedForms = new Set<TsVariable>();
    const uninitializedControls = new Set<TsVariable>();
    const bindingNamed = (node: Node, name: string): TsVariable | null => findVariable(context.sourceCode.getScope(node), name);
    const bindingOf = (node: Identifier): TsVariable | null => bindingNamed(node, node.name);
    const importedKind = (node: Identifier | ESTree.JSXIdentifier): HookKind | null => {
      const variable = bindingNamed(node, node.name);
      return variable === null ? null : imported.get(variable) ?? null;
    };
    const isDefinitelyUndefined = (node: Node): boolean => {
      const value = unwrapExpression(node);
      return (value.type === "UnaryExpression" && value.operator === "void") ||
        (value.type === "Identifier" && value.name === "undefined" && (bindingOf(value)?.defs.length ?? 0) === 0);
    };
    const uninitializedUseFormCall = (node: Node): boolean => {
      node = unwrapExpression(node);
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "Identifier" || importedKind(callee) !== "useForm") return false;
      const options = node.arguments[0];
      return options?.type !== "SpreadElement" && initializationState(options) === "uninitialized";
    };

    const initializationState = (node: Node | undefined): "initialized" | "uninitialized" | "unknown" => {
      if (node === undefined) return "uninitialized";
      if (node.type !== "ObjectExpression") return "unknown";
      const initialization = new Map<string, boolean>();
      for (const property of node.properties) {
        if (property.type === "SpreadElement" || property.computed) return "unknown";
        if (property.type !== "Property") continue;
        const name = staticPropertyName(property);
        if (name === "defaultValues" || name === "values") initialization.set(name, !isDefinitelyUndefined(property.value));
      }
      return [...initialization.values()].some(Boolean) ? "initialized" : "uninitialized";
    };
    const isUninitializedForm = (node: Node): boolean => {
      node = unwrapExpression(node);
      if (node.type !== "Identifier") return false;
      const variable = bindingOf(node);
      return variable !== null && uninitializedForms.has(variable);
    };
    const isUninitializedControl = (node: Node): boolean => {
      node = unwrapExpression(node);
      if (node.type === "Identifier") {
        const variable = bindingOf(node);
        return variable !== null && uninitializedControls.has(variable);
      }
      return node.type === "MemberExpression" && getPropertyName(node) === "control" && isUninitializedForm(node.object);
    };
    const fieldOptionsNeedDefault = (node: Node | undefined): boolean => {
      if (node?.type !== "ObjectExpression") return false;
      let control: Node | null = null;
      let hasDefault = false;
      for (const property of node.properties) {
        if (property.type === "SpreadElement" || property.computed) return false;
        if (property.type !== "Property") continue;
        const name = staticPropertyName(property);
        if (name === "control") control = property.value;
        if (name === "defaultValue") hasDefault = !isDefinitelyUndefined(property.value);
      }
      return control !== null && isUninitializedControl(control) && !hasDefault;
    };
    const jsxAttribute = (node: ESTree.JSXOpeningElement, name: string): ESTree.JSXAttribute | null => {
      let result: ESTree.JSXAttribute | null = null;
      for (const attribute of node.attributes) {
        if (attribute.type === "JSXSpreadAttribute") return null;
        if (attribute.name.type === "JSXIdentifier" && attribute.name.name === name) result = attribute;
      }
      return result;
    };
    const trackDestructuredControl = (pattern: ESTree.ObjectPattern): void => {
      for (const property of pattern.properties) {
        if (property.type !== "Property" || staticPropertyName(property) !== "control" || property.value.type !== "Identifier") continue;
        const variable = bindingOf(property.value);
        if (variable !== null && stableValueBinding(variable)) uninitializedControls.add(variable);
      }
    };

    return {
      before() {
        imported.clear();
        uninitializedForms.clear();
        uninitializedControls.clear();
        if (!context.sourceCode.ast.body.some((statement) => statement.type === "ImportDeclaration" && statement.source.value === "react-hook-form")) return false;
        return undefined;
      },
      ImportDeclaration(node) {
        if (node.source.value !== "react-hook-form") return;
        for (const specifier of node.specifiers) {
          if (specifier.type !== "ImportSpecifier") continue;
          const name = importSpecifierName(specifier);
          if (name !== "Controller" && name !== "useController" && name !== "useForm") continue;
          const variable = bindingOf(specifier.local);
          if (variable !== null && stableValueBinding(variable)) imported.set(variable, name);
        }
      },
      VariableDeclarator(node) {
        if (node.init === null) return;
        if (uninitializedUseFormCall(node.init)) {
          if (node.id.type === "Identifier") {
            const variable = bindingOf(node.id);
            if (variable !== null && stableForm(variable)) uninitializedForms.add(variable);
          } else if (node.id.type === "ObjectPattern") {
            trackDestructuredControl(node.id);
          }
          return;
        }
        if (node.id.type === "ObjectPattern" && isUninitializedForm(node.init)) {
          trackDestructuredControl(node.id);
          return;
        }
        if (node.id.type === "Identifier" && node.init.type === "MemberExpression" && getPropertyName(node.init) === "control" && isUninitializedForm(node.init.object)) {
          const variable = bindingOf(node.id);
          if (variable !== null && stableValueBinding(variable)) uninitializedControls.add(variable);
        }
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        const options = node.arguments[0];
        if (callee.type !== "Identifier" || importedKind(callee) !== "useController" ||
          !fieldOptionsNeedDefault(options?.type === "SpreadElement" ? undefined : options)) return;
        context.report({ node, messageId: "requireUseFormDefaultValues" });
      },
      JSXOpeningElement(node) {
        if (node.name.type !== "JSXIdentifier" || importedKind(node.name) !== "Controller") return;
        if (node.attributes.some((attribute) => attribute.type === "JSXSpreadAttribute")) return;
        const control = jsxAttribute(node, "control");
        if (control?.value?.type !== "JSXExpressionContainer" || control.value.expression.type === "JSXEmptyExpression" || !isUninitializedControl(control.value.expression)) return;
        const defaultValue = jsxAttribute(node, "defaultValue");
        if (defaultValue !== null && (defaultValue.value === null || defaultValue.value.type !== "JSXExpressionContainer" ||
          (defaultValue.value.expression.type !== "JSXEmptyExpression" && !isDefinitelyUndefined(defaultValue.value.expression)))) return;
        context.report({ node, messageId: "requireUseFormDefaultValues" });
      },
    };
  },
});
