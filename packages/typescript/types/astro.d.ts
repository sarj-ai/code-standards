import type { Node, Plugin, Scope } from "@oxlint/plugins";
import type { Node as ParserNode } from "oxc-parser";

export interface StaticValue {
  value: unknown;
  optional?: true;
}

export declare function getStaticValue(
  node: Node | ParserNode | null | undefined,
  initialScope?: Scope | null,
): StaticValue | null;

export declare function getPropertyName(
  node: Node | ParserNode,
  initialScope?: Scope | null,
): string | null | undefined;

declare const plugin: Plugin;
export default plugin;
