/**
 * @fileoverview types — Oxlint plugin types, plus the TS-ESLint scope fields
 * that Oxlint provides at runtime but leaves out of its typings.
 *
 * Oxlint builds scopes with the TS-ESLint scope manager, so variables,
 * references and definitions carry `isTypeVariable`, `isTypeReference`,
 * `isTypeDefinition` and `eslintUsed` at runtime. Its published types only
 * declare the ESLint subset.
 */

import type { Context, CreateOnceRule, Definition, ESTree, Reference, Scope, SourceCode, Variable } from "@oxlint/plugins";

export type { Context, CreateOnceRule, ESTree, Scope, SourceCode };

export type Node = ESTree.Node;

/** Any Oxlint identifier node; they differ only in their `typeAnnotation` typing. */
export type Identifier = Extract<Node, { type: "Identifier" }>;

export interface TsDefinition extends Definition {
  readonly isTypeDefinition: boolean;
  readonly isVariableDefinition: boolean;
}

export interface TsReference extends Reference {
  readonly isTypeReference: boolean;
  readonly isValueReference: boolean;
  resolved: TsVariable | null;
}

export interface TsVariable extends Variable {
  readonly isTypeVariable: boolean;
  readonly isValueVariable: boolean;
  readonly eslintUsed: boolean;
  references: TsReference[];
  defs: TsDefinition[];
}

/** View an Oxlint scope variable with its runtime TS-ESLint fields. */
export function tsVariable(variable: Variable): TsVariable {
  return variable as TsVariable;
}

/** View an Oxlint reference with its runtime TS-ESLint fields. */
export function tsReference(reference: Reference): TsReference {
  return reference as TsReference;
}

/** A rule written for Oxlint: set up once per run, reset per file in `before`. */
export type SarjRule = CreateOnceRule;

/** Type a rule as `SarjRule` while keeping the default export anonymous. */
export function defineRule(rule: SarjRule): SarjRule {
  return rule;
}
