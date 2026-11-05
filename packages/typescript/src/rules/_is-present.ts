/** @fileoverview _is-present — test an optional AST child; Oxlint passes null where typescript-eslint passes undefined. */

export function isPresent<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}
