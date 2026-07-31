import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import { ESLint } from "eslint";
import reactHooks from "eslint-plugin-react-hooks";
import unicorn from "eslint-plugin-unicorn";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import perfectionist from "eslint-plugin-perfectionist";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import betterTailwindcss from "eslint-plugin-better-tailwindcss";
import sarj from "@sarj/eslint-plugin";
import zod from "eslint-plugin-zod";

// unicorn ships 341 rules; this config used to run 12 of them. The set below
// was chosen by RUNNING every non-deprecated unicorn 72 rule over 4,356 deduped
// first-party production `.ts`/`.tsx` files (deduped by content hash — two of
// the repos in the corpus are ~97% byte-identical, so an un-deduped count is
// inflated roughly 2x) and deciding rule by rule. Trailing numbers are
// `total / total excluding the two near-duplicate repos`; a rule with no number
// measured ZERO findings and is enabled as a RATCHET, which is the whole point
// for the correctness family: the cost today is nothing and the pattern can
// never enter.
//
// Rules are declared as two objects rather than inline so the version guard
// below can check them, and so the two intents stay separable.
//
// REQUIRES eslint-plugin-unicorn >= 72 (and therefore eslint >= 10.4). 121 of
// these rules do not exist in unicorn 64 and 96 do not exist in 65; on an older
// plugin ESLint would emit "Definition for rule ... was not found" once per rule
// per file. The guard below turns that into one actionable line.

// Correctness. These catch BUGS, not style: useless/unnecessary constructs that
// are almost always a symptom of a wrong edit (`no-unnecessary-await`,
// `no-useless-fallback-in-spread`), calls that silently do nothing
// (`no-single-promise-in-promise-methods`, `no-invalid-fetch-options`), and
// footguns with real production failure modes (`no-thenable`,
// `no-array-fill-with-reference-type`, `no-unsafe-string-replacement`).
//
// DOM-family entries are included UNSCOPED on purpose. They are receiver-matched
// — they only fire on `document.*`, an `Element`, or an event API — so they are
// inert in a Node package and cost nothing there. Scoping them to `**/*.tsx`
// would have been worse than useless: measured, DOM code lives in plain `.ts`
// hooks and utility modules too, so a `.tsx` glob silently drops the findings.
// The DOM *modernisation* rules (prefer-query-selector, prefer-dom-node-append,
// dom-node-dataset, …) are rejected instead — see the rejection list below.
const UNICORN_CORRECTNESS_RULES = {
  "unicorn/class-reference-in-static-methods": "error",
  "unicorn/consistent-assert": "error",
  "unicorn/consistent-date-clone": "error",  // 4 / 0
  "unicorn/consistent-empty-array-spread": "error",
  "unicorn/consistent-json-file-read": "error",
  "unicorn/error-message": "error",  // 6 / 6
  "unicorn/explicit-timer-delay": "error",
  "unicorn/new-for-builtins": "error",  // 17 / 15
  "unicorn/no-accessor-recursion": "error",
  "unicorn/no-accidental-bitwise-operator": "error",
  "unicorn/no-array-concat-in-loop": "error",
  "unicorn/no-array-fill-with-reference-type": "error",
  "unicorn/no-array-from-fill": "error",
  "unicorn/no-array-method-this-argument": "error",
  "unicorn/no-array-sort-for-min-max": "error",
  "unicorn/no-async-promise-finally": "error",
  "unicorn/no-await-in-promise-methods": "error",
  "unicorn/no-blob-to-file": "error",
  "unicorn/no-boolean-sort-comparator": "error",
  "unicorn/no-canvas-to-image": "error",
  "unicorn/no-chained-comparison": "error",
  "unicorn/no-collection-bracket-access": "error",
  "unicorn/no-confusing-array-splice": "error",
  "unicorn/no-confusing-array-with": "error",
  "unicorn/no-constant-zero-expression": "error",  // 2 / 2
  "unicorn/no-document-cookie": "error",
  "unicorn/no-double-comparison": "error",
  "unicorn/no-duplicate-if-branches": "error",  // 4 / 3
  "unicorn/no-duplicate-logical-operands": "error",
  "unicorn/no-duplicate-loops": "error",  // 5 / 4
  "unicorn/no-duplicate-set-values": "error",  // 2 / 0
  "unicorn/no-empty-file": "error",
  "unicorn/no-error-property-assignment": "error",
  "unicorn/no-exports-in-scripts": "error",  // 2 / 0
  "unicorn/no-global-object-property-assignment": "error",  // 4 / 2
  "unicorn/no-immediate-mutation": "error",  // 3 / 0
  "unicorn/no-impossible-length-comparison": "error",
  "unicorn/no-incorrect-query-selector": "error",
  "unicorn/no-incorrect-template-string-interpolation": "error",  // 18 / 6
  "unicorn/no-instanceof-builtins": "error",
  "unicorn/no-invalid-argument-count": "error",
  "unicorn/no-invalid-character-comparison": "error",
  "unicorn/no-invalid-fetch-options": "error",
  "unicorn/no-invalid-file-input-accept": "error",  // 6 / 3
  "unicorn/no-invalid-remove-event-listener": "error",
  "unicorn/no-invalid-well-known-symbol-methods": "error",
  "unicorn/no-late-current-target-access": "error",
  "unicorn/no-late-event-control": "error",
  "unicorn/no-loop-iterable-mutation": "error",
  "unicorn/no-magic-array-flat-depth": "error",
  "unicorn/no-mismatched-map-key": "error",
  "unicorn/no-misrefactored-assignment": "error",
  "unicorn/no-missing-local-resource": "error",
  "unicorn/no-multiple-promise-resolver-calls": "error",
  "unicorn/no-negation-in-equality-check": "error",
  "unicorn/no-new-array": "error",  // 18 / 3
  "unicorn/no-new-buffer": "error",
  "unicorn/no-nonstandard-builtin-properties": "error",
  "unicorn/no-object-methods-with-collections": "error",
  "unicorn/no-optional-chaining-on-undeclared-variable": "error",  // 17 / 2
  "unicorn/no-redundant-comparison": "error",  // 2 / 0
  "unicorn/no-return-array-push": "error",  // 14 / 0
  "unicorn/no-selector-as-dom-name": "error",
  "unicorn/no-shorthand-property-overrides": "error",
  "unicorn/no-single-promise-in-promise-methods": "error",
  "unicorn/no-subtraction-comparison": "error",
  "unicorn/no-thenable": "error",  // 1 / 1
  "unicorn/no-this-assignment": "error",
  "unicorn/no-this-outside-of-class": "error",  // 2 / 2
  "unicorn/no-typeof-undefined": "error",
  "unicorn/no-uncalled-method": "error",  // 1 / 1
  "unicorn/no-undeclared-class-members": "error",
  "unicorn/no-unnecessary-array-flat-depth": "error",
  "unicorn/no-unnecessary-array-flat-map": "error",
  "unicorn/no-unnecessary-array-splice-count": "error",
  "unicorn/no-unnecessary-await": "error",
  "unicorn/no-unnecessary-boolean-comparison": "error",
  "unicorn/no-unnecessary-fetch-options": "error",  // 1 / 1
  "unicorn/no-unnecessary-global-this": "error",
  "unicorn/no-unnecessary-nested-ternary": "error",  // 25 / 4
  "unicorn/no-unnecessary-polyfills": "error",
  "unicorn/no-unnecessary-slice-end": "error",
  "unicorn/no-unnecessary-splice": "error",
  "unicorn/no-unnecessary-string-trim": "error",  // 6 / 1
  "unicorn/no-unsafe-buffer-conversion": "error",
  "unicorn/no-unsafe-dom-html": "error",  // 6 / 1
  "unicorn/no-unsafe-promise-all-settled-values": "error",  // 1 / 0
  "unicorn/no-unsafe-property-key": "error",
  "unicorn/no-unsafe-string-replacement": "error",  // 25 / 14
  "unicorn/no-unused-array-method-return": "error",
  "unicorn/no-useless-boolean-cast": "error",
  "unicorn/no-useless-collection-argument": "error",  // 12 / 8
  "unicorn/no-useless-compound-assignment": "error",
  "unicorn/no-useless-concat": "error",  // 4 / 0
  "unicorn/no-useless-continue": "error",
  "unicorn/no-useless-delete-check": "error",
  "unicorn/no-useless-else": "error",  // 9 / 7
  "unicorn/no-useless-error-capture-stack-trace": "error",
  "unicorn/no-useless-fallback-in-spread": "error",  // 12 / 2
  "unicorn/no-useless-iterator-to-array": "error",
  "unicorn/no-useless-length-check": "error",  // 3 / 0
  "unicorn/no-useless-logical-operand": "error",
  "unicorn/no-useless-override": "error",
  "unicorn/no-useless-promise-resolve-reject": "error",  // 15 / 15
  "unicorn/no-useless-re-export": "error",
  "unicorn/no-useless-recursion": "error",  // 3 / 1
  "unicorn/no-useless-spread": "error",
  "unicorn/no-useless-switch-case": "error",  // 23 / 13
  "unicorn/no-xor-as-exponentiation": "error",
  "unicorn/prefer-add-event-listener": "error",  // 24 / 9
  "unicorn/prefer-add-event-listener-options": "error",  // 5 / 2
  "unicorn/prefer-keyboard-event-key": "error",
  "unicorn/require-array-join-separator": "error",
  "unicorn/require-css-escape": "error",  // 2 / 0
  "unicorn/require-module-attributes": "error",
  "unicorn/require-module-specifiers": "error",
  "unicorn/require-number-to-fixed-digits-argument": "error",
  "unicorn/require-passive-events": "error",
  "unicorn/require-post-message-target-origin": "error",
  "unicorn/require-proxy-trap-boolean-return": "error",
  "unicorn/text-encoding-identifier-case": "error",  // 26 / 18
};

// Modernisation. Enabled only where the fix is mechanical (autofix or a
// one-line suggestion), semantics-preserving, and reaches a platform API that
// actually EXISTS on the declared floor (Node 22 / `lib: ES2025`). That last
// clause is not theoretical: `prefer-error-is-error` is the single largest
// finding count in the whole corpus (608) and is rejected below precisely
// because `Error.isError` is absent on Node 22, so taking its autofix converts
// working `instanceof Error` checks into runtime TypeErrors.
//
// Two of these need `lib` >= ES2025 in the CONSUMER to typecheck after the fix
// (`prefer-iterator-to-array` -> `Iterator#toArray`, `prefer-set-methods` ->
// `Set#union` and friends). Both are ES2025 library types available in TS today;
// a consumer still on `lib: ES2024` bumps `lib`, it does not bump its runtime.
const UNICORN_MODERNISATION_RULES = {
  "unicorn/no-array-reverse": "error",  // 47 / 2
  "unicorn/no-array-sort": "error",  // 327 / 135
  "unicorn/no-for-loop": "error",  // 6 / 3
  "unicorn/prefer-abort-signal-any": "error",
  "unicorn/prefer-abort-signal-timeout": "error",
  "unicorn/prefer-aggregate-error": "error",
  "unicorn/prefer-array-flat": "error",
  "unicorn/prefer-array-flat-map": "error",
  "unicorn/prefer-array-from-async": "error",  // 1 / 1
  "unicorn/prefer-array-from-map": "error",  // 123 / 62
  "unicorn/prefer-array-from-range": "error",
  "unicorn/prefer-array-index-of": "error",
  "unicorn/prefer-array-iterable-methods": "error",
  "unicorn/prefer-array-last-methods": "error",  // 15 / 0
  "unicorn/prefer-array-slice": "error",
  "unicorn/prefer-array-some": "error",  // 15 / 2
  "unicorn/prefer-at": "error",  // 79 / 18
  "unicorn/prefer-bigint-literals": "error",
  "unicorn/prefer-blob-reading-methods": "error",  // 1 / 1
  "unicorn/prefer-class-fields": "error",
  "unicorn/prefer-code-point": "error",  // 73 / 13
  "unicorn/prefer-date-now": "error",
  "unicorn/prefer-default-parameters": "error",  // 8 / 1
  "unicorn/prefer-direct-iteration": "error",  // 47 / 12
  "unicorn/prefer-event-target": "error",
  "unicorn/prefer-export-from": "error",  // 75 / 44
  "unicorn/prefer-flat-math-min-max": "error",
  "unicorn/prefer-global-number-constants": "error",  // 10 / 4
  "unicorn/prefer-group-by": "error",
  "unicorn/prefer-has-check": "error",
  "unicorn/prefer-https": "error",  // 38 / 25
  "unicorn/prefer-identifier-import-export-specifiers": "error",
  "unicorn/prefer-import-meta-properties": "error",  // 6 / 6
  "unicorn/prefer-iterable-in-constructor": "error",  // 1 / 1
  "unicorn/prefer-iterator-concat": "error",  // 15 / 11
  "unicorn/prefer-iterator-to-array": "error",  // 79 / 43
  "unicorn/prefer-map-from-entries": "error",
  "unicorn/prefer-math-abs": "error",  // 2 / 0
  "unicorn/prefer-math-constants": "error",
  "unicorn/prefer-math-min-max": "error",  // 5 / 4
  "unicorn/prefer-math-trunc": "error",  // 19 / 3
  "unicorn/prefer-modern-math-apis": "error",  // 3 / 0
  "unicorn/prefer-module": "error",
  "unicorn/prefer-native-coercion-functions": "error",  // 21 / 0
  "unicorn/prefer-negative-index": "error",
  "unicorn/prefer-number-is-safe-integer": "error",  // 22 / 6
  "unicorn/prefer-number-properties": "error",  // 210 / 108
  "unicorn/prefer-object-define-properties": "error",  // 1 / 1
  "unicorn/prefer-object-destructuring-defaults": "error",
  "unicorn/prefer-object-from-entries": "error",  // 1 / 1
  "unicorn/prefer-object-iterable-methods": "error",  // 2 / 0
  "unicorn/prefer-optional-catch-binding": "error",  // 8 / 4
  "unicorn/prefer-promise-with-resolvers": "error",
  "unicorn/prefer-queue-microtask": "error",
  "unicorn/prefer-regexp-test": "error",  // 2 / 2
  "unicorn/prefer-response-static-json": "error",  // 10 / 8
  "unicorn/prefer-set-has": "error",  // 40 / 9
  "unicorn/prefer-set-methods": "error",  // 3 / 3
  "unicorn/prefer-set-size": "error",
  "unicorn/prefer-simple-sort-comparator": "error",  // 6 / 0
  "unicorn/prefer-simplified-conditions": "error",
  "unicorn/prefer-single-array-predicate": "error",
  "unicorn/prefer-single-replace": "error",
  "unicorn/prefer-split-limit": "error",  // 123 / 51
  "unicorn/prefer-spread": "error",  // 124 / 39
  "unicorn/prefer-string-match-all": "error",
  "unicorn/prefer-string-pad-start-end": "error",
  "unicorn/prefer-string-raw": "error",  // 78 / 36
  "unicorn/prefer-string-repeat": "error",  // 9 / 5
  "unicorn/prefer-string-slice": "error",  // 20 / 12
  "unicorn/prefer-string-trim-start-end": "error",
  "unicorn/prefer-then-catch": "error",
  "unicorn/prefer-type-error": "error",  // 4 / 4
  "unicorn/prefer-unary-minus": "error",
  "unicorn/prefer-unicode-code-point-escapes": "error",  // 45 / 31
  "unicorn/prefer-url-can-parse": "error",
  "unicorn/prefer-url-search-parameters": "error",
  "unicorn/prefer-while-loop-condition": "error",
};

// One actionable line instead of N x M "Definition for rule ... was not found".
// Self-maintaining: it re-derives the required names from the objects above, so
// adding a rule that a pinned consumer's plugin lacks fails loudly at config
// load rather than silently linting nothing.
const missingUnicornRules = [
  ...Object.keys(UNICORN_CORRECTNESS_RULES),
  ...Object.keys(UNICORN_MODERNISATION_RULES),
]
  .map((key) => key.slice("unicorn/".length))
  .filter((name) => !(name in unicorn.rules));

if (missingUnicornRules.length > 0) {
  throw new Error(
    `sarj-lint-configs: ${String(missingUnicornRules.length)} rule(s) this config enables do not exist ` +
      `in the installed eslint-plugin-unicorn (${missingUnicornRules.slice(0, 5).join(", ")}). ` +
      `Either the plugin is older than the required >= 72 (which also needs eslint >= 10.4), ` +
      `or a rule name in this config is a typo or was renamed upstream.`,
  );
}

// Rules deliberately NOT enabled. A rejection is a decision, not an omission, so
// each family says why. Counts are `total / excluding the two near-duplicate
// repos` over the same 4,356-file corpus.
//
// 1. UNAVAILABLE ON THE DECLARED FLOOR (Node 22 / lib ES2025). Their autofix
//    produces code that throws at runtime, so a big count is a trap, not a
//    backlog:
//      prefer-error-is-error (608/364) `Error.isError` is ES2026; `typeof
//        Error.isError` is "undefined" on Node 22. This is the LARGEST single
//        count in the corpus and it is still a reject.
//      prefer-temporal (1808/695) `Temporal` is not in any consumer runtime;
//        migrating every `Date` is a rewrite, not a lint fix.
//      prefer-uint8array-base64 (5/5), prefer-regexp-escape (4/3),
//      prefer-promise-try (0), prefer-get-or-insert-computed (0) — all absent
//        on Node 22.
//      prefer-dispose (1/1) needs `using` plus a bundled `Symbol.dispose`.
//
// 2. DUPLICATES OF A RULE THIS CONFIG ALREADY OWNS. The repo rule is one
//    diagnostic per concern; a second plugin reporting the same line is noise:
//      prefer-includes (9/1) -> @typescript-eslint/prefer-includes
//      prefer-array-find (2/1) -> @typescript-eslint/prefer-find
//      prefer-string-starts-ends-with (4/0) -> the @typescript-eslint twin
//      require-array-sort-compare (36/19) -> the @typescript-eslint twin
//      no-useless-coercion (11/0) -> @typescript-eslint/no-unnecessary-type-conversion
//      no-useless-template-literals (6/0) -> @typescript-eslint/no-unnecessary-template-expression
//      try-complexity (1339/292) -> @sarj/no-fat-try-blocks, the declared single
//        owner of the oversized-try concern
//      no-for-each (210/58) -> the `no-restricted-syntax` forEach selector below
//      no-abusive-eslint-disable (0) -> @eslint-community/eslint-comments/no-unlimited-disable
//    ...and two that would actively FIGHT an enabled rule:
//      consistent-class-member-order (22/19) vs perfectionist/sort-classes
//      prefer-type-literal-last (14/9) vs perfectionist/sort-union-types
//      prefer-number-coercion (258/115) tells you to delete the `parseInt` that
//        prefer-number-properties just told you to qualify as `Number.parseInt`.
//
// 3. MASS NAMING / NULL CHURN — the famous ones, measured so the rejection is a
//    number rather than a vibe:
//      name-replacements (13493/5331) the unicorn 72 successor to
//        prevent-abbreviations, which is itself DEPRECATED in 72. Renaming
//        ~5.3k identifiers outside the demo repos alone is not a lint rollout.
//      no-null (9626/4060) `null` is load-bearing in JSON payloads, database
//        rows and React refs across every consumer.
//      no-keyword-prefix (4589/1658), consistent-boolean-name (1766/491),
//      consistent-compound-words (21/4), catch-error-name (984/354),
//      no-non-function-verb-prefix (0) — same family, same answer.
//
// 4. FORMATTING PRETTIER ALREADY OWNS, or pure cosmetics:
//      numeric-separators-style (4220/97), switch-case-braces (1355/492),
//      no-zero-fractions (576/20), empty-brace-spaces (267/0),
//      no-manually-wrapped-comments (255/3),
//      no-asterisk-prefix-in-documentation-comments (810/207),
//      number-literal-case (40/16), template-indent (26/4), escape-case (1/1).
//
// 5. READABILITY OPINION, not correctness. High volume, low signal, and each is
//    a taste this config has no business legislating:
//      no-nested-ternary (1292/278), no-unreadable-new-expression (1143/376),
//      explicit-length-check (665/304), no-negated-condition (560/187),
//      max-nested-calls (368/169), no-declarations-before-early-exit (184/52),
//      prefer-early-return (157/59), no-break-in-nested-loop (122/85),
//      consistent-conditional-object-spread (113/56), prefer-minimal-ternary
//      (99/7), no-unreadable-for-of-expression (68/40), no-array-reduce
//      (67/16), consistent-existence-index-check (63/37), no-negated-array-
//      predicate (47/16), prefer-single-call (40/4), prefer-ternary (35/16),
//      prefer-else-if (31/6), prefer-continue (22/7), default-export-style
//      (19/0), no-lonely-if (14/9), prefer-boolean-return (7/4),
//      prefer-short-arrow-method (5/5), prefer-hoisting-branch-code (3/1),
//      and the rest of the `consistent-*` / `no-unreadable-*` tail.
//
// 6. MEASURED FALSE-POSITIVE RATE TOO HIGH. These were sampled by hand, not
//    judged from the docs:
//      prefer-simple-condition-first (247/107) reorders `&&`/`||` operands; its
//        own message says "after verifying short-circuit behavior", and every
//        sample was a correct guard chain (`!room || !input.trim() || ...`).
//        Reordering also breaks TypeScript narrowing order.
//      no-array-callback-reference (202/41) every sample was a typed one-arg
//        local passed to `.map`. The bug it exists for (`map(parseInt)`) is
//        already a compile error under strict TS.
//      no-computed-property-existence-check (274/30) every sample was idiomatic
//        `if (!record[key])`, which `noUncheckedIndexedAccess` already types.
//      no-top-level-assignment-in-function (227/52) fires on the standard
//        lazy-singleton / memoised-init pattern.
//      prefer-includes-over-repeated-comparisons (103/39) `a === "x" || a ===
//        "y"` NARROWS the union in TypeScript; `.includes` does not.
//      prefer-await (881/125) suggestion-only, and mechanically rewriting a
//        promise chain into `await` changes which errors are caught where.
//      no-unused-properties (25/6), prefer-private-class-fields (5/5),
//      custom-error-definition (9/9), consistent-destructuring (4/4).
//
// 7. NEEDS PER-REPO CONFIGURATION to mean anything, so a SHARED config cannot
//    set it: import-style (12/8), comment-content (53/8), string-content (0),
//    id-match (0), expiring-todo-comments (0), require-frontmatter-fields (0),
//    no-top-level-side-effects (139/134, fires on every app entrypoint),
//    no-process-exit (37/7, legitimate in CLI entrypoints).
//
// 8. DOM MODERNISATION, as opposed to the DOM correctness rules enabled above.
//    In a React/Next codebase direct DOM manipulation is deliberate escape-hatch
//    code, so rewriting it buys nothing: prefer-query-selector (23/13),
//    prefer-dom-node-append (25/11), dom-node-dataset (23/13),
//    prefer-observer-apis (12/6), prefer-dom-node-remove (6/6),
//    prefer-classlist-toggle (4/1), prefer-toggle-attribute (3/0),
//    prefer-location-assign (8/3), prefer-url-href (29/20),
//    prefer-dom-node-replace-children (1/1), prefer-modern-dom-apis (0),
//    better-dom-traversing (0), prefer-scoped-selector (0), prefer-path2d (0).
//
// 9. DEPRECATED IN UNICORN 72 and therefore never a candidate: better-regex,
//    no-instanceof-array, no-length-as-slice-end, no-hex-escape,
//    no-array-push-push, prevent-abbreviations, prefer-json-parse-buffer,
//    prefer-dom-node-dataset. `prefer-explicit-viewport-units` is a CSS-language
//    rule and cannot be enabled in a JS config at all.


// eslint-plugin-react is UNUSABLE on ESLint 10, and this config's own unicorn
// floor requires ESLint 10.
//
// 7.37.5 is the newest published release. Its `lib/util/version.js` calls
// `context.getFilename()`, removed in ESLint 10, so every react rule dies with
// `TypeError: contextOrFilename.getFilename is not a function` the moment it
// lints a file. Not at config load -- `calculateConfigForFile` normalises the
// config without ever loading a rule's implementation, so the config-load test
// passed while the config could not lint a single file. Only running ESLint
// finds it, which is exactly the failure mode that ends with a consumer copying
// the file and hacking on the copy.
//
// So the 18 react rules below are opt-out rather than removed: they run on
// ESLint 9, and are skipped with a `plugins`-level omission on 10+ so the rest
// of the config (including the 199 unicorn rules that forced the 10 floor) is
// usable today. Delete this guard when eslint-plugin-react ships ESLint 10
// support; `tests/strict-config-runs.test.ts` fails if the guard stops being
// needed, so it cannot outlive the bug.
const ESLINT_MAJOR = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);
const REACT_PLUGIN_WORKS = ESLINT_MAJOR < 10;
const reactPlugins = REACT_PLUGIN_WORKS ? { react } : {};

/** Drop `react/*` keys when the plugin cannot run, so ESLint sees no unknown rule. */
const withoutReactRules = (rules) =>
  REACT_PLUGIN_WORKS
    ? rules
    : Object.fromEntries(
        Object.entries(rules).filter(([name]) => !name.startsWith("react/")),
      );

/** @type {import("eslint").Linter.Config[]} */
const config = [
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,

  {
    // Dead eslint-disable directives are an error (parity with ruff RUF100).
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    plugins: {
      "@typescript-eslint": tseslint.plugin,
      ...reactPlugins,
      "react-hooks": reactHooks,
      unicorn,
      "@eslint-community/eslint-comments": eslintComments,
      perfectionist,
      "simple-import-sort": simpleImportSort,
      "@sarj": sarj,
      zod,
    },
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: process.cwd(),
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: "detect" } },
    rules: withoutReactRules({
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-deprecated": "error",
      "@typescript-eslint/only-throw-error": [
        "error",
        {
          allow: [
            {
              from: "package",
              package: "@tanstack/react-router",
              name: ["redirect"],
            },
          ],
        },
      ],
      "@typescript-eslint/prefer-promise-reject-errors": "error",
      "@typescript-eslint/no-meaningless-void-operator": "error",
      "@typescript-eslint/no-mixed-enums": "error",
      "@typescript-eslint/prefer-find": "error",
      "@typescript-eslint/prefer-readonly": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-argument": "error",
      "@typescript-eslint/no-unsafe-call": "error",
      "@typescript-eslint/no-unsafe-return": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/await-thenable": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/require-await": "error",
      "@typescript-eslint/restrict-template-expressions": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
      "@typescript-eslint/consistent-indexed-object-style": ["error", "record"],
      "@typescript-eslint/consistent-type-imports": [
        "error",
        {
          prefer: "type-imports",
          fixStyle: "inline-type-imports",
        },
      ],
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        {
          assertionStyle: "never",
        },
      ],
      "@typescript-eslint/naming-convention": [
        "error",
        {
          selector: "default",
          format: ["camelCase"],
          leadingUnderscore: "allow",
          trailingUnderscore: "allow",
          filter: {
            regex: "^(UNSAFE_|__)",
            match: false,
          },
        },
        {
          selector: "variable",
          format: ["camelCase", "UPPER_CASE", "PascalCase"],
          leadingUnderscore: "allow",
        },
        { selector: "typeLike", format: ["PascalCase"] },
        {
          selector: "import",
          format: ["camelCase", "PascalCase", "UPPER_CASE"],
        },
        { selector: "objectLiteralProperty", format: null },
        { selector: "typeProperty", format: null },
        {
          selector: "parameter",
          format: ["camelCase", "snake_case"],
          leadingUnderscore: "allow",
        },
      ],

      // Additional type-aware strictness incorporated from a first-party base config.
      "@typescript-eslint/prefer-as-const": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/prefer-nullish-coalescing": [
        "error",
        { ignorePrimitives: { number: true, string: true, boolean: true } },
      ],
      "@typescript-eslint/prefer-optional-chain": "error",
      // checkMethodDeclarations is off because the autofix is destructive on
      // framework-defined methods. React's ReactNode union includes
      // Promise<AwaitedReactNode> (for async Server Components), so a class
      // component's render() infers as promise-returning and the fixer adds
      // `async` — which makes React throw #482 and takes down every route the
      // component wraps. Standalone functions and arrows are still checked.
      "@typescript-eslint/promise-function-async": ["error", { checkMethodDeclarations: false }],
      "@typescript-eslint/no-non-null-asserted-optional-chain": "error",
      "@typescript-eslint/no-unnecessary-type-assertion": "error",
      "@typescript-eslint/no-redundant-type-constituents": "error",
      "@typescript-eslint/require-array-sort-compare": "error",
      "@typescript-eslint/no-unsafe-type-assertion": "error",
      "@typescript-eslint/no-unsafe-enum-comparison": "error",
      "@typescript-eslint/no-base-to-string": "error",
      "@typescript-eslint/no-misused-spread": "error",
      "@typescript-eslint/no-unnecessary-type-conversion": "error",
      "@typescript-eslint/prefer-includes": "error",
      "@typescript-eslint/prefer-string-starts-ends-with": "error",
      "@typescript-eslint/no-confusing-non-null-assertion": "error",
      "@typescript-eslint/no-duplicate-type-constituents": "error",
      "@typescript-eslint/no-invalid-void-type": "error",
      "@typescript-eslint/no-unnecessary-template-expression": "error",
      "@typescript-eslint/no-import-type-side-effects": "error",
      "@typescript-eslint/array-type": "error",
      // `no-else-return` used to sit here. It is gone because
      // `unicorn/no-useless-else` (enabled below) is a strict superset: it flags
      // `else` after `throw`, `break` and `continue` as well as after `return`.
      // Keeping both would double-report the return case, which this config
      // treats as a bug (one diagnostic per concern). Measured at 9 findings
      // corpus-wide, so the superset is not a churn event.

      "react/jsx-no-leaked-render": [
        "error",
        { validStrategies: ["ternary", "coerce"] },
      ],
      "react/no-unstable-nested-components": "error",
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/rules-of-hooks": "error",
      "react/forbid-elements": [
        "error",
        {
          forbid: [
            {
              element: "button",
              message: "Use <Button> from your design system.",
            },
            {
              element: "input",
              message:
                "Use <Input> / <Checkbox> / <RadioGroup> from your design system.",
            },
            {
              element: "select",
              message: "Use <Select> from your design system.",
            },
            {
              element: "textarea",
              message: "Use <Textarea> from your design system.",
            },
            {
              element: "dialog",
              message: "Use <Dialog> / <AlertDialog> from your design system.",
            },
            {
              element: "table",
              message: "Use <Table> family from your design system.",
            },
          ],
        },
      ],
      "react/forbid-component-props": [
        "error",
        {
          forbid: [
            {
              propName: "style",
              message:
                "Use design-token utility classes. For dynamic values, set a CSS custom property and reference it via an arbitrary-value class.",
            },
          ],
        },
      ],
      "react/forbid-dom-props": [
        "error",
        {
          forbid: [
            {
              propName: "style",
              message:
                "Use design-token utility classes. For dynamic values, set a CSS custom property and reference it via an arbitrary-value class.",
            },
          ],
        },
      ],
      "react/jsx-pascal-case": "error",
      "react/no-danger": "error",
      "react/no-this-in-sfc": "error",
      "react/jsx-no-comment-textnodes": "error",
      "react/jsx-no-duplicate-props": "error",
      "react/jsx-no-target-blank": "error",
      "react/jsx-no-undef": "error",
      "react/void-dom-elements-no-children": "error",
      "react/jsx-fragments": "error",
      "react/jsx-no-script-url": "error",
      "react/self-closing-comp": "error",
      "react/jsx-no-useless-fragment": "error",
      "react/jsx-boolean-value": ["error", "never"],

      "unicorn/consistent-function-scoping": "error",
      // Kebab-case filenames. unicorn handles most framework shapes for free:
      // brackets and parens are "ignored characters" so `[id].tsx`,
      // `[...slug].tsx` and `(marketing)/` only have their inner word checked,
      // and `multipleFileExtensions` (default true) checks only the segment
      // before the FIRST dot, so `vite.config.ts`, `foo.test.ts` and
      // `app.module.css.ts` all pass on the stem alone.
      //
      // Measured over 11,088 tracked `.ts`/`.tsx` files in 50 repos under
      // ~/code, the shapes people assume need exemptions do not: Next.js
      // special files (`page`/`layout`/`route`/`loading`/`error`, 1,924 files)
      // produce ZERO violations, as do `*.config.ts` (338), `.d.ts` (123) and
      // barrel `index.*` (176). Everything is App Router; `_app.tsx` and
      // `_document.tsx` do not occur at all.
      //
      // The `ignore` list below is therefore short and each entry is earned:
      //   - `^__root\.`   TanStack Router's root route (a rename breaks routing)
      //   - `^_`          TanStack `_layout` / pathless routes, and this repo's
      //                   own `_paths.ts` / `_comments.ts` private helpers
      //   - `^\$`         TanStack dynamic segments, e.g. `$benchmarkId.tsx`
      //   - `^\+`         Expo Router specials, e.g. `+not-found.tsx`
      //   - `\.gen\.`     generated output — the generator owns the name, so a
      //                   rename is undone on the next codegen run
      // `\.d\.ts$` is deliberately DROPPED: it was redundant (the stem check
      // already ignores the `.d` middle segment) and over-broad — it let
      // `apiTypes.d.ts` through, which is a genuine violation.
      //
      // `checkDirectories` is deliberately NOT passed. The version argument for
      // withholding it is moot now that this config carries a hard `>= 72`
      // floor. The surviving reason is the measured one: on the real corpus it
      // earns nothing — 4 findings, all 4 false positives on App Router
      // directories whose names ARE the public URL, where a rename silently
      // changes a user-visible route.
      "unicorn/filename-case": [
        "error",
        {
          cases: { kebabCase: true },
          ignore: [
            String.raw`^__root\.`,
            String.raw`^_`,
            String.raw`^\$`,
            String.raw`^\+`,
            String.raw`\.gen\.`,
          ],
        },
      ],
      "unicorn/prefer-switch": "warn",
      "unicorn/no-useless-undefined": "error",
      "unicorn/prefer-node-protocol": "error",
      "unicorn/prefer-string-replace-all": "error",
      "unicorn/prefer-top-level-await": "error",
      "unicorn/no-await-expression-member": "error",
      "unicorn/prefer-structured-clone": "error",
      "unicorn/prefer-logical-operator-over-ternary": "error",
      "unicorn/relative-url-style": ["error", "never"],
      "unicorn/throw-new-error": "error",

      // The unicorn 72 expansion, declared and explained above the config.
      ...UNICORN_CORRECTNESS_RULES,
      ...UNICORN_MODERNISATION_RULES,

      "@sarj/prefer-zod-enum": "error",
      // A type hand-written beside the Zod schema it restates drifts the moment
      // the schema gains a field. Measured over 30,759 files in 17 repos: 5
      // reports, 5 true positives. `requireIdenticalShape: false` widens it to
      // name correlation alone (8 reports, 1 of them noise).
      "@sarj/prefer-zod-infer": "error",

      // Two candidate in-house rules were dropped in favour of these, because a
      // maintained upstream rule that already reports the exact position beats a
      // local copy of it. Measured over 30,546 .ts/.tsx files in 17 repos
      // (7 first-party + zod, trpc, dub, openstatus, formbricks, documenso,
      // unkey, midday, papermark, cal.com), non-test source only:
      //
      //   prefer-nullish  691 hits in 12 of the 17 repos. `.nullable().optional()`
      //     IS `.nullish()` by Zod's own definition, so the rewrite is exact and
      //     the rule ships an autofix. Collapsing the two spellings to one also
      //     makes the tri-state `T | null | undefined` legible at review time
      //     instead of hiding behind a two-word chain.
      //   no-any-schema   159 hits in 10 of the 17 repos. `z.any()` puts `any`
      //     into the INFERRED type, which is the one place
      //     `@typescript-eslint/no-explicit-any` cannot see it: there is no
      //     `any` keyword to flag. `z.unknown()` accepts the same inputs and
      //     forces the narrowing that was skipped.
      //
      // Verified with ESLint#calculateConfigForFile against this file: of the
      // 204 rules it resolved as enabled, none reported at either position.
      "zod/prefer-nullish": "error",
      "zod/no-any-schema": "error",

      // Deterministic ordering (incorporated from a first-party config).
      // perfectionist sorts
      // structural members; simple-import-sort owns import/export ordering
      // (chosen over eslint-plugin-import to avoid Next.js resolver conflicts).
      "perfectionist/sort-objects": [
        "error",
        { type: "natural", order: "asc" },
      ],
      "perfectionist/sort-interfaces": "error",
      "perfectionist/sort-classes": "error",
      "perfectionist/sort-jsx-props": "error",
      "perfectionist/sort-union-types": "error",
      // Public API first, private machinery below — a file should read
      // newspaper-style. This is the ALREADY-INSTALLED rule for that job; it was
      // simply never switched on. It is enabled here instead of growing a
      // `@sarj` rule, because building in-house what an available plugin rule
      // already does is this repo's repeated failure mode.
      //
      // WARN, not error: this introduces an opinion rather than ratcheting an
      // existing one. Adoption where the rule can fire is 20.6% for function
      // declarations (4.0% counting all member kinds), and OSS agrees (20.8% /
      // 3.4%). The narrowest variant shipped here still produces 5,280 reports
      // across first-party code, so it is a migration; 75% of violating files
      // need exactly one move, so it is cheap per file.
      //
      // The two options are load-bearing, not cosmetic:
      //   - `type: "unsorted"` drops the default ALPHABETICAL constraint. Left
      //     on, it demands `apple` before `zebra` among two exported functions —
      //     an enormous reordering unrelated to the public-API-first question.
      //   - the explicit `groups` correct the default order, which lists
      //     `declare-class, class, export-class` and therefore REQUIRES a
      //     non-exported class ABOVE an exported one — the exact opposite of the
      //     intent. Verified by running it: `export class Apple {} / class Zebra {}`
      //     reports "Expected Zebra (class) to come before Apple (export-class)".
      //
      // Two known blind spots, deliberately accepted and recorded so they are
      // not re-litigated: `const` arrow functions are invisible to this rule
      // (it has no variable group), and any top-level `const` partitions the
      // module so members either side are never compared. Together those are why
      // it covers ~70% rather than 100% of the convention. They are also exactly
      // the members that are TDZ-UNSAFE to move: `function` declarations hoist,
      // so reordering them can never throw, whereas moving a `const`/`class`
      // below a module-initialisation-time use is a live `ReferenceError` at
      // import. Measured: 0 unsafe moves for declarations in either corpus,
      // against 31 first-party + 23 OSS for const arrows and 1,114 + 432 for all
      // member kinds. The blind spots and the safety boundary coincide, so the
      // scope stops at declarations on purpose.
      //
      // Not covered by `@sarj/enforce-file-structure`, which orders only
      // imports-first and `use server`-first and deliberately PERMITS both
      // public-first and private-first layouts. This is additive.
      "perfectionist/sort-modules": [
        "warn",
        {
          type: "unsorted",
          groups: [
            ["declare-enum", "declare-interface", "declare-type", "declare-class", "declare-function"],
            ["export-enum", "export-interface", "export-type", "export-class", "export-function"],
            ["enum", "interface", "type", "class", "function"],
          ],
        },
      ],
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",

      // Every suppression must say WHY. `require-description` already covers
      // eslint-disable comments and `@typescript-eslint/ban-ts-comment` (from
      // strictTypeChecked) covers `@ts-expect-error`, so a bespoke rule would be
      // a duplicate.
      "@eslint-community/eslint-comments/require-description": [
        "error",
        { ignore: [] },
      ],
      // ...and a suppression must name the rule it suppresses. A bare
      // `/* eslint-disable */` at the top of a file silently switches off EVERY
      // rule for the whole file — including ones added later — which is the
      // file-level-suppression escape hatch flagged repeatedly in review.
      "@eslint-community/eslint-comments/no-unlimited-disable": "error",
      "@eslint-community/eslint-comments/no-restricted-disable": [
        "warn",
        "no-console",
        "react-hooks/exhaustive-deps",
      ],

      // Dedup: TS-enum ban → @sarj/no-enum, oversized-try-block ban →
      // @sarj/no-fat-try-blocks, and process.env ban → @sarj/no-raw-env (all
      // added below). Only the selectors WITHOUT a @sarj equivalent stay here,
      // so each concern fires exactly one diagnostic.
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.property.name='forEach']",
          message: "Prefer a for-of loop over forEach.",
        },
        {
          selector: "TSModuleDeclaration[kind='namespace']",
          message: "Use ES modules instead of namespaces.",
        },
        {
          selector: "CallExpression[callee.name='useCallback']",
          message:
            "Don't memoize by hand — the React Compiler handles it. Remove useCallback.",
        },
        {
          selector: "CallExpression[callee.name='useMemo']",
          message:
            "Don't memoize by hand — the React Compiler handles it. Remove useMemo (extract a plain function or compute inline).",
        },
      ],
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@clerk/nextjs",
              importNames: ["auth", "currentUser"],
              message: "Prefer an internal user-service wrapper.",
            },
            {
              name: "@clerk/nextjs/server",
              message: "Prefer an internal user-service wrapper.",
            },
          ],
          patterns: ["*/index", "*/index.ts"],
        },
      ],

      "object-shorthand": ["error", "always"],
      "no-return-await": "error",
      eqeqeq: ["error", "always"],
      "no-await-in-loop": "error",
      "no-param-reassign": "error",
      "array-callback-return": "error",
      "no-fallthrough": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
      "prefer-const": "error",
      "prefer-template": "error",
      "no-var": "error",
      "no-shadow": "off",
      "@typescript-eslint/no-shadow": "error",

      // The COMPLETE @sarj/eslint-plugin strict ruleset, every rule at `error`.
      //
      // No version pin and no per-rule notes: a hand-written "@2.7.0" claim went
      // stale twice, and a declared list of tier deviations outlived the last
      // deviation it described. Both are now assertions instead of prose —
      // packages/typescript/tests/strict-config-sync.test.ts fails if this block
      // omits a shipped rule, names one that does not exist, or sets a tier the
      // plugin's own `configs.strict` does not. Each rule's measurements live in
      // docs/rules/<rule>.md, which its `meta.docs.url` points at.
      //
      // A `files:`-scoped block further down turns no-raw-env off for env
      // source-of-truth files; that is an override, not a tier change.
      "@sarj/zod-naming-convention": "error",
      "@sarj/require-assert-never": "error",
      "@sarj/require-zod-form-validation": "error",
      "@sarj/prefer-schema-for-api-payload": "error",
      "@sarj/no-client-side-data-fetching": "error",
      "@sarj/prefer-server-actions": "error",
      "@sarj/no-unnecessary-use-client": "error",
      "@sarj/no-enum": "error",
      "@sarj/no-raw-env": "error",
      "@sarj/no-sentinel-return-on-catch": "error",
      "@sarj/no-log-only-catch": "error",
      "@sarj/no-insecure-random-id": "error",
      "@sarj/no-json-stringify-error": "error",
      "@sarj/no-string-concat-in-loop": "error",
      "@sarj/prefer-discriminated-union": "error",
      "@sarj/no-comment-cruft": "error",
      "@sarj/no-fat-try-blocks": "error",
      "@sarj/no-cors-wildcard-with-credentials": "error",
      "@sarj/no-secret-in-log": "error",
      "@sarj/no-hand-rolled-sleep": "error",
      "@sarj/require-fetch-timeout": "error",
      "@sarj/no-silent-promise-catch": "error",
      "@sarj/enforce-file-structure": "error",
      "@sarj/prefer-semantic-colors": [
        "error",
        { requireSemanticTokens: true },
      ],
      "@sarj/prefer-string-literal-union": "error",
      "@sarj/prefer-constant-time-secret-compare": "error",
      "@sarj/no-dynamic-sql": "error",
      "@sarj/store-insert-requires-on-conflict": "error",
      "@sarj/no-offset-pagination": "error",
      "@sarj/no-select-star": "error",
      "@sarj/no-zod-native-enum": "error",
      "@sarj/prefer-module-level-constant": "error",
      "@sarj/prefer-module-level-schema": "error",
      "@sarj/prefer-non-nullable-collection": "error",
      "@sarj/no-sleep-in-test-body": "error",
      "@sarj/no-positional-tuple-return": "error",
      "@sarj/no-restated-comment": "error",
      "@sarj/no-restated-jsdoc": "error",
      "@sarj/no-trailing-value-narration": "error",
      "@sarj/no-type-member-comment-wall": "error",
      "@sarj/no-repeated-string-literal": "error",
      "@sarj/no-tautological-expect": "error",
      "@sarj/require-interface-for-injected-service": "error",
      "@sarj/no-conditional-in-test": "error",
      "@sarj/no-unsafe-mock-casting": "error",
      "@sarj/prefer-whole-object-assertion": "error",
      "@sarj/no-async-callback-in-wait-for": "error",
      // Deliberately NOT enabled here — these two are architectural rules that
      // are meaningless without per-repo paths, so a shared config cannot set
      // them. `no-storage-in-stateless-modules` defaults to `modules: []` and is
      // inert until a consumer names its stateless modules;
      // `no-raw-fetch-outside-clients` needs an `allow` list matching that
      // repo's client-layer convention (the default assumes `clients/`). Opt in
      // per repo:
      //   "@sarj/no-storage-in-stateless-modules": ["error", { modules: [...] }],
      //   "@sarj/no-raw-fetch-outside-clients": ["error", { allow: [...] }],
    }),
  },

  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/__tests__/**/*"],
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },

  {
    files: ["**/components/ui/**", "**/components/design-system/**"],
    rules: withoutReactRules({
      "react/forbid-elements": "off",
    }),
  },

  {
    // The env source-of-truth files parse process.env into a Zod-validated
    // object the rest of the app imports; they're the one place raw env access
    // is legitimate, so @sarj/no-raw-env (which replaced the native
    // no-restricted-properties process.env ban) is disabled here.
    files: [
      "**/*.config.{ts,tsx,js,jsx,mjs,cjs,mts,cts}",
      "**/scripts/**",
      "**/env/**",
      "**/env.{ts,tsx,js,mjs}",
      "**/server-env.{ts,tsx,js,mjs}",
      "**/client-env.{ts,tsx,js,mjs}",
      "**/server-settings.{ts,tsx,js,mjs}",
      "**/client-settings.{ts,tsx,js,mjs}",
    ],
    rules: {
      "@sarj/no-raw-env": "off",
    },
  },

  // better-tailwindcss: class-string hygiene for Tailwind repos. Scoped to JSX/TSX
  // (where className strings live) and harmless where no Tailwind classes exist —
  // these three rules only inspect literal class strings, so non-Tailwind repos
  // simply see zero findings. Kept in its own block so the plugin is only wired
  // where it applies.
  {
    files: ["**/*.{jsx,tsx}"],
    plugins: {
      "better-tailwindcss": betterTailwindcss,
    },
    rules: {
      "better-tailwindcss/no-conflicting-classes": "error",
      "better-tailwindcss/no-duplicate-classes": "error",
      "better-tailwindcss/no-deprecated-classes": "error",
    },
  },
  // React components may be PascalCase. This is the single highest-impact
  // exemption in the config: measured over 11,088 tracked `.ts`/`.tsx` files in
  // 50 repos, PascalCase `.tsx` accounts for 2,128 of 2,568 total filename
  // violations (82.9%), and 93.5% of those files export a component with the
  // same name as the file. Allowing it takes the corpus-wide cost from 2,568
  // renames to 400, and two first-party repos plus this one from 51 to 17.
  //
  // Scoped to `.tsx` ON PURPOSE. Only 27 PascalCase `.ts` files exist across all
  // 50 repos and they are service classes (`AuthService.ts`, `SessionStore.ts`),
  // not components — those should be kebab, so the allowance must not reach them.
  //
  // Two of our own repos had already adopted exactly this
  // unilaterally, which is part of why it belongs in the canonical config: it
  // converges hand-rolled configs back onto the synchronizer.
  {
    files: ["**/*.tsx"],
    rules: {
      "unicorn/filename-case": [
        "error",
        {
          cases: { kebabCase: true, pascalCase: true },
          ignore: [
            String.raw`^__root\.`,
            String.raw`^_`,
            String.raw`^\$`,
            String.raw`^\+`,
            String.raw`\.gen\.`,
          ],
        },
      ],
    },
  },

];

export default config;
