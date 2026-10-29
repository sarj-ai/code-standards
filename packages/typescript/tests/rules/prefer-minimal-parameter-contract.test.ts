import rule from "../../src/rules/prefer-minimal-parameter-contract.js";
import { CONSUMER_PREFIX, INLINE_CONTRACT, PRIVATE_CONSUMER_TESTER, runPrivateConsumerBoundaries } from "../private-consumer-cases.js";

const PREFIX = CONSUMER_PREFIX;
runPrivateConsumerBoundaries("prefer-minimal-parameter-contract", rule, INLINE_CONTRACT);
for (const contract of ["{name: string; email: string}", "{readonly name: string; email: string}"]) {
  runPrivateConsumerBoundaries("prefer-minimal-parameter-contract " + contract, rule, contract);
}
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract", rule, {
  valid: [
    ...[
      ["all required fields consumed", `function label(p: ${INLINE_CONTRACT}): string {return p.name + p.email;}`],
      ["unused destructured fields are still read", `function label({name, email}: ${INLINE_CONTRACT}): string {return name;}`],
      ["optional unused field does not restrict structural callers", "function label(p: {readonly name: string; readonly email?: string}): string {return p.name;}"],
      ["optional-only reduced contract can reject weak-type callers", "function label(p: {readonly name?: string; readonly email: string}): string {return p.name ?? '';}"],
      ["all plain required fields consumed", "function label(p: {name: string; email: string}): string {return p.name + p.email;}"],
      ["plain destructuring still reads an unreturned field", "function label({name, email}: {name: string; email: string}): string {return name;}"],
      ["unused plain optional field does not restrict callers", "function label(p: {name: string; email?: string}): string {return p.name;}"],
      ["mixed optional-only reduced contract remains excluded", "function label(p: {name?: string; readonly email: string}): string {return p.name ?? '';}"],
      ["plain literal field retains a domain invariant", "function label(p: {name: string; kind: 'account'}): string {return p.name;}"],
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
      ["plain field declarations retain read-only usage", "function label(p: {name: string; email: string}): string {return p.name;}", "function label(p: {name: string; }): string {return p.name;}"],
      ["retained readonly field is not rewritten", "function label(p: {readonly name: string; email: string}): string {return p.name;}", "function label(p: {readonly name: string; }): string {return p.name;}"],
      ["removed readonly field does not make the retained field readonly", "function label(p: {name: string; readonly email: string}): string {return p.name;}", "function label(p: {name: string; }): string {return p.name;}"],
      ["mixed optional modifiers and reads remain", "function label(p: {name: string; email: string; readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}", "function label(p: {name: string;  readonly suffix?: string}): string {return p.name + (p.suffix ?? '');}"],
      ["readonly producer keeps its full object type", "const input = {name: 'Ada', email: 'a'} as const; function label(p: {name: string; email: string}): string {return p.name;}", "const input = {name: 'Ada', email: 'a'} as const; function label(p: {name: string; }): string {return p.name;}", "input"],
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
    {name: "plain contract with an invalid original caller stays manual", filename: "probe.tsx", code: "export {}; const account = {name: 'Ada', email: 42}; function label(p: {name: string; email: string}): string {return p.name;} label(account);", output: null, errors: [{messageId: "minimal"}]},
    {name: "plain contract with unknown caller data stays manual", filename: "probe.tsx", code: "export {}; declare const input: {name: string; email: any}; function label(p: {name: string; email: string}): string {return p.name;} label(input);", output: null, errors: [{messageId: "minimal"}]},
    {name: "comments remain manual", filename: "probe.tsx", code: `${PREFIX}function label(p: {readonly name: string; /* rationale */ readonly email: string}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "preexisting invalid identifier caller stays rejected", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada', email: 42}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "minimal"}]},
    ...["any", "unknown"].map((type) => ({name: "unsafe relevant caller field remains manual " + type, filename: "probe.tsx",
      code: `${PREFIX}declare const value: {name: string; email: ${type}}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal" as const}]})),
    {name: "unresolved error caller field remains manual", filename: "probe.tsx", code: `${PREFIX}declare const value: {name: string; email: Missing}; function label(p: ${INLINE_CONTRACT}): string {return p.name;} label(value);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "a required ts-expect-error must not become unused", filename: "probe.tsx", code: `export {}; const account = {name: 'Ada'}; function label(p: ${INLINE_CONTRACT}): string {return p.name;}\n// @ts-expect-error the original private contract requires email\nlabel(account);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});

const SCALAR_HELPER = "function formatName(name: string): string {return name.toUpperCase();}";
const HELPER_CONSUMER = "function label(p: {name: string; email: string}): string {return formatName(p.name);}";
PRIVATE_CONSUMER_TESTER.run("prefer-minimal-parameter-contract scalar helpers", rule, {
  valid: [
    ...[
      ["inferred helper returns remain unsupported", "function formatName(name: string) {return name;}", HELPER_CONSUMER],
      ["callee aliases remain unsupported", SCALAR_HELPER + "const alias = formatName;", HELPER_CONSUMER.replace("formatName(p.name)", "alias(p.name)")],
      ["helper arguments cannot mutate the parameter", SCALAR_HELPER, HELPER_CONSUMER.replace("p.name)", "p.name = 'updated')")],
      ["callbacks cannot capture the parameter", "function formatName(read: () => string): string {return read();}", HELPER_CONSUMER.replace("formatName(p.name)", "formatName(() => p.name)")],
      ["predicate helpers retain refinement semantics", "function accepts(value: unknown): value is string {return typeof value === 'string';}", "function label(p: {name: string; email: string}): boolean {return accepts(p.name);}"],
      ["a native-invalid original helper caller is unavailable", SCALAR_HELPER, HELPER_CONSUMER + "const broken = {name: 'Ada', email: 42}; label(broken);"],
    ].map(([name, helper, consumer]) => ({name, filename: "probe.tsx", code: `${PREFIX}${helper}${consumer}label(account);`})),
  ],
  invalid: [
    ...[
      ["local implementation receives only a scalar", SCALAR_HELPER, HELPER_CONSUMER, "label(account);"],
      ["raw const arrow implementation", "const formatName = (name: string): string => name;", HELPER_CONSUMER, "label(account);"],
      ["all identifier callers and producer aliases remain unchanged", SCALAR_HELPER, HELPER_CONSUMER, "const alias = account; label(account); label(alias);"],
      ["two scalar arguments retain only their fixed field dependency", "function formatName(name: string, suffix: string): string {return name + suffix;}", HELPER_CONSUMER.replace("formatName(p.name)", "formatName(p.name, '!')"), "label(account);"],
    ].map(([name, helper, consumer, calls]) => ({name, filename: "probe.tsx", code: `${PREFIX}${helper}${consumer}${calls}`,
      output: `${PREFIX}${helper}${consumer?.replace("email: string", "")}${calls}`, errors: [{messageId: "minimal" as const}]})),
    {name: "comments in a new helper contract preserve manual review", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_HELPER}${HELPER_CONSUMER.replace("email: string", "/* private dependency rationale */ email: string")}label(account);`, output: null, errors: [{messageId: "minimal"}]},
    {name: "an Any caller cannot certify an automatic contract edit", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_HELPER}${HELPER_CONSUMER}declare const opaque: {name: string; email: any}; label(account); label(opaque);`, output: null, errors: [{messageId: "minimal"}]},
  ],
});
