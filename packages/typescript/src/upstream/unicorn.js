// Native stock Oxlint source port of licensed Unicorn syntax rules.
// Versions, licenses, and changes are recorded in vendor/PROVENANCE.json.
import { definePlugin } from "@oxlint/plugins";
import toRule from "../../vendor/unicorn/rules/rule/to-eslint-rule.js";
import rule0 from "../../vendor/unicorn/rules/class-reference-in-static-methods.js";
import rule1 from "../../vendor/unicorn/rules/consistent-json-file-read.js";
import rule2 from "../../vendor/unicorn/rules/iteration-fallback-style.js";
import rule3 from "../../vendor/unicorn/rules/no-accidental-bitwise-operator.js";
import rule4 from "../../vendor/unicorn/rules/no-array-concat-in-loop.js";
import rule5 from "../../vendor/unicorn/rules/no-array-from-fill.js";
import rule6 from "../../vendor/unicorn/rules/no-array-sort-for-min-max.js";
import rule7 from "../../vendor/unicorn/rules/no-async-iterator-callback.js";
import rule8 from "../../vendor/unicorn/rules/no-async-promise-finally.js";
import rule9 from "../../vendor/unicorn/rules/no-blob-to-file.js";
import rule10 from "../../vendor/unicorn/rules/no-boolean-sort-comparator.js";
import rule11 from "../../vendor/unicorn/rules/no-canvas-to-image.js";
import rule12 from "../../vendor/unicorn/rules/no-chained-comparison.js";
import rule13 from "../../vendor/unicorn/rules/no-collection-bracket-access.js";
import rule14 from "../../vendor/unicorn/rules/no-computed-property-existence-check.js";
import rule15 from "../../vendor/unicorn/rules/no-confusing-array-splice.js";
import rule16 from "../../vendor/unicorn/rules/no-constant-zero-expression.js";
import rule17 from "../../vendor/unicorn/rules/no-double-comparison.js";
import rule18 from "../../vendor/unicorn/rules/no-duplicate-if-branches.js";
import rule19 from "../../vendor/unicorn/rules/no-duplicate-logical-operands.js";
import rule20 from "../../vendor/unicorn/rules/no-duplicate-loops.js";
import rule21 from "../../vendor/unicorn/rules/no-duplicate-set-values.js";
import rule22 from "../../vendor/unicorn/rules/no-error-property-assignment.js";
import rule23 from "../../vendor/unicorn/rules/no-exports-in-scripts.js";
import rule24 from "../../vendor/unicorn/rules/no-for-loop.js";
import rule25 from "../../vendor/unicorn/rules/no-global-object-property-assignment.js";
import rule26 from "../../vendor/unicorn/rules/no-impossible-length-comparison.js";
import rule27 from "../../vendor/unicorn/rules/no-incorrect-query-selector.js";
import rule28 from "../../vendor/unicorn/rules/no-incorrect-template-string-interpolation.js";
import rule29 from "../../vendor/unicorn/rules/no-invalid-argument-count.js";
import rule30 from "../../vendor/unicorn/rules/no-invalid-character-comparison.js";
import rule31 from "../../vendor/unicorn/rules/no-invalid-file-input-accept.js";
import rule32 from "../../vendor/unicorn/rules/no-invalid-well-known-symbol-methods.js";
import rule33 from "../../vendor/unicorn/rules/no-late-current-target-access.js";
import rule34 from "../../vendor/unicorn/rules/no-late-event-control.js";
import rule35 from "../../vendor/unicorn/rules/no-loop-iterable-mutation.js";
import rule36 from "../../vendor/unicorn/rules/no-mismatched-map-key.js";
import rule37 from "../../vendor/unicorn/rules/no-misrefactored-assignment.js";
import rule39 from "../../vendor/unicorn/rules/no-multiple-promise-resolver-calls.js";
import rule40 from "../../vendor/unicorn/rules/no-nonstandard-builtin-properties.js";
import rule41 from "../../vendor/unicorn/rules/no-object-methods-with-collections.js";
import rule42 from "../../vendor/unicorn/rules/no-optional-chaining-on-undeclared-variable.js";
import rule43 from "../../vendor/unicorn/rules/no-redundant-comparison.js";
import rule44 from "../../vendor/unicorn/rules/no-return-array-push.js";
import rule45 from "../../vendor/unicorn/rules/no-selector-as-dom-name.js";
import rule47 from "../../vendor/unicorn/rules/no-subtraction-comparison.js";
import rule48 from "../../vendor/unicorn/rules/no-this-outside-of-class.js";
import rule49 from "../../vendor/unicorn/rules/no-uncalled-method.js";
import rule50 from "../../vendor/unicorn/rules/no-undeclared-class-members.js";
import rule51 from "../../vendor/unicorn/rules/no-unnecessary-array-flat-map.js";
import rule52 from "../../vendor/unicorn/rules/no-unnecessary-boolean-comparison.js";
import rule53 from "../../vendor/unicorn/rules/no-unnecessary-fetch-options.js";
import rule54 from "../../vendor/unicorn/rules/no-unnecessary-global-this.js";
import rule55 from "../../vendor/unicorn/rules/no-unnecessary-nested-ternary.js";
import rule56 from "../../vendor/unicorn/rules/no-unnecessary-polyfills.js";
import rule57 from "../../vendor/unicorn/rules/no-unnecessary-splice.js";
import rule58 from "../../vendor/unicorn/rules/no-unnecessary-string-trim.js";
import rule59 from "../../vendor/unicorn/rules/no-unsafe-buffer-conversion.js";
import rule60 from "../../vendor/unicorn/rules/no-unsafe-dom-html.js";
import rule61 from "../../vendor/unicorn/rules/no-unsafe-promise-all-settled-values.js";
import rule62 from "../../vendor/unicorn/rules/no-unsafe-property-key.js";
import rule63 from "../../vendor/unicorn/rules/no-unsafe-sqlite-interpolation.js";
import rule64 from "../../vendor/unicorn/rules/no-unsafe-string-replacement.js";
import rule65 from "../../vendor/unicorn/rules/no-unused-builtin-method-return.js";
import rule66 from "../../vendor/unicorn/rules/no-unused-iterator-helper.js";
import rule67 from "../../vendor/unicorn/rules/no-useless-boolean-cast.js";
import rule68 from "../../vendor/unicorn/rules/no-useless-coercion.js";
import rule69 from "../../vendor/unicorn/rules/no-useless-compound-assignment.js";
import rule70 from "../../vendor/unicorn/rules/no-useless-concat.js";
import rule71 from "../../vendor/unicorn/rules/no-useless-continue.js";
import rule72 from "../../vendor/unicorn/rules/no-useless-delete-check.js";
import rule73 from "../../vendor/unicorn/rules/no-useless-else.js";
import rule74 from "../../vendor/unicorn/rules/no-useless-logical-operand.js";
import rule75 from "../../vendor/unicorn/rules/no-useless-override.js";
import rule76 from "../../vendor/unicorn/rules/no-useless-re-export.js";
import rule77 from "../../vendor/unicorn/rules/no-useless-recursion.js";
import rule78 from "../../vendor/unicorn/rules/no-useless-set-construction.js";
import rule79 from "../../vendor/unicorn/rules/no-xor-as-exponentiation.js";
import rule80 from "../../vendor/unicorn/rules/prefer-abort-signal-any.js";
import rule81 from "../../vendor/unicorn/rules/prefer-abort-signal-timeout.js";
import rule82 from "../../vendor/unicorn/rules/prefer-add-event-listener-options.js";
import rule83 from "../../vendor/unicorn/rules/prefer-aggregate-error.js";
import rule84 from "../../vendor/unicorn/rules/prefer-array-from-async.js";
import rule85 from "../../vendor/unicorn/rules/prefer-array-from-map.js";
import rule86 from "../../vendor/unicorn/rules/prefer-array-from-range.js";
import rule87 from "../../vendor/unicorn/rules/prefer-array-iterable-methods.js";
import rule88 from "../../vendor/unicorn/rules/prefer-array-last-methods.js";
import rule89 from "../../vendor/unicorn/rules/prefer-array-slice.js";
import rule90 from "../../vendor/unicorn/rules/prefer-combined-guards.js";
import rule91 from "../../vendor/unicorn/rules/prefer-direct-iteration.js";
import rule92 from "../../vendor/unicorn/rules/prefer-flat-math-min-max.js";
import rule93 from "../../vendor/unicorn/rules/prefer-global-number-constants.js";
import rule94 from "../../vendor/unicorn/rules/prefer-group-by.js";
import rule95 from "../../vendor/unicorn/rules/prefer-has-check.js";
import rule96 from "../../vendor/unicorn/rules/prefer-https.js";
import rule97 from "../../vendor/unicorn/rules/prefer-identifier-import-export-specifiers.js";
import rule98 from "../../vendor/unicorn/rules/prefer-iterable-in-constructor.js";
import rule99 from "../../vendor/unicorn/rules/prefer-iterator-concat.js";
import rule100 from "../../vendor/unicorn/rules/prefer-iterator-helpers.js";
import rule101 from "../../vendor/unicorn/rules/prefer-iterator-to-array.js";
import rule102 from "../../vendor/unicorn/rules/prefer-iterator-to-array-at-end.js";
import rule103 from "../../vendor/unicorn/rules/prefer-map-from-entries.js";
import rule104 from "../../vendor/unicorn/rules/prefer-math-abs.js";
import rule105 from "../../vendor/unicorn/rules/prefer-math-constants.js";
import rule106 from "../../vendor/unicorn/rules/prefer-number-is-safe-integer.js";
import rule107 from "../../vendor/unicorn/rules/prefer-object-define-properties.js";
import rule108 from "../../vendor/unicorn/rules/prefer-object-destructuring-defaults.js";
import rule109 from "../../vendor/unicorn/rules/prefer-object-iterable-methods.js";
import rule110 from "../../vendor/unicorn/rules/prefer-promise-with-resolvers.js";
import rule111 from "../../vendor/unicorn/rules/prefer-queue-microtask.js";
import rule112 from "../../vendor/unicorn/rules/prefer-set-methods.js";
import rule113 from "../../vendor/unicorn/rules/prefer-simple-sort-comparator.js";
import rule114 from "../../vendor/unicorn/rules/prefer-simplified-conditions.js";
import rule115 from "../../vendor/unicorn/rules/prefer-single-array-predicate.js";
import rule116 from "../../vendor/unicorn/rules/prefer-single-object-destructuring.js";
import rule117 from "../../vendor/unicorn/rules/prefer-single-replace.js";
import rule118 from "../../vendor/unicorn/rules/prefer-split-limit.js";
import rule119 from "../../vendor/unicorn/rules/prefer-string-match-all.js";
import rule120 from "../../vendor/unicorn/rules/prefer-string-pad-start-end.js";
import rule121 from "../../vendor/unicorn/rules/prefer-string-repeat.js";
import rule122 from "../../vendor/unicorn/rules/prefer-switch.js";
import rule123 from "../../vendor/unicorn/rules/prefer-then-catch.js";
import rule124 from "../../vendor/unicorn/rules/prefer-unary-minus.js";
import rule125 from "../../vendor/unicorn/rules/prefer-unicode-code-point-escapes.js";
import rule126 from "../../vendor/unicorn/rules/prefer-url-can-parse.js";
import rule127 from "../../vendor/unicorn/rules/prefer-url-search-parameters.js";
import rule128 from "../../vendor/unicorn/rules/prefer-while-loop-condition.js";
import rule129 from "../../vendor/unicorn/rules/require-css-escape.js";
import rule130 from "../../vendor/unicorn/rules/require-passive-events.js";
import rule131 from "../../vendor/unicorn/rules/require-proxy-trap-boolean-return.js";
import rule132 from "../../vendor/unicorn/rules/single-line-block-comment-style.js";
import preferTopLevelAwait from "../../vendor/unicorn/rules/prefer-top-level-await.js";
import preferNumberProperties from "../../vendor/unicorn/rules/prefer-number-properties.js";
import preferLogicalOperatorOverTernary from "../../vendor/unicorn/rules/prefer-logical-operator-over-ternary.js";
import noUselessSpread from "../../vendor/unicorn/rules/no-useless-spread.js";
import noInvalidFetchOptions from "../../vendor/unicorn/rules/no-invalid-fetch-options.js";
import requireModuleSpecifiers from "../../vendor/unicorn/rules/require-module-specifiers.js";

export default definePlugin({
  meta: { name: "sarj-upstream-unicorn", version: "76.0.0" },
  rules: {
    "require-module-specifiers": toRule(
      "require-module-specifiers",
      requireModuleSpecifiers,
    ),
    "no-useless-spread": toRule("no-useless-spread", noUselessSpread),
    "no-invalid-fetch-options": toRule(
      "no-invalid-fetch-options",
      noInvalidFetchOptions,
    ),
    "prefer-number-properties": toRule(
      "prefer-number-properties",
      preferNumberProperties,
    ),
    "prefer-logical-operator-over-ternary": toRule(
      "prefer-logical-operator-over-ternary",
      preferLogicalOperatorOverTernary,
    ),
    "prefer-top-level-await": toRule(
      "prefer-top-level-await",
      preferTopLevelAwait,
    ),
    "class-reference-in-static-methods": toRule(
      "class-reference-in-static-methods",
      rule0,
    ),
    "consistent-json-file-read": toRule("consistent-json-file-read", rule1),
    "iteration-fallback-style": toRule("iteration-fallback-style", rule2),
    "no-accidental-bitwise-operator": toRule(
      "no-accidental-bitwise-operator",
      rule3,
    ),
    "no-array-concat-in-loop": toRule("no-array-concat-in-loop", rule4),
    "no-array-from-fill": toRule("no-array-from-fill", rule5),
    "no-array-sort-for-min-max": toRule("no-array-sort-for-min-max", rule6),
    "no-async-iterator-callback": toRule("no-async-iterator-callback", rule7),
    "no-async-promise-finally": toRule("no-async-promise-finally", rule8),
    "no-blob-to-file": toRule("no-blob-to-file", rule9),
    "no-boolean-sort-comparator": toRule("no-boolean-sort-comparator", rule10),
    "no-canvas-to-image": toRule("no-canvas-to-image", rule11),
    "no-chained-comparison": toRule("no-chained-comparison", rule12),
    "no-collection-bracket-access": toRule(
      "no-collection-bracket-access",
      rule13,
    ),
    "no-computed-property-existence-check": toRule(
      "no-computed-property-existence-check",
      rule14,
    ),
    "no-confusing-array-splice": toRule("no-confusing-array-splice", rule15),
    "no-constant-zero-expression": toRule(
      "no-constant-zero-expression",
      rule16,
    ),
    "no-double-comparison": toRule("no-double-comparison", rule17),
    "no-duplicate-if-branches": toRule("no-duplicate-if-branches", rule18),
    "no-duplicate-logical-operands": toRule(
      "no-duplicate-logical-operands",
      rule19,
    ),
    "no-duplicate-loops": toRule("no-duplicate-loops", rule20),
    "no-duplicate-set-values": toRule("no-duplicate-set-values", rule21),
    "no-error-property-assignment": toRule(
      "no-error-property-assignment",
      rule22,
    ),
    "no-exports-in-scripts": toRule("no-exports-in-scripts", rule23),
    "no-for-loop": toRule("no-for-loop", rule24),
    "no-global-object-property-assignment": toRule(
      "no-global-object-property-assignment",
      rule25,
    ),
    "no-impossible-length-comparison": toRule(
      "no-impossible-length-comparison",
      rule26,
    ),
    "no-incorrect-query-selector": toRule(
      "no-incorrect-query-selector",
      rule27,
    ),
    "no-incorrect-template-string-interpolation": toRule(
      "no-incorrect-template-string-interpolation",
      rule28,
    ),
    "no-invalid-argument-count": toRule("no-invalid-argument-count", rule29),
    "no-invalid-character-comparison": toRule(
      "no-invalid-character-comparison",
      rule30,
    ),
    "no-invalid-file-input-accept": toRule(
      "no-invalid-file-input-accept",
      rule31,
    ),
    "no-invalid-well-known-symbol-methods": toRule(
      "no-invalid-well-known-symbol-methods",
      rule32,
    ),
    "no-late-current-target-access": toRule(
      "no-late-current-target-access",
      rule33,
    ),
    "no-late-event-control": toRule("no-late-event-control", rule34),
    "no-loop-iterable-mutation": toRule("no-loop-iterable-mutation", rule35),
    "no-mismatched-map-key": toRule("no-mismatched-map-key", rule36),
    "no-misrefactored-assignment": toRule(
      "no-misrefactored-assignment",
      rule37,
    ),
    "no-multiple-promise-resolver-calls": toRule(
      "no-multiple-promise-resolver-calls",
      rule39,
    ),
    "no-nonstandard-builtin-properties": toRule(
      "no-nonstandard-builtin-properties",
      rule40,
    ),
    "no-object-methods-with-collections": toRule(
      "no-object-methods-with-collections",
      rule41,
    ),
    "no-optional-chaining-on-undeclared-variable": toRule(
      "no-optional-chaining-on-undeclared-variable",
      rule42,
    ),
    "no-redundant-comparison": toRule("no-redundant-comparison", rule43),
    "no-return-array-push": toRule("no-return-array-push", rule44),
    "no-selector-as-dom-name": toRule("no-selector-as-dom-name", rule45),
    "no-subtraction-comparison": toRule("no-subtraction-comparison", rule47),
    "no-this-outside-of-class": toRule("no-this-outside-of-class", rule48),
    "no-uncalled-method": toRule("no-uncalled-method", rule49),
    "no-undeclared-class-members": toRule(
      "no-undeclared-class-members",
      rule50,
    ),
    "no-unnecessary-array-flat-map": toRule(
      "no-unnecessary-array-flat-map",
      rule51,
    ),
    "no-unnecessary-boolean-comparison": toRule(
      "no-unnecessary-boolean-comparison",
      rule52,
    ),
    "no-unnecessary-fetch-options": toRule(
      "no-unnecessary-fetch-options",
      rule53,
    ),
    "no-unnecessary-global-this": toRule("no-unnecessary-global-this", rule54),
    "no-unnecessary-nested-ternary": toRule(
      "no-unnecessary-nested-ternary",
      rule55,
    ),
    "no-unnecessary-polyfills": toRule("no-unnecessary-polyfills", rule56),
    "no-unnecessary-splice": toRule("no-unnecessary-splice", rule57),
    "no-unnecessary-string-trim": toRule("no-unnecessary-string-trim", rule58),
    "no-unsafe-buffer-conversion": toRule(
      "no-unsafe-buffer-conversion",
      rule59,
    ),
    "no-unsafe-dom-html": toRule("no-unsafe-dom-html", rule60),
    "no-unsafe-promise-all-settled-values": toRule(
      "no-unsafe-promise-all-settled-values",
      rule61,
    ),
    "no-unsafe-property-key": toRule("no-unsafe-property-key", rule62),
    "no-unsafe-sqlite-interpolation": toRule(
      "no-unsafe-sqlite-interpolation",
      rule63,
    ),
    "no-unsafe-string-replacement": toRule(
      "no-unsafe-string-replacement",
      rule64,
    ),
    "no-unused-builtin-method-return": toRule(
      "no-unused-builtin-method-return",
      rule65,
    ),
    "no-unused-iterator-helper": toRule("no-unused-iterator-helper", rule66),
    "no-useless-boolean-cast": toRule("no-useless-boolean-cast", rule67),
    "no-useless-coercion": toRule("no-useless-coercion", rule68),
    "no-useless-compound-assignment": toRule(
      "no-useless-compound-assignment",
      rule69,
    ),
    "no-useless-concat": toRule("no-useless-concat", rule70),
    "no-useless-continue": toRule("no-useless-continue", rule71),
    "no-useless-delete-check": toRule("no-useless-delete-check", rule72),
    "no-useless-else": toRule("no-useless-else", rule73),
    "no-useless-logical-operand": toRule("no-useless-logical-operand", rule74),
    "no-useless-override": toRule("no-useless-override", rule75),
    "no-useless-re-export": toRule("no-useless-re-export", rule76),
    "no-useless-recursion": toRule("no-useless-recursion", rule77),
    "no-useless-set-construction": toRule(
      "no-useless-set-construction",
      rule78,
    ),
    "no-xor-as-exponentiation": toRule("no-xor-as-exponentiation", rule79),
    "prefer-abort-signal-any": toRule("prefer-abort-signal-any", rule80),
    "prefer-abort-signal-timeout": toRule(
      "prefer-abort-signal-timeout",
      rule81,
    ),
    "prefer-add-event-listener-options": toRule(
      "prefer-add-event-listener-options",
      rule82,
    ),
    "prefer-aggregate-error": toRule("prefer-aggregate-error", rule83),
    "prefer-array-from-async": toRule("prefer-array-from-async", rule84),
    "prefer-array-from-map": toRule("prefer-array-from-map", rule85),
    "prefer-array-from-range": toRule("prefer-array-from-range", rule86),
    "prefer-array-iterable-methods": toRule(
      "prefer-array-iterable-methods",
      rule87,
    ),
    "prefer-array-last-methods": toRule("prefer-array-last-methods", rule88),
    "prefer-array-slice": toRule("prefer-array-slice", rule89),
    "prefer-combined-guards": toRule("prefer-combined-guards", rule90),
    "prefer-direct-iteration": toRule("prefer-direct-iteration", rule91),
    "prefer-flat-math-min-max": toRule("prefer-flat-math-min-max", rule92),
    "prefer-global-number-constants": toRule(
      "prefer-global-number-constants",
      rule93,
    ),
    "prefer-group-by": toRule("prefer-group-by", rule94),
    "prefer-has-check": toRule("prefer-has-check", rule95),
    "prefer-https": toRule("prefer-https", rule96),
    "prefer-identifier-import-export-specifiers": toRule(
      "prefer-identifier-import-export-specifiers",
      rule97,
    ),
    "prefer-iterable-in-constructor": toRule(
      "prefer-iterable-in-constructor",
      rule98,
    ),
    "prefer-iterator-concat": toRule("prefer-iterator-concat", rule99),
    "prefer-iterator-helpers": toRule("prefer-iterator-helpers", rule100),
    "prefer-iterator-to-array": toRule("prefer-iterator-to-array", rule101),
    "prefer-iterator-to-array-at-end": toRule(
      "prefer-iterator-to-array-at-end",
      rule102,
    ),
    "prefer-map-from-entries": toRule("prefer-map-from-entries", rule103),
    "prefer-math-abs": toRule("prefer-math-abs", rule104),
    "prefer-math-constants": toRule("prefer-math-constants", rule105),
    "prefer-number-is-safe-integer": toRule(
      "prefer-number-is-safe-integer",
      rule106,
    ),
    "prefer-object-define-properties": toRule(
      "prefer-object-define-properties",
      rule107,
    ),
    "prefer-object-destructuring-defaults": toRule(
      "prefer-object-destructuring-defaults",
      rule108,
    ),
    "prefer-object-iterable-methods": toRule(
      "prefer-object-iterable-methods",
      rule109,
    ),
    "prefer-promise-with-resolvers": toRule(
      "prefer-promise-with-resolvers",
      rule110,
    ),
    "prefer-queue-microtask": toRule("prefer-queue-microtask", rule111),
    "prefer-set-methods": toRule("prefer-set-methods", rule112),
    "prefer-simple-sort-comparator": toRule(
      "prefer-simple-sort-comparator",
      rule113,
    ),
    "prefer-simplified-conditions": toRule(
      "prefer-simplified-conditions",
      rule114,
    ),
    "prefer-single-array-predicate": toRule(
      "prefer-single-array-predicate",
      rule115,
    ),
    "prefer-single-object-destructuring": toRule(
      "prefer-single-object-destructuring",
      rule116,
    ),
    "prefer-single-replace": toRule("prefer-single-replace", rule117),
    "prefer-split-limit": toRule("prefer-split-limit", rule118),
    "prefer-string-match-all": toRule("prefer-string-match-all", rule119),
    "prefer-string-pad-start-end": toRule(
      "prefer-string-pad-start-end",
      rule120,
    ),
    "prefer-string-repeat": toRule("prefer-string-repeat", rule121),
    "prefer-switch": toRule("prefer-switch", rule122),
    "prefer-then-catch": toRule("prefer-then-catch", rule123),
    "prefer-unary-minus": toRule("prefer-unary-minus", rule124),
    "prefer-unicode-code-point-escapes": toRule(
      "prefer-unicode-code-point-escapes",
      rule125,
    ),
    "prefer-url-can-parse": toRule("prefer-url-can-parse", rule126),
    "prefer-url-search-parameters": toRule(
      "prefer-url-search-parameters",
      rule127,
    ),
    "prefer-while-loop-condition": toRule(
      "prefer-while-loop-condition",
      rule128,
    ),
    "require-css-escape": toRule("require-css-escape", rule129),
    "require-passive-events": toRule("require-passive-events", rule130),
    "require-proxy-trap-boolean-return": toRule(
      "require-proxy-trap-boolean-return",
      rule131,
    ),
    "single-line-block-comment-style": toRule(
      "single-line-block-comment-style",
      rule132,
    ),
  },
});
