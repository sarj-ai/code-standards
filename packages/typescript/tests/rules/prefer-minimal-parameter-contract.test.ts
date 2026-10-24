import rule from "../../src/rules/prefer-minimal-parameter-contract.js";
import { CONSUMER_PREFIX, INLINE_CONTRACT, PRIVATE_CONSUMER_TESTER, runPrivateConsumerBoundaries } from "../private-consumer-cases.js";

const PREFIX = CONSUMER_PREFIX;
runPrivateConsumerBoundaries("prefer-minimal-parameter-contract", rule, INLINE_CONTRACT);
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract", rule, {
  valid: [
    ...[
      ["all required fields consumed", `function label(p: ${INLINE_CONTRACT}): string {return p.name + p.email;}`],
      ["unused destructured fields are still read", `function label({name, email}: ${INLINE_CONTRACT}): string {return name;}`],
      ["optional unused field does not restrict structural callers", "function label(p: {readonly name: string; readonly email?: string}): string {return p.name;}"],
      ["optional-only reduced contract can reject weak-type callers", "function label(p: {readonly name?: string; readonly email: string}): string {return p.name ?? '';}"],
      ["mutable data has no readonly contract proof", "function label(p: {name: string; email: string}): string {return p.name;}"],
      ["named domain contract", "interface Account {readonly name: string; readonly email: string} function label(p: Account): string {return p.name;}"],
      ["literal discriminant retains a domain invariant", "function label(p: {readonly name: string; readonly kind: 'account'}): string {return p.name;}"],
      ["object-valued property", "function label(p: {readonly name: string; readonly metadata: object}): string {return p.name;}"],
      ["implicit Object capability can observe unread data", "declare global {interface Object {readonly label: string}} function label(p: {readonly name: string; readonly email: string}): string {return p.name + p.label;}"],
      ["unused function has no evaluated consumer calls", `function label(p: ${INLINE_CONTRACT}): string {return p.name;}`],
    ].map(([name, declaration]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}${name?.startsWith("unused function") ? "" : "label(account);"}`})),
  ],
  invalid: [
    ...[
      ["unused required field", `function label(p: ${INLINE_CONTRACT}): string {return p.name;}`],
      ["const arrow with boolean field", "const enabledAccount = {...account, enabled: true}; const label = (p: {readonly name: string; readonly enabled: boolean}): string => p.name;", "enabledAccount"],
      ["destructured alias", `function label({name: displayName}: ${INLINE_CONTRACT}): string {return displayName;}`],
      ["same-named parameter is not the callable binding", `function label(label: ${INLINE_CONTRACT}): string {return label.name;}`],
      ["fixed string key", `function label(p: ${INLINE_CONTRACT}): string {return p['name'];}`],
      ["optional field retained alongside used required field", "function label(p: {readonly name: string; readonly email: string; readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
    ].map(([name, declaration, argument = "account"]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}label(${argument});`, errors: [{messageId: "minimal" as const}]})),
  ],
});
