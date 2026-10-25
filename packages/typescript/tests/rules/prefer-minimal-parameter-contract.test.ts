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
      ["unused required field", `function label(p: ${INLINE_CONTRACT}): string {return p.name;}`, "function label(p: {readonly name: string; }): string {return p.name;}"],
      ["const arrow with boolean field", "const enabledAccount = {...account, enabled: true}; const label = (p: {readonly name: string; readonly enabled: boolean}): string => p.name;", "const enabledAccount = {...account, enabled: true}; const label = (p: {readonly name: string; }): string => p.name;", "enabledAccount"],
      ["destructured alias", `function label({name: displayName}: ${INLINE_CONTRACT}): string {return displayName;}`, "function label({name: displayName}: {readonly name: string; }): string {return displayName;}"],
      ["same-named parameter is not the callable binding", `function label(label: ${INLINE_CONTRACT}): string {return label.name;}`, "function label(label: {readonly name: string; }): string {return label.name;}"],
      ["fixed string key", `function label(p: ${INLINE_CONTRACT}): string {return p['name'];}`, "function label(p: {readonly name: string; }): string {return p['name'];}"],
      ["optional field retained alongside used required field", "function label(p: {readonly name: string; readonly email: string; readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}", "function label(p: {readonly name: string;  readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
    ].map(([name, declaration, fixed, argument = "account"]) => ({name, filename: "probe.tsx", code: `${PREFIX}${declaration}label(${argument});`, output: `${PREFIX}${fixed}label(${argument});`, errors: [{messageId: "minimal" as const}]})),
  ],
});

PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract safe source edits", rule, {
  valid: [],
  invalid: [
    {name: "a first inline member owns only its horizontal leading trivia", filename: "probe.tsx",
      code: `${PREFIX}function label(p: { readonly email: string; readonly name: string }): string {return p.name;} label(account);`,
      output: `${PREFIX}function label(p: { readonly name: string }): string {return p.name;} label(account);`, errors: [{messageId: "minimal"}]},
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({name: "a first member keeps its newline-leading trivia " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}function label(p: {${ending}  readonly email: string;${ending}  readonly name: string${ending}}): string {return p.name;} label(account);`,
      output: `${PREFIX}function label(p: {${ending}  ${ending}  readonly name: string${ending}}): string {return p.name;} label(account);`, errors: [{messageId: "minimal" as const}]})),
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({name: "preserve raw member and line terminators " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}const compass = '🧭'; function label(p: {readonly name: string;${ending}readonly email:${ending}string}): string {return p.name;} label(account);`,
      output: `${PREFIX}const compass = '🧭'; function label(p: {readonly name: string;${ending}${ending}}): string {return p.name;} label(account);`, errors: [{messageId: "minimal" as const}]})),
    ...["{readonly name: string; readonly email:\r string\n}", "{readonly name: string;\rreadonly email:\nstring}"].map((contract) => ({
      name: "member deletion cannot merge distinct CR and LF terminators " + JSON.stringify(contract), filename: "probe.tsx",
      code: `${PREFIX}function label(p: ${contract}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal" as const}],
    })),
    {name: "multiple unread required members keep an unused optional member", filename: "probe.tsx", code: `${PREFIX}const value = {...account, count: 1}; function label(p: {readonly email: string; readonly name: string; readonly count: number; readonly note?: string}): string {return p.name;} label(value);`,
      output: `${PREFIX}const value = {...account, count: 1}; function label(p: { readonly name: string;  readonly note?: string}): string {return p.name;} label(value);`, errors: [{messageId: "minimal"}]},
    {name: "comments remain manual", filename: "probe.tsx", code: `${PREFIX}function label(p: {readonly name: string; /* rationale */ readonly email: string}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "preexisting invalid identifier caller stays rejected", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada', email: 42}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    ...["any", "unknown"].map((type) => ({name: "unsafe relevant caller field remains manual " + type, filename: "probe.tsx",
      code: `${PREFIX}declare const value: {name: string; email: ${type}}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal" as const}]})),
    {name: "unresolved error caller field remains manual", filename: "probe.tsx", code: `${PREFIX}declare const value: {name: string; email: Missing}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "a required ts-expect-error must not become unused", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada'}; function label(p: ${INLINE_CONTRACT}): string {return p.name;}\n// @ts-expect-error the original private contract requires email\nlabel(account);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});
